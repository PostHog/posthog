from __future__ import annotations

import json

from parameterized import parameterized

from products.data_catalog.evals.scorers import MetricsCatalogBeforeAnswer, SemanticMetadataQueried


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


def _sql_call_updates(call_id: str, query: str, sequence: int, *, status: str = "completed") -> list[str]:
    return [
        _session_update(
            sequence,
            {
                "sessionUpdate": "tool_call",
                "toolCallId": call_id,
                "status": "pending",
                "rawInput": {},
                "title": "execute-sql",
                "_meta": {"claudeCode": {"toolName": "execute-sql"}},
            },
        ),
        _session_update(
            sequence + 1,
            {
                "sessionUpdate": "tool_call_update",
                "toolCallId": call_id,
                "status": None,
                "rawInput": {"query": query},
            },
        ),
        _session_update(
            sequence + 2,
            {
                "sessionUpdate": "tool_call_update",
                "toolCallId": call_id,
                "status": status,
                "rawOutput": "ok",
            },
        ),
    ]


def _sql_log(query: str, *, status: str = "completed") -> str:
    return "\n".join(_sql_call_updates("call-1", query, 1, status=status))


def _multi_sql_log(queries: list[str]) -> str:
    lines: list[str] = []
    for index, query in enumerate(queries):
        lines.extend(_sql_call_updates(f"call-{index + 1}", query, index * 3 + 1))
    return "\n".join(lines)


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


_CATALOG_LOOKUP = "SELECT name, status, is_drifted FROM system.information_schema.metrics"
_ANSWER_QUERY = "SELECT sum(toFloat(properties.amount_usd)) FROM events WHERE event = 'paid_bill'"
_SCHEMA_DISCOVERY = "SELECT table_name FROM system.information_schema.tables"


@parameterized.expand(
    [
        ("catalog_first", [_CATALOG_LOOKUP, _ANSWER_QUERY], 1.0),
        ("answer_before_catalog", [_ANSWER_QUERY, _CATALOG_LOOKUP], 0.0),
        ("discovery_does_not_count_as_answer", [_SCHEMA_DISCOVERY, _CATALOG_LOOKUP, _ANSWER_QUERY], 1.0),
        ("no_catalog_at_all", [_ANSWER_QUERY], 0.0),
    ]
)
def test_metrics_catalog_before_answer_ordering(_name: str, queries: list[str], expected_score: float) -> None:
    score = MetricsCatalogBeforeAnswer()._run_eval_sync(
        {"raw_log": _multi_sql_log(queries)},
        {"metrics_catalog_before_answer": {}},
    )

    assert score.score == expected_score
