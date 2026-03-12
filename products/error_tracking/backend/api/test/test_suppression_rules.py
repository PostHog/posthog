from posthog.test.base import APIBaseTest

from django.test import TestCase

from parameterized import parameterized
from rest_framework import status

from products.error_tracking.backend.api.suppression_rules import (
    _get_client_safe_filters,
    get_client_safe_suppression_rules,
)
from products.error_tracking.backend.models import ErrorTrackingSuppressionRule


class TestGetClientSafeFilters(TestCase):
    @parameterized.expand(
        [
            # AND rules: all filters must be client-safe, returned as-is or None
            (
                "and_all_client_safe",
                {"type": "AND", "values": [{"operator": "is", "key": "$exception_types", "value": "TypeError"}]},
                {"type": "AND", "values": [{"operator": "is", "key": "$exception_types", "value": "TypeError"}]},
            ),
            (
                "and_with_negative_operator_returns_none",
                {"type": "AND", "values": [{"operator": "is_not", "key": "$exception_types", "value": "TypeError"}]},
                None,
            ),
            (
                "and_with_server_only_property_returns_none",
                {"type": "AND", "values": [{"operator": "is", "key": "$exception_sources", "value": "app.js"}]},
                None,
            ),
            (
                "and_mixed_safe_and_unsafe_returns_none",
                {
                    "type": "AND",
                    "values": [
                        {"operator": "is", "key": "$exception_types", "value": "TypeError"},
                        {"operator": "is", "key": "$exception_sources", "value": "app.js"},
                    ],
                },
                None,
            ),
            # OR rules: strip server-only, keep client-safe
            (
                "or_all_client_safe",
                {"type": "OR", "values": [{"operator": "is", "key": "$exception_types", "value": "TypeError"}]},
                {"type": "OR", "values": [{"operator": "is", "key": "$exception_types", "value": "TypeError"}]},
            ),
            (
                "or_strips_server_only_keeps_safe",
                {
                    "type": "OR",
                    "values": [
                        {"operator": "is", "key": "$exception_types", "value": "TypeError"},
                        {"operator": "is", "key": "$exception_sources", "value": "app.js"},
                    ],
                },
                {
                    "type": "OR",
                    "values": [{"operator": "is", "key": "$exception_types", "value": "TypeError"}],
                },
            ),
            (
                "or_strips_negative_operator_keeps_safe",
                {
                    "type": "OR",
                    "values": [
                        {"operator": "is", "key": "$exception_types", "value": "TypeError"},
                        {"operator": "is_not", "key": "$exception_values", "value": "expected"},
                    ],
                },
                {
                    "type": "OR",
                    "values": [{"operator": "is", "key": "$exception_types", "value": "TypeError"}],
                },
            ),
            (
                "or_all_server_only_returns_none",
                {
                    "type": "OR",
                    "values": [
                        {"operator": "is", "key": "$exception_sources", "value": "app.js"},
                        {"operator": "regex", "key": "$exception_functions", "value": "handleClick"},
                    ],
                },
                None,
            ),
            # Default type is AND
            (
                "default_type_is_and",
                {"values": [{"operator": "is", "key": "$exception_sources", "value": "app.js"}]},
                None,
            ),
            # Edge cases
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
            # Nested groups
            (
                "nested_and_all_safe",
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
                "nested_and_with_server_only_returns_none",
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
                "or_with_nested_and_strips_unsafe_group",
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
                {
                    "type": "OR",
                    "values": [{"operator": "is", "key": "$exception_types", "value": "TypeError"}],
                },
            ),
        ]
    )
    def test_get_client_safe_filters(self, _name: str, filters: dict, expected: dict | None) -> None:
        assert _get_client_safe_filters(filters) == expected


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

    def test_or_rule_strips_server_only_keeps_client_safe(self) -> None:
        filters = {
            "type": "OR",
            "values": [
                {"operator": "is", "key": "$exception_types", "value": "TypeError"},
                {"operator": "is", "key": "$exception_sources", "value": "app.js"},
            ],
        }
        ErrorTrackingSuppressionRule.objects.create(team=self.team, filters=filters, bytecode=[], order_key=0)

        result = get_client_safe_suppression_rules(self.team)

        assert len(result) == 1
        assert result[0] == {
            "type": "OR",
            "values": [{"operator": "is", "key": "$exception_types", "value": "TypeError"}],
        }

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
        and_with_server_only = {
            "type": "AND",
            "values": [
                {"operator": "is", "key": "$exception_types", "value": "TypeError"},
                {"operator": "is", "key": "$exception_sources", "value": "app.js"},
            ],
        }
        or_mixed = {
            "type": "OR",
            "values": [
                {"operator": "regex", "key": "$exception_values", "value": ".*null.*"},
                {"operator": "is_not", "key": "$exception_types", "value": "RangeError"},
            ],
        }

        ErrorTrackingSuppressionRule.objects.create(team=self.team, filters=safe_filters, bytecode=[], order_key=0)
        ErrorTrackingSuppressionRule.objects.create(
            team=self.team, filters=and_with_server_only, bytecode=[], order_key=1
        )
        ErrorTrackingSuppressionRule.objects.create(team=self.team, filters=or_mixed, bytecode=[], order_key=2)

        result = get_client_safe_suppression_rules(self.team)

        assert len(result) == 2
        assert safe_filters in result
        assert {
            "type": "OR",
            "values": [{"operator": "regex", "key": "$exception_values", "value": ".*null.*"}],
        } in result

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


