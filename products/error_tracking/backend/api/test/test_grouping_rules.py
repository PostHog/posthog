from posthog.test.base import APIBaseTest

from rest_framework import status

from products.error_tracking.backend.models import ErrorTrackingGroupingRule

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

    def test_create_with_description_and_user_assignee(self) -> None:
        response = self.client.post(
            self._url(),
            data={
                "filters": VALID_FILTERS,
                "assignee": {"type": "user", "id": self.user.id},
                "description": "Group similar TypeErrors together",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["filters"] == VALID_FILTERS
        assert data["assignee"] == {"type": "user", "id": self.user.id}
        assert data["description"] == "Group similar TypeErrors together"

        rule = ErrorTrackingGroupingRule.objects.get(id=data["id"])
        assert rule.user_id == self.user.id
        assert rule.role_id is None
        assert rule.description == "Group similar TypeErrors together"
        assert rule.bytecode is not None
        assert len(rule.bytecode) > 0

    def test_create_without_assignee(self) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS, "description": "Leave unassigned"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["assignee"] is None
        assert data["description"] == "Leave unassigned"

    def test_create_requires_filters(self) -> None:
        response = self.client.post(
            self._url(),
            data={"description": "Missing filters"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "type": "validation_error",
            "code": "required",
            "detail": "This field is required.",
            "attr": "filters",
        }
