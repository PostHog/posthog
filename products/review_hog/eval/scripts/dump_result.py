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
import re
from collections import defaultdict
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


# List prices per token, mirroring LiteLLM's cost map (the source of the gateway's
# `$ai_total_cost_usd`) as of 2026-07-06: (fresh_input, output, cache_read, cache_write).
# The write rate here is the 5-minute-TTL one (1.25× input); 1h-TTL writes bill at 2× input
# and the events don't carry the 5m/1h split, so `true_usd` prices all writes at 1.25× and the
# gateway's `$ai_cache_creation_cost_usd` (when emitted) is the accurate write-side cost.
_LIST_PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-sonnet-5": (2e-06, 1e-05, 2e-07, 2.5e-06),
    "claude-opus-4-8": (5e-06, 2.5e-05, 5e-07, 6.25e-06),
    "claude-fable-5": (1e-05, 5e-05, 1e-06, 1.25e-05),
    "claude-haiku-4-5": (1e-06, 5e-06, 1e-07, 1.25e-06),
    # Not a pinned model — appears when a session loses its model pin mid-run (session-restart
    # class); priced so a switched unit doesn't poison the run total.
    "claude-sonnet-4-6": (3e-06, 1.5e-05, 3e-07, 3.75e-06),
}

# Anthropic's long-context boundary for one request. The gateway's LiteLLM map prices these
# models flat, so the `>200K` column is a diagnostic count, not a pricing input.
_LONG_CTX_TOKENS = 200_000


def _price_for(model: str) -> tuple[float, float, float, float] | None:
    """List-price row for a model as `$ai_model` reports it; handles date-suffixed variants."""
    if model in _LIST_PRICES:
        return _LIST_PRICES[model]
    stripped = re.sub(r"-\d{8}$", "", model)
    if stripped in _LIST_PRICES:
        return _LIST_PRICES[stripped]
    for known, prices in _LIST_PRICES.items():
        if known in model:
            return prices
    return None


def _stage_of(task_title: str, ai_stage: str) -> str:
    """Pipeline stage of one gen: sandbox units carry `[sandbox_prompt:<step>]` in `task_title`;
    the one-shot chunking/dedup gateway calls carry `ai_stage` instead."""
    m = re.match(r"\[sandbox_prompt:([a-z0-9_-]+)\]", task_title or "")
    step = m.group(1) if m else (ai_stage or "")
    for prefix, stage in (
        ("issues-review", "review"),
        ("blind-spots", "blind-spot"),
        ("validation", "validation"),
        ("chunking", "chunking"),
        ("dedup", "dedup"),
        ("warmup", "warmup"),
    ):
        if step.startswith(prefix):
            return stage
    return f"other:{step}" if step else "other"


def _spend_rows(start_dt):
    """Per-gen `$ai_generation` rows since the run started, time-ordered. Raises on CH errors."""
    from posthog.clickhouse.client import sync_execute  # noqa: PLC0415 — optional, only for the spend tally

    return sync_execute(
        """
        SELECT
            timestamp,
            JSONExtractString(properties, '$ai_model') AS model,
            JSONExtractString(properties, 'ai_stage') AS ai_stage,
            JSONExtractString(properties, 'task_title') AS task_title,
            JSONExtractString(properties, 'task_run_id') AS task_run_id,
            toFloat64OrZero(JSONExtractString(properties, '$ai_input_tokens')) AS input_tokens,
            toFloat64OrZero(JSONExtractString(properties, '$ai_output_tokens')) AS output_tokens,
            toFloat64OrZero(JSONExtractString(properties, '$ai_cache_read_input_tokens')) AS cache_read,
            toFloat64OrZero(JSONExtractString(properties, '$ai_cache_creation_input_tokens')) AS cache_write,
            toFloat64OrNull(JSONExtractString(properties, '$ai_total_cost_usd')) AS gw_cost,
            toFloat64OrNull(JSONExtractString(properties, '$ai_input_cost_usd')) AS gw_input_cost,
            toFloat64OrNull(JSONExtractString(properties, '$ai_output_cost_usd')) AS gw_output_cost,
            toFloat64OrNull(JSONExtractString(properties, '$ai_cache_read_cost_usd')) AS gw_cache_read_cost,
            toFloat64OrNull(JSONExtractString(properties, '$ai_cache_creation_cost_usd')) AS gw_cache_write_cost
        FROM events
        WHERE event = '$ai_generation' AND timestamp >= %(start)s
        ORDER BY timestamp
        """,
        {"start": start_dt},
    )


