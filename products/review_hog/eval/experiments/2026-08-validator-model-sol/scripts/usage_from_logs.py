"""Token usage + cost per pipeline stage, read from the sandbox agent logs (fallback when local
`$ai_generation` telemetry is down).

Each ACP turn ends with `{"result": {"stopReason": ..., "usage": {inputTokens, outputTokens,
cachedReadTokens, cachedWriteTokens}}}` in the task run's JSONL log. `inputTokens` includes the
cached reads, so fresh input = inputTokens - cachedReadTokens.

Run via manage.py shell:

    RUN_START_EPOCH=<epoch> [RUN_END_EPOCH=<epoch>] \
    PRICES='{"gpt-5.6-sol":[in,out,cache_read],"claude-opus-5":[in,out,cache_read]}' \
    python manage.py shell -c "exec(open('products/review_hog/eval/experiments/2026-08-validator-model-sol/scripts/usage_from_logs.py').read())"

Prices are $/token (list price); cache writes are charged as fresh input.
"""

import os
import re
import json
from collections import defaultdict
from datetime import UTC, datetime

from posthog.storage import object_storage

from products.tasks.backend.models import TaskRun

_start = datetime.fromtimestamp(int(os.environ["RUN_START_EPOCH"]), tz=UTC)
_end = datetime.fromtimestamp(int(os.environ["RUN_END_EPOCH"]), tz=UTC) if os.environ.get("RUN_END_EPOCH") else None
_prices: dict[str, list[float]] = json.loads(os.environ.get("PRICES", "{}"))


def _stage_of(title: str) -> str:
    m = re.match(r"\[sandbox_prompt:([a-z0-9_-]+)\]", title or "")
    step = m.group(1) if m else ""
    for prefix, stage in (
        ("issues-review", "review"),
        ("blind-spots", "blind-spot"),
        ("validation", "validation"),
        ("chunking", "chunking"),
        ("dedup", "dedup"),
    ):
        if step.startswith(prefix):
            return stage
    return f"other:{step}" if step else "other"


def _model_of(data: str) -> str:
    m2 = re.search(r'"model":\s*"([\w.-]+)"', data)
    return m2.group(1) if m2 else "unknown"


runs = TaskRun.objects.filter(task__team_id=1, created_at__gte=_start).select_related("task").order_by("created_at")
if _end is not None:
    runs = runs.filter(created_at__lte=_end)

agg: dict[tuple[str, str], list[float]] = defaultdict(
    lambda: [0, 0, 0, 0, 0, 0]
)  # runs, turns, fresh_in, cache_read, cache_write, out
per_run: list[tuple[str, str, str, int, int, int, int, float]] = []
for run in runs:
    title = run.task.title or ""
    if "[sandbox_prompt:" not in title or not run.log_url:
        continue
    data = object_storage.read(run.log_url) or ""
    model = _model_of(data)
    turns = fresh = cread = cwrite = out = 0
    for line in data.splitlines():
        if '"usage"' not in line or '"stopReason"' not in line:
            continue
        try:
            res = json.loads(line)["notification"].get("result") or {}
        except Exception:
            continue
        u = res.get("usage") or {}
        if not u:
            continue
        turns += 1
        ci = int(u.get("cachedReadTokens") or 0)
        fresh += int(u.get("inputTokens") or 0) - ci
        cread += ci
        cwrite += int(u.get("cachedWriteTokens") or 0)
        out += int(u.get("outputTokens") or 0)
    secs = (run.updated_at - run.created_at).total_seconds()
    stage = _stage_of(title)
    per_run.append((stage, model, str(run.id)[:8], turns, fresh, cread, out, secs))
    a = agg[(stage, model)]
    a[0] += 1
    a[1] += turns
    a[2] += fresh
    a[3] += cread
    a[4] += cwrite
    a[5] += out


def _cost(model: str, fresh: float, cread: float, cwrite: float, out: float) -> str:
    p = _prices.get(model) or next((v for k, v in _prices.items() if model.startswith(k)), None)
    if not p:
        return "—"
    return f"${(fresh + cwrite) * p[0] + cread * p[2] + out * p[1]:.2f}"


print(f"window start={_start.isoformat()} end={_end.isoformat() if _end else 'open'}  runs={len(per_run)}")
print("| stage | model | runs | turns | fresh in | cache read | cache write | output | list $ |")
print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
tot = [0, 0, 0, 0, 0, 0]
for (stage, model), a in sorted(agg.items()):
    print(
        f"| {stage} | {model} | {a[0]} | {a[1]} | {a[2]:,} | {a[3]:,} | {a[4]:,} | {a[5]:,} | {_cost(model, a[2], a[3], a[4], a[5])} |"
    )
    for i in range(6):
        tot[i] += a[i]
print(f"| **total** | | {tot[0]} | {tot[1]} | {tot[2]:,} | {tot[3]:,} | {tot[4]:,} | {tot[5]:,} | |")
print()
print("| stage | model | run | turns | fresh in | cache read | output | wall s |")
print("| --- | --- | --- | --- | --- | --- | --- | --- |")
for row in per_run:
    print(
        "| "
        + " | ".join(f"{x:,}" if isinstance(x, int) else (f"{x:.0f}" if isinstance(x, float) else str(x)) for x in row)
        + " |"
    )
