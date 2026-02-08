# LLMA (LLM Analytics) Dagster Location

Data pipelines for LLM analytics and observability.

## Overview

The LLMA location contains pipelines for aggregating and analyzing AI/LLM
events tracked through PostHog. These pipelines power analytics, cost tracking,
and observability features for AI products.

## Structure

```text
products/llm_analytics/dags/
├── README.md
├── daily_metrics/                 # Daily aggregation pipeline
│   ├── README.md                  # Detailed pipeline documentation
│   ├── config.py                  # Pipeline configuration
│   ├── main.py                    # Dagster asset and schedule
│   ├── utils.py                   # SQL generation helpers
│   └── sql/                       # Modular SQL templates
│       ├── event_counts.sql       # Event count metrics
│       ├── error_rates.sql        # Error rate metrics
│       ├── trace_counts.sql       # Unique trace count metrics
│       ├── session_counts.sql     # Unique session count metrics
│       ├── trace_error_rates.sql  # Trace-level error rates
│       └── pageview_counts.sql    # LLM Analytics pageview metrics
└── __init__.py

Tests: products/llm_analytics/dags/tests/daily_metrics/test_sql_metrics.py
```

## Pipelines

### Daily Metrics

Aggregates AI event metrics ($ai_trace, $ai_generation, $ai_span,
$ai_embedding) by team and date into the `llma_metrics_daily` ClickHouse
table.

Features:

- Modular SQL template system for easy metric additions
- Event counts, trace counts, session counts, and pageview metrics
- Error rates at event and trace level (proportions 0.0-1.0)
- Long-format schema for schema-less evolution
- Daily schedule at 6 AM UTC

See [daily_metrics/README.md](daily_metrics/README.md) for detailed
documentation.

## Local Development

The LLMA location is loaded in `.dagster_home/workspace.yaml` for local
development.

View in Dagster UI:

```bash
# Dagster runs on port 3030
open http://localhost:3030
```
