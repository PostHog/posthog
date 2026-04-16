from posthog.test.base import APIBaseTest

from rest_framework import status

from products.error_tracking.backend.models import ErrorTrackingAssignmentRule

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


class TestAssignmentRuleAPI(APIBaseTest):
    def _url(self, rule_id: str | None = None) -> str:
        base = f"/api/environments/{self.team.id}/error_tracking/assignment_rules/"
        if rule_id:
            return f"{base}{rule_id}/"
        return base

    def test_create_with_valid_user_assignee(self) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS, "assignee": {"type": "user", "id": self.user.id}},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["filters"] == VALID_FILTERS
        assert data["assignee"] == {"type": "user", "id": self.user.id}

        rule = ErrorTrackingAssignmentRule.objects.get(id=data["id"])
        assert rule.user_id == self.user.id
        assert rule.role_id is None
        assert rule.bytecode is not None
        assert len(rule.bytecode) > 0

    def test_create_requires_filters(self) -> None:
        response = self.client.post(
            self._url(),
            data={"assignee": {"type": "user", "id": self.user.id}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "type": "validation_error",
            "code": "required",
            "detail": "This field is required.",
            "attr": "filters",
        }

    def test_create_requires_assignee(self) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "type": "validation_error",
            "code": "required",
            "detail": "This field is required.",
            "attr": "assignee",
        }

    def test_create_rejects_non_object_filters(self) -> None:
        for invalid_filters in ([], 42, "string"):
            response = self.client.post(
                self._url(),
                data={"filters": invalid_filters, "assignee": {"type": "user", "id": self.user.id}},
                format="json",
            )

            assert response.status_code == status.HTTP_400_BAD_REQUEST, invalid_filters
            body = response.json()
            assert body["type"] == "validation_error"
            assert body["attr"] == "filters"

    def test_create_rejects_invalid_filters_shape_without_leaking_exception(self) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": {"not": "a valid property group"}, "assignee": {"type": "user", "id": self.user.id}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["type"] == "validation_error"
        assert body["attr"] == "filters"
        assert body["detail"] == "Invalid filters payload."
