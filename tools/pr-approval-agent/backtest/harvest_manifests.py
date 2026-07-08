#!/usr/bin/env python3
# ruff: noqa: T201
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""Harvest the backtest manifest from PostHog (team 2) into data/manifest.jsonl.

One row per distinct (repo, pr, cohort) with the latest review's fields, where
cohort is the stamphog_version that reviewed it ('unmarked' for pre-2.0 rows).
Trace ids come from a separate query against generation events, joined locally.

Run this soon after a version ships: posthog.ai_events retention (~30 days)
bounds how far back pull_traces.py can recover prompts.

Env: POSTHOG_PERSONAL_API_KEY (phx_..., query:read on project 2).
Usage: uv run harvest_manifests.py [--days 30]
"""

from __future__ import annotations

import os
import sys
import json
import argparse

import requests
from backtest_lib import data_dir

QUERY_URL = "https://us.posthog.com/api/environments/2/query/"
PAGE = 500

REVIEW_SQL = """
SELECT repo, pr, cohort,
       argMax(final, ts) AS final_verdict, argMax(gate, ts) AS gate_verdict,
       argMax(llm, ts) AS llm_verdict, argMax(ctype, ts) AS commit_type,
       argMax(subclass, ts) AS t1_subclass, argMax(risk, ts) AS llm_risk,
       argMax(files, ts) AS files_changed, argMax(lines, ts) AS lines_total,
       argMax(author, ts) AS author, argMax(commit, ts) AS commit,
       max(ts) AS ts_last
FROM (
    SELECT properties.stamphog_repo AS repo,
           toInt(properties.stamphog_pr_number) AS pr,
           coalesce(nullIf(properties.stamphog_version, ''), 'unmarked') AS cohort,
           properties.stamphog_final_verdict AS final,
           properties.stamphog_gate_verdict AS gate,
           properties.stamphog_llm_verdict AS llm,
           properties.stamphog_commit_type AS ctype,
           properties.stamphog_t1_subclass AS subclass,
           properties.stamphog_llm_risk AS risk,
           properties.stamphog_files_changed AS files,
           properties.stamphog_lines_total AS lines,
           properties.stamphog_author AS author,
           properties.stamphog_commit AS commit,
           timestamp AS ts
    FROM events
    WHERE event = 'stamphog_review_completed' AND timestamp >= now() - INTERVAL {days} DAY
)
GROUP BY repo, pr, cohort
ORDER BY repo, pr, cohort
LIMIT {limit} OFFSET {offset}
"""

# Traced-path runs share one UUID trace id across all their spans; gateway runs
# use one trace id per turn, but every turn's stored input contains the full
# message history, so the latest matching event per (repo, pr, cohort) always
# leads to a trace whose input carries the original review prompt.
TRACE_SQL = """
SELECT properties.stamphog_repo AS repo,
       toInt(properties.stamphog_pr_number) AS pr,
       coalesce(nullIf(properties.stamphog_version, ''), 'unmarked') AS cohort,
       argMax(properties.$ai_trace_id, timestamp) AS trace_id
FROM events
WHERE event = '$ai_generation'
  AND properties.ai_product IN ('stamphog', 'aio_stamphog')
  AND timestamp >= now() - INTERVAL {days} DAY
GROUP BY repo, pr, cohort
ORDER BY repo, pr, cohort
LIMIT {limit} OFFSET {offset}
"""


def run_paged(session: requests.Session, sql_template: str, days: int) -> list[list]:
    rows: list[list] = []
    offset = 0
    while True:
        sql = sql_template.format(days=days, limit=PAGE, offset=offset)
        resp = session.post(QUERY_URL, json={"query": {"kind": "HogQLQuery", "query": sql}}, timeout=120)
        resp.raise_for_status()
        page = resp.json()["results"]
        rows.extend(page)
        if len(page) < PAGE:
            return rows
        offset += PAGE


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    api_key = os.environ.get("POSTHOG_PERSONAL_API_KEY", "")
    if not api_key:
        sys.exit("POSTHOG_PERSONAL_API_KEY not set")
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {api_key}"

    reviews = run_paged(session, REVIEW_SQL, args.days)
    traces = run_paged(session, TRACE_SQL, args.days)
    trace_by_key = {(r[0], int(r[1]), r[2]): r[3] for r in traces}

    data_dir().mkdir(parents=True, exist_ok=True)
    out = data_dir() / "manifest.jsonl"
    keys = [
        "repo",
        "pr",
        "cohort",
        "final_verdict",
        "gate_verdict",
        "llm_verdict",
        "commit_type",
        "t1_subclass",
        "llm_risk",
        "files_changed",
        "lines_total",
        "author",
        "commit",
        "ts_last",
    ]
    with out.open("w") as fh:
        for row in reviews:
            record = dict(zip(keys, row))
            record["pr"] = int(record["pr"])
            record["trace_id"] = trace_by_key.get((record["repo"], record["pr"], record["cohort"]))
            fh.write(json.dumps(record) + "\n")

    with_trace = sum(1 for r in reviews if trace_by_key.get((r[0], int(r[1]), r[2])))
    print(f"{len(reviews)} manifest rows -> {out} ({with_trace} with trace_id)")


if __name__ == "__main__":
    main()
