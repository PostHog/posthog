# Autoresearch: ClickHouse query **QUERY_ID**

## Metrics

- **Primary**: **PRIMARY_METRIC** (**METRIC_UNIT**, **DIRECTION** is better)
- **Secondary**: rows_read, bytes_read, peak_memory_mb

## How to run

- Benchmark: `./autoresearch.py`
- Checks: `./autoresearch_checks.py`

For optimization priority, timeout handling, adapter capabilities, and the
campaign loop: see the `clickhouse-autoresearch-campaign` skill — it ships
with `SKILL.md` and `orchestration.md` (siblings of each other). This file
is your durable per-campaign log — append findings, learnings, and decisions
here as the campaign progresses.

## What's been tried

- Baseline captured: pending
- Initial lanes: pending
- Key learning: pending
