from __future__ import annotations

import json

from parameterized import parameterized

from products.data_catalog.evals.scorers import SemanticMetadataQueried


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


def _sql_log(query: str, *, status: str = "completed") -> str:
    return "\n".join(
        [
            _session_update(
                1,
                {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "call-1",
                    "status": "pending",
                    "rawInput": {},
                    "title": "execute-sql",
                    "_meta": {"claudeCode": {"toolName": "execute-sql"}},
                },
            ),
            _session_update(
                2,
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "call-1",
                    "status": None,
                    "rawInput": {"query": query},
                },
            ),
            _session_update(
                3,
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "call-1",
                    "status": status,
                    "rawOutput": "ok",
                },
            ),
        ]
    )


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
