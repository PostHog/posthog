from posthog.test.base import APIBaseTest

from django.test import TestCase

from parameterized import parameterized

from products.error_tracking.backend.facade import get_client_safe_suppression_rules
from products.error_tracking.backend.logic import get_client_safe_filters
from products.error_tracking.backend.models import ErrorTrackingSuppressionRule


class TestGetClientSafeFilters(TestCase):
    @parameterized.expand(
        [
            (
                "all_client_safe",
                {"type": "AND", "values": [{"operator": "is", "key": "$exception_types", "value": "TypeError"}]},
                {"type": "AND", "values": [{"operator": "is", "key": "$exception_types", "value": "TypeError"}]},
            ),
            (
                "or_all_client_safe",
                {"type": "OR", "values": [{"operator": "is", "key": "$exception_types", "value": "TypeError"}]},
                {"type": "OR", "values": [{"operator": "is", "key": "$exception_types", "value": "TypeError"}]},
            ),
            (
                "negative_operator_is_client_safe",
                {
                    "type": "AND",
                    "values": [
                        {"operator": "is_not", "key": "$exception_types", "value": "TypeError"},
                        {"operator": "not_icontains", "key": "$exception_values", "value": "expected"},
                    ],
                },
                {
                    "type": "AND",
                    "values": [
                        {"operator": "is_not", "key": "$exception_types", "value": "TypeError"},
                        {"operator": "not_icontains", "key": "$exception_values", "value": "expected"},
                    ],
                },
            ),
            (
                "server_only_property_returns_none",
                {"type": "AND", "values": [{"operator": "is", "key": "$exception_sources", "value": "app.js"}]},
                None,
            ),
            (
                "mixed_safe_and_server_only_returns_none",
                {
                    "type": "AND",
                    "values": [
                        {"operator": "is", "key": "$exception_types", "value": "TypeError"},
                        {"operator": "is", "key": "$exception_sources", "value": "app.js"},
                    ],
                },
                None,
            ),
            (
                "or_with_server_only_returns_none",
                {
                    "type": "OR",
                    "values": [
                        {"operator": "is", "key": "$exception_types", "value": "TypeError"},
                        {"operator": "is", "key": "$exception_sources", "value": "app.js"},
                    ],
                },
                None,
            ),
            (
                "empty_values_list",
                {"values": []},
                {"values": []},
            ),
            (
                "missing_values_key",
                {"type": "AND"},
                {"type": "AND"},
            ),
            (
                "nested_all_safe",
                {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"operator": "is", "key": "$exception_types", "value": "TypeError"},
                                {"operator": "regex", "key": "$exception_values", "value": ".*null.*"},
                            ],
                        }
                    ],
                },
                {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"operator": "is", "key": "$exception_types", "value": "TypeError"},
                                {"operator": "regex", "key": "$exception_values", "value": ".*null.*"},
                            ],
                        }
                    ],
                },
            ),
            (
                "nested_with_server_only_returns_none",
                {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"operator": "is", "key": "$exception_types", "value": "TypeError"},
                                {"operator": "is", "key": "$exception_sources", "value": "app.js"},
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
                        {"operator": "is", "key": "$exception_types", "value": "TypeError"},
                        {
                            "type": "AND",
                            "values": [
                                {"operator": "is", "key": "$exception_sources", "value": "app.js"},
                            ],
                        },
                    ],
                },
                None,
            ),
        ]
    )
    def test_get_client_safe_filters(self, _name: str, filters: dict, expected: dict | None) -> None:
        assert get_client_safe_filters(filters) == expected


class TestGetClientSafeSuppressionRules(APIBaseTest):
    def test_returns_fully_client_safe_rule(self) -> None:
        filters = {"values": [{"operator": "is", "key": "$exception_types", "value": "TypeError"}]}
        ErrorTrackingSuppressionRule.objects.create(team=self.team, filters=filters, bytecode=[], order_key=0)

        result = get_client_safe_suppression_rules(self.team)

        assert len(result) == 1
        assert result[0] == filters

    def test_excludes_and_rule_with_server_only_filter(self) -> None:
        filters = {
            "type": "AND",
            "values": [
                {"operator": "is", "key": "$exception_types", "value": "TypeError"},
                {"operator": "is", "key": "$exception_sources", "value": "app.js"},
            ],
        }
        ErrorTrackingSuppressionRule.objects.create(team=self.team, filters=filters, bytecode=[], order_key=0)

        result = get_client_safe_suppression_rules(self.team)

        assert result == []

    def test_or_rule_with_server_only_excluded(self) -> None:
        filters = {
            "type": "OR",
            "values": [
                {"operator": "is", "key": "$exception_types", "value": "TypeError"},
                {"operator": "is", "key": "$exception_sources", "value": "app.js"},
            ],
        }
        ErrorTrackingSuppressionRule.objects.create(team=self.team, filters=filters, bytecode=[], order_key=0)

        result = get_client_safe_suppression_rules(self.team)

        assert result == []

    def test_or_rule_all_server_only_excluded(self) -> None:
        filters = {
            "type": "OR",
            "values": [
                {"operator": "is", "key": "$exception_sources", "value": "app.js"},
                {"operator": "regex", "key": "$exception_functions", "value": "handleClick"},
            ],
        }
        ErrorTrackingSuppressionRule.objects.create(team=self.team, filters=filters, bytecode=[], order_key=0)

        result = get_client_safe_suppression_rules(self.team)

        assert result == []

    def test_returns_empty_list_when_no_rules_exist(self) -> None:
        result = get_client_safe_suppression_rules(self.team)

        assert result == []

    def test_handles_mixed_rules(self) -> None:
        safe_filters = {"values": [{"operator": "is", "key": "$exception_types", "value": "TypeError"}]}
        has_server_only = {
            "type": "AND",
            "values": [
                {"operator": "is", "key": "$exception_types", "value": "TypeError"},
                {"operator": "is", "key": "$exception_sources", "value": "app.js"},
            ],
        }
        also_safe = {
            "type": "OR",
            "values": [
                {"operator": "regex", "key": "$exception_values", "value": ".*null.*"},
                {"operator": "is_not", "key": "$exception_types", "value": "RangeError"},
            ],
        }

        ErrorTrackingSuppressionRule.objects.create(team=self.team, filters=safe_filters, bytecode=[], order_key=0)
        ErrorTrackingSuppressionRule.objects.create(team=self.team, filters=has_server_only, bytecode=[], order_key=1)
        ErrorTrackingSuppressionRule.objects.create(team=self.team, filters=also_safe, bytecode=[], order_key=2)

        result = get_client_safe_suppression_rules(self.team)

        assert len(result) == 2
        assert safe_filters in result
        assert also_safe in result

    def test_includes_sampling_rate_when_less_than_one(self) -> None:
        filters = {"values": [{"operator": "is", "key": "$exception_types", "value": "TypeError"}]}
        ErrorTrackingSuppressionRule.objects.create(
            team=self.team, filters=filters, bytecode=[], order_key=0, sampling_rate=0.5
        )

        result = get_client_safe_suppression_rules(self.team)

        assert len(result) == 1
        assert result[0] == {**filters, "samplingRate": 0.5}

    def test_omits_sampling_rate_when_one(self) -> None:
        filters = {"values": [{"operator": "is", "key": "$exception_types", "value": "TypeError"}]}
        ErrorTrackingSuppressionRule.objects.create(
            team=self.team, filters=filters, bytecode=[], order_key=0, sampling_rate=1.0
        )

        result = get_client_safe_suppression_rules(self.team)

        assert len(result) == 1
        assert "samplingRate" not in result[0]
