from __future__ import annotations

import json
from typing import Any

from parameterized import parameterized

from products.data_catalog.evals.constants import (
    DEPRECATION_CANONICAL_SOURCE_NAME,
    DEPRECATION_STALE_SOURCE_NAME,
    EVAL_DESCRIPTION_CHAR_LIMIT,
    METRIC_CREATE_TOOL,
    METRIC_UPDATE_TOOL,
)
from products.data_catalog.evals.scorers import (
    AnswerTableQueried,
    AnswerValueStated,
    CanonicalMetricRun,
    DeprecationProposed,
    MetricDescriptionConcise,
    MetricDescriptionQuality,
    MetricsCatalogBeforeAnswer,
    MetricsCatalogBeforeDataDiscovery,
    MetricsCatalogQueried,
    NoncanonicalBadgeShown,
    SemanticMetadataQueried,
    TrustBadgeShown,
)

CATALOG_QUERY = "SELECT name, status, is_drifted FROM system.information_schema.metrics"
METRIC_NAME = "top_customers_mrr_by_business_model"
PROPOSE_TOOL = "data-catalog-certification-propose"
DEPRECATION_SEED = {
    "deprecation_candidate": {
        "stale_table_name": DEPRECATION_STALE_SOURCE_NAME,
        "stale_table_id": "stale-uuid",
        "canonical_table_name": DEPRECATION_CANONICAL_SOURCE_NAME,
        "canonical_table_id": "canonical-uuid",
    }
}


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
            "star_projection_reads_every_column",
            "SELECT * FROM system.information_schema.tables WHERE position(lower(table_name), 'acv') > 0",
            "information_schema.tables",
            ["description"],
            "completed",
            1.0,
        ),
        (
            "star_over_a_subquery_without_the_column",
            "SELECT * FROM (SELECT table_name FROM system.information_schema.tables)",
            "information_schema.tables",
            ["description"],
            "completed",
            0.0,
        ),
        (
            "star_inside_count_is_not_a_projection",
            "SELECT count(*) FROM system.information_schema.tables",
            "information_schema.tables",
            ["description"],
            "completed",
            0.0,
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


def test_metric_list_counts_as_a_catalog_lookup() -> None:
    calls: list[tuple[str, dict[str, Any], str]] = [
        ("metric-list", {"offset": 0, "limit": 100}, "completed"),
        ("execute-sql", {"query": "SELECT * FROM paid_bills LIMIT 1"}, "completed"),
    ]
    output = {"raw_log": _tool_log(calls)}

    queried = MetricsCatalogQueried()._run_eval_sync(output, {"metrics_catalog_queried": {}})
    before_answer = MetricsCatalogBeforeAnswer()._run_eval_sync(output, {"metrics_catalog_before_answer": {}})
    before_discovery = MetricsCatalogBeforeDataDiscovery()._run_eval_sync(
        output, {"metrics_catalog_before_data_discovery": {}}
    )

    assert queried.score == 1.0
    assert before_answer.score == 1.0
    assert before_discovery.score == 1.0


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
            "succeeded_after_metric_list",
            [
                ("metric-list", {"offset": 0, "limit": 100}, "completed"),
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
        (
            "deprecates_stale_by_name",
            [
                (
                    PROPOSE_TOOL,
                    {"table_name": DEPRECATION_STALE_SOURCE_NAME, "proposed_status": "deprecated"},
                    "completed",
                )
            ],
            1.0,
        ),
        (
            "deprecates_stale_by_id",
            [(PROPOSE_TOOL, {"table_id": "stale-uuid", "proposed_status": "deprecated"}, "completed")],
            1.0,
        ),
        (
            "certifying_the_stale_source_is_not_a_deprecation",
            [
                (
                    PROPOSE_TOOL,
                    {"table_name": DEPRECATION_STALE_SOURCE_NAME, "proposed_status": "certified"},
                    "completed",
                )
            ],
            0.0,
        ),
        (
            "omitting_proposed_status_is_not_a_deprecation",
            [(PROPOSE_TOOL, {"table_name": DEPRECATION_STALE_SOURCE_NAME}, "completed")],
            0.0,
        ),
        (
            "deprecating_the_canonical_source_fails",
            [
                (
                    PROPOSE_TOOL,
                    {"table_name": DEPRECATION_CANONICAL_SOURCE_NAME, "proposed_status": "deprecated"},
                    "completed",
                )
            ],
            0.0,
        ),
        (
            "deprecating_canonical_dominates_a_correct_stale_call",
            [
                (
                    PROPOSE_TOOL,
                    {"table_name": DEPRECATION_STALE_SOURCE_NAME, "proposed_status": "deprecated"},
                    "completed",
                ),
                (
                    PROPOSE_TOOL,
                    {"table_name": DEPRECATION_CANONICAL_SOURCE_NAME, "proposed_status": "deprecated"},
                    "completed",
                ),
            ],
            0.0,
        ),
        (
            "no_propose_call",
            [("execute-sql", {"query": CATALOG_QUERY}, "completed")],
            0.0,
        ),
        (
            "failed_propose_does_not_count",
            [(PROPOSE_TOOL, {"table_name": DEPRECATION_STALE_SOURCE_NAME, "proposed_status": "deprecated"}, "failed")],
            0.0,
        ),
    ]
)
def test_deprecation_proposed(
    _name: str,
    calls: list[tuple[str, dict[str, Any], str]],
    expected_score: float,
) -> None:
    score = DeprecationProposed()._run_eval_sync(
        {"raw_log": _tool_log(calls), "seed": DEPRECATION_SEED},
        {"deprecation_proposed": {}},
    )

    assert score.score == expected_score


