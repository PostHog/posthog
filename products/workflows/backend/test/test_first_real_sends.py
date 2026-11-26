from datetime import timedelta
from uuid import UUID

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.test.fixtures import create_app_metric2

from products.workflows.backend.facade.tasks import capture_workflow_first_real_sends
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.first_real_sends import FIRST_REAL_SEND_CUTOFF, WORKFLOW_FIRST_REAL_SEND_EVENT

SERVICE = "products.workflows.backend.services.first_real_sends"
NOW = FIRST_REAL_SEND_CUTOFF + timedelta(days=3)
ENTRY_ATTEMPT_ID = UUID("6f1c4a52-0d7e-4b8a-9c3d-2e5f8a1b7c90")


def captured_events(scoped_capture: MagicMock) -> list[dict]:
    capture = scoped_capture.return_value.__enter__.return_value
    return [call.kwargs for call in capture.call_args_list]


@time_machine.travel(NOW, tick=False)
class TestCaptureWorkflowFirstRealSends(ClickhouseTestMixin, BaseTest):
    def _flow(self, created_at=NOW - timedelta(days=1), entry_attempt_id: UUID | None = None) -> HogFlow:
        flow = HogFlow.objects.create(
            team=self.team,
            name="Welcome",
            created_by=self.user,
            status=HogFlow.State.ACTIVE,
            origin_product="broadcasts",
            entry_attempt_id=entry_attempt_id,
        )
        HogFlow.objects.filter(pk=flow.pk).update(created_at=created_at)
        return flow

    def _metric(self, flow: HogFlow, at, metric_name: str = "billable_invocation") -> None:
        create_app_metric2(
            team_id=self.team.pk,
            app_source="hog_flow",
            app_source_id=str(flow.id),
            metric_kind="email",
            metric_name=metric_name,
            timestamp=at,
        )

    @parameterized.expand([("with_entry_attempt", ENTRY_ATTEMPT_ID), ("without_entry_attempt", None)])
    @patch(f"{SERVICE}.ph_scoped_capture")
    def test_first_run_records_the_first_billable_email_and_captures_it_once(
        self, _name: str, entry_attempt_id: UUID | None, scoped_capture: MagicMock
    ) -> None:
        flow = self._flow(entry_attempt_id=entry_attempt_id)
        first_send = (NOW - timedelta(hours=20)).replace(microsecond=0)
        self._metric(flow, NOW - timedelta(hours=22), metric_name="succeeded")
        self._metric(flow, first_send)
        self._metric(flow, NOW - timedelta(hours=2))

        capture_workflow_first_real_sends()

        flow.refresh_from_db()
        assert flow.first_real_send_at == first_send
        [event] = captured_events(scoped_capture)
        assert event["event"] == WORKFLOW_FIRST_REAL_SEND_EVENT
        assert event["distinct_id"] == str(self.team.uuid)
        assert event["timestamp"] == first_send
        assert event["groups"]["organization"] == str(self.organization.id)
        assert event["properties"] == {
            "hog_flow_id": str(flow.id),
            "entry_attempt_id": str(entry_attempt_id) if entry_attempt_id else None,
            "origin_product": "broadcasts",
            "first_real_send_at": first_send.isoformat(),
        }

        scoped_capture.reset_mock()
        capture_workflow_first_real_sends()

        assert captured_events(scoped_capture) == []
        flow.refresh_from_db()
        assert flow.first_real_send_at == first_send

    @patch(f"{SERVICE}.ph_scoped_capture")
    def test_skips_workflows_created_before_the_cutoff(self, scoped_capture: MagicMock) -> None:
        flow = self._flow(created_at=FIRST_REAL_SEND_CUTOFF - timedelta(minutes=1))
        self._metric(flow, NOW - timedelta(hours=2))

        capture_workflow_first_real_sends()

        flow.refresh_from_db()
        assert flow.first_real_send_at is None
        assert captured_events(scoped_capture) == []

    @patch(f"{SERVICE}.ph_scoped_capture")
    @patch(f"{SERVICE}.sync_execute", side_effect=Exception("ClickHouse is down"))
    def test_a_clickhouse_error_leaves_the_column_unset(
        self, _sync_execute: MagicMock, scoped_capture: MagicMock
    ) -> None:
        flow = self._flow()
        self._metric(flow, NOW - timedelta(hours=2))

        with self.assertRaises(Exception):
            capture_workflow_first_real_sends()

        flow.refresh_from_db()
        assert flow.first_real_send_at is None
        assert captured_events(scoped_capture) == []
