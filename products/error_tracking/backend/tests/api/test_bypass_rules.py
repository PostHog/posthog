from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from products.error_tracking.backend.models import ErrorTrackingBypassRule

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


class TestBypassRuleAPI(APIBaseTest):
    def _url(self, rule_id: str | None = None) -> str:
        base = f"/api/environments/{self.team.id}/error_tracking/bypass_rules/"
        if rule_id:
            return f"{base}{rule_id}/"
        return base

    def test_create_with_valid_filters_compiles_bytecode(self) -> None:
        response = self.client.post(self._url(), data={"filters": VALID_FILTERS}, format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        data = response.json()
        assert data["filters"] == VALID_FILTERS
        assert "sampling_rate" not in data

        rule = ErrorTrackingBypassRule.objects.get(id=data["id"])
        assert rule.bytecode is not None
        assert len(rule.bytecode) > 0

    def test_create_without_filters_returns_400(self) -> None:
        response = self.client.post(self._url(), data={}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "filters"
        assert not ErrorTrackingBypassRule.objects.exists()

    def test_create_invalid_filters_returns_400(self) -> None:
        response = self.client.post(self._url(), data={"filters": {"not": "valid"}}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "filters"

    @parameterized.expand(
        [
            ("empty_values", {"type": "AND", "values": []}),
            ("empty_object_leaf", {"type": "AND", "values": [{}]}),
            ("keyless_leaf", {"type": "AND", "values": [{"not": "valid"}]}),
            ("empty_nested_group", {"type": "AND", "values": [{"type": "AND", "values": []}]}),
        ]
    )
    def test_create_rejects_filters_without_values(self, _name: str, filters: dict) -> None:
        # An empty or keyless filter would compile to a match-all bypass that disables all rate
        # limiting for the project — the API must reject it, mirroring the UI's disabled Save button.
        response = self.client.post(self._url(), data={"filters": filters}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "filters"
        assert not ErrorTrackingBypassRule.objects.exists()

    def test_update_with_empty_filters_returns_400(self) -> None:
        rule = ErrorTrackingBypassRule.objects.create(team=self.team, filters=VALID_FILTERS, bytecode=[], order_key=0)

        response = self.client.patch(
            self._url(str(rule.id)), data={"filters": {"type": "AND", "values": []}}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "filters"
        rule.refresh_from_db()
        assert rule.filters == VALID_FILTERS

    def test_update_recompiles_bytecode_and_clears_disabled_data(self) -> None:
        rule = ErrorTrackingBypassRule.objects.create(
            team=self.team,
            filters={"type": "AND", "values": []},
            bytecode=[],
            order_key=0,
            disabled_data={"message": "broke"},
        )

        response = self.client.patch(self._url(str(rule.id)), data={"filters": VALID_FILTERS}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        rule.refresh_from_db()
        assert rule.filters == VALID_FILTERS
        assert rule.bytecode
        assert rule.disabled_data is None

    def test_list_returns_only_team_rules(self) -> None:
        ErrorTrackingBypassRule.objects.create(team=self.team, filters=VALID_FILTERS, bytecode=[], order_key=0)
        other_team = self.create_team_with_organization(organization=self.organization)
        ErrorTrackingBypassRule.objects.create(team=other_team, filters=VALID_FILTERS, bytecode=[], order_key=0)

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["results"]) == 1

    def test_reorder_updates_order_keys(self) -> None:
        first = self.client.post(self._url(), data={"filters": VALID_FILTERS}, format="json").json()["id"]
        second = self.client.post(self._url(), data={"filters": VALID_FILTERS}, format="json").json()["id"]

        response = self.client.patch(f"{self._url()}reorder/", data={"orders": {first: 1, second: 0}}, format="json")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert ErrorTrackingBypassRule.objects.get(id=first).order_key == 1
        assert ErrorTrackingBypassRule.objects.get(id=second).order_key == 0

    def test_delete_removes_rule(self) -> None:
        rule = ErrorTrackingBypassRule.objects.create(team=self.team, filters=VALID_FILTERS, bytecode=[], order_key=0)

        response = self.client.delete(self._url(str(rule.id)))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not ErrorTrackingBypassRule.objects.filter(id=rule.id).exists()

    def test_cannot_access_another_teams_rule(self) -> None:
        other_team = self.create_team_with_organization(organization=self.organization)
        other_rule = ErrorTrackingBypassRule.objects.create(
            team=other_team, filters=VALID_FILTERS, bytecode=[], order_key=0
        )

        response = self.client.get(self._url(str(other_rule.id)))

        assert response.status_code == status.HTTP_404_NOT_FOUND
