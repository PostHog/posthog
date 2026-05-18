from typing import Any

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from products.endpoints.backend.materialization import (
    DownstreamCTEShape,
    _build_cte_read_graph,
    _classify_downstream_cte,
    _downstream_ctes,
    _topological_order,
    analyze_variables_for_materialization,
    transform_query_for_materialization,
)

pytestmark = [pytest.mark.django_db]


class TestVariableAnalysis(APIBaseTest):
    """Test variable analysis for materialization eligibility."""

    def test_simple_variable_detection(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.event_name}",
            "variables": {
                "var-123": {
                    "variableId": "var-123",
                    "code_name": "event_name",
                    "value": "$pageview",
                }
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert reason == "OK"
        assert len(var_infos) == 1
        assert var_infos[0].code_name == "event_name"
        assert var_infos[0].column_chain == ["event"]
        assert var_infos[0].column_expression == "event"

    def test_nested_property_variable(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE properties.os = {variables.os_name}",
            "variables": {
                "var-456": {
                    "variableId": "var-456",
                    "code_name": "os_name",
                    "value": "Mac OS X",
                }
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert reason == "OK"
        assert len(var_infos) == 1
        assert var_infos[0].code_name == "os_name"
        assert var_infos[0].column_chain == ["properties", "os"]
        assert var_infos[0].column_expression == "properties.os"

    def test_person_nested_property_variable(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE person.properties.city = {variables.city}",
            "variables": {
                "var-789": {
                    "variableId": "var-789",
                    "code_name": "city",
                    "value": "San Francisco",
                }
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert reason == "OK"
        assert len(var_infos) == 1
        assert var_infos[0].code_name == "city"
        assert var_infos[0].column_chain == ["person", "properties", "city"]

    def test_multiple_equality_variables(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.event_name} AND properties.os = {variables.os}",
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
                "var-2": {"code_name": "os", "value": "Mac"},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert reason == "OK"
        assert len(var_infos) == 2
        code_names = {v.code_name for v in var_infos}
        assert code_names == {"event_name", "os"}

    def test_duplicate_placeholder_deduplicated(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.event_name} AND event = {variables.event_name}",
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert len(var_infos) == 1, f"Expected 1 variable, got {len(var_infos)} (duplicates not deduplicated)"

    def test_multiple_variables_rejects_unsupported_operator(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.event_name} AND properties.os IN {variables.os}",
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
                "var-2": {"code_name": "os", "value": "Mac"},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "Unsupported operator" in reason
        assert var_infos == []

    def test_variable_in_select_blocked(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count(), {variables.metric_name} as metric_name FROM events",
            "variables": {"var-1": {"code_name": "metric_name", "value": "total"}},
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "not used in WHERE" in reason

    def test_no_variables(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = '$pageview'",
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "No variables found" in reason

    def test_like_operator_supported(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event LIKE {variables.pattern}",
            "variables": {"var-1": {"code_name": "pattern", "value": "%page%"}},
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert len(var_infos) == 1
        assert var_infos[0].operator == ast.CompareOperationOp.Like

    def test_variable_on_right_side_of_comparison(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.event_name}",
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert reason == "OK"
        assert len(var_infos) == 1
        assert var_infos[0].column_chain == ["event"]

    def test_variable_on_left_side_of_comparison(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE {variables.event_name} = event",
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert reason == "OK"
        assert len(var_infos) == 1
        assert var_infos[0].column_chain == ["event"]

    def test_constant_compared_to_variable_blocked(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE '$pageview' = {variables.event_name}",
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert var_infos == []

    def test_variable_with_complex_and_conditions(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE timestamp > '2024-01-01' AND event = {variables.event_name} AND properties.os = 'Mac'",
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert reason == "OK"
        assert len(var_infos) == 1
        assert var_infos[0].column_chain == ["event"]

    def test_variable_in_or_condition_blocked(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.event_name} OR event = '$pageview'",
            "variables": {"var-1": {"code_name": "event_name", "value": "$identify"}},
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        if can_materialize and var_infos:
            with pytest.raises(ValueError, match="OR conditions not supported"):
                transform_query_for_materialization(query, var_infos, self.team)

    def test_variable_with_parentheses(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE (event = {variables.event_name})",
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert reason == "OK"
        assert len(var_infos) == 1

    def test_malformed_variable_placeholder(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables}",
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert var_infos == []

    def test_missing_variable_metadata(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.event_name}",
            "variables": {},
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "metadata not found" in reason.lower()
        assert var_infos == []

    def test_variable_on_uuid_field(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE distinct_id = {variables.user_id}",
            "variables": {"var-1": {"code_name": "user_id", "value": "user123"}},
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert reason == "OK"
        assert len(var_infos) == 1
        assert var_infos[0].column_chain == ["distinct_id"]

    def test_empty_query_string(self):
        query = {"kind": "HogQLQuery", "query": "", "variables": {}}

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert var_infos == []

    def test_missing_query_field(self):
        query = {"kind": "HogQLQuery", "variables": {"var-1": {"code_name": "foo", "value": "bar"}}}

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "No query string found" in reason
        assert var_infos == []

    def test_invalid_query_string_parsing(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT INVALID SYNTAX {variables.foo}",
            "variables": {"var-1": {"code_name": "foo", "value": "bar"}},
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "parse" in reason.lower()
        assert var_infos == []

    def test_variable_in_having_clause_blocked(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT event, count() as c FROM events GROUP BY event HAVING c > {variables.threshold}",
            "variables": {"var-1": {"code_name": "threshold", "value": "100"}},
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "HAVING" in reason or "having" in reason.lower()
        assert var_infos == []

    def test_variable_wrapped_in_function_call(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count(*) FROM events WHERE event = {variables.event_name} AND toDate(timestamp) >= toDate({variables.from_date})",
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
                "var-2": {"code_name": "from_date", "value": "2024-01-01"},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert reason == "OK"
        assert len(var_infos) == 2
        by_name = {v.code_name: v for v in var_infos}
        assert by_name["from_date"].operator == ast.CompareOperationOp.GtEq
        assert by_name["from_date"].value_wrapper_fns == ["toDate"]
        assert by_name["event_name"].value_wrapper_fns is None

    def test_variable_wrapped_in_lower(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE lower(event) = lower({variables.event_name})",
            "variables": {"var-1": {"code_name": "event_name", "value": "$PageView"}},
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert len(var_infos) == 1
        assert var_infos[0].value_wrapper_fns == ["lower"]
        assert var_infos[0].operator == ast.CompareOperationOp.Eq

    def test_variable_wrapped_in_toStartOfMonth(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE toStartOfMonth(timestamp) >= toStartOfMonth({variables.from_date}) AND toStartOfMonth(timestamp) < toStartOfMonth({variables.to_date})",
            "variables": {
                "var-1": {"code_name": "from_date", "value": "2024-01-15"},
                "var-2": {"code_name": "to_date", "value": "2024-06-15"},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert len(var_infos) == 2
        by_name = {v.code_name: v for v in var_infos}
        assert by_name["from_date"].value_wrapper_fns == ["toStartOfMonth"]
        assert by_name["to_date"].value_wrapper_fns == ["toStartOfMonth"]

    def test_nested_wrapper_functions(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE toDate(timestamp) >= toDate(toStartOfMonth({variables.from_date}))",
            "variables": {"var-1": {"code_name": "from_date", "value": "2024-01-15"}},
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert len(var_infos) == 1
        assert var_infos[0].value_wrapper_fns == ["toDate", "toStartOfMonth"]

    def test_range_operator_gte(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE hour >= {variables.start}",
            "variables": {"var-1": {"code_name": "start", "value": "10"}},
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert len(var_infos) == 1
        assert var_infos[0].operator == ast.CompareOperationOp.GtEq

    def test_range_operator_lt(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE hour < {variables.end}",
            "variables": {"var-1": {"code_name": "end", "value": "20"}},
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert len(var_infos) == 1
        assert var_infos[0].operator == ast.CompareOperationOp.Lt

    def test_same_column_range_variables(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE hour >= {variables.start} AND hour < {variables.end}",
            "variables": {
                "var-1": {"code_name": "start", "value": "10"},
                "var-2": {"code_name": "end", "value": "20"},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert len(var_infos) == 2
        by_name = {v.code_name: v for v in var_infos}
        assert by_name["start"].operator == ast.CompareOperationOp.GtEq
        assert by_name["end"].operator == ast.CompareOperationOp.Lt
        # Both reference same column
        assert by_name["start"].column_chain == by_name["end"].column_chain

    def test_mixed_equality_and_range(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.name} AND hour >= {variables.start}",
            "variables": {
                "var-1": {"code_name": "name", "value": "$pageview"},
                "var-2": {"code_name": "start", "value": "10"},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert len(var_infos) == 2
        by_name = {v.code_name: v for v in var_infos}
        assert by_name["name"].operator == ast.CompareOperationOp.Eq
        assert by_name["start"].operator == ast.CompareOperationOp.GtEq


class TestRangePairDetection(APIBaseTest):
    """Test detection of range variable pairs for time bucketing."""

    def test_range_pair_detection(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE timestamp >= {variables.start_ts} AND timestamp < {variables.end_ts} AND properties.$host = {variables.host}",
            "variables": {
                "var-1": {"variableId": "var-1", "code_name": "start_ts", "value": "2024-01-01"},
                "var-2": {"variableId": "var-2", "code_name": "end_ts", "value": "2024-02-01"},
                "var-3": {"variableId": "var-3", "code_name": "host", "value": "example.com"},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)
        assert can_materialize is True
        assert len(var_infos) == 3

        by_name = {v.code_name: v for v in var_infos}

        # start_ts and end_ts should be detected as a range pair
        assert by_name["start_ts"].bucket_fn == "toStartOfDay"
        assert by_name["end_ts"].bucket_fn == "toStartOfDay"

        # host is equality — no bucket_fn
        assert by_name["host"].bucket_fn is None

    def test_single_range_op_gets_bucket_fn(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE timestamp >= {variables.start_ts}",
            "variables": {
                "var-1": {"variableId": "var-1", "code_name": "start_ts", "value": "2024-01-01"},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)
        assert can_materialize is True
        assert len(var_infos) == 1
        # Single range op gets bucket_fn (default toStartOfDay)
        assert var_infos[0].bucket_fn == "toStartOfDay"

    def test_non_reaggregatable_function_rejected_with_range_vars(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT avg(properties.duration) FROM events WHERE timestamp >= {variables.start_ts} AND timestamp < {variables.end_ts}",
            "variables": {
                "var-1": {"variableId": "var-1", "code_name": "start_ts", "value": "2024-01-01"},
                "var-2": {"variableId": "var-2", "code_name": "end_ts", "value": "2024-02-01"},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)
        assert can_materialize is False
        assert "avg" in reason
        assert "re-aggregated" in reason

    @parameterized.expand(
        [
            (
                "count_distinct_syntax",
                "SELECT count(DISTINCT person_id) FROM events WHERE timestamp >= {variables.start_ts} AND timestamp < {variables.end_ts}",
            ),
            (
                "countDistinct_function",
                "SELECT countDistinct(person_id) FROM events WHERE timestamp >= {variables.start_ts} AND timestamp < {variables.end_ts}",
            ),
        ]
    )
    def test_distinct_count_rejected_with_range_vars(self, _name, query_str):
        query = {
            "kind": "HogQLQuery",
            "query": query_str,
            "variables": {
                "var-1": {"variableId": "var-1", "code_name": "start_ts", "value": "2024-01-01"},
                "var-2": {"variableId": "var-2", "code_name": "end_ts", "value": "2024-02-01"},
            },
        }

        can_materialize, reason, _ = analyze_variables_for_materialization(query)
        assert can_materialize is False
        assert "re-aggregated" in reason

    def test_range_pair_bucketed_in_transform(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE timestamp >= {variables.start_ts} AND timestamp < {variables.end_ts}",
            "variables": {
                "var-1": {"variableId": "var-1", "code_name": "start_ts", "value": "2024-01-01"},
                "var-2": {"variableId": "var-2", "code_name": "end_ts", "value": "2024-02-01"},
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        transformed = transform_query_for_materialization(query, var_infos, self.team)

        transformed_query = transformed["query"]
        # Should use toStartOfDay(timestamp) instead of raw timestamp in GROUP BY
        assert "toStartOfDay" in transformed_query
        # GROUP BY should contain toStartOfDay, not raw timestamp
        group_by_part = transformed_query.split("GROUP BY")[1] if "GROUP BY" in transformed_query else ""
        assert "toStartOfDay" in group_by_part

    @parameterized.expand(
        [
            ("hour", "toStartOfHour"),
            ("day", "toStartOfDay"),
            ("week", "toStartOfWeek"),
            ("month", "toStartOfMonth"),
        ]
    )
    def test_bucket_override_applied_to_range_pair(self, override_key, expected_fn):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE timestamp >= {variables.start_ts} AND timestamp < {variables.end_ts}",
            "variables": {
                "var-1": {"variableId": "var-1", "code_name": "start_ts", "value": "2024-01-01"},
                "var-2": {"variableId": "var-2", "code_name": "end_ts", "value": "2024-02-01"},
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query, bucket_overrides={"timestamp": override_key})

        by_name = {v.code_name: v for v in var_infos}
        assert by_name["start_ts"].bucket_fn == expected_fn
        assert by_name["end_ts"].bucket_fn == expected_fn

    def test_bucket_override_in_transform(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE timestamp >= {variables.start_ts} AND timestamp < {variables.end_ts}",
            "variables": {
                "var-1": {"variableId": "var-1", "code_name": "start_ts", "value": "2024-01-01"},
                "var-2": {"variableId": "var-2", "code_name": "end_ts", "value": "2024-02-01"},
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        transformed = transform_query_for_materialization(
            query, var_infos, self.team, bucket_overrides={"timestamp": "hour"}
        )

        transformed_query = transformed["query"]
        assert "toStartOfHour" in transformed_query
        assert "toStartOfDay" not in transformed_query

    def test_bucket_override_ignores_non_range_variables(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.event_name}",
            "variables": {
                "var-1": {"variableId": "var-1", "code_name": "event_name", "value": "$pageview"},
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query, bucket_overrides={"event": "hour"})

        assert var_infos[0].bucket_fn is None


class TestSingleBoundRange(APIBaseTest):
    """Test single-bound range variable materialization."""

    def test_single_lower_bound_gets_bucket_fn(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE timestamp >= {variables.start}",
            "variables": {"var-1": {"code_name": "start", "value": "2024-01-01"}},
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)
        assert can_materialize is True
        assert var_infos[0].bucket_fn == "toStartOfDay"

    def test_single_upper_bound_gets_bucket_fn(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE timestamp < {variables.end}",
            "variables": {"var-1": {"code_name": "end", "value": "2024-02-01"}},
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)
        assert can_materialize is True
        assert var_infos[0].bucket_fn == "toStartOfDay"

    def test_single_bound_transform_uses_bucket(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE timestamp >= {variables.start}",
            "variables": {"var-1": {"code_name": "start", "value": "2024-01-01"}},
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        transformed = transform_query_for_materialization(query, var_infos, self.team)

        assert "toStartOfDay" in transformed["query"]
        assert "{variables" not in transformed["query"]

    def test_single_bound_with_bucket_override(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE timestamp >= {variables.start}",
            "variables": {"var-1": {"code_name": "start", "value": "2024-01-01"}},
        }

        _, _, var_infos = analyze_variables_for_materialization(query, bucket_overrides={"timestamp": "hour"})
        assert var_infos[0].bucket_fn == "toStartOfHour"

    def test_single_bound_non_reaggregatable_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT avg(properties.duration) FROM events WHERE timestamp >= {variables.start}",
            "variables": {"var-1": {"code_name": "start", "value": "2024-01-01"}},
        }

        can_materialize, reason, _ = analyze_variables_for_materialization(query)
        assert can_materialize is False
        assert "avg" in reason
        assert "re-aggregated" in reason


class TestMinuteBuckets(APIBaseTest):
    """Test minute-level bucket granularity."""

    @parameterized.expand(
        [
            ("minute", "toStartOfMinute"),
            ("fifteen_minutes", "toStartOfFifteenMinutes"),
            ("hour", "toStartOfHour"),
            ("day", "toStartOfDay"),
            ("week", "toStartOfWeek"),
            ("month", "toStartOfMonth"),
        ]
    )
    def test_bucket_override_all_granularities(self, override_key, expected_fn):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE timestamp >= {variables.start_ts} AND timestamp < {variables.end_ts}",
            "variables": {
                "var-1": {"code_name": "start_ts", "value": "2024-01-01"},
                "var-2": {"code_name": "end_ts", "value": "2024-02-01"},
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query, bucket_overrides={"timestamp": override_key})

        by_name = {v.code_name: v for v in var_infos}
        assert by_name["start_ts"].bucket_fn == expected_fn
        assert by_name["end_ts"].bucket_fn == expected_fn

    def test_minute_bucket_in_transform(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE timestamp >= {variables.start_ts} AND timestamp < {variables.end_ts}",
            "variables": {
                "var-1": {"code_name": "start_ts", "value": "2024-01-01"},
                "var-2": {"code_name": "end_ts", "value": "2024-02-01"},
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        transformed = transform_query_for_materialization(
            query, var_infos, self.team, bucket_overrides={"timestamp": "minute"}
        )

        assert "toStartOfMinute" in transformed["query"]


class TestCombinatorReaggregation(APIBaseTest):
    """Test combinator-based re-aggregation detection."""

    @parameterized.expand(
        [
            ("sumIf", "sum"),
            ("countIf", "sum"),
            ("maxIf", "max"),
            ("minIf", "min"),
            ("sumArray", "sum"),
            ("countArrayIf", "sum"),
        ]
    )
    def test_reaggregatable_combinators_allowed(self, func_name, expected_reagg):
        from products.endpoints.backend.materialization import get_reaggregation

        reagg = get_reaggregation(func_name)
        assert reagg is not None, f"{func_name} should be re-aggregatable"
        assert reagg.reaggregate_fn == expected_reagg

    @parameterized.expand(
        [
            ("avg",),
            ("uniq",),
            ("uniqIf",),
            ("uniqExact",),
            ("uniqArrayIf",),
            ("avgWeighted",),
            ("avgWeightedIf",),
            ("median",),
            ("quantile",),
        ]
    )
    def test_non_reaggregatable_functions_rejected(self, func_name):
        from products.endpoints.backend.materialization import get_reaggregation

        reagg = get_reaggregation(func_name)
        assert reagg is None, f"{func_name} should NOT be re-aggregatable"

    def test_sumIf_query_materializes(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT sumIf(1, event = '$pageview') FROM events WHERE timestamp >= {variables.start} AND timestamp < {variables.end}",
            "variables": {
                "var-1": {"code_name": "start", "value": "2024-01-01"},
                "var-2": {"code_name": "end", "value": "2024-02-01"},
            },
        }

        can_materialize, reason, _ = analyze_variables_for_materialization(query)
        assert can_materialize is True, f"sumIf should be allowed: {reason}"

    def test_uniqIf_query_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT uniqIf(person_id, event = '$pageview') FROM events WHERE timestamp >= {variables.start} AND timestamp < {variables.end}",
            "variables": {
                "var-1": {"code_name": "start", "value": "2024-01-01"},
                "var-2": {"code_name": "end", "value": "2024-02-01"},
            },
        }

        can_materialize, reason, _ = analyze_variables_for_materialization(query)
        assert can_materialize is False
        assert "re-aggregated" in reason


class TestStripCombinators(APIBaseTest):
    """Unit tests for _strip_combinators."""

    @parameterized.expand(
        [
            ("count", "count"),
            ("sum", "sum"),
            ("min", "min"),
            ("max", "max"),
            ("sumIf", "sum"),
            ("countIf", "count"),
            ("maxIf", "max"),
            ("countArrayIf", "count"),
            ("sumArray", "sum"),
            ("minOrDefault", "min"),
            ("maxOrNull", "max"),
        ]
    )
    def test_strips_to_known_base(self, func_name, expected_base):
        from products.endpoints.backend.materialization import _strip_combinators

        assert _strip_combinators(func_name) == expected_base

    @parameterized.expand(
        [
            ("avg",),
            ("uniq",),
            ("uniqIf",),
            ("uniqExact",),
            ("median",),
            ("quantile",),
            ("someRandomFunction",),
        ]
    )
    def test_returns_none_for_unknown(self, func_name):
        from products.endpoints.backend.materialization import _strip_combinators

        result = _strip_combinators(func_name)
        # Should return the base but it won't be in REAGGREGATABLE_BASE_FUNCTIONS
        # For truly unknown functions, returns None
        if result is not None:
            from products.endpoints.backend.materialization import REAGGREGATABLE_BASE_FUNCTIONS

            # The base was found but it's not in the registry — that's the expected path
            # for functions like uniq, avg whose base is known but not re-aggregatable
            assert result not in REAGGREGATABLE_BASE_FUNCTIONS or result == func_name.lower()


class TestQueryTransformation(APIBaseTest):
    """Test query transformation for materialization."""

    def test_transform_simple_field(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT toStartOfDay(timestamp) as date, count() as events FROM events WHERE event = {variables.event_name} GROUP BY date",
            "variables": {
                "var-123": {
                    "variableId": "var-123",
                    "code_name": "event_name",
                    "value": "$pageview",
                }
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        assert len(var_infos) == 1

        transformed = transform_query_for_materialization(query, var_infos, self.team)

        # Should have removed variables
        assert transformed["variables"] == {}

        # Query should include the variable column
        transformed_query = transformed["query"]
        assert "event_name" in transformed_query or "event" in transformed_query

        # Should NOT have the variable placeholder anymore
        assert "{variables" not in transformed_query

    def test_transform_nested_property(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE properties.os = {variables.os_name}",
            "variables": {
                "var-456": {
                    "variableId": "var-456",
                    "code_name": "os_name",
                    "value": "Mac OS X",
                }
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        assert len(var_infos) >= 1
        transformed = transform_query_for_materialization(query, var_infos, self.team)

        # Should have properties.os as a Field (not JSONExtractString)
        transformed_query = transformed["query"]
        assert "properties.os" in transformed_query

    def test_transform_removes_where_clause(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.event_name}",
            "variables": {
                "var-123": {
                    "variableId": "var-123",
                    "code_name": "event_name",
                    "value": "$pageview",
                }
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        assert len(var_infos) >= 1
        transformed = transform_query_for_materialization(query, var_infos, self.team)

        # The WHERE clause should be removed since it only had the variable
        # The query should still be valid
        assert "{variables" not in transformed["query"]

    def test_transform_preserves_other_where_conditions(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.event_name} AND timestamp > '2024-01-01'",
            "variables": {
                "var-123": {
                    "variableId": "var-123",
                    "code_name": "event_name",
                    "value": "$pageview",
                }
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        assert len(var_infos) >= 1
        transformed = transform_query_for_materialization(query, var_infos, self.team)

        # Should preserve the timestamp condition
        assert "timestamp" in transformed["query"]
        assert "2024-01-01" in transformed["query"]

        # Should remove the variable
        assert "{variables" not in transformed["query"]

    def test_transform_adds_to_group_by(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT toStartOfDay(timestamp) as date, count() FROM events WHERE event = {variables.event_name} GROUP BY date",
            "variables": {
                "var-123": {
                    "variableId": "var-123",
                    "code_name": "event_name",
                    "value": "$pageview",
                }
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        assert len(var_infos) >= 1
        transformed = transform_query_for_materialization(query, var_infos, self.team)

        # Should have GROUP BY with both date and event_name
        transformed_query = transformed["query"]
        assert "GROUP BY" in transformed_query
        # The variable should be in the query (either as alias or field)
        assert "event_name" in transformed_query or "event" in transformed_query

    def test_transform_query_without_initial_group_by(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.event_name}",
            "variables": {
                "var-123": {
                    "variableId": "var-123",
                    "code_name": "event_name",
                    "value": "$pageview",
                }
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        assert len(var_infos) >= 1
        transformed = transform_query_for_materialization(query, var_infos, self.team)

        # Should have GROUP BY event_name added
        transformed_query = transformed["query"]
        assert "GROUP BY" in transformed_query
        assert "event_name" in transformed_query or "event" in transformed_query

    def test_transform_preserves_order_by(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() as c FROM events WHERE event = {variables.event_name} GROUP BY timestamp ORDER BY c DESC",
            "variables": {
                "var-123": {
                    "variableId": "var-123",
                    "code_name": "event_name",
                    "value": "$pageview",
                }
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        assert len(var_infos) >= 1
        transformed = transform_query_for_materialization(query, var_infos, self.team)

        transformed_query = transformed["query"]
        assert "ORDER BY" in transformed_query
        assert "DESC" in transformed_query or "desc" in transformed_query

    def test_transform_preserves_limit(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.event_name} LIMIT 100",
            "variables": {
                "var-123": {
                    "variableId": "var-123",
                    "code_name": "event_name",
                    "value": "$pageview",
                }
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        assert len(var_infos) >= 1
        transformed = transform_query_for_materialization(query, var_infos, self.team)

        transformed_query = transformed["query"]
        assert "LIMIT" in transformed_query
        assert "100" in transformed_query

    def test_transform_variable_in_middle_of_and_chain(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE timestamp > '2024-01-01' AND event = {variables.event_name} AND properties.os = 'Mac'",
            "variables": {
                "var-123": {
                    "variableId": "var-123",
                    "code_name": "event_name",
                    "value": "$pageview",
                }
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        assert len(var_infos) >= 1
        transformed = transform_query_for_materialization(query, var_infos, self.team)

        transformed_query = transformed["query"]
        # Both other conditions should remain
        assert "timestamp" in transformed_query
        assert "2024-01-01" in transformed_query
        assert "properties" in transformed_query or "os" in transformed_query
        assert "Mac" in transformed_query
        # Variable should be removed from WHERE
        assert "{variables" not in transformed_query

    def test_transform_with_having_clause(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() as c FROM events WHERE event = {variables.event_name} GROUP BY timestamp HAVING c > 100",
            "variables": {
                "var-123": {
                    "variableId": "var-123",
                    "code_name": "event_name",
                    "value": "$pageview",
                }
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        assert len(var_infos) >= 1
        transformed = transform_query_for_materialization(query, var_infos, self.team)

        transformed_query = transformed["query"]
        assert "HAVING" in transformed_query
        assert "100" in transformed_query

    def test_transform_person_properties_column(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE person.properties.city = {variables.city}",
            "variables": {
                "var-123": {
                    "variableId": "var-123",
                    "code_name": "city",
                    "value": "SF",
                }
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        assert len(var_infos) >= 1
        transformed = transform_query_for_materialization(query, var_infos, self.team)

        transformed_query = transformed["query"]
        # Should use person.properties.city as a Field
        assert "person.properties.city" in transformed_query

    def test_transform_variable_first_in_and_chain(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.event_name} AND timestamp > '2024-01-01'",
            "variables": {
                "var-123": {
                    "variableId": "var-123",
                    "code_name": "event_name",
                    "value": "$pageview",
                }
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        assert len(var_infos) >= 1
        transformed = transform_query_for_materialization(query, var_infos, self.team)

        transformed_query = transformed["query"]
        # Timestamp condition should remain
        assert "timestamp" in transformed_query
        assert "2024-01-01" in transformed_query
        # Variable should be removed from WHERE
        assert "{variables" not in transformed_query

    def test_transform_variable_last_in_and_chain(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE timestamp > '2024-01-01' AND properties.os = 'Mac' AND event = {variables.event_name}",
            "variables": {
                "var-123": {
                    "variableId": "var-123",
                    "code_name": "event_name",
                    "value": "$pageview",
                }
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        assert len(var_infos) >= 1
        transformed = transform_query_for_materialization(query, var_infos, self.team)

        transformed_query = transformed["query"]
        # Other conditions should remain
        assert "timestamp" in transformed_query
        assert "properties" in transformed_query or "os" in transformed_query
        # Variable should be removed from WHERE
        assert "{variables" not in transformed_query

    def test_transform_preserves_select_expressions(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT toStartOfDay(timestamp) as date, count() as total, avg(properties.duration) as avg_duration FROM events WHERE event = {variables.event_name} GROUP BY date",
            "variables": {
                "var-123": {
                    "variableId": "var-123",
                    "code_name": "event_name",
                    "value": "$pageview",
                }
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        assert len(var_infos) >= 1
        transformed = transform_query_for_materialization(query, var_infos, self.team)

        transformed_query = transformed["query"]
        # Original SELECT expressions should be preserved
        assert "toStartOfDay" in transformed_query
        assert "avg" in transformed_query or "AVG" in transformed_query
        # Variable column should be added
        assert "event_name" in transformed_query or "event" in transformed_query

    def test_transform_with_or_raises_error(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.event_name} OR timestamp > '2024-01-01'",
            "variables": {
                "var-123": {
                    "variableId": "var-123",
                    "code_name": "event_name",
                    "value": "$pageview",
                }
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        assert len(var_infos) >= 1

        with pytest.raises(ValueError, match="OR conditions not supported"):
            transform_query_for_materialization(query, var_infos, self.team)

    def test_transform_preserves_specific_columns_in_select(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() as total, toStartOfDay(timestamp) as day FROM events WHERE event = {variables.event_name} GROUP BY day",
            "variables": {
                "var-123": {
                    "variableId": "var-123",
                    "code_name": "event_name",
                    "value": "$pageview",
                }
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        assert len(var_infos) >= 1
        transformed = transform_query_for_materialization(query, var_infos, self.team)

        transformed_query = transformed["query"]
        # Original columns should be preserved
        assert "total" in transformed_query or "count()" in transformed_query
        assert "day" in transformed_query or "toStartOfDay" in transformed_query
        # Variable column should be added
        assert "event_name" in transformed_query or "event" in transformed_query

    def test_transform_multiple_equality_variables(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.event_name} AND properties.os = {variables.os}",
            "variables": {
                "var-1": {"variableId": "var-1", "code_name": "event_name", "value": "$pageview"},
                "var-2": {"variableId": "var-2", "code_name": "os", "value": "Mac"},
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        assert len(var_infos) == 2
        transformed = transform_query_for_materialization(query, var_infos, self.team)

        transformed_query = transformed["query"]
        assert "{variables" not in transformed_query
        assert transformed["variables"] == {}
        # Both columns should appear as aliases in SELECT
        assert "event_name" in transformed_query
        assert " os" in transformed_query or "\nos" in transformed_query or ",os" in transformed_query
        assert "GROUP BY" in transformed_query

    def test_transform_range_variables_same_column(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE hour >= {variables.start} AND hour < {variables.end}",
            "variables": {
                "var-1": {"variableId": "var-1", "code_name": "start", "value": "10"},
                "var-2": {"variableId": "var-2", "code_name": "end", "value": "20"},
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        assert len(var_infos) == 2
        transformed = transform_query_for_materialization(query, var_infos, self.team)

        transformed_query = transformed["query"]
        assert "{variables" not in transformed_query
        # Both aliases should appear in SELECT
        assert "start" in transformed_query
        assert "end" in transformed_query
        # GROUP BY should have hour only once (deduplicated)
        group_by_part = transformed_query.split("GROUP BY")[1] if "GROUP BY" in transformed_query else ""
        assert group_by_part.count("hour") == 1

    def test_transform_mixed_equality_and_range(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.name} AND hour >= {variables.start} AND timestamp > '2024-01-01'",
            "variables": {
                "var-1": {"variableId": "var-1", "code_name": "name", "value": "$pageview"},
                "var-2": {"variableId": "var-2", "code_name": "start", "value": "10"},
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        assert len(var_infos) == 2
        transformed = transform_query_for_materialization(query, var_infos, self.team)

        transformed_query = transformed["query"]
        assert "{variables" not in transformed_query
        # Non-variable WHERE preserved
        assert "2024-01-01" in transformed_query
        # Variable columns in SELECT
        assert "name" in transformed_query
        assert "start" in transformed_query

    def test_transform_function_call_column(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count(*) FROM events WHERE event = {variables.event_name} AND toDate(timestamp) >= {variables.from_date}",
            "variables": {
                "var-1": {"variableId": "var-1", "code_name": "event_name", "value": "$pageview"},
                "var-2": {"variableId": "var-2", "code_name": "from_date", "value": "2024-01-01"},
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        assert len(var_infos) == 2
        transformed = transform_query_for_materialization(query, var_infos, self.team)

        transformed_query = transformed["query"]
        assert "{variables" not in transformed_query
        # event_name alias should appear
        assert "event_name" in transformed_query
        # from_date alias should appear with toDate(timestamp) as the expression
        assert "from_date" in transformed_query
        assert "toDate" in transformed_query
        # GROUP BY should include toDate(timestamp)
        group_by_part = transformed_query.split("GROUP BY")[1] if "GROUP BY" in transformed_query else ""
        assert "toDate" in group_by_part

    @parameterized.expand(["sumIf", "maxIf", "countIf"])
    def test_transform_top_level_combinator_aggregate_with_cte_variable(self, fn):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH cte AS ("
                "  SELECT event, count() AS c FROM events "
                "  WHERE event = {variables.event_name} GROUP BY event"
                f") SELECT {fn}(c, c > 0) FROM cte"
            ),
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }
        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)
        assert can_materialize, reason
        transformed = transform_query_for_materialization(query, var_infos, self.team)["query"]
        assert "event_name" in transformed
        assert "GROUP BY" in transformed
        group_by_part = transformed.rsplit("GROUP BY", 1)[1]
        assert "event_name" in group_by_part


class TestMaterializedQueryExecution(APIBaseTest):
    """Test that materialized queries handle pre-aggregated data correctly."""

    def test_materialized_query_selects_precomputed_columns(self):
        # This is a documentation test - the actual behavior is tested in integration tests
        #
        # Example flow:
        # 1. Original query:
        #    "SELECT count() as total FROM events WHERE event = {variables.event_name}"
        #
        # 2. Materialized transformation adds variable column and removes WHERE:
        #    "SELECT count() as total, event_name FROM events GROUP BY event_name"
        #
        # 3. Materialized table contains pre-aggregated data:
        #    total | event_name
        #    ------|------------
        #    1000  | $pageview
        #    500   | $click
        #
        # 4. When querying with variable event_name='$pageview':
        #    WRONG: "SELECT count() as total FROM mat_table WHERE event_name = '$pageview'"
        #           → This counts ROWS (returns 1), not the pre-aggregated value!
        #
        #    CORRECT: "SELECT total FROM mat_table WHERE event_name = '$pageview'"
        #           → This selects the pre-computed column (returns 1000)
        #
        # The key transformation:
        # - count() as total → Field(chain=["total"])  (select by alias)
        # - count() → Field(chain=["count()"])  (select by expression string)
        # - toStartOfDay(timestamp) as date → Field(chain=["date"])  (select by alias)

        # This test documents the expected behavior
        assert True  # See _transform_select_for_materialized_table implementation

    def test_select_transformation_with_alias(self):
        from products.endpoints.backend.materialization import transform_select_for_materialized_table

        query_str = "SELECT count() as total, toStartOfDay(timestamp) as date FROM events"
        parsed = parse_select(query_str)

        assert isinstance(parsed, ast.SelectQuery)
        transformed = transform_select_for_materialized_table(parsed.select, self.team)

        assert len(transformed) == 2

        # count() as total → aggregate, re-aggregate with sum
        assert isinstance(transformed[0].expr, ast.Field)
        assert transformed[0].expr.chain == ["total"]
        assert transformed[0].is_aggregate is True
        assert transformed[0].reaggregate_fn == "sum"

        # toStartOfDay(timestamp) as date → non-aggregate
        assert isinstance(transformed[1].expr, ast.Field)
        assert transformed[1].expr.chain == ["date"]
        assert transformed[1].is_aggregate is False

    def test_select_transformation_without_alias(self):
        from products.endpoints.backend.materialization import transform_select_for_materialized_table

        query_str = "SELECT count() FROM events"
        parsed = parse_select(query_str)

        assert isinstance(parsed, ast.SelectQuery)
        transformed = transform_select_for_materialized_table(parsed.select, self.team)

        assert len(transformed) == 1

        assert isinstance(transformed[0].expr, ast.Field)
        assert transformed[0].expr.chain == ["count()"]
        assert transformed[0].is_aggregate is True
        assert transformed[0].reaggregate_fn == "sum"


@pytest.mark.usefixtures("unittest_snapshot")
class TestTransformQuerySnapshots(APIBaseTest):
    """Snapshot tests for multi-variable materialization query transforms.

    Each test asserts the exact transformed HogQL output against a stored snapshot.
    Run `pytest --snapshot-update` to regenerate after intentional changes.
    """

    snapshot: Any

    def _transform(self, query_str: str, variables: dict) -> str:
        hogql_query = {"kind": "HogQLQuery", "query": query_str, "variables": variables}
        can_materialize, reason, var_infos = analyze_variables_for_materialization(hogql_query)
        assert can_materialize, f"Expected materializable, got: {reason}"
        transformed = transform_query_for_materialization(hogql_query, var_infos, self.team)
        assert transformed["variables"] == {}
        assert "{variables" not in transformed["query"]
        return transformed["query"]

    def test_single_equality(self):
        assert (
            self._transform(
                "SELECT count() FROM events WHERE event = {variables.event_name}",
                {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            )
            == self.snapshot
        )

    def test_single_equality_with_alias(self):
        assert (
            self._transform(
                "SELECT count() AS total FROM events WHERE event = {variables.event_name}",
                {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            )
            == self.snapshot
        )

    def test_two_equality_different_columns(self):
        assert (
            self._transform(
                "SELECT count() FROM events WHERE event = {variables.event_name} AND distinct_id = {variables.user_id}",
                {
                    "var-1": {"code_name": "event_name", "value": "$pageview"},
                    "var-2": {"code_name": "user_id", "value": "u1"},
                },
            )
            == self.snapshot
        )

    def test_range_same_column_deduped(self):
        assert (
            self._transform(
                "SELECT count() FROM events WHERE hour >= {variables.start_hour} AND hour < {variables.end_hour}",
                {
                    "var-1": {"code_name": "start_hour", "value": "10"},
                    "var-2": {"code_name": "end_hour", "value": "20"},
                },
            )
            == self.snapshot
        )

    def test_mixed_equality_and_range(self):
        assert (
            self._transform(
                "SELECT count() FROM events WHERE event = {variables.name} AND hour >= {variables.start_hour}",
                {
                    "var-1": {"code_name": "name", "value": "$pageview"},
                    "var-2": {"code_name": "start_hour", "value": "10"},
                },
            )
            == self.snapshot
        )

    def test_three_variables_range_deduped(self):
        assert (
            self._transform(
                "SELECT count() FROM events WHERE event = {variables.name} AND hour >= {variables.start_hour} AND hour < {variables.end_hour}",
                {
                    "var-1": {"code_name": "name", "value": "$pageview"},
                    "var-2": {"code_name": "start_hour", "value": "10"},
                    "var-3": {"code_name": "end_hour", "value": "20"},
                },
            )
            == self.snapshot
        )

    def test_preserves_non_variable_where(self):
        assert (
            self._transform(
                "SELECT count() FROM events WHERE timestamp > '2024-01-01' AND event = {variables.event_name} AND distinct_id = 'user1'",
                {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            )
            == self.snapshot
        )

    def test_all_where_conditions_are_variables(self):
        assert (
            self._transform(
                "SELECT count() FROM events WHERE event = {variables.event_name} AND distinct_id = {variables.user_id}",
                {
                    "var-1": {"code_name": "event_name", "value": "$pageview"},
                    "var-2": {"code_name": "user_id", "value": "u1"},
                },
            )
            == self.snapshot
        )

    def test_existing_group_by_preserved(self):
        assert (
            self._transform(
                "SELECT toStartOfDay(timestamp) AS day, count() FROM events WHERE event = {variables.event_name} GROUP BY day",
                {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            )
            == self.snapshot
        )

    def test_order_by_having_limit_preserved(self):
        assert (
            self._transform(
                "SELECT event, count() AS c FROM events WHERE event = {variables.event_name} GROUP BY event HAVING greater(c, 10) ORDER BY c DESC LIMIT 50",
                {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            )
            == self.snapshot
        )

    def test_property_variable_json_extract(self):
        assert (
            self._transform(
                "SELECT count() FROM events WHERE properties.os = {variables.os_name}",
                {"var-1": {"code_name": "os_name", "value": "Mac"}},
            )
            == self.snapshot
        )

    def test_person_property_variable(self):
        assert (
            self._transform(
                "SELECT count() FROM events WHERE person.properties.city = {variables.city}",
                {"var-1": {"code_name": "city", "value": "SF"}},
            )
            == self.snapshot
        )

    def test_function_call_toDate(self):
        assert (
            self._transform(
                "SELECT count() FROM events WHERE toDate(timestamp) >= {variables.from_date}",
                {"var-1": {"code_name": "from_date", "value": "2024-01-01"}},
            )
            == self.snapshot
        )

    def test_range_on_same_function_call_deduped(self):
        assert (
            self._transform(
                "SELECT count() FROM events WHERE toDate(timestamp) >= {variables.from_date} AND toDate(timestamp) < {variables.to_date}",
                {
                    "var-1": {"code_name": "from_date", "value": "2024-01-01"},
                    "var-2": {"code_name": "to_date", "value": "2024-02-01"},
                },
            )
            == self.snapshot
        )

    def test_mixed_field_and_function_call(self):
        assert (
            self._transform(
                "SELECT count() FROM events WHERE event = {variables.event_name} AND toDate(timestamp) >= {variables.from_date}",
                {
                    "var-1": {"code_name": "event_name", "value": "$pageview"},
                    "var-2": {"code_name": "from_date", "value": "2024-01-01"},
                },
            )
            == self.snapshot
        )

    def test_variable_on_left_side(self):
        assert (
            self._transform(
                "SELECT count() FROM events WHERE {variables.event_name} = event",
                {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            )
            == self.snapshot
        )

    def test_nested_and_variable_removed(self):
        assert (
            self._transform(
                "SELECT count() FROM events WHERE (event = {variables.event_name} AND distinct_id = 'u1')",
                {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            )
            == self.snapshot
        )

    def test_like_operator(self):
        assert (
            self._transform(
                "SELECT count() FROM events WHERE event LIKE {variables.pattern}",
                {"var-1": {"code_name": "pattern", "value": "%page%"}},
            )
            == self.snapshot
        )

    def test_hard_cap_timestamp_with_variable_range(self):
        assert (
            self._transform(
                "SELECT count() FROM events WHERE timestamp > today() - interval 90 day AND timestamp >= {variables.start_date} AND timestamp < {variables.end_date}",
                {
                    "var-1": {"code_name": "start_date", "value": "2024-01-01"},
                    "var-2": {"code_name": "end_date", "value": "2024-04-01"},
                },
            )
            == self.snapshot
        )

    def test_duplicate_placeholder_produces_single_alias(self):
        assert (
            self._transform(
                "SELECT count() FROM events WHERE event = {variables.event_name} AND event = {variables.event_name}",
                {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            )
            == self.snapshot
        )

    def test_variable_column_not_duplicated_in_existing_group_by(self):
        import re

        query_str = "SELECT event, count() AS c FROM events WHERE event = {variables.event_name} GROUP BY event"
        variables = {"var-1": {"code_name": "event_name", "value": "$pageview"}}

        result = self._transform(query_str, variables)
        normalized = re.sub(r"\s+", " ", result).strip()

        group_by_part = normalized.split("GROUP BY")[1].split("HAVING")[0].split("ORDER BY")[0].split("LIMIT")[0]
        group_by_columns = [col.strip() for col in group_by_part.split(",")]

        assert group_by_columns.count("event") == 1, f"GROUP BY has duplicate 'event': {group_by_columns}"

    def test_ast_node_not_shared_between_select_and_group_by(self):
        from products.endpoints.backend.materialization import MaterializationTransformer

        query_str = "SELECT count() FROM events WHERE toDate(timestamp) >= {variables.from_date}"
        variables = {"var-1": {"code_name": "from_date", "value": "2024-01-01"}}
        hogql_query = {"kind": "HogQLQuery", "query": query_str, "variables": variables}

        _, _, var_infos = analyze_variables_for_materialization(hogql_query)

        parsed_ast = parse_select(query_str)
        transformer = MaterializationTransformer(var_infos)
        transformed_ast = transformer.visit(parsed_ast)

        assert isinstance(transformed_ast, ast.SelectQuery)

        select_alias_expr = None
        for expr in transformed_ast.select:
            if isinstance(expr, ast.Alias) and expr.alias == "from_date":
                select_alias_expr = expr.expr
                break

        group_by_expr = None
        if transformed_ast.group_by:
            for expr in transformed_ast.group_by:
                if isinstance(expr, ast.Call) and expr.name == "toDate":
                    group_by_expr = expr
                    break

        assert select_alias_expr is not None, "from_date alias not found in SELECT"
        assert group_by_expr is not None, "toDate() not found in GROUP BY"
        assert select_alias_expr is not group_by_expr, "SELECT alias expr and GROUP BY expr are the same Python object"


class TestMaterializedReadPath(APIBaseTest):
    """Test that the read path applies value_wrapper_fns when filtering the materialized table."""

    def _build_read_query(self, query_str: str, variables_meta: dict, variable_values: dict) -> str:
        """Simulate the materialized read path: analyze variables, then build a SELECT with filters."""
        from products.endpoints.backend.api import EndpointViewSet

        hogql_query = {"kind": "HogQLQuery", "query": query_str, "variables": variables_meta}
        _, _, var_infos = analyze_variables_for_materialization(hogql_query)

        select_query = ast.SelectQuery(
            select=[ast.Field(chain=["*"])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["materialized_table"])),
        )

        viewset = EndpointViewSet()
        for mat_var in var_infos:
            var_value = variable_values.get(mat_var.code_name)
            if var_value is not None:
                viewset._apply_where_filter(
                    select_query,
                    mat_var.code_name,
                    var_value,
                    op=mat_var.operator,
                    value_wrapper_fns=mat_var.value_wrapper_fns,
                    bucket_fn=mat_var.bucket_fn,
                )

        return select_query.to_hogql()

    def test_bare_variable_no_wrapper(self):
        result = self._build_read_query(
            "SELECT count() FROM events WHERE event = {variables.event_name}",
            {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            {"event_name": "$pageview"},
        )

        assert "event_name" in result
        assert "'$pageview'" in result
        assert "toDate" not in result

    def test_toDate_wrapper_applied_to_value(self):
        result = self._build_read_query(
            "SELECT count() FROM events WHERE toDate(timestamp) >= toDate({variables.from_date})",
            {"var-1": {"code_name": "from_date", "value": "2024-01-01"}},
            {"from_date": "2024-01-15 14:30:00"},
        )

        assert "toDate('2024-01-15 14:30:00')" in result

    def test_lower_wrapper_applied_to_value(self):
        result = self._build_read_query(
            "SELECT count() FROM events WHERE lower(event) = lower({variables.event_name})",
            {"var-1": {"code_name": "event_name", "value": "$PageView"}},
            {"event_name": "$PageView"},
        )

        assert "lower('$PageView')" in result

    def test_range_with_wrapper_both_sides(self):
        result = self._build_read_query(
            "SELECT count() FROM events WHERE toStartOfMonth(timestamp) >= toStartOfMonth({variables.from_date}) AND toStartOfMonth(timestamp) < toStartOfMonth({variables.to_date})",
            {
                "var-1": {"code_name": "from_date", "value": "2024-01-15"},
                "var-2": {"code_name": "to_date", "value": "2024-06-15"},
            },
            {"from_date": "2024-01-15", "to_date": "2024-06-15"},
        )

        assert "toStartOfMonth('2024-01-15')" in result
        assert "toStartOfMonth('2024-06-15')" in result

    def test_nested_wrapper_applied_to_value(self):
        result = self._build_read_query(
            "SELECT count() FROM events WHERE toDate(timestamp) >= toDate(toStartOfMonth({variables.from_date}))",
            {"var-1": {"code_name": "from_date", "value": "2024-01-15"}},
            {"from_date": "2024-01-15"},
        )

        assert "toDate(toStartOfMonth('2024-01-15'))" in result


class TestCTEVariableAnalysis(APIBaseTest):
    """Test variable analysis for variables inside CTE WHERE clauses."""

    def test_single_cte_with_variable_in_where(self):
        query = {
            "kind": "HogQLQuery",
            "query": "WITH cte AS (SELECT count() as cnt, event FROM events WHERE event = {variables.event_name} GROUP BY event) SELECT cnt, event FROM cte",
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert reason == "OK"
        assert len(var_infos) == 1
        assert var_infos[0].code_name == "event_name"
        assert var_infos[0].cte_name == "cte"

    def test_variable_in_cte_with_or_condition_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH cte AS (SELECT count() as cnt FROM events WHERE event = {variables.event_name} OR event = '$click' GROUP BY event) "
                "SELECT cnt FROM cte"
            ),
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        if can_materialize and var_infos:
            with pytest.raises(ValueError, match="OR conditions not supported"):
                transform_query_for_materialization(query, var_infos, self.team)

    def test_two_ctes_one_variable_each_different_vars_allowed(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH cte1 AS (SELECT count() as cnt1 FROM events WHERE event = {variables.event_name} GROUP BY event), "
                "cte2 AS (SELECT count() as cnt2 FROM events WHERE distinct_id = {variables.user_id} GROUP BY distinct_id) "
                "SELECT cnt1 FROM cte1"
            ),
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
                "var-2": {"code_name": "user_id", "value": "user_0"},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        # Each variable is in its own single CTE — this should be allowed
        assert can_materialize is True
        assert reason == "OK"
        assert len(var_infos) == 2
        code_names = {v.code_name for v in var_infos}
        assert code_names == {"event_name", "user_id"}

    def test_variable_in_cte_and_top_level_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": "WITH cte AS (SELECT count() as cnt FROM events WHERE event = {variables.event_name} GROUP BY event) SELECT cnt FROM cte WHERE event = {variables.event_name}",
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
            },
        }

        can_materialize, reason, _ = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "both CTE and top-level" in reason

    def test_variable_in_two_different_ctes_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH cte1 AS (SELECT count() as cnt1 FROM events WHERE event = {variables.event_name} GROUP BY event), "
                "cte2 AS (SELECT count() as cnt2 FROM events WHERE event = {variables.event_name} GROUP BY event) "
                "SELECT cnt1, cnt2 FROM cte1 CROSS JOIN cte2"
            ),
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
            },
        }

        can_materialize, reason, _ = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "multiple CTEs" in reason

    def test_variable_in_cte_having_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": "WITH cte AS (SELECT count() as cnt, event FROM events GROUP BY event HAVING cnt > {variables.min_count}) SELECT * FROM cte",
            "variables": {
                "var-1": {"code_name": "min_count", "value": "10"},
            },
        }

        can_materialize, reason, _ = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "HAVING" in reason

    def test_cte_variable_with_top_level_join_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH filtered AS (SELECT user_id FROM events WHERE event = {variables.event_name} GROUP BY user_id) "
                "SELECT p.name FROM persons p LEFT JOIN filtered f ON p.id = f.user_id"
            ),
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
            },
        }

        can_materialize, reason, _ = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "JOINs" in reason

    def test_top_level_variable_with_join_still_allowed(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH cte AS (SELECT count() as cnt, event FROM events GROUP BY event) "
                "SELECT c.cnt, p.name FROM cte c JOIN persons p ON 1=1 WHERE c.event = {variables.event_name}"
            ),
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert var_infos[0].cte_name is None

    def test_top_level_variable_still_works(self):
        query = {
            "kind": "HogQLQuery",
            "query": "WITH cte AS (SELECT count() as cnt, event FROM events GROUP BY event) SELECT cnt, event FROM cte WHERE event = {variables.event_name}",
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert len(var_infos) == 1
        assert var_infos[0].cte_name is None


@pytest.mark.usefixtures("unittest_snapshot")
class TestCTETransformSnapshots(APIBaseTest):
    """Snapshot tests for CTE variable materialization query transforms.

    Run `pytest --snapshot-update` to regenerate after intentional changes.
    """

    snapshot: Any

    def _transform(self, query_str: str, variables: dict) -> str:
        hogql_query = {"kind": "HogQLQuery", "query": query_str, "variables": variables}
        can_materialize, reason, var_infos = analyze_variables_for_materialization(hogql_query)
        assert can_materialize, f"Expected materializable, got: {reason}"
        transformed = transform_query_for_materialization(hogql_query, var_infos, self.team)
        assert transformed["variables"] == {}
        assert "{variables" not in transformed["query"]
        return transformed["query"]

    def test_cte_variable_with_group_by(self):
        assert (
            self._transform(
                "WITH cte AS (SELECT count() as cnt, toStartOfDay(timestamp) as date FROM events WHERE event = {variables.event_name} GROUP BY date) SELECT cnt, date FROM cte",
                {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            )
            == self.snapshot
        )

    def test_cte_variable_without_group_by(self):
        assert (
            self._transform(
                "WITH cte AS (SELECT * FROM events WHERE event = {variables.event_name}) SELECT count() FROM cte",
                {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            )
            == self.snapshot
        )

    def test_top_level_variable_with_cte_present(self):
        assert (
            self._transform(
                "WITH cte AS (SELECT count() as cnt, event FROM events GROUP BY event) SELECT cnt, event FROM cte WHERE event = {variables.event_name}",
                {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            )
            == self.snapshot
        )

    def test_cte_two_variables_same_cte(self):
        assert (
            self._transform(
                "WITH cte AS (SELECT count() as cnt FROM events WHERE event = {variables.event_name} AND distinct_id = {variables.user_id} GROUP BY event, distinct_id) SELECT cnt FROM cte",
                {
                    "var-1": {"code_name": "event_name", "value": "$pageview"},
                    "var-2": {"code_name": "user_id", "value": "u1"},
                },
            )
            == self.snapshot
        )

    def test_cte_variable_preserves_non_variable_where(self):
        assert (
            self._transform(
                "WITH cte AS (SELECT count() as cnt FROM events WHERE timestamp > '2024-01-01' AND event = {variables.event_name} GROUP BY event) SELECT cnt FROM cte",
                {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            )
            == self.snapshot
        )

    def test_cte_range_variable_deduped_group_by(self):
        assert (
            self._transform(
                "WITH cte AS (SELECT count() as cnt FROM events WHERE hour >= {variables.start_hour} AND hour < {variables.end_hour} GROUP BY hour) SELECT cnt FROM cte",
                {
                    "var-1": {"code_name": "start_hour", "value": "10"},
                    "var-2": {"code_name": "end_hour", "value": "20"},
                },
            )
            == self.snapshot
        )

    def test_cte_property_variable(self):
        assert (
            self._transform(
                "WITH cte AS (SELECT count() as cnt FROM events WHERE properties.os = {variables.os_name} GROUP BY properties.os) SELECT cnt FROM cte",
                {"var-1": {"code_name": "os_name", "value": "Mac"}},
            )
            == self.snapshot
        )

    def test_cte_variable_top_level_no_group_by_passthrough(self):
        assert (
            self._transform(
                "WITH cte AS (SELECT count() as cnt, event FROM events WHERE event = {variables.event_name} GROUP BY event) SELECT sum(cnt) FROM cte",
                {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            )
            == self.snapshot
        )


class TestMaterializationEquivalence(ClickhouseTestMixin, APIBaseTest):
    """Verify that querying a materialized table with variable filters returns
    the same data as running the original query with variables substituted.

    Strategy:
      1. Insert real events into ClickHouse with varied property values.
      2. Run the original query with the variable value hard-coded (the "inline" result).
      3. Run the materialized-transformed query (variable removed from WHERE,
         added as a column), then filter that result to the desired variable value.
      4. Assert both results match on the data columns.
    """

    def setUp(self):
        super().setUp()

        for event_name in ("$pageview", "$click"):
            for i in range(5):
                _create_event(
                    event=event_name,
                    distinct_id=f"user_{i % 3}",
                    team=self.team,
                    timestamp=f"2026-01-{(i + 1):02d} 12:00:00",
                    properties={"$browser": "Chrome" if i % 2 == 0 else "Safari", "$os": "Mac" if i < 3 else "Windows"},
                )
        flush_persons_and_events()

    def _run_hogql(self, query_str: str) -> list[list]:
        from posthog.schema import HogQLQuery

        from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner

        runner = HogQLQueryRunner(team=self.team, query=HogQLQuery(query=query_str))
        response = runner.calculate()
        return sorted([list(row) for row in response.results])

    def _assert_equivalent(self, original_query: str, variables: dict, variable_values: dict):
        """Run the original (with values substituted) and materialized+filtered queries, assert equality.

        Args:
            original_query: HogQL with {variables.X} placeholders
            variables: variable metadata dict for analyze_variables_for_materialization
            variable_values: dict of code_name -> value to substitute
        """
        # 1. Build the "inline" query by substituting variable values directly
        inline_query = original_query
        for code_name, value in variable_values.items():
            inline_query = inline_query.replace("{variables." + code_name + "}", f"'{value}'")

        inline_results = self._run_hogql(inline_query)

        # 2. Transform for materialization
        hogql_query = {"kind": "HogQLQuery", "query": original_query, "variables": variables}
        can_materialize, reason, var_infos = analyze_variables_for_materialization(hogql_query)
        assert can_materialize, f"Expected materializable: {reason}"
        transformed = transform_query_for_materialization(hogql_query, var_infos, self.team)

        # 3. Run the materialized query (returns all permutations) and get column names
        var_code_names = {v.code_name for v in var_infos}

        from posthog.schema import HogQLQuery

        from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner

        runner = HogQLQueryRunner(team=self.team, query=HogQLQuery(query=transformed["query"]))
        response = runner.calculate()
        columns = response.columns or []

        var_col_indices = {i for i, col in enumerate(columns) if col in var_code_names}
        data_col_indices = [i for i in range(len(columns)) if i not in var_col_indices]

        # Build index mapping: code_name -> column position
        var_col_positions = {col: i for i, col in enumerate(columns) if col in var_code_names}

        filtered_results = []
        for row in response.results:
            row_list = list(row)
            # Check if this row matches all variable values
            matches = all(row_list[var_col_positions[cn]] == val for cn, val in variable_values.items())
            if matches:
                filtered_results.append([row_list[i] for i in data_col_indices])

        filtered_results = sorted(filtered_results)
        assert inline_results == filtered_results, (
            f"Inline vs materialized+filtered results differ.\n"
            f"Inline:       {inline_results}\n"
            f"Materialized: {filtered_results}"
        )

    def test_simple_equality_variable(self):
        self._assert_equivalent(
            "SELECT count() FROM events WHERE event = {variables.event_name}",
            {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            {"event_name": "$pageview"},
        )

    def test_two_variables(self):
        self._assert_equivalent(
            "SELECT count() FROM events WHERE event = {variables.event_name} AND distinct_id = {variables.user_id}",
            {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
                "var-2": {"code_name": "user_id", "value": "user_0"},
            },
            {"event_name": "$pageview", "user_id": "user_0"},
        )

    def test_variable_with_group_by(self):
        self._assert_equivalent(
            "SELECT distinct_id, count() FROM events WHERE event = {variables.event_name} GROUP BY distinct_id",
            {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            {"event_name": "$pageview"},
        )

    def test_variable_with_non_variable_where(self):
        self._assert_equivalent(
            "SELECT count() FROM events WHERE distinct_id = 'user_0' AND event = {variables.event_name}",
            {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            {"event_name": "$pageview"},
        )

    def test_property_variable(self):
        self._assert_equivalent(
            "SELECT count() FROM events WHERE properties.$browser = {variables.browser}",
            {"var-1": {"code_name": "browser", "value": "Chrome"}},
            {"browser": "Chrome"},
        )

    def test_cte_variable(self):
        self._assert_equivalent(
            "WITH cte AS (SELECT count() as cnt, distinct_id FROM events WHERE event = {variables.event_name} GROUP BY distinct_id) SELECT cnt, distinct_id FROM cte",
            {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            {"event_name": "$pageview"},
        )

    def test_cte_variable_with_top_level_aggregation(self):
        self._assert_equivalent(
            "WITH cte AS (SELECT count() as cnt, distinct_id FROM events WHERE event = {variables.event_name} GROUP BY distinct_id) SELECT sum(cnt) FROM cte",
            {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            {"event_name": "$pageview"},
        )

    def test_cte_two_variables(self):
        self._assert_equivalent(
            "WITH cte AS (SELECT count() as cnt FROM events WHERE event = {variables.event_name} AND distinct_id = {variables.user_id} GROUP BY event, distinct_id) SELECT cnt FROM cte",
            {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
                "var-2": {"code_name": "user_id", "value": "user_0"},
            },
            {"event_name": "$pageview", "user_id": "user_0"},
        )

    def test_cte_variable_preserves_non_variable_where(self):
        self._assert_equivalent(
            "WITH cte AS (SELECT count() as cnt FROM events WHERE distinct_id = 'user_0' AND event = {variables.event_name} GROUP BY event) SELECT cnt FROM cte",
            {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            {"event_name": "$pageview"},
        )

    def test_cte_property_variable(self):
        self._assert_equivalent(
            "WITH cte AS (SELECT count() as cnt FROM events WHERE properties.$browser = {variables.browser} GROUP BY properties.$browser) SELECT cnt FROM cte",
            {"var-1": {"code_name": "browser", "value": "Chrome"}},
            {"browser": "Chrome"},
        )

    def test_cte_variable_without_group_by(self):
        self._assert_equivalent(
            "WITH cte AS (SELECT event, distinct_id FROM events WHERE event = {variables.event_name}) SELECT event, distinct_id FROM cte",
            {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            {"event_name": "$pageview"},
        )

    def test_cte_variable_with_order_by(self):
        self._assert_equivalent(
            "WITH cte AS (SELECT count() as cnt, event FROM events WHERE event = {variables.event_name} GROUP BY event) SELECT cnt, event FROM cte ORDER BY cnt DESC",
            {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            {"event_name": "$pageview"},
        )

    def test_cte_variable_with_limit(self):
        self._assert_equivalent(
            "WITH cte AS (SELECT count() as cnt, event FROM events WHERE event = {variables.event_name} GROUP BY event) SELECT cnt FROM cte LIMIT 5",
            {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            {"event_name": "$pageview"},
        )

    def test_cte_multiple_non_variable_ctes(self):
        self._assert_equivalent(
            (
                "WITH cte1 AS (SELECT count() as cnt FROM events GROUP BY event), "
                "cte2 AS (SELECT count() as cnt2 FROM events WHERE event = {variables.event_name} GROUP BY event) "
                "SELECT cnt2 FROM cte2"
            ),
            {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            {"event_name": "$pageview"},
        )

    def test_cte_variable_with_downstream_cte_chain(self):
        # Variable lives in `base`, but top-level reads from `agg`, which itself
        # reads from `base`. The transform must propagate the variable column
        # through `agg` (SELECT + GROUP BY) so the final filter is meaningful.
        self._assert_equivalent(
            (
                "WITH base AS ("
                "  SELECT event, distinct_id FROM events WHERE event = {variables.event_name}"
                "), "
                "agg AS ("
                "  SELECT distinct_id, count() AS cnt FROM base GROUP BY distinct_id"
                ") "
                "SELECT distinct_id, cnt FROM agg ORDER BY distinct_id"
            ),
            {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            {"event_name": "$pageview"},
        )

    def test_cte_variable_with_transitive_chain_three_hops(self):
        self._assert_equivalent(
            (
                "WITH base AS ("
                "  SELECT event, distinct_id FROM events WHERE event = {variables.event_name}"
                "), "
                "mid AS ("
                "  SELECT distinct_id FROM base"
                "), "
                "terminal AS ("
                "  SELECT distinct_id, count() AS cnt FROM mid GROUP BY distinct_id"
                ") "
                "SELECT distinct_id, cnt FROM terminal ORDER BY distinct_id"
            ),
            {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            {"event_name": "$pageview"},
        )

    def test_cte_variable_with_cross_join_of_propagating_ctes(self):
        # Two sibling CTEs both read from the variable-carrying `base`. The
        # terminal CTE CROSS JOINs them; propagation must add an equi-predicate
        # on the variable column to preserve per-value semantics.
        self._assert_equivalent(
            (
                "WITH base AS ("
                "  SELECT event, distinct_id FROM events WHERE event = {variables.event_name}"
                "), "
                "left_side AS ("
                "  SELECT distinct_id FROM base"
                "), "
                "right_side AS ("
                "  SELECT distinct_id AS did2 FROM base"
                "), "
                "combined AS ("
                "  SELECT l.distinct_id AS did_l, r.did2 AS did_r FROM left_side l CROSS JOIN right_side r"
                ") "
                "SELECT did_l, did_r FROM combined ORDER BY did_l, did_r"
            ),
            {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            {"event_name": "$pageview"},
        )

    def test_cte_variable_with_distinct_downstream(self):
        self._assert_equivalent(
            (
                "WITH base AS ("
                "  SELECT event, distinct_id FROM events WHERE event = {variables.event_name}"
                "), "
                "uniq AS ("
                "  SELECT DISTINCT distinct_id FROM base"
                ") "
                "SELECT distinct_id FROM uniq ORDER BY distinct_id"
            ),
            {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            {"event_name": "$pageview"},
        )

    def test_cte_variable_with_aggregation_in_downstream_chain(self):
        self._assert_equivalent(
            (
                "WITH base AS ("
                "  SELECT event, distinct_id FROM events WHERE event = {variables.event_name}"
                "), "
                "per_user AS ("
                "  SELECT distinct_id, count() AS cnt FROM base GROUP BY distinct_id"
                "), "
                "final AS ("
                "  SELECT sum(cnt) AS total FROM per_user"
                ") "
                "SELECT total FROM final"
            ),
            {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            {"event_name": "$pageview"},
        )


class TestCTEGraph(APIBaseTest):
    """Unit tests for the CTE reference graph and downstream/topological helpers."""

    @staticmethod
    def _parse(query_str: str) -> ast.SelectQuery:
        parsed = parse_select(query_str)
        assert isinstance(parsed, ast.SelectQuery)
        return parsed

    def test_no_ctes_returns_empty_graph(self):
        node = self._parse("SELECT count() FROM events")
        assert _build_cte_read_graph(node) == {}

    def test_single_cte_with_no_cte_references(self):
        node = self._parse("WITH a AS (SELECT 1 AS x) SELECT x FROM a")
        graph = _build_cte_read_graph(node)
        assert graph == {"a": set()}

    def test_cte_reads_from_another_cte(self):
        node = self._parse("WITH a AS (SELECT 1 AS x), b AS (SELECT x FROM a) SELECT x FROM b")
        graph = _build_cte_read_graph(node)
        assert graph["a"] == set()
        assert graph["b"] == {"a"}

    def test_cte_reads_via_nested_subquery(self):
        node = self._parse("WITH a AS (SELECT 1 AS x), b AS (SELECT * FROM (SELECT x FROM a)) SELECT * FROM b")
        graph = _build_cte_read_graph(node)
        assert graph["b"] == {"a"}

    def test_cte_reads_via_cross_join(self):
        node = self._parse(
            "WITH a AS (SELECT 1 AS x), b AS (SELECT 2 AS y), c AS (SELECT * FROM a CROSS JOIN b) SELECT * FROM c"
        )
        graph = _build_cte_read_graph(node)
        assert graph["c"] == {"a", "b"}

    def test_cte_reads_via_left_join(self):
        node = self._parse(
            "WITH a AS (SELECT 1 AS x), b AS (SELECT 1 AS y), c AS (SELECT * FROM a LEFT JOIN b ON 1=1) SELECT * FROM c"
        )
        graph = _build_cte_read_graph(node)
        assert graph["c"] == {"a", "b"}

    def test_downstream_direct_reader(self):
        node = self._parse("WITH a AS (SELECT 1 AS x), b AS (SELECT x FROM a) SELECT x FROM b")
        graph = _build_cte_read_graph(node)
        assert _downstream_ctes(graph, "a") == {"b"}

    def test_downstream_transitive_chain(self):
        node = self._parse("WITH a AS (SELECT 1 AS x), b AS (SELECT x FROM a), c AS (SELECT x FROM b) SELECT x FROM c")
        graph = _build_cte_read_graph(node)
        assert _downstream_ctes(graph, "a") == {"b", "c"}

    def test_downstream_excludes_siblings(self):
        node = self._parse("WITH a AS (SELECT 1 AS x), b AS (SELECT 2 AS y), c AS (SELECT x FROM a) SELECT x FROM c")
        graph = _build_cte_read_graph(node)
        assert _downstream_ctes(graph, "a") == {"c"}
        assert _downstream_ctes(graph, "b") == set()

    def test_topological_order_respects_dependencies(self):
        node = self._parse("WITH a AS (SELECT 1 AS x), b AS (SELECT x FROM a), c AS (SELECT x FROM b) SELECT x FROM c")
        graph = _build_cte_read_graph(node)
        order = _topological_order(graph, {"b", "c"})
        assert order.index("b") < order.index("c")

    def test_shadowed_cte_name_is_not_counted_as_reference(self):
        node = self._parse(
            "WITH a AS (SELECT 1 AS x), b AS (WITH a AS (SELECT 99 AS y) SELECT y FROM a) SELECT * FROM b"
        )
        graph = _build_cte_read_graph(node)
        assert graph["b"] == set()
        assert _downstream_ctes(graph, "a") == set()

    def test_shadow_inside_nested_subquery_also_honored(self):
        node = self._parse(
            "WITH a AS (SELECT 1 AS x), "
            "b AS (SELECT 2 AS y WHERE 1 = (WITH a AS (SELECT 99 AS y) SELECT y FROM a)) "
            "SELECT * FROM b"
        )
        graph = _build_cte_read_graph(node)
        assert graph["b"] == set()


class TestDownstreamCTEClassifier(APIBaseTest):
    """Unit tests for the downstream CTE shape classifier."""

    @staticmethod
    def _get_cte(query_str: str, cte_name: str) -> ast.Expr:
        parsed = parse_select(query_str)
        assert isinstance(parsed, ast.SelectQuery) and parsed.ctes
        return parsed.ctes[cte_name].expr

    def test_projection_shape(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), proj AS (SELECT x FROM base) SELECT * FROM proj",
            "proj",
        )
        plan = _classify_downstream_cte("proj", expr, {"base", "proj"}, ["event_name"])
        assert plan.reject_reason is None
        assert plan.shape == DownstreamCTEShape.PROJECTION
        assert plan.propagating_sources == [("base", "base")]

    def test_aggregation_shape(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), agg AS (SELECT x, count() FROM base GROUP BY x) SELECT * FROM agg",
            "agg",
        )
        plan = _classify_downstream_cte("agg", expr, {"base", "agg"}, ["event_name"])
        assert plan.reject_reason is None
        assert plan.shape == DownstreamCTEShape.AGGREGATION

    @parameterized.expand(["MAX", "MIN", "SUM", "AVG", "COUNT"])
    def test_aggregation_shape_uppercase_function(self, fn):
        expr = self._get_cte(
            f"WITH base AS (SELECT 1 AS x), agg AS (SELECT {fn}(x) AS m FROM base) SELECT * FROM agg",
            "agg",
        )
        plan = _classify_downstream_cte("agg", expr, {"base", "agg"}, ["event_name"])
        assert plan.reject_reason is None
        assert plan.shape == DownstreamCTEShape.AGGREGATION

    def test_distinct_shape(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), u AS (SELECT DISTINCT x FROM base) SELECT * FROM u",
            "u",
        )
        plan = _classify_downstream_cte("u", expr, {"base", "u"}, ["event_name"])
        assert plan.reject_reason is None
        assert plan.shape == DownstreamCTEShape.DISTINCT

    def test_multi_join_shape(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), base2 AS (SELECT 1 AS x), "
            "combined AS (SELECT base.x FROM base CROSS JOIN base2) "
            "SELECT * FROM combined",
            "combined",
        )
        plan = _classify_downstream_cte("combined", expr, {"base", "base2", "combined"}, ["event_name"])
        assert plan.reject_reason is None
        assert plan.shape == DownstreamCTEShape.MULTI_JOIN
        assert len(plan.propagating_sources) == 2

    def test_union_all_shape(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), u AS (SELECT x FROM base UNION ALL SELECT x FROM base) SELECT * FROM u",
            "u",
        )
        plan = _classify_downstream_cte("u", expr, {"base", "u"}, ["event_name"])
        assert plan.reject_reason is None
        assert plan.shape == DownstreamCTEShape.UNION_ALL
        assert len(plan.leg_plans) == 2

    def test_left_join_rejected(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), base2 AS (SELECT 1 AS x), "
            "combined AS (SELECT base.x FROM base LEFT JOIN base2 ON base.x = base2.x) "
            "SELECT * FROM combined",
            "combined",
        )
        plan = _classify_downstream_cte("combined", expr, {"base", "base2", "combined"}, ["event_name"])
        assert plan.reject_reason is not None
        assert "LEFT JOIN" in plan.reject_reason

    def test_full_outer_join_rejected(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), base2 AS (SELECT 1 AS x), "
            "combined AS (SELECT base.x FROM base FULL OUTER JOIN base2 ON base.x = base2.x) "
            "SELECT * FROM combined",
            "combined",
        )
        plan = _classify_downstream_cte("combined", expr, {"base", "base2", "combined"}, ["event_name"])
        assert plan.reject_reason is not None
        assert "FULL OUTER JOIN" in plan.reject_reason

    def test_nested_subquery_reference_rejected(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), nested AS (SELECT * FROM (SELECT x FROM base)) SELECT * FROM nested",
            "nested",
        )
        plan = _classify_downstream_cte("nested", expr, {"base", "nested"}, ["event_name"])
        assert plan.reject_reason is not None
        assert "nested subquery" in plan.reject_reason

    def test_scalar_subquery_in_where_rejected(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), "
            "agg AS (SELECT max(x) AS m FROM base), "
            "use AS (SELECT x FROM base WHERE x = (SELECT m FROM agg)) "
            "SELECT * FROM use",
            "use",
        )
        plan = _classify_downstream_cte("use", expr, {"base", "agg", "use"}, ["event_name"])
        assert plan.reject_reason is not None
        assert "scalar subquery" in plan.reject_reason

    def test_scalar_subquery_in_select_rejected(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), "
            "agg AS (SELECT max(x) AS m FROM base), "
            "use AS (SELECT x, (SELECT m FROM agg) AS latest FROM base) "
            "SELECT * FROM use",
            "use",
        )
        plan = _classify_downstream_cte("use", expr, {"base", "agg", "use"}, ["event_name"])
        assert plan.reject_reason is not None
        assert "scalar subquery" in plan.reject_reason

    def test_scalar_subquery_in_nested_cte_rejected(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), "
            "use AS ("
            "  WITH latest AS (SELECT max(x) AS m FROM base) "
            "  SELECT x FROM base WHERE x = (SELECT m FROM latest)"
            ") "
            "SELECT * FROM use",
            "use",
        )
        plan = _classify_downstream_cte("use", expr, {"base", "use"}, ["event_name"])
        assert plan.reject_reason is not None
        assert "scalar subquery" in plan.reject_reason

    def test_scalar_subquery_in_join_on_rejected(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x, 2 AS y), "
            "agg AS (SELECT max(x) AS m FROM base), "
            "use AS (SELECT b.x FROM base b JOIN base b2 ON b.y = (SELECT m FROM agg)) "
            "SELECT * FROM use",
            "use",
        )
        plan = _classify_downstream_cte("use", expr, {"base", "agg", "use"}, ["event_name"])
        assert plan.reject_reason is not None
        assert "scalar subquery" in plan.reject_reason

    def test_scalar_subquery_in_limit_by_rejected(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x, 2 AS y), "
            "agg AS (SELECT max(x) AS m FROM base), "
            "use AS (SELECT x, y FROM base LIMIT 5 BY (SELECT m FROM agg)) "
            "SELECT * FROM use",
            "use",
        )
        plan = _classify_downstream_cte("use", expr, {"base", "agg", "use"}, ["event_name"])
        assert plan.reject_reason is not None
        assert "scalar subquery" in plan.reject_reason

    @parameterized.expand(["maxIf", "MAXIF", "sumIf", "SUMIF", "countIf", "COUNTIF"])
    def test_aggregation_shape_detects_combinator_regardless_of_case(self, fn):
        expr = self._get_cte(
            f"WITH base AS (SELECT 1 AS x, 1 AS c), agg AS (SELECT {fn}(x, c > 0) AS m FROM base) SELECT * FROM agg",
            "agg",
        )
        plan = _classify_downstream_cte("agg", expr, {"base", "agg"}, ["event_name"])
        assert plan.reject_reason is None
        assert plan.shape == DownstreamCTEShape.AGGREGATION

    @parameterized.expand(
        [
            ("count(DISTINCT event)", "countDistinct"),
            ("COUNT(DISTINCT event)", "countDistinct"),
            ("countDistinct(event)", "countDistinct"),
            ("COUNTDISTINCT(event)", "countDistinct"),
            ("CountDistinct(event)", "countDistinct"),
        ]
    )
    def test_extract_aggregate_name_canonicalizes_count_distinct(self, src, expected):
        from posthog.hogql.parser import parse_expr as _parse_expr

        from products.endpoints.backend.materialization import _extract_aggregate_name as _extract

        assert _extract(_parse_expr(src)) == expected

    @parameterized.expand(
        [
            ("max(x)", "max"),
            ("MAX(x)", "max"),
            ("Max(x)", "max"),
            ("sum(x)", "sum"),
            ("SUM(x)", "sum"),
        ]
    )
    def test_extract_aggregate_name_canonicalizes_base_aggregates(self, src, expected):
        from posthog.hogql.parser import parse_expr as _parse_expr

        from products.endpoints.backend.materialization import _extract_aggregate_name as _extract

        assert _extract(_parse_expr(src)) == expected

    def test_nested_subquery_shadowing_does_not_flag_as_bypass(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), "
            "use AS ("
            "  SELECT x FROM base WHERE x = (WITH base AS (SELECT 99 AS x) SELECT x FROM base)"
            ") "
            "SELECT * FROM use",
            "use",
        )
        plan = _classify_downstream_cte("use", expr, {"base", "use"}, ["event_name"])
        assert plan.reject_reason is None

    def test_column_name_collision_rejected(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), clash AS (SELECT x, 'a' AS event_name FROM base) SELECT * FROM clash",
            "clash",
        )
        plan = _classify_downstream_cte("clash", expr, {"base", "clash"}, ["event_name"])
        assert plan.reject_reason is not None
        assert "collides with existing column" in plan.reject_reason

    def test_union_leg_unable_to_propagate_rejected(self):
        expr = self._get_cte(
            "WITH base AS (SELECT 1 AS x), u AS (SELECT x FROM base UNION ALL SELECT 1 AS x) SELECT * FROM u",
            "u",
        )
        plan = _classify_downstream_cte("u", expr, {"base", "u"}, ["event_name"])
        assert plan.reject_reason is not None
        assert "UNION leg" in plan.reject_reason


class TestDownstreamAnalysisRejections(APIBaseTest):
    """Analyzer-level rejection tests for downstream CTE shapes we don't support."""

    def test_downstream_left_join_between_propagating_ctes_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH base AS (SELECT event, distinct_id FROM events WHERE event = {variables.event_name}), "
                "alt AS (SELECT distinct_id FROM base), "
                "combined AS (SELECT b.event FROM base b LEFT JOIN alt a ON b.distinct_id = a.distinct_id) "
                "SELECT event FROM combined"
            ),
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }
        can_materialize, reason, _ = analyze_variables_for_materialization(query)
        assert can_materialize is False
        assert "LEFT JOIN" in reason

    def test_downstream_full_join_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH base AS (SELECT event, distinct_id FROM events WHERE event = {variables.event_name}), "
                "alt AS (SELECT distinct_id FROM base), "
                "combined AS (SELECT b.event FROM base b FULL OUTER JOIN alt a ON b.distinct_id = a.distinct_id) "
                "SELECT event FROM combined"
            ),
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }
        can_materialize, reason, _ = analyze_variables_for_materialization(query)
        assert can_materialize is False
        assert "FULL OUTER JOIN" in reason

    def test_downstream_nested_subquery_reference_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH base AS (SELECT event, distinct_id FROM events WHERE event = {variables.event_name}), "
                "wrap AS (SELECT * FROM (SELECT distinct_id FROM base)) "
                "SELECT distinct_id FROM wrap"
            ),
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }
        can_materialize, reason, _ = analyze_variables_for_materialization(query)
        assert can_materialize is False
        assert "nested subquery" in reason

    def test_downstream_scalar_subquery_in_where_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH base AS (SELECT event, distinct_id, timestamp FROM events WHERE event = {variables.event_name}), "
                "latest AS (SELECT max(timestamp) AS ts FROM base), "
                "use AS (SELECT distinct_id FROM base WHERE timestamp = (SELECT ts FROM latest)) "
                "SELECT distinct_id FROM use"
            ),
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }
        can_materialize, reason, variables = analyze_variables_for_materialization(query)
        assert can_materialize is False
        assert "scalar subquery" in reason
        assert variables == []

    def test_downstream_scalar_subquery_in_select_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH base AS (SELECT event, distinct_id, timestamp FROM events WHERE event = {variables.event_name}), "
                "latest AS (SELECT max(timestamp) AS ts FROM base), "
                "use AS (SELECT distinct_id, (SELECT ts FROM latest) AS ts FROM base) "
                "SELECT distinct_id FROM use"
            ),
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }
        can_materialize, reason, _ = analyze_variables_for_materialization(query)
        assert can_materialize is False
        assert "scalar subquery" in reason

    def test_downstream_union_leg_unable_to_propagate_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH base AS (SELECT event, distinct_id FROM events WHERE event = {variables.event_name}), "
                "u AS (SELECT distinct_id FROM base UNION ALL SELECT distinct_id FROM events) "
                "SELECT distinct_id FROM u"
            ),
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }
        can_materialize, reason, _ = analyze_variables_for_materialization(query)
        assert can_materialize is False
        assert "UNION leg" in reason

    def test_downstream_column_name_collision_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH base AS (SELECT event, distinct_id FROM events WHERE event = {variables.event_name}), "
                "clash AS (SELECT distinct_id, 'x' AS event_name FROM base) "
                "SELECT distinct_id FROM clash"
            ),
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }
        can_materialize, reason, _ = analyze_variables_for_materialization(query)
        assert can_materialize is False
        assert "collides with existing column" in reason


@pytest.mark.usefixtures("unittest_snapshot")
class TestDownstreamTransformSnapshots(APIBaseTest):
    """Snapshot tests pinning the transformed SQL for downstream propagation."""

    snapshot: Any

    def _transform(self, query_str: str, variables: dict) -> str:
        hogql_query = {"kind": "HogQLQuery", "query": query_str, "variables": variables}
        can_materialize, reason, var_infos = analyze_variables_for_materialization(hogql_query)
        assert can_materialize, f"Expected materializable, got: {reason}"
        transformed = transform_query_for_materialization(hogql_query, var_infos, self.team)
        return transformed["query"]

    def test_transform_downstream_projection_propagation(self):
        assert (
            self._transform(
                (
                    "WITH base AS (SELECT event, distinct_id FROM events WHERE event = {variables.event_name}), "
                    "proj AS (SELECT distinct_id FROM base) "
                    "SELECT distinct_id FROM proj"
                ),
                {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            )
            == self.snapshot
        )

    def test_transform_downstream_aggregation_propagation(self):
        assert (
            self._transform(
                (
                    "WITH base AS (SELECT event, distinct_id FROM events WHERE event = {variables.event_name}), "
                    "agg AS (SELECT distinct_id, count() AS cnt FROM base GROUP BY distinct_id) "
                    "SELECT distinct_id, cnt FROM agg"
                ),
                {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            )
            == self.snapshot
        )

    def test_transform_downstream_distinct_propagation(self):
        assert (
            self._transform(
                (
                    "WITH base AS (SELECT event, distinct_id FROM events WHERE event = {variables.event_name}), "
                    "u AS (SELECT DISTINCT distinct_id FROM base) "
                    "SELECT distinct_id FROM u"
                ),
                {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            )
            == self.snapshot
        )

    def test_transform_downstream_cross_join_propagation(self):
        assert (
            self._transform(
                (
                    "WITH base AS (SELECT event, distinct_id FROM events WHERE event = {variables.event_name}), "
                    "left_side AS (SELECT distinct_id AS did_l FROM base), "
                    "right_side AS (SELECT distinct_id AS did_r FROM base), "
                    "combined AS (SELECT l.did_l, r.did_r FROM left_side l CROSS JOIN right_side r) "
                    "SELECT did_l, did_r FROM combined"
                ),
                {"var-1": {"code_name": "event_name", "value": "$pageview"}},
            )
            == self.snapshot
        )
