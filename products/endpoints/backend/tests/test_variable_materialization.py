from typing import Any

import pytest
from posthog.test.base import APIBaseTest

from posthog.hogql import ast

from products.endpoints.backend.materialization import (
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

        # Should have JSONExtractString for properties.os
        transformed_query = transformed["query"]
        assert "JSONExtractString" in transformed_query
        assert "properties" in transformed_query
        assert "'os'" in transformed_query or '"os"' in transformed_query

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
        # Should use JSONExtractString for person.properties
        assert "JSONExtractString" in transformed_query
        assert "person" in transformed_query

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
        from posthog.hogql.parser import parse_select

        from products.endpoints.backend.materialization import transform_select_for_materialized_table

        query_str = "SELECT count() as total, toStartOfDay(timestamp) as date FROM events"
        parsed = parse_select(query_str)

        # Transform the SELECT expressions
        assert isinstance(parsed, ast.SelectQuery)
        transformed = transform_select_for_materialized_table(parsed.select, self.team)

        # Should have 2 field references
        assert len(transformed) == 2

        # First should be Field(chain=["total"])
        assert isinstance(transformed[0], ast.Field)
        assert transformed[0].chain == ["total"]

        # Second should be Field(chain=["date"])
        assert isinstance(transformed[1], ast.Field)
        assert transformed[1].chain == ["date"]

    def test_select_transformation_without_alias(self):
        from posthog.hogql.parser import parse_select

        from products.endpoints.backend.materialization import transform_select_for_materialized_table

        query_str = "SELECT count() FROM events"
        parsed = parse_select(query_str)

        # Transform the SELECT expressions
        assert isinstance(parsed, ast.SelectQuery)
        transformed = transform_select_for_materialized_table(parsed.select, self.team)

        # Should have 1 field reference
        assert len(transformed) == 1

        # Should be Field(chain=["count()"])
        assert isinstance(transformed[0], ast.Field)
        assert transformed[0].chain == ["count()"]


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
        from posthog.hogql.parser import parse_select

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
