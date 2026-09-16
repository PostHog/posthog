"""Token usage, reasoning tokens, effort and gateway-computed cost per pipeline stage, read straight from the
local Kafka topic the LLM gateway's `$ai_generation` events land in (they stay there when the local ingestion
consumer is down). Authoritative, unlike the earlier agent-log method: it sees every LLM call, not one per turn.

    TOPIC=events_plugin_ingestion_ai RUN_START_EPOCH=<epoch> RUN_END_EPOCH=<epoch> OUT=<json> \
    python products/review_hog/eval/experiments/2026-08-validator-model-sol/scripts/kafka_ai_usage.py

Run inside the flox env from the repo root (needs the `kafka` client and a reachable localhost:9092).
"""

import os
import json
from collections import defaultdict

from kafka import KafkaConsumer, TopicPartition

start_ms = int(os.environ["RUN_START_EPOCH"]) * 1000
end_ms = int(os.environ["RUN_END_EPOCH"]) * 1000 + 120_000
topic = os.environ.get("TOPIC", "events_plugin_ingestion")
c = KafkaConsumer(bootstrap_servers="localhost:9092", enable_auto_commit=False, consumer_timeout_ms=4000)
parts = [TopicPartition(topic, p) for p in c.partitions_for_topic(topic)]
c.assign(parts)
offs = c.offsets_for_times(dict.fromkeys(parts, start_ms))
ends = c.end_offsets(parts)
for p in parts:
    o = offs.get(p)
    c.seek(p, o.offset if o else ends[p])
rows = []
n = 0
for msg in c:
    n += 1
    if msg.timestamp > end_ms:
        break
    try:
        outer = json.loads(msg.value)
        data = outer.get("data")
        ev = json.loads(data) if isinstance(data, str) else (data or outer)
    except Exception:
        continue
    if ev.get("event") != "$ai_generation":
        continue
    pr = ev.get("properties", {})
    rows.append(
        {
            "ts": msg.timestamp,
            "stage": pr.get("ai_stage"),
            "model": pr.get("$ai_model"),
            "session": pr.get("$ai_session_id"),
            "in": pr.get("$ai_input_tokens") or 0,
            "cache_read": pr.get("$ai_cache_read_input_tokens") or 0,
            "cache_write": pr.get("$ai_cache_creation_input_tokens") or 0,
            "out": pr.get("$ai_output_tokens") or 0,
            "reasoning": pr.get("$ai_reasoning_tokens") or 0,
            "cost": pr.get("$ai_total_cost_usd"),
            "effort": pr.get("$ai_effort"),
            "keys": sorted(k for k in pr if "reason" in k or "effort" in k),
        }
    )
print(f"scanned {n} messages, {len(rows)} $ai_generation events in window")
agg: defaultdict[tuple[str | None, str | None], list[float]] = defaultdict(lambda: [0, 0, 0, 0, 0, 0, 0.0])
for r in rows:
    a = agg[(r["stage"], r["model"])]
    a[0] += 1
    a[1] += r["in"]
    a[2] += r["cache_read"]
    a[3] += r["cache_write"]
    a[4] += r["out"]
    a[5] += r["reasoning"]
    a[6] += float(r["cost"] or 0)
fam: defaultdict[tuple[str, str | None], list[float]] = defaultdict(lambda: [0, 0, 0, 0, 0, 0, 0.0])
fam_effort: defaultdict[tuple[str, str | None], set[str]] = defaultdict(set)
for r in rows:
    st = r["stage"] or "?"
    f = (
        "review"
        if st.startswith("issues-review")
        else "blind-spot"
        if st.startswith("blind-spots")
        else "validation"
        if st.startswith("validation")
        else st
    )
    a = fam[(f, r["model"])]
    a[0] += 1
    a[1] += r["in"]
    a[2] += r["cache_read"]
    a[3] += r["cache_write"]
    a[4] += r["out"]
    a[5] += r["reasoning"]
    a[6] += float(r["cost"] or 0)
    fam_effort[(f, r["model"])].add(str(r["effort"]))
print("| stage family | model | calls | input | cache read | output | reasoning | gateway $ | effort |")
print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
for (f, model), a in sorted(fam.items(), key=lambda kv: str(kv[0])):
    print(
        f"| {f} | {model} | {a[0]} | {a[1]:,} | {a[2]:,} | {a[4]:,} | {a[5]:,} | ${a[6]:.2f} | {','.join(sorted(fam_effort[(f, model)]))} |"
    )
print()
print("| stage | model | calls | input | cache read | cache write | output | reasoning | gateway $ |")
print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
for (stage, model), a in sorted(agg.items(), key=lambda kv: str(kv[0])):
    print(f"| {stage} | {model} | {a[0]} | {a[1]:,} | {a[2]:,} | {a[3]:,} | {a[4]:,} | {a[5]:,} | ${a[6]:.2f} |")
if rows:
    print("sample keys:", rows[0]["keys"], "effort:", rows[0]["effort"])
    print("sample effort by stage:", {r["stage"]: r["effort"] for r in rows})
json.dump(rows, open(os.environ.get("OUT", "/dev/null"), "w"), indent=1)
