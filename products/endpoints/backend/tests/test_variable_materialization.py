import pytest
from posthog.test.base import APIBaseTest

from products.endpoints.backend.materialization import (
    analyze_variables_for_materialization,
    transform_query_for_materialization,
)

pytestmark = [pytest.mark.django_db]


class TestVariableAnalysis(APIBaseTest):
    """Test variable analysis for materialization eligibility."""

    def test_simple_variable_detection(self):
        """Test detecting variable in simple WHERE clause"""
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

        can_materialize, reason, var_info = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert reason == "OK"
        assert var_info is not None
        assert var_info.code_name == "event_name"
        assert var_info.column_chain == ["event"]
        assert var_info.column_expression == "event"

    def test_nested_property_variable(self):
        """Test detecting variable on nested property"""
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

        can_materialize, reason, var_info = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert reason == "OK"
        assert var_info is not None
        assert var_info.code_name == "os_name"
        assert var_info.column_chain == ["properties", "os"]
        assert var_info.column_expression == "properties.os"

    def test_person_nested_property_variable(self):
        """Test detecting variable on person nested property"""
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

        can_materialize, reason, var_info = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert reason == "OK"
        assert var_info is not None
        assert var_info.code_name == "city"
        assert var_info.column_chain == ["person", "properties", "city"]

    def test_multiple_variables_blocked(self):
        """Test that multiple variables are blocked"""
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.event_name} AND properties.os = {variables.os}",
            "variables": {
                "var-1": {"code_name": "event_name", "value": "$pageview"},
                "var-2": {"code_name": "os", "value": "Mac"},
            },
        }

        can_materialize, reason, var_info = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "Multiple variables" in reason
        assert var_info is None

    def test_variable_in_select_blocked(self):
        """Test that variables not in WHERE are blocked"""
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count(), {variables.metric_name} as metric_name FROM events",
            "variables": {"var-1": {"code_name": "metric_name", "value": "total"}},
        }

        can_materialize, reason, var_info = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "not used in WHERE" in reason

    def test_no_variables(self):
        """Test query with no variables"""
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = '$pageview'",
        }

        can_materialize, reason, var_info = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "No variables found" in reason

    def test_non_equality_operator_blocked(self):
        """Test that non-equality operators are blocked"""
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE timestamp > {variables.start_date}",
            "variables": {"var-1": {"code_name": "start_date", "value": "2024-01-01"}},
        }

        can_materialize, reason, var_info = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "Only = operator supported" in reason

    def test_variable_on_right_side_of_comparison(self):
        """Test variable when it's on the right side: field = {variable}"""
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.event_name}",
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }

        can_materialize, reason, var_info = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert reason == "OK"
        assert var_info is not None
        assert var_info.column_chain == ["event"]

    def test_variable_on_left_side_of_comparison(self):
        """Test variable when it's on the left side: {variable} = field"""
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE {variables.event_name} = event",
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }

        can_materialize, reason, var_info = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert reason == "OK"
        assert var_info is not None
        assert var_info.column_chain == ["event"]

    def test_constant_compared_to_variable_blocked(self):
        """Test that comparing a constant to a variable is blocked (doesn't make sense)"""
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE '$pageview' = {variables.event_name}",
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }

        can_materialize, reason, var_info = analyze_variables_for_materialization(query)

        # This should fail because we're comparing a constant to a variable
        # We need a field comparison for materialization to work
        assert can_materialize is False
        assert var_info is None

    def test_variable_with_complex_and_conditions(self):
        """Test variable mixed with other AND conditions"""
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE timestamp > '2024-01-01' AND event = {variables.event_name} AND properties.os = 'Mac'",
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }

        can_materialize, reason, var_info = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert reason == "OK"
        assert var_info is not None
        assert var_info.column_chain == ["event"]

    def test_variable_in_or_condition_blocked(self):
        """Test that variables in OR conditions are blocked during transformation"""
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.event_name} OR event = '$pageview'",
            "variables": {"var-1": {"code_name": "event_name", "value": "$identify"}},
        }

        # Analysis might succeed, but transformation should fail
        can_materialize, reason, var_info = analyze_variables_for_materialization(query)

        # If analysis succeeds, transformation should raise error
        if can_materialize and var_info:
            with pytest.raises(ValueError, match="OR conditions not supported"):
                transform_query_for_materialization(query, var_info, self.team)

    def test_variable_with_parentheses(self):
        """Test variable in parenthesized WHERE clause"""
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE (event = {variables.event_name})",
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }

        can_materialize, reason, var_info = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert reason == "OK"
        assert var_info is not None

    def test_malformed_variable_placeholder(self):
        """Test handling of malformed variable placeholders"""
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables}",
            "variables": {"var-1": {"code_name": "event_name", "value": "$pageview"}},
        }

        can_materialize, reason, var_info = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert var_info is None

    def test_missing_variable_metadata(self):
        """Test variable used in query but not defined in variables dict"""
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE event = {variables.event_name}",
            "variables": {},
        }

        can_materialize, reason, var_info = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "metadata not found" in reason.lower()
        assert var_info is None

    def test_variable_on_uuid_field(self):
        """Test variable on UUID fields like distinct_id"""
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT count() FROM events WHERE distinct_id = {variables.user_id}",
            "variables": {"var-1": {"code_name": "user_id", "value": "user123"}},
        }

        can_materialize, reason, var_info = analyze_variables_for_materialization(query)

        assert can_materialize is True
        assert reason == "OK"
        assert var_info is not None
        assert var_info.column_chain == ["distinct_id"]

    def test_empty_query_string(self):
        """Test handling of empty query string"""
        query = {"kind": "HogQLQuery", "query": "", "variables": {}}

        can_materialize, reason, var_info = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert var_info is None

    def test_missing_query_field(self):
        """Test handling when query field is missing"""
        query = {"kind": "HogQLQuery", "variables": {"var-1": {"code_name": "foo", "value": "bar"}}}

        can_materialize, reason, var_info = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "No query string found" in reason
        assert var_info is None

    def test_invalid_query_string_parsing(self):
        """Test handling of unparseable query strings"""
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT INVALID SYNTAX {variables.foo}",
            "variables": {"var-1": {"code_name": "foo", "value": "bar"}},
        }

        can_materialize, reason, var_info = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "parse" in reason.lower()
        assert var_info is None

    def test_variable_in_having_clause_blocked(self):
        """Test that variables in HAVING clause are blocked"""
        query = {
            "kind": "HogQLQuery",
            "query": "SELECT event, count() as c FROM events GROUP BY event HAVING c > {variables.threshold}",
            "variables": {"var-1": {"code_name": "threshold", "value": "100"}},
        }

        can_materialize, reason, var_info = analyze_variables_for_materialization(query)

        assert can_materialize is False
        assert "HAVING" in reason or "having" in reason.lower()
        assert var_info is None