@parameterized.expand(
    [
        ("dollars_with_trailing_zero", "437.50", "We collected $437.50 in paid revenue.", 1.0),
        ("dollars_without_trailing_zero", "437.50", "Collected revenue: 437.5 USD.", 1.0),
        ("thousands_separator", "1387.50", "Total is $1,387.50.", 1.0),
        ("raw_cents", "437.50", "The sum of amount is 43,750.", 0.0),
        ("longer_number_with_same_digits", "437.50", "Revenue was $1437.50.", 0.0),
        ("different_cents", "437.50", "Revenue was $437.55.", 0.0),
        ("integer_inside_a_larger_integer", "10", "There are 100 refunded lines.", 0.0),
        ("integer", "10", "10 lines were refunded.", 1.0),
        ("negative_amount", "437.50", "We collected -$437.50 in paid revenue.", 0.0),
        ("unicode_minus", "437.50", "Net change: \u2212437.50.", 0.0),
        ("range_with_a_hyphen", "437.50", "Line totals ran 400-437.50.", 1.0),
        ("round_value_without_decimals", "800.00", "Paid invoices total $800.", 1.0),
        ("round_value_inside_a_larger_integer", "800.00", "Paid invoices total 8000.", 0.0),
        ("round_value_with_other_cents", "18050.00", "Revenue was $18,050.88.", 0.0),
        ("integer_with_a_fraction", "13", "There are 13.5 approved requests.", 0.0),
        ("integer_at_the_end_of_a_sentence", "13", "Approved requests: 13.", 1.0),
    ]
)
def test_answer_value_stated(_name: str, value: str, answer: str, expected_score: float) -> None:
    score = AnswerValueStated()._run_eval_sync({"last_message": answer}, {"answer_value_stated": {"value": value}})

    assert score.score == expected_score


_TABLE_CHOICE = {
    "tables": ["postgres_contracts_acv", "postgres.contracts_acv"],
    "decoys": ["postgres_contracts_acv_v2", "postgres.contracts_acv_v2"],
}


