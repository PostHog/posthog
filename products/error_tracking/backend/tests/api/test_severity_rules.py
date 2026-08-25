from datetime import UTC, datetime
from typing import Any

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.error_tracking.backend.logic.rules import MAX_SEVERITY_RULE_BYTECODE_OPS, MAX_SEVERITY_RULES_PER_TEAM
from products.error_tracking.backend.models import ErrorTrackingSeverityRule

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass

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


class TestSeverityRuleAPI(APIBaseTest):
    def _url(self, rule_id: str | None = None) -> str:
        base = f"/api/environments/{self.team.id}/error_tracking/severity_rules/"
        return f"{base}{rule_id}/" if rule_id else base

    def test_create_persists_compiled_ordered_rule(self) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS, "severity": "critical", "order_key": 7},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        data = response.json()
        assert data["filters"] == VALID_FILTERS
        assert data["severity"] == "critical"
        assert data["order_key"] == 7

        rule = ErrorTrackingSeverityRule.objects.unscoped().get(id=data["id"])
        assert rule.team_id == self.team.id
        assert rule.bytecode

    @parameterized.expand(
        [
            ("unsupported_severity", {"filters": VALID_FILTERS, "severity": "urgent"}, "severity"),
            ("invalid_filters", {"filters": {"not": "valid"}, "severity": "high"}, "filters"),
            ("missing_filters", {"severity": "high"}, "filters"),
            ("missing_severity", {"filters": VALID_FILTERS}, "severity"),
        ]
    )
    def test_create_rejects_invalid_payload(self, _name: str, payload: dict[str, Any], attr: str) -> None:
        response = self.client.post(self._url(), data=payload, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == attr
        assert not ErrorTrackingSeverityRule.objects.unscoped().exists()

    def test_create_rejects_rule_above_project_limit(self) -> None:
        ErrorTrackingSeverityRule.objects.unscoped().bulk_create(
            [
                ErrorTrackingSeverityRule(
                    team=self.team,
                    filters=VALID_FILTERS,
                    bytecode=[],
                    severity="low",
                    order_key=index,
                )
                for index in range(MAX_SEVERITY_RULES_PER_TEAM)
            ]
        )

        response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS, "severity": "critical"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            ErrorTrackingSeverityRule.objects.unscoped().filter(team=self.team).count() == MAX_SEVERITY_RULES_PER_TEAM
        )

    @patch("products.error_tracking.backend.logic.rules._rule_bytecode")
    def test_create_rejects_oversized_bytecode(self, mock_rule_bytecode) -> None:
        mock_rule_bytecode.return_value = [0] * (MAX_SEVERITY_RULE_BYTECODE_OPS + 1)

        response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS, "severity": "critical"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not ErrorTrackingSeverityRule.objects.unscoped().exists()

    def test_update_recompiles_and_clears_disabled_data(self) -> None:
        rule = ErrorTrackingSeverityRule.objects.unscoped().create(
            team=self.team,
            filters={"type": "AND", "values": []},
            bytecode=[],
            severity="low",
            order_key=0,
            disabled_data={"message": "invalid program"},
        )

        response = self.client.patch(
            self._url(str(rule.id)),
            data={"filters": VALID_FILTERS, "severity": "high"},
            format="json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT, response.json()
        rule.refresh_from_db()
        assert rule.filters == VALID_FILTERS
        assert rule.severity == "high"
        assert rule.bytecode
        assert rule.disabled_data is None

    def test_severity_only_update_preserves_disabled_data(self) -> None:
        disabled_data = {"message": "invalid program"}
        rule = ErrorTrackingSeverityRule.objects.unscoped().create(
            team=self.team,
            filters=VALID_FILTERS,
            bytecode=[],
            severity="low",
            order_key=0,
            disabled_data=disabled_data,
        )

        response = self.client.patch(self._url(str(rule.id)), data={"severity": "high"}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT, response.json()
        rule.refresh_from_db()
        assert rule.severity == "high"
        assert rule.disabled_data == disabled_data

    def test_list_uses_rule_id_to_break_exact_order_ties(self) -> None:
        high_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        low_id = "00000000-0000-0000-0000-000000000001"
        for rule_id in (high_id, low_id):
            ErrorTrackingSeverityRule.objects.unscoped().create(
                id=rule_id,
                team=self.team,
                filters=VALID_FILTERS,
                bytecode=[],
                severity="low",
                order_key=0,
            )
        ErrorTrackingSeverityRule.objects.unscoped().filter(id__in=(high_id, low_id)).update(
            created_at=datetime(2026, 1, 1, tzinfo=UTC)
        )

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        assert [rule["id"] for rule in response.json()["results"]] == [low_id, high_id]

    def test_list_and_reorder_are_project_scoped(self) -> None:
        first = self.client.post(
            self._url(), data={"filters": VALID_FILTERS, "severity": "low", "order_key": 0}, format="json"
        ).json()["id"]
        second = self.client.post(
            self._url(), data={"filters": VALID_FILTERS, "severity": "high", "order_key": 1}, format="json"
        ).json()["id"]
        other_team = self.create_team_with_organization(organization=self.organization)
        ErrorTrackingSeverityRule.objects.unscoped().create(
            team=other_team, filters=VALID_FILTERS, bytecode=[], severity="critical", order_key=0
        )

        reorder_response = self.client.patch(
            f"{self._url()}reorder/", data={"orders": {first: 1, second: 0}}, format="json"
        )
        list_response = self.client.get(self._url())

        assert reorder_response.status_code == status.HTTP_204_NO_CONTENT
        assert list_response.status_code == status.HTTP_200_OK
        assert [rule["id"] for rule in list_response.json()["results"]] == [second, first]

    def test_cannot_access_or_delete_another_projects_rule(self) -> None:
        other_team = self.create_team_with_organization(organization=self.organization)
        other_rule = ErrorTrackingSeverityRule.objects.unscoped().create(
            team=other_team, filters=VALID_FILTERS, bytecode=[], severity="medium", order_key=0
        )

        assert self.client.get(self._url(str(other_rule.id))).status_code == status.HTTP_404_NOT_FOUND
        assert self.client.delete(self._url(str(other_rule.id))).status_code == status.HTTP_404_NOT_FOUND
        assert ErrorTrackingSeverityRule.objects.unscoped().filter(id=other_rule.id).exists()

    def test_delete_removes_rule(self) -> None:
        response = self.client.post(self._url(), data={"filters": VALID_FILTERS, "severity": "medium"}, format="json")
        rule_id = response.json()["id"]

        delete_response = self.client.delete(self._url(rule_id))

        assert delete_response.status_code == status.HTTP_204_NO_CONTENT
        assert not ErrorTrackingSeverityRule.objects.unscoped().filter(id=rule_id).exists()

    @pytest.mark.ee
    def test_project_wide_rules_require_resource_level_access(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        restricted_user = User.objects.create_and_join(self.organization, "restricted@posthog.com", "testtest")
        membership = OrganizationMembership.objects.get(user=restricted_user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="error_tracking",
            access_level="none",
        )
        AccessControl.objects.create(
            team=self.team,
            resource="error_tracking",
            resource_id="00000000-0000-0000-0000-000000000001",
            access_level="editor",
            organization_member=membership,
        )
        rule = ErrorTrackingSeverityRule.objects.unscoped().create(
            team=self.team,
            filters=VALID_FILTERS,
            bytecode=[],
            severity="low",
            order_key=0,
        )
        self.client.force_login(restricted_user)

        response = self.client.patch(self._url(str(rule.id)), data={"severity": "high"}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        rule.refresh_from_db()
        assert rule.severity == "low"