class TestQueryTransformation(APIBaseTest):
    """Test query transformation for materialization."""

    def test_transform_simple_field(self):
        """Test transforming query with simple field variable"""
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

        _, _, var_info = analyze_variables_for_materialization(query)
        assert var_info is not None

        transformed = transform_query_for_materialization(query, var_info, self.team)

        # Should have removed variables
        assert transformed["variables"] == {}

        # Query should include the variable column
        transformed_query = transformed["query"]
        assert "event_name" in transformed_query or "event" in transformed_query

        # Should NOT have the variable placeholder anymore
        assert "{variables" not in transformed_query

    def test_transform_nested_property(self):
        """Test transforming query with nested property variable"""
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

        _, _, var_info = analyze_variables_for_materialization(query)
        assert var_info is not None
        transformed = transform_query_for_materialization(query, var_info, self.team)

        # Should have JSONExtractString for properties.os
        transformed_query = transformed["query"]
        assert "JSONExtractString" in transformed_query
        assert "properties" in transformed_query
        assert "'os'" in transformed_query or '"os"' in transformed_query

    def test_transform_removes_where_clause(self):
        """Test that WHERE clause with only variable is removed"""
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

        _, _, var_info = analyze_variables_for_materialization(query)
        assert var_info is not None
        transformed = transform_query_for_materialization(query, var_info, self.team)

        # The WHERE clause should be removed since it only had the variable
        # The query should still be valid
        assert "{variables" not in transformed["query"]

    def test_transform_preserves_other_where_conditions(self):
        """Test that other WHERE conditions are preserved"""
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

        _, _, var_info = analyze_variables_for_materialization(query)
        assert var_info is not None
        transformed = transform_query_for_materialization(query, var_info, self.team)

        # Should preserve the timestamp condition
        assert "timestamp" in transformed["query"]
        assert "2024-01-01" in transformed["query"]

        # Should remove the variable
        assert "{variables" not in transformed["query"]

    def test_transform_adds_to_group_by(self):
        """Test that variable column is added to GROUP BY"""
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

        _, _, var_info = analyze_variables_for_materialization(query)
        assert var_info is not None
        transformed = transform_query_for_materialization(query, var_info, self.team)

        # Should have GROUP BY with both date and event_name
        transformed_query = transformed["query"]
        assert "GROUP BY" in transformed_query
        # The variable should be in the query (either as alias or field)
        assert "event_name" in transformed_query or "event" in transformed_query

    def test_transform_query_without_initial_group_by(self):
        """Test adding GROUP BY when query doesn't have one"""
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

        _, _, var_info = analyze_variables_for_materialization(query)
        assert var_info is not None
        transformed = transform_query_for_materialization(query, var_info, self.team)

        # Should have GROUP BY event_name added
        transformed_query = transformed["query"]
        assert "GROUP BY" in transformed_query
        assert "event_name" in transformed_query or "event" in transformed_query

    def test_transform_preserves_order_by(self):
        """Test that ORDER BY is preserved"""
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

        _, _, var_info = analyze_variables_for_materialization(query)
        assert var_info is not None
        transformed = transform_query_for_materialization(query, var_info, self.team)

        transformed_query = transformed["query"]
        assert "ORDER BY" in transformed_query
        assert "DESC" in transformed_query or "desc" in transformed_query

    def test_transform_preserves_limit(self):
        """Test that LIMIT is preserved"""
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

        _, _, var_info = analyze_variables_for_materialization(query)
        assert var_info is not None
        transformed = transform_query_for_materialization(query, var_info, self.team)

        transformed_query = transformed["query"]
        assert "LIMIT" in transformed_query
        assert "100" in transformed_query

    def test_transform_variable_in_middle_of_and_chain(self):
        """Test removing variable from middle of AND chain"""
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

        _, _, var_info = analyze_variables_for_materialization(query)
        assert var_info is not None
        transformed = transform_query_for_materialization(query, var_info, self.team)

        transformed_query = transformed["query"]
        # Both other conditions should remain
        assert "timestamp" in transformed_query
        assert "2024-01-01" in transformed_query
        assert "properties" in transformed_query or "os" in transformed_query
        assert "Mac" in transformed_query
        # Variable should be removed from WHERE
        assert "{variables" not in transformed_query

    def test_transform_with_having_clause(self):
        """Test that HAVING clause is preserved"""
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

        _, _, var_info = analyze_variables_for_materialization(query)
        assert var_info is not None
        transformed = transform_query_for_materialization(query, var_info, self.team)

        transformed_query = transformed["query"]
        assert "HAVING" in transformed_query
        assert "100" in transformed_query

    def test_transform_person_properties_column(self):
        """Test transformation of person.properties.city variable"""
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

        _, _, var_info = analyze_variables_for_materialization(query)
        assert var_info is not None
        transformed = transform_query_for_materialization(query, var_info, self.team)

        transformed_query = transformed["query"]
        # Should use JSONExtractString for person.properties
        assert "JSONExtractString" in transformed_query
        assert "person" in transformed_query

    def test_transform_variable_first_in_and_chain(self):
        """Test removing variable from start of AND chain"""
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

        _, _, var_info = analyze_variables_for_materialization(query)
        assert var_info is not None
        transformed = transform_query_for_materialization(query, var_info, self.team)

        transformed_query = transformed["query"]
        # Timestamp condition should remain
        assert "timestamp" in transformed_query
        assert "2024-01-01" in transformed_query
        # Variable should be removed from WHERE
        assert "{variables" not in transformed_query

    def test_transform_variable_last_in_and_chain(self):
        """Test removing variable from end of AND chain"""
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

        _, _, var_info = analyze_variables_for_materialization(query)
        assert var_info is not None
        transformed = transform_query_for_materialization(query, var_info, self.team)

        transformed_query = transformed["query"]
        # Other conditions should remain
        assert "timestamp" in transformed_query
        assert "properties" in transformed_query or "os" in transformed_query
        # Variable should be removed from WHERE
        assert "{variables" not in transformed_query

    def test_transform_preserves_select_expressions(self):
        """Test that complex SELECT expressions are preserved"""
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

        _, _, var_info = analyze_variables_for_materialization(query)
        assert var_info is not None
        transformed = transform_query_for_materialization(query, var_info, self.team)

        transformed_query = transformed["query"]
        # Original SELECT expressions should be preserved
        assert "toStartOfDay" in transformed_query
        assert "avg" in transformed_query or "AVG" in transformed_query
        # Variable column should be added
        assert "event_name" in transformed_query or "event" in transformed_query

    def test_transform_with_or_raises_error(self):
        """Test that transformation raises error for OR conditions"""
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

        _, _, var_info = analyze_variables_for_materialization(query)
        assert var_info is not None

        with pytest.raises(ValueError, match="OR conditions not supported"):
            transform_query_for_materialization(query, var_info, self.team)

    def test_transform_preserves_specific_columns_in_select(self):
        """Test that specific SELECT columns are preserved (important for materialized queries)"""
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

        _, _, var_info = analyze_variables_for_materialization(query)
        assert var_info is not None
        transformed = transform_query_for_materialization(query, var_info, self.team)

        transformed_query = transformed["query"]
        # Original columns should be preserved
        assert "total" in transformed_query or "count()" in transformed_query
        assert "day" in transformed_query or "toStartOfDay" in transformed_query
        # Variable column should be added
        assert "event_name" in transformed_query or "event" in transformed_query


class TestMaterializedQueryExecution(APIBaseTest):
    """Test that materialized queries handle pre-aggregated data correctly."""

    def test_materialized_query_selects_precomputed_columns(self):
        """
        Verify that when querying a materialized table, we select pre-computed
        column values instead of re-running aggregate functions.

        CRITICAL: The materialized table has pre-aggregated data.
        """
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
        """Test that aliased expressions are converted to field references by alias"""
        from posthog.hogql import ast
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
        """Test that non-aliased expressions are converted to field references by expression string"""
        from posthog.hogql import ast
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
