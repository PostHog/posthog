"""Dump the latest team-1 ReviewHog run to a per-config `.md` for reviewer-quality experiments.

Run via manage.py shell so Django is configured; set OUT_DIR to the experiment's runs/ directory:

    LABEL=C0-baseline RUN_SECONDS=812 RUN_START_EPOCH=1751... OUT_DIR=products/review_hog/eval/experiments/<exp>/runs \
        python manage.py shell -c "exec(open('products/review_hog/eval/scripts/dump_result.py').read())"

Reads the most-recent `ReviewReport` for team 1 (the eval team) and its artefacts, then writes
`<OUT_DIR>/<LABEL>.md` with: the config snapshot, the chunking, the
per-perspective breakdown, the raw→dedup→valid funnel, the review-unit count, wall-clock, a
best-effort cache-aware local `$ai_generation` spend split (fresh/cache-write/cache-read/output
per model × stage, list-price `true_usd` vs gateway `gw_usd`, per-unit turn-1 cache reads), and
the full findings list with validator verdicts.
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
from products.review_hog.eval.scripts.spend_report import spend_report

TEAM = 1
LABEL = os.environ.get("LABEL", "unlabeled")
RUN_SECONDS = os.environ.get("RUN_SECONDS")
RUN_START_EPOCH = float(os.environ.get("RUN_START_EPOCH", "0"))
OUT_DIR = os.environ.get("OUT_DIR", "products/review_hog/eval/experiments/2026-07-reviewer-topology/runs")


def _fmt_lines(lines) -> str:
    return ",".join(f"{lr.start}-{lr.end}" if lr.end else str(lr.start) for lr in lines) or "—"


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

# Perspective results → raw issue count + per-(pass,chunk) breakdown (+ completion timestamps for
# stage timing; pass >= 1000 is the blind-spot sweep's reserved pass number).
perspective_rows: list[tuple[int, int, str, int]] = []  # (pass, chunk, source_perspective, n_issues)
raw_issues = 0
wave_done_ts: list[datetime] = []
blind_done_ts: list[datetime] = []
for a in arts:
    if a.type == ReviewReportArtefact.ArtefactType.PERSPECTIVE_RESULT:
        c = parse_artefact_content(a.type, a.content)
        if isinstance(c, PerspectiveResultArtefact):
            n = len(c.review.issues)
            raw_issues += n
            src = next((i.source_perspective for i in c.review.issues if i.source_perspective), "?")
            perspective_rows.append((c.pass_number, c.chunk_id, src, n))
            (blind_done_ts if c.pass_number >= 1000 else wave_done_ts).append(a.created_at)
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


# Stage timing — wall-clock derived from artefact `created_at` (each stage/unit persists on
# completion). Valid for fresh, non-resumed runs; a resumed run reuses old artefacts and skews this.
def _stage_secs(a: datetime | None, b: datetime | None) -> float | None:
    return (b - a).total_seconds() if a and b and b > a else None


def _fmt_dur(secs: float | None) -> str:
    if secs is None:
        return "—"
    m, s = divmod(int(secs), 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


_ts: dict[str, list[datetime]] = {}
for a in arts:
    _ts.setdefault(str(a.type), []).append(a.created_at)
_snapshot_ts = max(_ts.get("pr_snapshot", []), default=None)
_chunk_ts = max(_ts.get("chunk_set", []), default=None)
_select_ts = max(_ts.get("perspective_selection", []), default=None)
_wave_end = max(wave_done_ts, default=None)
_blind_end = max(blind_done_ts, default=None)
_finding_first = min(_ts.get("issue_finding", []), default=None)  # dedup persists findings in one batch
_verdict_end = max(_ts.get("validation_verdict", []), default=None)
stage_timing_rows = [
    ("fetch + snapshot", _stage_secs(report.created_at, _snapshot_ts)),
    ("chunking", _stage_secs(_snapshot_ts, _chunk_ts)),
    ("perspective selection", _stage_secs(_chunk_ts, _select_ts)),
    ("review wave (perspectives)", _stage_secs(_select_ts, _wave_end)),
    ("blind-spot sweep", _stage_secs(_wave_end, _blind_end)),
    ("dedup (incl. combine/clean)", _stage_secs(_blind_end or _wave_end, _finding_first)),
    ("validation", _stage_secs(_finding_first, _verdict_end)),
]
review_stage_secs = _stage_secs(_select_ts, _blind_end or _wave_end)

# Spend (best-effort).
start_dt = (
    datetime.fromtimestamp(RUN_START_EPOCH, tz=UTC) if RUN_START_EPOCH else datetime.now(UTC) - timedelta(hours=2)
)
spend_lines, spend_headline = spend_report(start_dt)

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
w(
    f"- **review units** = every (perspective|blind-spot × chunk) sandbox review that ran = the model-held-constant cost proxy."
)
for line in spend_lines:
    w(line)
w("")

w("## Stage timing (wall-clock)\n")
w("| stage | duration |")
w("| ----- | -------- |")
for stage_name, stage_secs in stage_timing_rows:
    w(f"| {stage_name} | {_fmt_dur(stage_secs)} |")
w("")
w(
    f"- **Review stage total (selection → last finder unit, wave + blind-spot):** {_fmt_dur(review_stage_secs)} — the reviewer-model speed comparison number."
)
w("- Derived from artefact `created_at` (persisted on completion); only meaningful for fresh, non-resumed runs.")
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
for pass_no, chunk_id, source, raw_count in perspective_rows:
    w(f"| {pass_no} | {chunk_id} | {source} | {raw_count} |")
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
    f"DUMP_OK label={LABEL} chunks={chunk_count} units={review_units} raw={raw_issues} dedup={dedup_count} valid={valid_count} review_stage={_fmt_dur(review_stage_secs)} -> {path}"
)
if spend_headline:
    print(spend_headline)  # noqa: T201 — playground eval script, stdout is the intended output channel
