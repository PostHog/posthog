import json
from typing import Any
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

# The form an SDK writes: lowercase hex, 32 characters for a trace and 16 for a span.
TRACE_A = "4bf92f3577b34da6a3ce929d0e0e4736"
TRACE_B = "8a3c60f7d188f8fa79d48a391a778fa6"
SPAN_A = "00f067aa0ba902b7"
SPAN_B = "b9c7c989f97918e1"


class TestErrorCounts(ClickhouseTestMixin, APIBaseTest):
    def _post(self, **body: Any) -> HttpResponse:
        return self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/error-counts/",
            {"dateFrom": DATE_FROM, "dateTo": DATE_TO, **body},
            format="json",
        )

    def _create_exception(
        self,
        *,
        timestamp: str = "2026-06-02T08:00:00Z",
        session_id: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        linked_to_issue: bool = True,
    ) -> None:
        properties: dict[str, str] = {}
        if session_id is not None:
            properties["$session_id"] = session_id
        if trace_id is not None:
            properties["$trace_id"] = trace_id
        if span_id is not None:
            properties["$span_id"] = span_id
        if linked_to_issue:
            properties["$exception_issue_id"] = str(uuid4())
        _create_event(
            distinct_id="user-1", event="$exception", team=self.team, properties=properties, timestamp=timestamp
        )

    def test_counts_issue_linked_exceptions_per_requested_session_in_the_window(self) -> None:
        self._create_exception(session_id="session-a", timestamp="2026-06-02T08:00:00Z")
        self._create_exception(session_id="session-a", timestamp="2026-06-02T09:00:00Z")
        self._create_exception(session_id="session-a", timestamp="2026-06-02T08:30:00Z", linked_to_issue=False)
        self._create_exception(session_id="session-a", timestamp="2026-06-02T11:00:00Z")
        self._create_exception(session_id="session-b", timestamp="2026-06-02T08:00:00Z")
        self._create_exception(session_id="session-not-asked", timestamp="2026-06-02T08:00:00Z")
        flush_persons_and_events()

        response = self._post(sessionIds=["session-a", "session-b", "session-quiet"])

        assert response.status_code == status.HTTP_200_OK, response.content
        counts = {row["session_id"]: row["exceptions"] for row in json.loads(response.content)["sessionResults"]}
        assert counts == {"session-a": 2, "session-b": 1}

    def test_counts_issue_linked_exceptions_per_requested_trace_in_the_window(self) -> None:
        self._create_exception(trace_id=TRACE_A, timestamp="2026-06-02T08:00:00Z")
        self._create_exception(trace_id=TRACE_A, timestamp="2026-06-02T09:00:00Z")
        self._create_exception(trace_id=TRACE_A, timestamp="2026-06-02T08:30:00Z", linked_to_issue=False)
        self._create_exception(trace_id=TRACE_A, timestamp="2026-06-02T11:00:00Z")
        self._create_exception(trace_id=TRACE_B, timestamp="2026-06-02T08:00:00Z")
        flush_persons_and_events()

        response = self._post(traceIds=[TRACE_A, TRACE_B])

        assert response.status_code == status.HTTP_200_OK, response.content
        counts = {row["trace_id"]: row["exceptions"] for row in json.loads(response.content)["traceResults"]}
        assert counts == {TRACE_A: 2, TRACE_B: 1}

    # The span rows the caller holds carry uppercase hex, because the query runner reads the ids
    # back through ClickHouse `hex()`, while an SDK writes them lowercase. Match the two raw and
    # every count comes back zero, which reads as a clean trace rather than as a bug. Both sides
    # vary, so neither half of the normalization can be dropped without a failure here.
    @parameterized.expand(
        [
            ("stored lower, asked lower", str.lower, str.lower),
            ("stored lower, asked upper", str.lower, str.upper),
            ("stored upper, asked lower", str.upper, str.lower),
            ("stored upper, asked upper", str.upper, str.upper),
        ]
    )
    def test_matches_ids_whatever_case_either_side_uses(self, _name: str, stored: Any, asked: Any) -> None:
        self._create_exception(trace_id=stored(TRACE_A), span_id=stored(SPAN_A))
        flush_persons_and_events()

        response = self._post(traceIds=[asked(TRACE_A)], spanIds=[asked(SPAN_A)])

        assert response.status_code == status.HTTP_200_OK, response.content
        body = json.loads(response.content)
        assert {row["trace_id"]: row["exceptions"] for row in body["traceResults"]} == {TRACE_A: 1}
        assert {row["span_id"]: row["exceptions"] for row in body["spanResults"]} == {SPAN_A: 1}

    # A span id is only unique inside its trace, so a span count that ignores the trace would fold
    # an unrelated trace's exceptions into this one's row.
    def test_counts_a_span_only_within_the_requested_traces(self) -> None:
        self._create_exception(trace_id=TRACE_A, span_id=SPAN_A)
        self._create_exception(trace_id=TRACE_B, span_id=SPAN_A)
        flush_persons_and_events()

        response = self._post(traceIds=[TRACE_A], spanIds=[SPAN_A])

        assert response.status_code == status.HTTP_200_OK, response.content
        counts = {row["span_id"]: row["exceptions"] for row in json.loads(response.content)["spanResults"]}
        assert counts == {SPAN_A: 1}

    def test_answers_every_requested_session_past_the_default_row_limit(self) -> None:
        session_ids = [f"session-{i}" for i in range(150)]
        for session_id in session_ids:
            self._create_exception(session_id=session_id)
        flush_persons_and_events()

        response = self._post(sessionIds=session_ids)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert len(json.loads(response.content)["sessionResults"]) == 150

    @parameterized.expand([("traceIds",), ("spanIds",), ("sessionIds",)])
    def test_rejects_more_ids_than_one_lookup_allows(self, field: str) -> None:
        body: dict[str, Any] = {field: [f"id-{i}" for i in range(201)]}
        if field == "spanIds":
            body["traceIds"] = [TRACE_A]

        response = self._post(**body)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert json.loads(response.content)["attr"] == field

    @parameterized.expand(
        [
            ("no ids at all", {}),
            ("spans without their traces", {"spanIds": [SPAN_B]}),
        ]
    )
    def test_rejects_a_request_it_cannot_answer(self, _name: str, body: dict[str, Any]) -> None:
        response = self._post(**body)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content

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

        response = self._post(sessionIds=["session-a"])

        assert response.status_code == expected_status, response.content
