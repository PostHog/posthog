from typing import Any, Optional
from uuid import uuid4

from posthog.test.base import APIBaseTest

from parameterized import parameterized
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

    @parameterized.expand(
        [
            ("with_user_assignee", "self_user", "Group similar TypeErrors together"),
            ("without_assignee", None, "Leave unassigned"),
        ]
    )
    def test_create_rule(self, _name: str, assignee_marker: Optional[str], description: str) -> None:
        payload: dict[str, Any] = {"filters": VALID_FILTERS, "description": description}
        if assignee_marker == "self_user":
            payload["assignee"] = {"type": "user", "id": self.user.id}

        response = self.client.post(self._url(), data=payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["filters"] == VALID_FILTERS
        assert data["description"] == description

        rule = ErrorTrackingGroupingRule.objects.get(id=data["id"])
        assert rule.description == description
        assert rule.bytecode is not None
        assert len(rule.bytecode) > 0

        if assignee_marker == "self_user":
            assert data["assignee"] == {"type": "user", "id": self.user.id}
            assert rule.user_id == self.user.id
            assert rule.role_id is None
        else:
            assert data["assignee"] is None
            assert rule.user_id is None
            assert rule.role_id is None

    def test_create_accepts_frontend_payload_shape_with_extra_fields(self) -> None:
        response = self.client.post(
            self._url(),
            data={
                "filters": VALID_FILTERS,
                "assignee": {"type": "user", "id": self.user.id},
                "description": "Group similar TypeErrors together",
                "order_key": 123,
                "disabled_data": {"reason": "frontend-local-state"},
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED

        rule = ErrorTrackingGroupingRule.objects.get(id=response.json()["id"])
        assert rule.filters == VALID_FILTERS
        assert rule.user_id == self.user.id
        assert rule.order_key == 0
        assert rule.disabled_data is None

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
            data={"filters": invalid_filters},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["type"] == "validation_error"
        assert body["attr"] == "filters"

    def test_create_rejects_invalid_filters_shape_without_leaking_exception(self) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": {"not": "a valid property group"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["type"] == "validation_error"
        assert body["attr"] == "filters"
        assert body["detail"] == "Invalid filters payload."

    @parameterized.expand(
        [
            ("empty_values", {"type": "AND", "values": []}),
            ("empty_nested_filter", {"type": "AND", "values": [{"type": "empty"}]}),
            ("or_empty_nested_filter", {"type": "OR", "values": [{"type": "empty"}]}),
            (
                "deeply_nested_empty",
                {"type": "AND", "values": [{"type": "AND", "values": [{"type": "empty"}]}]},
            ),
        ]
    )
    def test_create_rejects_no_op_filters(self, _name: str, empty_filters: dict[str, Any]) -> None:
        response = self.client.post(
            self._url(),
            data={"filters": empty_filters},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["type"] == "validation_error"
        assert body["attr"] == "filters"
        assert body["detail"] == "Filters must contain at least one filter value."

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

    def _create_rule(self) -> ErrorTrackingGroupingRule:
        response = self.client.post(
            self._url(),
            data={
                "filters": VALID_FILTERS,
                "assignee": {"type": "user", "id": self.user.id},
                "description": "Original description",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        return ErrorTrackingGroupingRule.objects.get(id=response.json()["id"])

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
        assert rule.description == "Original description"

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

    def test_update_silently_drops_non_filters_fields(self) -> None:
        """The update endpoint mirrors the UI's grouping-rule edit form, which only edits filters.

        The frontend round-trips the whole rule object on save (including `assignee`,
        `description`, `order_key`, `disabled_data`, timestamps), so the endpoint must accept
        those keys without 400-ing, but it must never use them to overwrite stored values —
        otherwise an MCP or curl caller could silently clear an assignee that was set out of
        band by sending `{"assignee": null}` alongside an unrelated filter edit.
        """
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
                "assignee": None,
                "description": "Updated description",
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
        # Non-filter fields from the request body are silently ignored: the
        # original assignee and description survive the round-trip.
        assert rule.user_id == self.user.id
        assert rule.description == "Original description"
        assert rule.order_key == 0
        assert rule.disabled_data is None