VALID_FILTERS = {
    "type": "AND",
    "values": [
        {
            "type": "AND",
            "values": [
                {
                    "key": "$exception_type",
                    "type": "event",
                    "value": ["TypeError"],
                    "operator": "exact",
                }
            ],
        }
    ],
}


class TestSuppressionRuleAPI(APIBaseTest):
    def _url(self, rule_id: str | None = None) -> str:
        base = f"/api/environments/{self.team.id}/error_tracking/suppression_rules/"
        if rule_id:
            return f"{base}{rule_id}/"
        return base

    def test_create_with_valid_filters(self) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["filters"] == VALID_FILTERS

        rule = ErrorTrackingSuppressionRule.objects.get(id=data["id"])
        assert rule.bytecode is not None
        assert len(rule.bytecode) > 0

    def test_create_without_filters_creates_match_all_rule(self) -> None:
        response = self.client.post(
            self._url(),
            data={"sampling_rate": 0.5},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["filters"] == {"type": "AND", "values": []}
        assert data["sampling_rate"] == 0.5

        rule = ErrorTrackingSuppressionRule.objects.get(id=data["id"])
        assert rule.bytecode is not None

    def test_create_with_empty_filters_creates_match_all_rule(self) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": {"type": "OR", "values": []}},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["filters"] == {"type": "OR", "values": []}

        rule = ErrorTrackingSuppressionRule.objects.get(id=data["id"])
        assert rule.bytecode is not None

    def test_create_invalid_filters(self) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": {"not": "valid"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "Invalid filters"

    def test_update_changes_bytecode(self) -> None:
        create_response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS},
            format="json",
        )
        rule_id = create_response.json()["id"]
        original_bytecode = ErrorTrackingSuppressionRule.objects.get(id=rule_id).bytecode

        new_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$exception_message",
                            "type": "event",
                            "value": ["something went wrong"],
                            "operator": "icontains",
                        }
                    ],
                }
            ],
        }

        response = self.client.put(
            self._url(rule_id),
            data={"filters": new_filters},
            format="json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        rule = ErrorTrackingSuppressionRule.objects.get(id=rule_id)
        assert rule.bytecode != original_bytecode
        assert rule.filters == new_filters

    def test_update_disabled_rule_without_filter_change_clears_disabled_data(self) -> None:
        rule = ErrorTrackingSuppressionRule.objects.create(
            team=self.team,
            filters=VALID_FILTERS,
            bytecode=[1, 2, 3],
            order_key=0,
            disabled_data={"message": "Rule disabled due to error"},
        )

        response = self.client.put(
            self._url(str(rule.id)),
            data={},
            format="json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        rule.refresh_from_db()
        assert rule.disabled_data is None

    def test_update_disabled_rule_with_filter_change_clears_disabled_data(self) -> None:
        rule = ErrorTrackingSuppressionRule.objects.create(
            team=self.team,
            filters=VALID_FILTERS,
            bytecode=[1, 2, 3],
            order_key=0,
            disabled_data={"message": "Rule disabled due to error"},
        )

        new_filters = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$exception_message",
                            "type": "event",
                            "value": ["something went wrong"],
                            "operator": "icontains",
                        }
                    ],
                }
            ],
        }

        response = self.client.put(
            self._url(str(rule.id)),
            data={"filters": new_filters},
            format="json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        rule.refresh_from_db()
        assert rule.disabled_data is None
        assert rule.filters == new_filters
        assert rule.bytecode != [1, 2, 3]

    def test_create_with_sampling_rate(self) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS, "sampling_rate": 0.5},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["sampling_rate"] == 0.5

    def test_create_defaults_sampling_rate_to_one(self) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["sampling_rate"] == 1.0

    def test_create_rejects_invalid_sampling_rate(self) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS, "sampling_rate": 1.5},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "sampling_rate" in response.json()["error"]

    def test_update_sampling_rate(self) -> None:
        create_response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS},
            format="json",
        )
        rule_id = create_response.json()["id"]

        response = self.client.put(
            self._url(rule_id),
            data={"sampling_rate": 0.25},
            format="json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        rule = ErrorTrackingSuppressionRule.objects.get(id=rule_id)
        assert rule.sampling_rate == 0.25
