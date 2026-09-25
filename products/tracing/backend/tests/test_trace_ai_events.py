import json
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.http import HttpResponse

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, User
from posthog.models.ai_events.test_util import bulk_create_ai_events

from products.access_control.backend.models.access_control import AccessControl

# The form OTel ingestion writes: lowercase hex, 32 characters for a trace and 16 for a span.
TRACE_A = "4bf92f3577b34da6a3ce929d0e0e4736"
TRACE_B = "8a3c60f7d188f8fa79d48a391a778fa6"
# The form the LLM gateway writes for the same trace from a `traceparent` header.
TRACE_A_UUID = "4bf92f35-77b3-4da6-a3ce-929d0e0e4736"
PARENT_SPAN = "00f067aa0ba902b7"


class TestTraceAiEvents(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag_patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        flag_patcher.start()
        self.addCleanup(flag_patcher.stop)

    def _get(self, trace_id: str) -> HttpResponse:
        return self.client.get(f"/api/projects/{self.team.id}/tracing/spans/trace/{trace_id}/ai_events/")

    def _create_ai_event(
        self,
        trace_id: str,
        *,
        event: str = "$ai_generation",
        timestamp: str = "2026-06-02T08:00:00Z",
        properties: dict[str, Any] | None = None,
    ) -> str:
        event_uuid = str(uuid4())
        _create_event(
            event_uuid=event_uuid,
            distinct_id="user-1",
            event=event,
            team=self.team,
            properties={"$ai_trace_id": trace_id, **(properties or {})},
            timestamp=timestamp,
        )
        return event_uuid

    def test_lists_the_traces_ai_events_earliest_start_first(self) -> None:
        generation = self._create_ai_event(
            TRACE_A,
            timestamp="2026-06-02T08:00:05Z",
            properties={
                "$ai_span_id": "b9c7c989f97918e1",
                "$ai_parent_id": PARENT_SPAN,
                "$ai_latency": 4.5,
                "$ai_model": "model-x",
                "$ai_provider": "provider-y",
                "$ai_input_tokens": 120,
                "$ai_output_tokens": 30,
                "$ai_total_cost_usd": 0.0071,
                "$ai_is_error": True,
            },
        )
        span = self._create_ai_event(TRACE_A, event="$ai_span", timestamp="2026-06-02T08:00:01Z")
        self._create_ai_event(TRACE_B)
        self._create_ai_event(TRACE_A, event="$ai_feedback")
        flush_persons_and_events()

        response = self._get(TRACE_A.upper())

        assert response.status_code == status.HTTP_200_OK, response.content
        results = json.loads(response.content)["results"]
        # The generation is stamped after the span but started before it, so it sorts first.
        assert [row["uuid"] for row in results] == [generation, span]
        assert results[0] == {
            "uuid": generation,
            "event": "$ai_generation",
            "started_at": "2026-06-02T08:00:00.500000Z",
            "ai_trace_id": TRACE_A,
            "ai_span_id": "b9c7c989f97918e1",
            "ai_parent_id": PARENT_SPAN,
            "span_name": None,
            "latency_seconds": 4.5,
            "model": "model-x",
            "provider": "provider-y",
            "input_tokens": 120,
            "output_tokens": 30,
            "total_cost_usd": 0.0071,
            "is_error": True,
        }
        assert results[1]["is_error"] is False

    @parameterized.expand(
        [
            ("an SDK event stamped at the finish", {"$ai_latency": 4}, "2026-06-02T08:00:00Z", 4),
            ("an SDK event with no latency", {}, "2026-06-02T08:00:04Z", None),
            (
                "an OTel event stamped at the start",
                {"$ai_latency": 4, "$ai_ingestion_source": "otel"},
                "2026-06-02T08:00:04Z",
                4,
            ),
            # A sender-controlled latency past any real call is dropped rather than overflowing.
            ("a junk latency", {"$ai_latency": 1e20}, "2026-06-02T08:00:04Z", None),
            ("a negative latency", {"$ai_latency": -3}, "2026-06-02T08:00:04Z", None),
        ]
    )
    def test_normalizes_the_start_time_by_ingestion_source(
        self, _name: str, properties: dict[str, Any], expected_start: str, expected_latency: float | None
    ) -> None:
        self._create_ai_event(TRACE_A, timestamp="2026-06-02T08:00:04Z", properties=properties)
        flush_persons_and_events()

        response = self._get(TRACE_A)

        assert response.status_code == status.HTTP_200_OK, response.content
        rows = json.loads(response.content)["results"]
        assert [(row["started_at"], row["latency_seconds"]) for row in rows] == [(expected_start, expected_latency)]

    def test_finds_the_gateway_uuid_form_of_the_trace_id(self) -> None:
        by_uuid = self._create_ai_event(TRACE_A_UUID)
        flush_persons_and_events()

        response = self._get(TRACE_A)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert [row["uuid"] for row in json.loads(response.content)["results"]] == [by_uuid]

    def test_collapses_duplicate_rows_of_one_event(self) -> None:
        # ai_events is a plain MergeTree fed by at-least-once ingestion, so one event can land twice.
        row = {
            "event_uuid": str(uuid4()),
            "event": "$ai_generation",
            "distinct_id": "user-1",
            "team": self.team,
            "properties": {"$ai_trace_id": TRACE_A, "$ai_model": "model-x"},
            "timestamp": "2026-06-02T08:00:00Z",
        }
        bulk_create_ai_events([row, row])

        response = self._get(TRACE_A)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert [r["uuid"] for r in json.loads(response.content)["results"]] == [row["event_uuid"]]

    def test_rejects_a_non_hex_trace_id(self) -> None:
        response = self._get("zz92f3577b34da6a3ce929d0e0e4736")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content

    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_requires_the_feature_flag(self, _flag: Any) -> None:
        response = self._get(TRACE_A)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content

    @parameterized.expand([("viewer", status.HTTP_200_OK), ("none", status.HTTP_403_FORBIDDEN)])
    def test_requires_llm_analytics_viewer_access(self, access_level: str, expected_status: int) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        user = User.objects.create_and_join(self.organization, "tracing-only@posthog.com", "testtest")
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            resource_id=None,
            access_level=access_level,
            organization_member=membership,
        )
        self.client.force_login(user)

        response = self._get(TRACE_A)

        assert response.status_code == expected_status, response.content
