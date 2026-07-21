from __future__ import annotations

import json
from typing import Any

from parameterized import parameterized

from products.data_catalog.evals.scorers import (
    CanonicalMetricRun,
    MetricsCatalogBeforeDataDiscovery,
    SemanticMetadataQueried,
)

CATALOG_QUERY = "SELECT name, status, is_drifted FROM system.information_schema.metrics"
METRIC_NAME = "top_customers_mrr_by_business_model"


def _session_update(sequence: int, update: dict) -> str:
    return json.dumps(
        {
            "type": "notification",
            "timestamp": f"2026-07-16T10:00:{sequence:02d}.000Z",
            "notification": {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {"sessionId": "session", "update": update},
            },
        }
    )


def _tool_log(calls: list[tuple[str, dict[str, Any], str]]) -> str:
    updates: list[str] = []
    sequence = 0
    for index, (tool_name, raw_input, status) in enumerate(calls, start=1):
        call_id = f"call-{index}"
        sequence += 1
        updates.append(
            _session_update(
                sequence,
                {
                    "sessionUpdate": "tool_call",
                    "toolCallId": call_id,
                    "status": "pending",
                    "rawInput": raw_input,
                    "title": tool_name,
                    "_meta": {"claudeCode": {"toolName": tool_name}},
                },
            )
        )
        sequence += 1
        updates.append(
            _session_update(
                sequence,
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": call_id,
                    "status": status,
                    "rawOutput": "error" if status == "failed" else "ok",
                },
            )
        )
    return "\n".join(updates)


def _sql_log(query: str, *, status: str = "completed") -> str:
    return _tool_log([("execute-sql", {"query": query}, status)])


@parameterized.expand(
    [
        (
            "certification_lookup",
            "SELECT table_name, certification FROM system.information_schema.tables",
            "information_schema.tables",
            ["certification"],
            "completed",
            1.0,
        ),
        (
            "relationship_lookup",
            "SELECT source_table, confidence, reasoning FROM system.information_schema.relationships",
            "information_schema.relationships",
            ["confidence", "reasoning"],
            "completed",
            1.0,
        ),
        (
            "missing_column",
            "SELECT table_name FROM system.information_schema.tables",
            "information_schema.tables",
            ["certification"],
            "completed",
            0.0,
        ),
        (
            "wrong_surface",
            "SELECT certification FROM system.information_schema.columns",
            "information_schema.tables",
            ["certification"],
            "completed",
            0.0,
        ),
        (
            "failed_call",
            "SELECT table_name, certification FROM system.information_schema.tables",
            "information_schema.tables",
            ["certification"],
            "failed",
            0.0,
        ),
    ]
)
def test_semantic_metadata_queried(
    _name: str,
    query: str,
    surface: str,
    required_columns: list[str],
    status: str,
    expected_score: float,
) -> None:
    score = SemanticMetadataQueried()._run_eval_sync(
        {"raw_log": _sql_log(query, status=status)},
        {"semantic_metadata_queried": {"surface": surface, "required_columns": required_columns}},
    )

    assert score.score == expected_score


@parameterized.expand(
    [
        (
            "catalog_first",
            [
                ("execute-sql", {"query": CATALOG_QUERY}, "completed"),
                ("read-data-schema", {"kind": "data_warehouse", "name": "paid_bills"}, "completed"),
            ],
            1.0,
        ),
        (
            "tool_discovery_allowed",
            [
                ("Read", {"file_path": "/root/.claude/skills/querying-posthog-data/SKILL.md"}, "completed"),
                ("learn", {"topic": "analytics"}, "completed"),
                ("exec", {"command": "learn analytics"}, "completed"),
                ("exec", {"command": "search metrics"}, "completed"),
                ("exec", {"command": "info execute-sql"}, "completed"),
                ("ToolSearch", {"query": "select:mcp__posthog__execute-sql"}, "completed"),
                ("execute-sql", {"query": CATALOG_QUERY}, "completed"),
            ],
            1.0,
        ),
        (
            "schema_before_catalog",
            [
                ("read-data-schema", {"kind": "data_warehouse", "name": "paid_bills"}, "completed"),
                ("execute-sql", {"query": CATALOG_QUERY}, "completed"),
            ],
            0.0,
        ),
        (
            "sql_before_catalog",
            [
                ("execute-sql", {"query": "SELECT * FROM paid_bills LIMIT 1"}, "completed"),
                ("execute-sql", {"query": CATALOG_QUERY}, "completed"),
            ],
            0.0,
        ),
        (
            "query_tool_before_catalog",
            [
                ("query-trends", {"query": {"kind": "TrendsQuery"}}, "completed"),
                ("execute-sql", {"query": CATALOG_QUERY}, "completed"),
            ],
            0.0,
        ),
        (
            "regional_mcp_before_catalog",
            [
                ("mcp__posthog_us__exec", {"command": "SELECT count() FROM events"}, "completed"),
                ("execute-sql", {"query": CATALOG_QUERY}, "completed"),
            ],
            0.0,
        ),
        (
            "failed_catalog_does_not_unlock",
            [
                ("execute-sql", {"query": CATALOG_QUERY}, "failed"),
                ("read-data-schema", {"kind": "data_warehouse", "name": "paid_bills"}, "completed"),
            ],
            0.0,
        ),
        (
            "failed_catalog_then_success",
            [
                ("execute-sql", {"query": CATALOG_QUERY}, "failed"),
                ("execute-sql", {"query": CATALOG_QUERY}, "completed"),
                ("execute-sql", {"query": "SELECT * FROM paid_bills LIMIT 1"}, "completed"),
            ],
            1.0,
        ),
    ]
)
def test_metrics_catalog_before_data_discovery(
    _name: str,
    calls: list[tuple[str, dict[str, Any], str]],
    expected_score: float,
) -> None:
    score = MetricsCatalogBeforeDataDiscovery()._run_eval_sync(
        {"raw_log": _tool_log(calls)},
        {"metrics_catalog_before_data_discovery": {}},
    )

    assert score.score == expected_score