def _fmt_tok(n: float) -> str:
    return f"{int(n):,}"


def _fmt_usd(x: float | None) -> str:
    return "—" if x is None else f"${x:,.2f}"


def _spend_report(start_dt):
    """Cache-aware spend section for the dump, plus a one-line stdout headline.

    `$ai_input_tokens` from the gateway is the FULL prompt (fresh + cache read + cache write) —
    summing it at input price is the old, naive method and overstates true cost ~5× on
    cache-heavy runs. Here every gen splits into fresh (`input - read - write`, 1×) /
    cache write (1.25×) / cache read (0.1×) / output per (model × stage); `true_usd` prices that
    split at list, `gw_usd` is the gateway's LiteLLM-computed `$ai_total_cost_usd`, and the
    per-side `$ai_*_cost_usd` fields cross-check the split. Returns (md_lines, headline);
    never raises — spend is a secondary metric next to the review-unit count.
    """
    try:
        rows = _spend_rows(start_dt)
    except Exception as e:  # pragma: no cover - best effort
        return [f"- cache-aware spend: unavailable ({type(e).__name__}: {e})"], None
    if not rows:
        return [
            "- cache-aware spend: no `$ai_generation` events in the window "
            "(likely emitted to a cloud project, or not yet ingested)."
        ], None

    by_bucket: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0] * 6)  # gens/fresh/write/read/out/longctx
    true_by_bucket: dict[tuple[str, str], float | None] = defaultdict(float)
    gw_by_bucket: dict[tuple[str, str], float] = defaultdict(float)
    gw_missing = 0
    naive_usd = 0.0
    gw_sides = {"input": [0.0, 0], "output": [0.0, 0], "cache_read": [0.0, 0], "cache_write": [0.0, 0]}
    true_sides = {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0}
    turn1: dict[str, tuple] = {}  # task_run_id -> (ts, stage, step, cache_read, cache_write); rows are time-ordered

    for ts, model, ai_stage, task_title, task_run_id, tin, tout, cread, cwrite, gw, gwi, gwo, gwr, gww in rows:
        stage = _stage_of(task_title, ai_stage)
        fresh = max(0.0, tin - cread - cwrite)
        key = (model or "(unknown)", stage)
        agg = by_bucket[key]
        agg[0] += 1
        agg[1] += fresh
        agg[2] += cwrite
        agg[3] += cread
        agg[4] += tout
        agg[5] += 1 if tin > _LONG_CTX_TOKENS else 0

        prices = _price_for(model or "")
        if prices is None:
            true_by_bucket[key] = None
        else:
            p_in, p_out, p_read, p_write = prices
            if true_by_bucket[key] is not None:
                true_by_bucket[key] += fresh * p_in + cwrite * p_write + cread * p_read + tout * p_out
            naive_usd += tin * p_in + tout * p_out
            true_sides["input"] += fresh * p_in
            true_sides["output"] += tout * p_out
            true_sides["cache_read"] += cread * p_read
            true_sides["cache_write"] += cwrite * p_write
        if gw is None:
            gw_missing += 1
        else:
            gw_by_bucket[key] += gw
        for side, value in (("input", gwi), ("output", gwo), ("cache_read", gwr), ("cache_write", gww)):
            if value is not None:
                gw_sides[side][0] += value
                gw_sides[side][1] += 1
        if task_run_id and task_run_id not in turn1 and stage in ("review", "blind-spot", "validation", "warmup"):
            step_match = re.match(r"\[sandbox_prompt:([a-z0-9_-]+)\]", task_title or "")
            turn1[task_run_id] = (ts, stage, step_match.group(1) if step_match else "", cread, cwrite, {model})
        elif task_run_id in turn1:
            # Track every model the unit's session touched — a set > 1 exposes a silent mid-session
            # model switch (e.g. the overload rescue), which breaks cache sharing and cost pinning.
            turn1[task_run_id][5].add(model)

    lines: list[str] = []
    w = lines.append
    w("### Cache-aware spend (local `$ai_generation`, best-effort)\n")
    w("| model | stage | gens | fresh in | cache write | cache read | output | >200K gens | true $ | gw $ |")
    w("| ----- | ----- | ---- | -------- | ----------- | ---------- | ------ | ---------- | ------ | ---- |")
    totals = [0.0] * 6
    true_total = 0.0
    gw_total = 0.0
    unpriced: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])  # model -> [gens, gw_usd]
    for key in sorted(by_bucket, key=lambda k: -gw_by_bucket.get(k, 0.0)):
        model, stage = key
        agg = by_bucket[key]
        t = true_by_bucket[key]
        g = gw_by_bucket.get(key, 0.0)
        w(
            f"| {model} | {stage} | {int(agg[0])} | {_fmt_tok(agg[1])} | {_fmt_tok(agg[2])} | {_fmt_tok(agg[3])} "
            f"| {_fmt_tok(agg[4])} | {int(agg[5])} | {_fmt_usd(t)} | {_fmt_usd(g)} |"
        )
        for i in range(6):
            totals[i] += agg[i]
        if t is None:
            unpriced[model][0] += agg[0]
            unpriced[model][1] += g
        else:
            true_total += t
        gw_total += g
    w(
        f"| **total** |  | **{int(totals[0])}** | **{_fmt_tok(totals[1])}** | **{_fmt_tok(totals[2])}** "
        f"| **{_fmt_tok(totals[3])}** | **{_fmt_tok(totals[4])}** | **{int(totals[5])}** "
        f"| **{_fmt_usd(true_total)}** | **{_fmt_usd(gw_total)}** |"
    )
    w("")
    gw_priced = gw_total - sum(g for _gens, g in unpriced.values())
    w(
        "- `true $` = list-price back-calc (fresh 1× + cache write 1.25× + cache read 0.1× + output); "
        "`gw $` = gateway `$ai_total_cost_usd` (LiteLLM). "
        + (f"Δ (priced buckets) = {(gw_priced - true_total) / true_total:+.1%}." if true_total else "Δ not computable.")
    )
    for model, (gens, g) in unpriced.items():
        w(f"- `true $` total excludes unpriced model `{model}` ({int(gens)} gen(s), gw {_fmt_usd(g)}).")
    if gw_missing:
        w(f"- {gw_missing} gen(s) had no `$ai_total_cost_usd` — `gw $` undercounts by those gens.")
    if naive_usd and true_total:
        w(
            f"- naive method (all prompt tokens at input price): ${naive_usd:,.2f} — "
            f"{naive_usd / true_total:.1f}× the true cost; never gate on it."
        )
    if any(count for _total, count in gw_sides.values()):
        input_total, input_count = gw_sides["input"]
        read_total, read_count = gw_sides["cache_read"]
        write_total, write_count = gw_sides["cache_write"]
        out_total, out_count = gw_sides["output"]
        w(
            "- gateway per-side cross-check (gens emitting the field; LiteLLM's `input_cost` "
            "is the whole input side, cache included):"
        )
        checks = [
            (
                "input side (fresh + cache write + cache read)",
                input_total,
                input_count,
                true_sides["input"] + true_sides["cache_write"] + true_sides["cache_read"],
            ),
            ("· of which cache read", read_total, read_count, true_sides["cache_read"]),
            ("· of which cache write", write_total, write_count, true_sides["cache_write"]),
            ("· of which fresh (derived)", input_total - read_total - write_total, input_count, true_sides["input"]),
            ("output", out_total, out_count, true_sides["output"]),
        ]
        for label, total, count, true_value in checks:
            delta = f" (true ${true_value:,.4f}, Δ {(total - true_value) / true_value:+.1%})" if true_value else ""
            w(f"  - {label}: ${total:,.4f} over {count} gen(s){delta}")
        if write_count and true_sides["cache_write"] and write_total > true_sides["cache_write"] * 1.05:
            w(
                "  - write-side excess over the 1.25× back-calc = 1h-TTL cache writes "
                "(billed 2×; the token split can't see the TTL)."
            )
    if totals[5]:
        w(
            f"- {int(totals[5])} gen(s) ran with >200K-token prompts; the gateway map prices these models "
            "flat, so no long-context premium is included in either column."
        )
    w("")

    if turn1:
        hits = sum(1 for _ts, _stage, _step, cread, _cwrite, _models in turn1.values() if cread > 0)
        w("### Turn-1 cache reads per sandbox unit (cross-sandbox sharing tripwire)\n")
        w("| unit | step | first gen | t1 cache read | t1 cache write | models |")
        w("| ---- | ---- | --------- | ------------- | -------------- | ------ |")
        for run_id, (ts, stage, step, cread, cwrite, models) in sorted(turn1.items(), key=lambda kv: kv[1][0]):
            model_cell = ", ".join(sorted(models)) + (" ⚠️SWITCHED" if len(models) > 1 else "")
            w(
                f"| …{run_id[-8:]} | {step or stage} | {ts:%H:%M:%S} | {_fmt_tok(cread)} "
                f"| {_fmt_tok(cwrite)} | {model_cell} |"
            )
        w("")
        w(f"- units with turn-1 cache_read > 0: **{hits}/{len(turn1)}** (report the distribution, not a median).")
        switched = [run_id for run_id, v in turn1.items() if len(v[5]) > 1]
        if switched:
            w(
                f"- ⚠️ {len(switched)} unit(s) switched models mid-session (overload rescue?) — "
                "cache sharing and cost pinning are broken for them: " + ", ".join(f"…{r[-8:]}" for r in switched)
            )
        # Fork collision tracker (warm-up+fork arm): per chunk, forked units landing inside the
        # seconds-wide cache-write window each rewrite the shared replay prefix. 1 writer + N readers
        # is the ideal; more writers = harmless double-writes (~$0.10 each) worth a stagger if common.
        by_chunk: dict[str, list[tuple]] = defaultdict(list)
        for _run_id, (_ts, stage, step, cread, cwrite, _models) in turn1.items():
            m = re.search(r"-c(\d+)$", step)
            if m and stage in ("review", "blind-spot"):
                by_chunk[m.group(1)].append((cread, cwrite))
        if any(step.startswith("warmup") for _ts, _stage, step, _cr, _cw, _m in turn1.values()):
            for chunk_id in sorted(by_chunk):
                units = by_chunk[chunk_id]
                writers = sum(1 for _cread, cwrite in units if cwrite > 20_000)
                w(
                    f"- chunk {chunk_id} forked units: **{writers} prefix writer(s) / "
                    f"{len(units) - writers} reader(s)** at turn 1 (1 writer is the ideal fork)."
                )
        w("")

    headline = (
        f"SPEND gens={int(totals[0])} true_usd={_fmt_usd(true_total)} gw_usd={_fmt_usd(gw_total)} "
        f"naive_usd={_fmt_usd(naive_usd) if naive_usd else '—'} "
        f"turn1_hits={sum(1 for v in turn1.values() if v[3] > 0)}/{len(turn1)} "
        f"model_switches={sum(1 for v in turn1.values() if len(v[5]) > 1)}"
    )
    return lines, headline


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

# Spend (best-effort).
start_dt = (
    datetime.fromtimestamp(RUN_START_EPOCH, tz=UTC) if RUN_START_EPOCH else datetime.now(UTC) - timedelta(hours=2)
)
spend_lines, spend_headline = _spend_report(start_dt)

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
    f"DUMP_OK label={LABEL} chunks={chunk_count} units={review_units} raw={raw_issues} dedup={dedup_count} valid={valid_count} -> {path}"
)
if spend_headline:
    print(spend_headline)  # noqa: T201 — playground eval script, stdout is the intended output channel
