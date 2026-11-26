from datetime import timedelta
from uuid import UUID

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.db import OperationalError, connection

from parameterized import parameterized

from posthog.test.fixtures import create_app_metric2

from products.workflows.backend.facade.tasks import capture_workflow_first_real_sends
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.first_real_sends import FIRST_REAL_SEND_CUTOFF, FirstRealSendCaptureError

SERVICE = "products.workflows.backend.services.first_real_sends"
NOW = FIRST_REAL_SEND_CUTOFF + timedelta(days=3)
ENTRY_ATTEMPT_ID = UUID("6f1c4a52-0d7e-4b8a-9c3d-2e5f8a1b7c90")


def captured_events(scoped_capture: MagicMock) -> list[dict]:
    capture = scoped_capture.return_value.__enter__.return_value
    return [call.kwargs for call in capture.call_args_list]


@time_machine.travel(NOW, tick=False)
class TestCaptureWorkflowFirstRealSends(ClickhouseTestMixin, BaseTest):
    def _flow(
        self, created_at=FIRST_REAL_SEND_CUTOFF + timedelta(minutes=1), entry_attempt_id: UUID | None = None
    ) -> HogFlow:
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

    def _metric(
        self,
        flow: HogFlow,
        at,
        metric_name: str = "billable_invocation",
        metric_kind: str = "email",
        app_source: str = "hog_flow",
    ) -> None:
        create_app_metric2(
            team_id=self.team.pk,
            app_source=app_source,
            app_source_id=str(flow.id),
            metric_kind=metric_kind,
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
        self._metric(flow, NOW - timedelta(days=2, hours=1))
        self._metric(flow, NOW - timedelta(hours=22), metric_name="succeeded")
        self._metric(flow, NOW - timedelta(hours=22), metric_kind="sms")
        self._metric(flow, NOW - timedelta(hours=22), app_source="hog_function")
        self._metric(flow, first_send)
        self._metric(flow, NOW - timedelta(hours=2))

        test_depth = len(connection.atomic_blocks)
        capture_depths: list[int] = []
        scoped_capture.return_value.__enter__.return_value.side_effect = lambda **_: capture_depths.append(
            len(connection.atomic_blocks)
        )

        capture_workflow_first_real_sends()

        flow.refresh_from_db()
        assert flow.first_real_send_at == first_send
        assert capture_depths == [test_depth]
        [event] = captured_events(scoped_capture)
        assert event["event"] == "workflow first real send"
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
    def test_a_clickhouse_failure_leaves_the_column_unset(self, scoped_capture: MagicMock) -> None:
        flow = self._flow()
        self._metric(flow, NOW - timedelta(hours=2))

        with patch(f"{SERVICE}.sync_execute", side_effect=ConnectionError("ClickHouse is down")):
            with self.assertRaises(ConnectionError):
                capture_workflow_first_real_sends()

        flow.refresh_from_db()
        assert flow.first_real_send_at is None
        assert captured_events(scoped_capture) == []

    @patch(f"{SERVICE}.CANDIDATE_BATCH_SIZE", 1)
    @patch(f"{SERVICE}.ph_scoped_capture")
    def test_a_failed_flush_keeps_its_stamp_and_later_batches_still_capture(self, scoped_capture: MagicMock) -> None:
        flows = [self._flow(), self._flow()]
        for flow in flows:
            self._metric(flow, NOW - timedelta(hours=2))
        scoped_capture.return_value.__exit__.side_effect = [ConnectionError("capture is down"), None]

        with self.assertRaises(FirstRealSendCaptureError):
            capture_workflow_first_real_sends()

        for flow in flows:
            flow.refresh_from_db()
            assert flow.first_real_send_at is not None
        assert scoped_capture.return_value.__exit__.call_count == 2
        assert sorted(event["properties"]["hog_flow_id"] for event in captured_events(scoped_capture)) == sorted(
            str(flow.id) for flow in flows
        )

    @patch(f"{SERVICE}.CANDIDATE_BATCH_SIZE", 1)
    @patch(f"{SERVICE}.ph_scoped_capture")
    def test_a_postgres_failure_in_one_batch_fails_the_run_after_the_others(self, scoped_capture: MagicMock) -> None:
        flows = [self._flow(), self._flow()]
        for flow in flows:
            self._metric(flow, NOW - timedelta(hours=2))
        flow_ids = {flow.id for flow in flows}
        failed_ids: list = []
        real_filter = HogFlow.objects.filter

        def filter_failing_for_first_batch(*args, **kwargs):
            batch_ids = flow_ids.intersection(kwargs.get("pk__in", []))
            if batch_ids and not failed_ids:
                failed_ids.extend(batch_ids)
                raise OperationalError("Postgres is down")
            return real_filter(*args, **kwargs)

        with patch.object(HogFlow.objects, "filter", side_effect=filter_failing_for_first_batch):
            with self.assertRaises(OperationalError):
                capture_workflow_first_real_sends()

        stamped = {flow.id for flow in HogFlow.objects.filter(pk__in=flow_ids, first_real_send_at__isnull=False)}
        assert stamped == flow_ids - set(failed_ids)
        assert len(stamped) == 1
        assert [event["properties"]["hog_flow_id"] for event in captured_events(scoped_capture)] == [
            str(flow_id) for flow_id in stamped
        ]