@parameterized.expand(
    [
        (
            "succeeded",
            [
                ("execute-sql", {"query": CATALOG_QUERY}, "completed"),
                ("data-catalog-metric-run", {"name": METRIC_NAME}, "completed"),
            ],
            {"metric_name": METRIC_NAME, "outcome": "succeeded"},
            1.0,
        ),
        (
            "failed",
            [
                ("execute-sql", {"query": CATALOG_QUERY}, "completed"),
                ("data-catalog-metric-run", {"name": METRIC_NAME}, "failed"),
            ],
            {"metric_name": METRIC_NAME, "outcome": "failed"},
            1.0,
        ),
        (
            "not_called",
            [("execute-sql", {"query": CATALOG_QUERY}, "completed")],
            {"outcome": "not_called"},
            1.0,
        ),
        (
            "wrong_name",
            [
                ("execute-sql", {"query": CATALOG_QUERY}, "completed"),
                ("data-catalog-metric-run", {"name": "monthly_recurring_revenue"}, "completed"),
            ],
            {"metric_name": METRIC_NAME, "outcome": "succeeded"},
            0.0,
        ),
        (
            "wrong_order",
            [
                ("data-catalog-metric-run", {"name": METRIC_NAME}, "completed"),
                ("execute-sql", {"query": CATALOG_QUERY}, "completed"),
            ],
            {"metric_name": METRIC_NAME, "outcome": "succeeded"},
            0.0,
        ),
        (
            "unexpected_error",
            [
                ("execute-sql", {"query": CATALOG_QUERY}, "completed"),
                ("data-catalog-metric-run", {"name": METRIC_NAME}, "failed"),
            ],
            {"metric_name": METRIC_NAME, "outcome": "succeeded"},
            0.0,
        ),
        (
            "mixed_outcomes_do_not_pass",
            [
                ("execute-sql", {"query": CATALOG_QUERY}, "completed"),
                ("data-catalog-metric-run", {"name": METRIC_NAME}, "failed"),
                ("data-catalog-metric-run", {"name": METRIC_NAME}, "completed"),
            ],
            {"metric_name": METRIC_NAME, "outcome": "failed"},
            0.0,
        ),
        (
            "unexpected_call",
            [
                ("execute-sql", {"query": CATALOG_QUERY}, "completed"),
                ("data-catalog-metric-run", {"name": METRIC_NAME}, "completed"),
            ],
            {"outcome": "not_called"},
            0.0,
        ),
    ]
)
def test_canonical_metric_run(
    _name: str,
    calls: list[tuple[str, dict[str, Any], str]],
    spec: dict[str, str],
    expected_score: float,
) -> None:
    score = CanonicalMetricRun()._run_eval_sync(
        {"raw_log": _tool_log(calls)},
        {"canonical_metric_run": spec},
    )

    assert score.score == expected_score


@parameterized.expand(
    [
        (MetricsCatalogBeforeDataDiscovery(), "metrics_catalog_before_data_discovery"),
        (CanonicalMetricRun(), "canonical_metric_run"),
    ]
)
def test_new_catalog_scorers_self_skip_when_not_requested(scorer: Any, scorer_name: str) -> None:
    score = scorer._run_eval_sync({"raw_log": _tool_log([])}, {})

    assert score.name == scorer_name
    assert score.score is None