@parameterized.expand(
    [
        ("reads_the_target", [("SELECT sum(acv) FROM postgres_contracts_acv", "completed")], 1.0),
        ("reads_the_dotted_name", [("SELECT sum(acv) FROM `postgres.contracts_acv`", "completed")], 1.0),
        (
            "reads_a_decoy_with_the_target_prefix",
            [("SELECT sum(acv) FROM postgres_contracts_acv_v2", "completed")],
            0.0,
        ),
        (
            "mixes_target_and_decoy",
            [
                (
                    "SELECT sum(acv) FROM postgres_contracts_acv UNION ALL SELECT sum(acv) FROM postgres_contracts_acv_v2",
                    "completed",
                )
            ],
            0.0,
        ),
        ("failed_target_query", [("SELECT sum(acv) FROM postgres_contracts_acv", "failed")], 0.0),
        (
            "names_the_target_only_in_a_catalog_filter",
            [
                (
                    "SELECT description FROM system.information_schema.tables WHERE table_name = 'postgres_contracts_acv'",
                    "completed",
                )
            ],
            0.0,
        ),
        (
            "decoy_then_target",
            [
                ("SELECT sum(acv) FROM postgres_contracts_acv_v2", "completed"),
                ("SELECT sum(acv) FROM postgres_contracts_acv", "completed"),
            ],
            1.0,
        ),
    ]
)
def test_answer_table_queried(_name: str, queries: list[tuple[str, str]], expected_score: float) -> None:
    log = _tool_log([("execute-sql", {"query": query}, status) for query, status in queries])
    score = AnswerTableQueried()._run_eval_sync({"raw_log": log}, {"answer_table_queried": _TABLE_CHOICE})

    assert score.score == expected_score


@parameterized.expand(
    [
        (MetricsCatalogBeforeDataDiscovery(), "metrics_catalog_before_data_discovery"),
        (CanonicalMetricRun(), "canonical_metric_run"),
        (DeprecationProposed(), "deprecation_proposed"),
        (AnswerValueStated(), "answer_value_stated"),
        (AnswerTableQueried(), "answer_table_queried"),
        (MetricDescriptionConcise(), "metric_description_concise"),
        (TrustBadgeShown(), "trust_badge"),
        (NoncanonicalBadgeShown(), "proposed_badge"),
    ]
)
def test_new_catalog_scorers_self_skip_when_not_requested(scorer: Any, scorer_name: str) -> None:
    score = scorer._run_eval_sync({"raw_log": _tool_log([])}, {})

    assert score.name == scorer_name
    assert score.score is None


@parameterized.expand(
    [
        ("badge_expected_and_shown", True, "\U0001f6e1\ufe0f **From your data catalog**: MRR\n\n$42k", 1.0),
        ("badge_expected_but_missing", True, "MRR is $42k.", 0.0),
        ("badge_expected_but_trailing", True, "MRR is $42k.\n\n\U0001f6e1\ufe0f **From your data catalog**: MRR", 0.0),
        ("no_badge_expected_and_none", False, "Activation is 31%.", 1.0),
        ("badge_claimed_for_unapproved", False, "\U0001f6e1 Activation is 31%.", 0.0),
    ]
)
def test_trust_badge_shown(_name: str, should_show: bool, answer: str, expected_score: float) -> None:
    score = TrustBadgeShown()._run_eval_sync({"last_message": answer}, {"trust_badge": {"shown": should_show}})

    assert score.score == expected_score


_PROPOSED_LINK = "[Activation](https://example.com/project/1/data-catalog/metrics/activation_rate)"


@parameterized.expand(
    [
        (
            "ran_with_badge_and_link",
            "completed",
            f"\U0001f4dd **Proposed definition in your data catalog**: {_PROPOSED_LINK}",
            1.0,
        ),
        ("ran_without_badge", "completed", f"Activation is 31%. {_PROPOSED_LINK}", 0.0),
        (
            "ran_with_badge_after_the_result",
            "completed",
            f"Activation is 31%.\n\n\U0001f4dd **Proposed definition in your data catalog**: {_PROPOSED_LINK}",
            0.0,
        ),
        (
            "ran_with_badge_but_no_link",
            "completed",
            "\U0001f4dd **Proposed definition in your data catalog**: Activation",
            0.0,
        ),
        (
            "ran_with_badge_and_bare_path",
            "completed",
            "\U0001f4dd **Proposed definition in your data catalog**: /data-catalog/metrics/activation_rate",
            0.0,
        ),
        (
            "ran_with_badge_linking_a_prefix_metric",
            "completed",
            "\U0001f4dd **Proposed definition in your data catalog**: "
            "[Activation v2](https://example.com/project/1/data-catalog/metrics/activation_rate_v2)",
            0.0,
        ),
        (
            "ran_with_link_outside_the_badge",
            "completed",
            f"\U0001f4dd **Proposed definition in your data catalog**: Activation\n\nSee {_PROPOSED_LINK}.",
            0.0,
        ),
        ("run_failed_so_not_used", "failed", "Activation is 31%.", None),
    ]
)
def test_proposed_badge_shown(_name: str, run_status: str, answer: str, expected_score: float | None) -> None:
    log = _tool_log([("data-catalog-metric-run", {"name": "activation_rate"}, run_status)])

    score = NoncanonicalBadgeShown()._run_eval_sync(
        {"raw_log": log, "last_message": answer}, {"proposed_badge": {"metric_name": "activation_rate"}}
    )

    assert score.score == expected_score


