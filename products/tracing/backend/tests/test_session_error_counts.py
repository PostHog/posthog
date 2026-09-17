import json
from uuid import uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.http import HttpResponse

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, User

from products.access_control.backend.models.access_control import AccessControl

DATE_FROM = "2026-06-02T06:00:00Z"
DATE_TO = "2026-06-02T10:00:00Z"


class TestSessionErrorCounts(ClickhouseTestMixin, APIBaseTest):
    def _post(self, session_ids: list[str]) -> HttpResponse:
        return self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/session-error-counts/",
            {"sessionIds": session_ids, "dateFrom": DATE_FROM, "dateTo": DATE_TO},
            format="json",
        )

    def _create_exception(self, session_id: str, *, timestamp: str, linked_to_issue: bool = True) -> None:
        properties: dict[str, str] = {"$session_id": session_id}
        if linked_to_issue:
            properties["$exception_issue_id"] = str(uuid4())
        _create_event(
            distinct_id="user-1", event="$exception", team=self.team, properties=properties, timestamp=timestamp
        )

    def test_counts_issue_linked_exceptions_per_requested_session_in_the_window(self) -> None:
        self._create_exception("session-a", timestamp="2026-06-02T08:00:00Z")
        self._create_exception("session-a", timestamp="2026-06-02T09:00:00Z")
        self._create_exception("session-a", timestamp="2026-06-02T08:30:00Z", linked_to_issue=False)
        self._create_exception("session-a", timestamp="2026-06-02T11:00:00Z")
        self._create_exception("session-b", timestamp="2026-06-02T08:00:00Z")
        self._create_exception("session-not-asked", timestamp="2026-06-02T08:00:00Z")
        flush_persons_and_events()

        response = self._post(["session-a", "session-b", "session-quiet"])

        assert response.status_code == status.HTTP_200_OK, response.content
        counts = {row["session_id"]: row["exceptions"] for row in json.loads(response.content)["results"]}
        assert counts == {"session-a": 2, "session-b": 1}

    def test_answers_every_requested_session_past_the_default_row_limit(self) -> None:
        session_ids = [f"session-{i}" for i in range(150)]
        for session_id in session_ids:
            self._create_exception(session_id, timestamp="2026-06-02T08:00:00Z")
        flush_persons_and_events()

        response = self._post(session_ids)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert len(json.loads(response.content)["results"]) == 150

    def test_rejects_more_sessions_than_one_lookup_allows(self) -> None:
        response = self._post([f"session-{i}" for i in range(201)])

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert json.loads(response.content)["attr"] == "sessionIds"

    @parameterized.expand([("viewer", status.HTTP_200_OK), ("none", status.HTTP_403_FORBIDDEN)])
    def test_requires_error_tracking_viewer_access(self, access_level: str, expected_status: int) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        user = User.objects.create_and_join(self.organization, "tracing-only@posthog.com", "testtest")
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="error_tracking",
            resource_id=None,
            access_level=access_level,
            organization_member=membership,
        )
        self.client.force_login(user)

        response = self._post(["session-a"])

        assert response.status_code == expected_status, response.content
