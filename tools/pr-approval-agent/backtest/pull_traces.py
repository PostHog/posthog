#!/usr/bin/env python3
# ruff: noqa: T201
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""Pull stored review-prompt inputs from posthog.ai_events into data/traces/.

Resumable: traces already on disk are skipped. Traces older than the ai_events
retention window (~30 days) come back empty and are reported as expired.

Env: POSTHOG_PERSONAL_API_KEY (phx_..., query:read on project 2).
Usage: uv run pull_traces.py
"""

from __future__ import annotations

import os
import sys
import json
import time

import requests
from backtest_lib import data_dir, load_manifest

QUERY_URL = "https://us.posthog.com/api/environments/2/query/"
BATCH = 40


def wanted_trace_ids() -> list[str]:
    traces_dir = data_dir() / "traces"
    rows = load_manifest(cohort=None, discretionary_only=False)
    return sorted({r["trace_id"] for r in rows if not (traces_dir / f"{r['trace_id']}.json").exists()})


def fetch_batch(session: requests.Session, trace_ids: list[str]) -> dict[str, str]:
    # Traced-path runs (UUID ids, span names) need the first-turn span; gateway
    # runs (32-hex ids, no span names) have one event per trace.
    uuid_ids = [t for t in trace_ids if "-" in t]
    turn_ids = [t for t in trace_ids if "-" not in t]
    rows: dict[str, str] = {}
    for ids, where in ((uuid_ids, "AND span_name = 'generation_1'"), (turn_ids, "")):
        if not ids:
            continue
        id_list = ", ".join(f"'{t}'" for t in ids)
        sql = (
            "SELECT trace_id, argMin(toString(input), timestamp) FROM posthog.ai_events "
            f"WHERE trace_id IN ({id_list}) {where} GROUP BY trace_id"
        )
        resp = session.post(QUERY_URL, json={"query": {"kind": "HogQLQuery", "query": sql}}, timeout=120)
        resp.raise_for_status()
        rows.update({row[0]: row[1] for row in resp.json()["results"]})
    return rows


def main() -> None:
    api_key = os.environ.get("POSTHOG_PERSONAL_API_KEY", "")
    if not api_key:
        sys.exit("POSTHOG_PERSONAL_API_KEY not set")
    traces_dir = data_dir() / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {api_key}"

    todo = wanted_trace_ids()
    print(f"{len(todo)} traces to fetch")
    fetched = missing = 0
    for i in range(0, len(todo), BATCH):
        batch = todo[i : i + BATCH]
        rows = fetch_batch(session, batch)
        for trace_id in batch:
            raw = rows.get(trace_id)
            if raw is None:
                missing += 1
                continue
            # Store the parsed message list, not the double-encoded string.
            (traces_dir / f"{trace_id}.json").write_text(json.dumps(json.loads(raw), indent=1))
            fetched += 1
        print(f"  {i + len(batch)}/{len(todo)} (fetched {fetched}, expired {missing})")
        time.sleep(0.5)
    print(f"done: {fetched} fetched, {missing} expired/missing")


if __name__ == "__main__":
    main()