_DRIFTED_LINK = "[Weekly active users](https://example.com/project/1/data-catalog/metrics/weekly_active_users)"


@parameterized.expand(
    [
        ("warning_badge", f"\u26a0\ufe0f **Drifted definition in your data catalog**: {_DRIFTED_LINK}", 1.0),
        ("proposed_badge_instead", f"\U0001f4dd **Proposed definition in your data catalog**: {_DRIFTED_LINK}", 0.0),
    ]
)
def test_drifted_badge_shown(_name: str, answer: str, expected_score: float) -> None:
    log = _tool_log([("data-catalog-metric-run", {"name": "weekly_active_users"}, "completed")])

    score = NoncanonicalBadgeShown()._run_eval_sync(
        {"raw_log": log, "last_message": answer},
        {"proposed_badge": {"metric_name": "weekly_active_users", "badge": "drifted"}},
    )

    assert score.score == expected_score


_SHORT_DESCRIPTION = "Canonical MRR over the trailing 30 days, excluding personal/free plans."
_LONG_DESCRIPTION = "x" * (EVAL_DESCRIPTION_CHAR_LIMIT + 1)


@parameterized.expand(
    [
        (
            "short_create_passes",
            [(METRIC_CREATE_TOOL, {"name": "mrr", "description": _SHORT_DESCRIPTION}, "completed")],
            1.0,
        ),
        (
            "long_create_fails",
            [(METRIC_CREATE_TOOL, {"name": "mrr", "description": _LONG_DESCRIPTION}, "completed")],
            0.0,
        ),
        (
            "short_create_then_long_update_fails",
            [
                (METRIC_CREATE_TOOL, {"name": "mrr", "description": _SHORT_DESCRIPTION}, "completed"),
                (METRIC_UPDATE_TOOL, {"name": "mrr", "description": _LONG_DESCRIPTION}, "completed"),
            ],
            0.0,
        ),
        (
            "failed_long_create_ignored",
            [(METRIC_CREATE_TOOL, {"name": "mrr", "description": _LONG_DESCRIPTION}, "failed")],
            None,
        ),
        (
            "no_metric_write",
            [("execute-sql", {"query": CATALOG_QUERY}, "completed")],
            None,
        ),
    ]
)
def test_metric_description_concise(
    _name: str,
    calls: list[tuple[str, dict[str, Any], str]],
    expected_score: float | None,
) -> None:
    score = MetricDescriptionConcise()._run_eval_sync(
        {"raw_log": _tool_log(calls)},
        {"metric_description_concise": {}},
    )

    assert score.score == expected_score


def test_metric_description_quality_judges_the_stored_description() -> None:
    narrating_update = "First it sums amount_usd, then it filters to the last 30 days, then it groups by plan."
    calls: list[tuple[str, dict[str, Any], str]] = [
        (
            METRIC_CREATE_TOOL,
            {"name": "mrr", "description": _SHORT_DESCRIPTION, "definition": {"kind": "HogQLQuery"}},
            "completed",
        ),
        (METRIC_UPDATE_TOOL, {"name": "mrr", "description": narrating_update}, "completed"),
    ]

    prepared = MetricDescriptionQuality()._prepare(
        {"raw_log": _tool_log(calls)},
        {"metric_description_quality": {}},
    )

    assert prepared["output"]["description"] == narrating_update
    assert prepared["output"]["definition"] == json.dumps({"kind": "HogQLQuery"})
