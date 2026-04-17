from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest

from parameterized import parameterized
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

    def test_create_accepts_frontend_payload_shape_with_extra_fields(self) -> None:
        response = self.client.post(
            self._url(),
            data={
                "filters": VALID_FILTERS,
                "assignee": {"type": "user", "id": self.user.id},
                "order_key": 123,
                "disabled_data": {"reason": "frontend-local-state"},
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED

        rule = ErrorTrackingAssignmentRule.objects.get(id=response.json()["id"])
        assert rule.filters == VALID_FILTERS
        assert rule.user_id == self.user.id
        assert rule.order_key == 0
        assert rule.disabled_data is None

    @parameterized.expand(
        [
            ("missing_filters", {"assignee": {"type": "user", "id": 1}}, "filters"),
            ("missing_assignee", {"filters": VALID_FILTERS}, "assignee"),
        ]
    )
    def test_create_requires_field(self, _name: str, payload: dict[str, Any], missing_attr: str) -> None:
        response = self.client.post(self._url(), data=payload, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "type": "validation_error",
            "code": "required",
            "detail": "This field is required.",
            "attr": missing_attr,
        }

    @parameterized.expand(
        [
            ("list", []),
            ("integer", 42),
            ("string", "not-an-object"),
        ]
    )
    def test_create_rejects_non_object_filters(self, _name: str, invalid_filters: Any) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": invalid_filters, "assignee": {"type": "user", "id": self.user.id}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
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

    @parameterized.expand(
        [
            ("user_type_with_uuid_id", {"type": "user", "id": str(uuid4())}, "User assignee IDs must be integers."),
            ("role_type_with_int_id", {"type": "role", "id": 42}, "Role assignee IDs must be UUIDs."),
        ]
    )
    def test_create_rejects_mismatched_assignee_type_and_id(
        self, _name: str, assignee: dict[str, Any], expected_detail: str
    ) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS, "assignee": assignee},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["type"] == "validation_error"
        assert body["attr"] == "assignee__id"
        assert body["detail"] == expected_detail

    @parameterized.expand(
        [
            ("bool_id", {"type": "user", "id": True}, "id", "Expected an integer user ID or UUID role ID."),
            ("float_id", {"type": "user", "id": 1.5}, "id", "Expected an integer user ID or UUID role ID."),
            (
                "non_digit_string_id",
                {"type": "user", "id": "abc"},
                "id",
                "Expected an integer user ID or UUID role ID.",
            ),
            ("invalid_type_enum", {"type": "group", "id": 1}, "type", '"group" is not a valid choice.'),
        ]
    )
    def test_create_rejects_invalid_assignee_shape(
        self, _name: str, assignee: dict[str, Any], sub_attr: str, expected_detail: str
    ) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS, "assignee": assignee},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["type"] == "validation_error"
        assert body["attr"] == f"assignee__{sub_attr}"
        assert body["detail"] == expected_detail

    def _create_rule(self) -> ErrorTrackingAssignmentRule:
        response = self.client.post(
            self._url(),
            data={"filters": VALID_FILTERS, "assignee": {"type": "user", "id": self.user.id}},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        return ErrorTrackingAssignmentRule.objects.get(id=response.json()["id"])

    def test_update_rejects_invalid_filters_payload(self) -> None:
        rule = self._create_rule()

        response = self.client.patch(
            self._url(str(rule.id)),
            data={"filters": {"not": "a valid property group"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["type"] == "validation_error"
        assert body["attr"] == "filters"
        assert body["detail"] == "Invalid filters payload."

    def test_update_rejects_mismatched_assignee(self) -> None:
        rule = self._create_rule()

        response = self.client.patch(
            self._url(str(rule.id)),
            data={"assignee": {"type": "role", "id": 42}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["type"] == "validation_error"
        assert body["attr"] == "assignee__id"

    def test_update_allows_partial_filters_payload(self) -> None:
        rule = self._create_rule()
        new_filters = {
            "type": "OR",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {"key": "$exception_type", "type": "event", "value": ["RangeError"], "operator": "exact"}
                    ],
                }
            ],
        }

        response = self.client.patch(
            self._url(str(rule.id)),
            data={"filters": new_filters},
            format="json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        rule.refresh_from_db()
        assert rule.filters == new_filters
        assert rule.user_id == self.user.id

    def test_update_accepts_frontend_payload_shape_with_extra_fields(self) -> None:
        rule = self._create_rule()
        new_filters = {
            "type": "OR",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {"key": "$exception_type", "type": "event", "value": ["RangeError"], "operator": "exact"}
                    ],
                }
            ],
        }

        response = self.client.patch(
            self._url(str(rule.id)),
            data={
                "filters": new_filters,
                "assignee": {"type": "user", "id": self.user.id},
                "order_key": 456,
                "disabled_data": {"reason": "frontend-local-state"},
                "created_at": rule.created_at.isoformat(),
                "updated_at": rule.updated_at.isoformat(),
            },
            format="json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        rule.refresh_from_db()
        assert rule.filters == new_filters
        assert rule.user_id == self.user.id
        assert rule.order_key == 0
        assert rule.disabled_data is None
