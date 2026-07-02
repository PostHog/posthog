"""Dump the latest team-1 ReviewHog run to a per-config `.md` for reviewer-quality experiments.

Run via manage.py shell so Django is configured; set OUT_DIR to the experiment's runs/ directory:

    LABEL=C0-baseline RUN_SECONDS=812 RUN_START_EPOCH=1751... OUT_DIR=products/review_hog/eval/experiments/<exp>/runs \
        python manage.py shell -c "exec(open('products/review_hog/eval/scripts/dump_result.py').read())"

Reads the most-recent `ReviewReport` for team 1 (the eval team) and its artefacts, then writes
`<OUT_DIR>/<LABEL>.md` with: the config snapshot, the chunking, the
per-perspective breakdown, the raw→dedup→valid funnel, the review-unit count, wall-clock, a
best-effort local `$ai_generation` token tally, and the full findings list with validator verdicts.
The findings list is the raw material for the coverage-vs-old-10 scoring pass.
"""

import os
from datetime import UTC, datetime, timedelta

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer import constants
from products.review_hog.backend.reviewer.artefact_content import (
    ChunkSetArtefact,
    PerspectiveResultArtefact,
    ReviewIssueFinding,
    ValidationVerdict,
    parse_artefact_content,
)

TEAM = 1
LABEL = os.environ.get("LABEL", "unlabeled")
RUN_SECONDS = os.environ.get("RUN_SECONDS")
RUN_START_EPOCH = float(os.environ.get("RUN_START_EPOCH", "0"))
OUT_DIR = os.environ.get("OUT_DIR", "products/review_hog/eval/experiments/2026-07-reviewer-topology/runs")


def _fmt_lines(lines) -> str:
    return ",".join(f"{lr.start}-{lr.end}" if lr.end else str(lr.start) for lr in lines) or "—"


def _tokens_by_provider(start_dt):
    """Best-effort local `$ai_generation` tally since the run started, grouped by `$ai_model`.

    Returns (rows, grand_total) or (None, None) if the events aren't queryable locally (they may live in
    a cloud project, or not be ingested yet). Never raises — tokens are a secondary metric; the review-unit
    count below is the reliable, model-held-constant cost signal. We group by raw model rather than a
    reviewer-vs-support split because the reviewer and dedup/validate can run on the same model.
    """
    try:
        from posthog.clickhouse.client import sync_execute  # noqa: PLC0415 — optional, only for the token tally

        rows = sync_execute(
            """
            SELECT JSONExtractString(properties, '$ai_model') AS model,
                   count() AS gens,
                   sum(toFloat64OrZero(JSONExtractString(properties, '$ai_input_tokens'))) AS input_tokens,
                   sum(toFloat64OrZero(JSONExtractString(properties, '$ai_output_tokens'))) AS output_tokens
            FROM events
            WHERE event = '$ai_generation' AND timestamp >= %(start)s
            GROUP BY model ORDER BY gens DESC
            """,
            {"start": start_dt},
        )
        if not rows:
            return None, None
        grand_total = [0, 0, 0]
        for _model, gens, tin, tout in rows:
            grand_total[0] += int(gens)
            grand_total[1] += int(tin)
            grand_total[2] += int(tout)
        return rows, grand_total
    except Exception as e:  # pragma: no cover - best effort
        return f"unavailable ({type(e).__name__}: {e})", None


report = ReviewReport.objects.for_team(TEAM).order_by("-created_at").first()
if report is None:
    raise SystemExit("No ReviewReport for team 1 — did the run persist?")

arts = list(ReviewReportArtefact.objects.for_team(TEAM).filter(report_id=report.id))

# Chunk set (latest).
chunks = None
for a in arts:
    if a.type == ReviewReportArtefact.ArtefactType.CHUNK_SET:
        c = parse_artefact_content(a.type, a.content)
        if isinstance(c, ChunkSetArtefact):
            chunks = c
chunk_count = len(chunks.chunks) if chunks else 0

# Perspective results → raw issue count + per-(pass,chunk) breakdown.
perspective_rows: list[tuple[int, int, str, int]] = []  # (pass, chunk, source_perspective, n_issues)
raw_issues = 0
for a in arts:
    if a.type == ReviewReportArtefact.ArtefactType.PERSPECTIVE_RESULT:
        c = parse_artefact_content(a.type, a.content)
        if isinstance(c, PerspectiveResultArtefact):
            n = len(c.review.issues)
            raw_issues += n
            src = next((i.source_perspective for i in c.review.issues if i.source_perspective), "?")
            perspective_rows.append((c.pass_number, c.chunk_id, src, n))
perspective_rows.sort()
review_units = len(perspective_rows)

# Findings (post-dedup) + verdicts, paired by issue_key.
findings: dict[str, ReviewIssueFinding] = {}
verdicts: dict[str, ValidationVerdict] = {}
for a in arts:
    if a.type == ReviewReportArtefact.ArtefactType.ISSUE_FINDING:
        c = parse_artefact_content(a.type, a.content)
        if isinstance(c, ReviewIssueFinding):
            findings[c.issue_key] = c
    elif a.type == ReviewReportArtefact.ArtefactType.VALIDATION_VERDICT:
        c = parse_artefact_content(a.type, a.content)
        if isinstance(c, ValidationVerdict):
            verdicts[c.issue_key] = c
