from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.logic.rules import get_client_safe_filters


class TestGetClientSafeFilters(SimpleTestCase):
    @parameterized.expand(
        [
            # All client-safe: returned as-is
            (
                "all_client_safe",
                {
                    "type": "AND",
                    "values": [{"type": "event", "operator": "exact", "key": "$exception_types", "value": "TypeError"}],
                },
                {
                    "type": "AND",
                    "values": [{"type": "event", "operator": "exact", "key": "$exception_types", "value": "TypeError"}],
                },
            ),
            (
                "or_all_client_safe",
                {
                    "type": "OR",
                    "values": [{"type": "event", "operator": "exact", "key": "$exception_types", "value": "TypeError"}],
                },
                {
                    "type": "OR",
                    "values": [{"type": "event", "operator": "exact", "key": "$exception_types", "value": "TypeError"}],
                },
            ),
            (
                "negative_operator_is_client_safe",
                {
                    "type": "AND",
                    "values": [
                        {"type": "event", "operator": "is_not", "key": "$exception_types", "value": "TypeError"},
                        {
                            "type": "event",
                            "operator": "not_icontains",
                            "key": "$exception_values",
                            "value": "expected",
                        },
                    ],
                },
                {
                    "type": "AND",
                    "values": [
                        {"type": "event", "operator": "is_not", "key": "$exception_types", "value": "TypeError"},
                        {
                            "type": "event",
                            "operator": "not_icontains",
                            "key": "$exception_values",
                            "value": "expected",
                        },
                    ],
                },
            ),
            # Any server-only property → entire rule returns None
            (
                "server_only_property_returns_none",
                {
                    "type": "AND",
                    "values": [{"type": "event", "operator": "exact", "key": "$exception_sources", "value": "app.js"}],
                },
                None,
            ),
            (
                "mixed_safe_and_server_only_returns_none",
                {
                    "type": "AND",
                    "values": [
                        {"type": "event", "operator": "exact", "key": "$exception_types", "value": "TypeError"},
                        {"type": "event", "operator": "exact", "key": "$exception_sources", "value": "app.js"},
                    ],
                },
                None,
            ),
            (
                "or_with_server_only_returns_none",
                {
                    "type": "OR",
                    "values": [
                        {"type": "event", "operator": "exact", "key": "$exception_types", "value": "TypeError"},
                        {"type": "event", "operator": "exact", "key": "$exception_sources", "value": "app.js"},
                    ],
                },
                None,
            ),
            # Operators withheld from client evaluation
            (
                "unimplemented_operator_returns_none",
                {
                    "type": "AND",
                    "values": [{"type": "event", "operator": "is_not_set", "key": "$exception_types", "value": None}],
                },
                None,
            ),
            (
                "server_only_operator_returns_none",
                {
                    "type": "AND",
                    "values": [
                        {"type": "event", "operator": "starts_with", "key": "$exception_values", "value": "Cannot"}
                    ],
                },
                None,
            ),
            (
                "greater_than_returns_none",
                {
                    "type": "AND",
                    "values": [{"type": "event", "operator": "gt", "key": "$exception_values", "value": "1"}],
                },
                None,
            ),
            (
                "less_than_returns_none",
                {
                    "type": "AND",
                    "values": [{"type": "event", "operator": "lt", "key": "$exception_values", "value": "1"}],
                },
                None,
            ),
            (
                "regex_returns_none",
                {
                    "type": "AND",
                    "values": [{"type": "event", "operator": "regex", "key": "$exception_values", "value": "error.*"}],
                },
                None,
            ),
            (
                "not_regex_returns_none",
                {
                    "type": "AND",
                    "values": [
                        {"type": "event", "operator": "not_regex", "key": "$exception_values", "value": "error.*"}
                    ],
                },
                None,
            ),
            (
                "missing_operator_returns_none",
                {"type": "AND", "values": [{"type": "event", "key": "$exception_types", "value": "TypeError"}]},
                None,
            ),
            (
                "nested_unimplemented_operator_returns_none",
                {
                    "type": "OR",
                    "values": [
                        {"operator": "exact", "key": "$exception_types", "value": "TypeError"},
                        {
                            "type": "AND",
                            "values": [{"operator": "is_not_set", "key": "$exception_values", "value": None}],
                        },
                    ],
                },
                None,
            ),
            # Edge cases
            (
                "empty_values_list",
                {"type": "AND", "values": []},
                None,
            ),
            (
                "empty_or_values_list",
                {"type": "OR", "values": []},
                None,
            ),
            (
                "missing_leaf_type",
                {"type": "AND", "values": [{"operator": "exact", "key": "$exception_types", "value": "TypeError"}]},
                None,
            ),
            (
                "non_string_leaf_type",
                {
                    "type": "AND",
                    "values": [{"type": 1, "operator": "exact", "key": "$exception_types", "value": "TypeError"}],
                },
                None,
            ),
            (
                "legacy_list_filters",
                [],
                None,
            ),
            (
                "missing_rule_type",
                {"values": []},
                None,
            ),
            (
                "invalid_rule_type",
                {"type": "NOT", "values": []},
                None,
            ),
            (
                "missing_values_key",
                {"type": "AND"},
                None,
            ),
            (
                "non_list_values",
                {"type": "AND", "values": "invalid"},
                None,
            ),
            (
                "non_object_value",
                {"type": "AND", "values": ["invalid"]},
                None,
            ),
            (
                "unsupported_property_returns_none",
                {"type": "AND", "values": [{"type": "event", "operator": "exact", "key": "$lib", "value": "web"}]},
                None,
            ),
            (
                "non_string_value_returns_none",
                {
                    "type": "AND",
                    "values": [{"type": "event", "operator": "exact", "key": "$exception_types", "value": 1}],
                },
                None,
            ),
            (
                "non_string_array_value_returns_none",
                {
                    "type": "AND",
                    "values": [
                        {"type": "event", "operator": "exact", "key": "$exception_types", "value": ["TypeError", 1]}
                    ],
                },
                None,
            ),
            # Nested groups
            (
                "nested_all_safe",
                {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"operator": "exact", "key": "$exception_types", "value": "TypeError"},
                                {"operator": "regex", "key": "$exception_values", "value": ".*null.*"},
                            ],
                        }
                    ],
                },
                None,
            ),
            (
                "nested_with_server_only_returns_none",
                {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"operator": "exact", "key": "$exception_types", "value": "TypeError"},
                                {"operator": "exact", "key": "$exception_sources", "value": "app.js"},
                            ],
                        }
                    ],
                },
                None,
            ),
            (
                "or_with_nested_server_only_returns_none",
                {
                    "type": "OR",
                    "values": [
                        {"operator": "exact", "key": "$exception_types", "value": "TypeError"},
                        {
                            "type": "AND",
                            "values": [
                                {"operator": "exact", "key": "$exception_sources", "value": "app.js"},
                            ],
                        },
                    ],
                },
                None,
            ),
        ]
    )
    def test_get_client_safe_filters(self, _name: str, filters: object, expected: dict | None) -> None:
        assert get_client_safe_filters(filters) == expected
