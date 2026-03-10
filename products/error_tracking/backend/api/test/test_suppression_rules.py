from posthog.test.base import APIBaseTest

from django.test import TestCase

from parameterized import parameterized
from rest_framework import status

from products.error_tracking.backend.api.suppression_rules import (
    _has_negative_operator,
    get_client_safe_suppression_rules,
)
from products.error_tracking.backend.models import ErrorTrackingSuppressionRule


class TestHasNegativeOperator(TestCase):
    @parameterized.expand(
        [
            (
                "flat_is_operator",
                {"values": [{"operator": "is", "key": "type", "value": "TypeError"}]},
                False,
            ),
            (
                "flat_regex_operator",
                {"values": [{"operator": "regex", "key": "type", "value": ".*Error"}]},
                False,
            ),
            (
                "flat_icontains_operator",
                {"values": [{"operator": "icontains", "key": "message", "value": "null"}]},
                False,
            ),
            (
                "flat_is_not_operator",
                {"values": [{"operator": "is_not", "key": "type", "value": "TypeError"}]},
                True,
            ),
            (
                "flat_not_regex_operator",
                {"values": [{"operator": "not_regex", "key": "type", "value": ".*Error"}]},
                True,
            ),
            (
                "flat_not_icontains_operator",
                {"values": [{"operator": "not_icontains", "key": "message", "value": "null"}]},
                True,
            ),
            (
                "nested_positive_only",
                {
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"operator": "is", "key": "type", "value": "TypeError"},
                                {"operator": "regex", "key": "message", "value": ".*null.*"},
                            ],
                        }
                    ]
                },
                False,
            ),
            (
                "nested_with_negative_in_inner_group",
                {
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"operator": "is", "key": "type", "value": "TypeError"},
                                {"operator": "is_not", "key": "message", "value": "expected"},
                            ],
                        }
                    ]
                },
                True,
            ),
            (
                "empty_values_list",
                {"values": []},
                False,
            ),
            (
                "missing_values_key",
                {"type": "AND"},
                False,
            ),
            (
                "mixed_positive_and_negative",
                {
                    "values": [
                        {"operator": "is", "key": "type", "value": "TypeError"},
                        {"operator": "not_regex", "key": "message", "value": ".*expected.*"},
                    ]
                },
                True,
            ),
        ]
    )
    def test_has_negative_operator(self, _name: str, filters: dict, expected: bool) -> None:
        assert _has_negative_operator(filters) is expected


class TestGetClientSafeSuppressionRules(APIBaseTest):
    def test_returns_rules_with_positive_operators_only(self) -> None:
        filters = {"values": [{"operator": "is", "key": "type", "value": "TypeError"}]}
        ErrorTrackingSuppressionRule.objects.create(team=self.team, filters=filters, bytecode=[], order_key=0)

        result = get_client_safe_suppression_rules(self.team)

        assert len(result) == 1
        assert result[0] == filters

    def test_excludes_rules_with_negative_operators(self) -> None:
        filters = {"values": [{"operator": "is_not", "key": "type", "value": "TypeError"}]}
        ErrorTrackingSuppressionRule.objects.create(team=self.team, filters=filters, bytecode=[], order_key=0)

        result = get_client_safe_suppression_rules(self.team)

        assert result == []

    def test_returns_empty_list_when_no_rules_exist(self) -> None:
        result = get_client_safe_suppression_rules(self.team)

        assert result == []

    def test_handles_mixed_rules(self) -> None:
        positive_filters = {"values": [{"operator": "is", "key": "type", "value": "TypeError"}]}
        negative_filters = {"values": [{"operator": "is_not", "key": "type", "value": "RangeError"}]}
        another_positive = {"values": [{"operator": "regex", "key": "message", "value": ".*null.*"}]}

        ErrorTrackingSuppressionRule.objects.create(team=self.team, filters=positive_filters, bytecode=[], order_key=0)
        ErrorTrackingSuppressionRule.objects.create(team=self.team, filters=negative_filters, bytecode=[], order_key=1)
        ErrorTrackingSuppressionRule.objects.create(team=self.team, filters=another_positive, bytecode=[], order_key=2)

        result = get_client_safe_suppression_rules(self.team)

        assert len(result) == 2
        assert positive_filters in result
        assert another_positive in result
        assert negative_filters not in result


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

    def test_create_missing_filters(self) -> None:
        response = self.client.post(
            self._url(),
            data={},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "Filters are required"

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