dedup_count = len(findings)
valid_count = sum(1 for k in findings if (v := verdicts.get(k)) and v.is_valid)

# Tokens (best-effort).
start_dt = (
    datetime.fromtimestamp(RUN_START_EPOCH, tz=UTC) if RUN_START_EPOCH else datetime.now(UTC) - timedelta(hours=2)
)
token_rows, token_totals = _tokens_by_provider(start_dt)

now = datetime.now(UTC).isoformat(timespec="seconds")
lines: list[str] = []
w = lines.append

w(f"# Reviewer-quality run — `{LABEL}`\n")
w(f"- **Dumped:** {now}")
w(f"- **Report id:** `{report.id}`  ·  **PR:** {report.pr_url}")
w(f"- **Head:** `{report.head_sha}`  ·  **run_count:** {report.run_count}  ·  **status:** {report.status}")
if RUN_SECONDS:
    w(f"- **Wall-clock:** {float(RUN_SECONDS):.0f}s ({float(RUN_SECONDS) / 60:.1f} min)")
w("")

w("## Config snapshot\n")
w(
    f"- runtime / model / effort: `{constants.REVIEW_RUNTIME_ADAPTER}` / `{constants.REVIEW_MODEL}` / `{constants.REVIEW_REASONING_EFFORT}`"
)
w(
    f"- single-chunk gate / chunk target / soft-max additions = {constants.SINGLE_CHUNK_GATE_ADDITIONS} / {constants.CHUNK_TARGET_ADDITIONS} / {constants.CHUNK_SOFT_MAX_ADDITIONS}"
)
w("")

w("## Funnel & cost\n")
w("| chunks | review units | raw issues | after dedup | passed validator |")
w("| ------ | ------------ | ---------- | ----------- | ---------------- |")
w(f"| {chunk_count} | {review_units} | {raw_issues} | {dedup_count} | {valid_count} |")
w("")
w(f"- **review units** = every (perspective|gap × chunk) sandbox review that ran = the model-held-constant cost proxy.")
if token_totals:
    w("- **local `$ai_generation` tokens (best-effort, may be pre-ingestion / partial):**")
    w("")
    w("  | model | gens | input tok | output tok |")
    w("  | ----- | ---- | --------- | ---------- |")
    for model, gens, tin, tout in token_rows:
        w(f"  | {model or '(unknown)'} | {int(gens)} | {int(tin)} | {int(tout)} |")
    g, ti, to = token_totals
    w(f"  | **total** | **{g}** | **{ti}** | **{to}** |")
elif isinstance(token_rows, str):
    w(f"- local `$ai_generation` tokens: {token_rows}")
else:
    w(
        "- local `$ai_generation` tokens: no matching events found in the window (likely emitted to a cloud project, or not yet ingested)."
    )
w("")

w("## Chunking\n")
if chunks:
    for ch in chunks.chunks:
        w(f"- **chunk {ch.chunk_id}** ({len(ch.files)} files): {', '.join(f.filename for f in ch.files)}")
else:
    w("- (no chunk_set artefact)")
w("")

w("## Per-review-unit breakdown\n")
w("| pass | chunk | perspective | raw issues |")
w("| ---- | ----- | ----------- | ---------- |")
for p, ch, src, n in perspective_rows:
    w(f"| {p} | {ch} | {src} | {n} |")
w("")

w("## Findings (post-dedup) with validator verdict\n")
if not findings:
    w("_(no findings)_")
for k, f in findings.items():
    v = verdicts.get(k)
    verdict = ("✅ VALID" if v.is_valid else "❌ dismissed") if v else "— no-verdict"
    adj = f" (validator→{v.adjusted_priority.value})" if v and v.adjusted_priority else ""
    cat = f" · {v.category}" if v and v.category else ""
    w(f"### [{verdict}] {f.priority.value}{adj}{cat} — {f.file}:{_fmt_lines(f.lines)}\n")
    w(
        f"**{f.title}**  \n_perspective: {f.source_perspective or '?'}  ·  directly-related: {f.is_directly_related_to_changes}_\n"
    )
    w(f"- **Problem:** {f.body}")
    if f.suggestion:
        w(f"- **Suggestion:** {f.suggestion}")
    if v:
        w(f"- **Validator:** {v.argumentation}")
    w("")

path = os.path.join(OUT_DIR, f"{LABEL}.md")
with open(path, "w") as fh:
    fh.write("\n".join(lines) + "\n")

print(  # noqa: T201 — playground eval script, stdout is the intended output channel
    f"DUMP_OK label={LABEL} chunks={chunk_count} units={review_units} raw={raw_issues} dedup={dedup_count} valid={valid_count} -> {path}"
)
