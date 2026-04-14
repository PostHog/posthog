from posthog.test.base import APIBaseTest

from rest_framework import status

from products.error_tracking.backend.models import ErrorTrackingGroupingRule


class TestGroupingRuleAPI(APIBaseTest):
    def _url(self, rule_id: str | None = None) -> str:
        base = f"/api/environments/{self.team.id}/error_tracking/grouping_rules/"
        if rule_id:
            return f"{base}{rule_id}/"
        return base

    def test_list_returns_results_wrapper_without_pagination_fields(self) -> None:
        ErrorTrackingGroupingRule.objects.create(
            team=self.team,
            filters={"type": "AND", "values": []},
            bytecode=[],
            order_key=0,
            description="Group similar TypeErrors together",
        )

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert list(data.keys()) == ["results"]
        assert len(data["results"]) == 1
        assert data["results"][0]["description"] == "Group similar TypeErrors together"
