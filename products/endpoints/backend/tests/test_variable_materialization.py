from typing import Any

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest import mock

from parameterized import parameterized

from posthog.schema import DataWarehouseNode, TrendsQuery

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.endpoints.backend.materialization_transforms import (
    MaterializableVariable,
    MaterializationNotSupportedError,
    analyze_variables_for_materialization,
    build_endpoint_hogql,
    transform_query_for_materialization,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

pytestmark = [pytest.mark.django_db]


class TestVariableAnalysis(APIBaseTest):
    """Test variable analysis for materialization eligibility."""

    def test_materialization_transform_compiles_warehouse_table_without_user_context(self):
        table = DataWarehouseTable.objects.create(
            team=self.team,
            name="web_vitals_mv",
            columns={"page": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True}},
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern="s3://test-bucket/web-vitals/*.parquet",
        )
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM web_vitals_mv WHERE page = {variables.page}",
            "variables": {
                "page-variable": {
                    "variableId": "page-variable",
                    "code_name": "page",
                    "value": "/pricing",
                }
            },
        }

        with mock.patch("posthog.hogql.database.database.feature_enabled_or_false", return_value=True):
            materialized_query = build_endpoint_hogql(query, self.team, bypass_warehouse_access_control=True)

        assert materialized_query["variables"] == {}
        assert "{variables" not in materialized_query["query"]
        assert table.name in materialized_query["query"]
        assert "page" in materialized_query["query"]

    def test_materialization_transform_respects_user_warehouse_access_control(self):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

        table = DataWarehouseTable.objects.create(
            team=self.team,
            name="denied_web_vitals_mv",
            columns={
                "id": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True},
                "timestamp": {"hogql": "DateTimeDatabaseField", "clickhouse": "DateTime", "valid": True},
            },
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern="s3://test-bucket/denied-web-vitals/*.parquet",
        )
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_table",
            resource_id=str(table.id),
            access_level="none",
            organization_member=membership,
        )
        query = TrendsQuery(
            series=[
                DataWarehouseNode(
                    id=table.name,
                    table_name=table.name,
                    id_field="id",
                    distinct_id_field="id",
                    timestamp_field="timestamp",
                )
            ]
        ).model_dump()

        with mock.patch("posthog.hogql.database.database.feature_enabled_or_false", return_value=True):
            with pytest.raises(QueryError, match=f"You don't have access to table `{table.name}`"):
                build_endpoint_hogql(query, self.team, user=self.user)

            materialized_query = build_endpoint_hogql(query, self.team, bypass_warehouse_access_control=True)

        assert table.name in materialized_query["query"]

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

    def test_variable_compared_against_expression_holding_another_variable(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "SELECT count() FROM events "
                "WHERE toDate(toTimeZone(timestamp, {variables.timezone})) >= toDate({variables.date_from})"
            ),
            "variables": {
                "var-1": {"code_name": "timezone", "value": "America/New_York"},
                "var-2": {"code_name": "date_from", "value": "2026-01-01"},
            },
        }

        can_materialize, reason, _ = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert reason == (
            "Variable compared against an expression containing another variable is not supported for materialization"
        )

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

    @parameterized.expand(
        [
            # Variable inside an OR can't be lifted into a single materialized key column.
            (
                "or_condition",
                "SELECT count() FROM events WHERE event = {variables.event_name} OR event = '$pageview'",
                {"var-1": {"code_name": "event_name", "value": "$identify"}},
                False,
                "OR conditions",
                0,
            ),
            # Reproduction of a real failure: same variable across two OR branches, two
            # different columns, one branch using ILIKE.
            (
                "or_with_multiple_columns",
                "SELECT count() FROM events\n"
                "WHERE (event = '$pageview' AND properties.$current_url ILIKE CONCAT('%/refer?p_ref=', {variables.playeruuid}, '%'))\n"
                "   OR (event = 'referral-impression' AND properties.referrer_uuid = {variables.playeruuid})",
                {"var-1": {"code_name": "playeruuid", "value": "191e674e"}},
                False,
                "OR conditions",
                0,
            ),
            # Same variable, two AND'd branches, but two different columns — no single bucket key.
            (
                "multiple_columns",
                "SELECT count() FROM events WHERE properties.a = {variables.v} AND properties.b = {variables.v}",
                {"var-1": {"code_name": "v", "value": "x"}},
                False,
                "multiple columns",
                0,
            ),
            # An OR that doesn't contain the variable must not trip the OR guard.
            (
                "or_without_variable_allowed",
                "SELECT count() FROM events WHERE event = {variables.event_name} AND (properties.a = '1' OR properties.b = '2')",
                {"var-1": {"code_name": "event_name", "value": "$pageview"}},
                True,
                "OK",
                1,
            ),
        ]
    )
    def test_or_and_multi_column_variable_analysis(
        self, _name, query_str, variables, expected_can_materialize, expected_reason, expected_var_count
    ):
        query = {"kind": "HogQLQuery", "query": query_str, "variables": variables}

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is expected_can_materialize
        assert expected_reason in reason
        assert len(var_infos) == expected_var_count

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

    def test_transform_variable_column_already_aliased_in_select(self):
        # Regression: enabling materialization raised "Cannot redefine an alias" when the
        # query already selects the variable's column aliased by the variable's code_name.
        query = {
            "kind": "HogQLQuery",
            "query": (
                "SELECT properties.profile_id AS profile_id, properties.card_id AS card_id, count() AS tap_count "
                "FROM events "
                "WHERE event = 'card_tapped' AND properties.profile_id = {variables.profile_id} "
                "GROUP BY profile_id, card_id"
            ),
            "variables": {
                "var-1": {"variableId": "var-1", "code_name": "profile_id", "value": ""},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)
        assert can_materialize is True, reason

        transformed = transform_query_for_materialization(query, var_infos, self.team)

        transformed_query = transformed["query"]
        assert "{variables" not in transformed_query
        assert transformed_query.count("AS profile_id") == 1

    def test_alias_collision_with_different_expression_rejected_preflight(self):
        # A variable code_name colliding with a SELECT alias for a *different* expression
        # can't be materialized (the table would need two columns named profile_id).
        # Pre-flight must reject it so enabling is never attempted — otherwise the transform
        # fails at enable time with a generic server error.
        query = {
            "kind": "HogQLQuery",
            "query": (
                "SELECT properties.card_id AS profile_id, count() AS tap_count "
                "FROM events "
                "WHERE properties.profile_id = {variables.profile_id} "
                "GROUP BY profile_id"
            ),
            "variables": {
                "var-1": {"variableId": "var-1", "code_name": "profile_id", "value": ""},
            },
        }

        can_materialize, reason, var_infos = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "conflicts with an existing SELECT alias" in reason
        assert var_infos == []

    def test_transform_alias_collision_raises_not_supported(self):
        # Backstop: if the transform is reached directly (bypassing pre-flight) on a colliding
        # query, it raises MaterializationNotSupportedError (a 400), not a bare ValueError (a 500).
        query = {
            "kind": "HogQLQuery",
            "query": (
                "SELECT properties.card_id AS profile_id, count() AS tap_count "
                "FROM events "
                "WHERE properties.profile_id = {variables.profile_id} "
                "GROUP BY profile_id"
            ),
            "variables": {
                "var-1": {"variableId": "var-1", "code_name": "profile_id", "value": ""},
            },
        }

        var_infos = [
            MaterializableVariable(
                variable_id="var-1",
                code_name="profile_id",
                column_chain=["properties", "profile_id"],
                column_expression="properties.profile_id",
            )
        ]

        with pytest.raises(MaterializationNotSupportedError, match="conflicts with an existing SELECT alias"):
            transform_query_for_materialization(query, var_infos, self.team)

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

        # Analysis now rejects OR up-front, so feed the transform a hand-built var_info to
        # confirm the transform itself still guards against OR as a backstop.
        var_infos = [
            MaterializableVariable(
                variable_id="var-123",
                code_name="event_name",
                column_chain=["event"],
                column_expression="event",
            )
        ]

        with pytest.raises(MaterializationNotSupportedError, match="OR conditions not supported"):
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
        from products.endpoints.backend.materialization_transforms import transform_select_for_materialized_table

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
        from products.endpoints.backend.materialization_transforms import transform_select_for_materialized_table

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
        from products.endpoints.backend.materialization_transforms import MaterializationTransformer

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


class TestMaterializationAnalyzerGaps(APIBaseTest):
    def test_top_level_scalar_subquery_consuming_propagating_cte_rejected(self):
        query = {
            "kind": "HogQLQuery",
            "query": (
                "WITH org_events AS ("
                "  SELECT timestamp, distinct_id FROM events WHERE event = {variables.event_name}"
                "), latest_ts AS ("
                "  SELECT max(timestamp) AS ts FROM org_events"
                ") "
                "SELECT distinct_id FROM org_events "
                "WHERE timestamp = (SELECT ts FROM latest_ts)"
            ),
            "variables": {
                "var-1": {"variableId": "var-1", "code_name": "event_name", "value": "$pageview"},
            },
        }

        can_materialize, reason, _ = analyze_variables_for_materialization(query)

        assert can_materialize is False, (
            f"Expected rejection — scalar subquery in top-level query consumes a propagating "
            f"CTE, which the transformer can't rewrite to a per-variable-value form. "
            f"Got reason={reason!r}."
        )
        assert "subquery" in reason.lower() or "scalar" in reason.lower(), (
            f"Rejection reason should mention the scalar-subquery pattern. Got: {reason!r}"
        )

    def test_top_level_variable_does_not_force_group_by_on_non_aggregate_select(self):
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT distinct_id, event, timestamp FROM events WHERE event = {variables.event_name}",
            "variables": {
                "var-1": {"variableId": "var-1", "code_name": "event_name", "value": "$pageview"},
            },
        }

        _, _, var_infos = analyze_variables_for_materialization(query)
        transformed = transform_query_for_materialization(query, var_infos, self.team)
        transformed_sql = transformed["query"]

        assert "GROUP BY" not in transformed_sql.upper(), (
            "Transformer must not add GROUP BY for a non-aggregating top-level SELECT — "
            "doing so makes the other projected columns invalid (not aggregated, not grouped). "
            f"Got:\n{transformed_sql}"
        )
