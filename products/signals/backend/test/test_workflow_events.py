import json
from datetime import timedelta
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from confluent_kafka import KafkaException
from parameterized import parameterized

from products.cdp.backend.internal_events import INBOX_REPORT_READY_EVENT
from products.signals.backend import workflow_events
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.workflow_events import emit_inbox_report_ready_event, reconcile_stranded_ready_events


class TestEmitInboxReportReadyEvent(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="Checkout button does nothing on Safari",
            summary="Clicking checkout on Safari 17 throws a TypeError and the order is never placed.",
            signal_count=2,
            total_weight=2.0,
        )
        SignalReportArtefact.objects.create(
            team=self.team,
            report=self.report,
            type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            content=json.dumps({"explanation": "Blocks purchases", "priority": "P1"}),
        )
        producer = patch("products.signals.backend.workflow_events.produce_internal_event")
        self.produce: MagicMock = producer.start()
        self.addCleanup(producer.stop)

    def _emit(self) -> None:
        emit_inbox_report_ready_event(
            team_id=self.team.id, report_id=str(self.report.id), source_products=["error_tracking", "session_replay"]
        )

    def _produced_events(self) -> list[Any]:
        return [call.args[1] for call in self.produce.call_args_list]

    def _sweep_after(self, delay: timedelta) -> None:
        with time_machine.travel(timezone.now() + delay, tick=False):
            reconcile_stranded_ready_events()

    @staticmethod
    def _pending_delivery() -> MagicMock:
        pending_delivery = MagicMock()
        pending_delivery.get.side_effect = TimeoutError("Timeout waiting for produce result")
        return pending_delivery

    def test_settled_report_starts_one_run_with_the_compact_report(self) -> None:
        self._emit()

        [event] = self._produced_events()
        assert self.produce.call_args.args[0] == self.team.id
        assert event.event == INBOX_REPORT_READY_EVENT == "$inbox_report_ready"
        assert event.properties == {
            "report_id": str(self.report.id),
            "title": "Checkout button does nothing on Safari",
            "summary": "Clicking checkout on Safari 17 throws a TypeError and the order is never placed.",
            "priority": "P1",
            "source_products": ["error_tracking", "session_replay"],
            "report_url": f"http://localhost:8010/project/{self.team.id}/inbox/reports/{self.report.id}?link_source=workflow",
        }

    def test_a_report_that_settles_again_does_not_start_another_run(self) -> None:
        self._emit()
        self._emit()

        assert len(self._produced_events()) == 1

    @parameterized.expand(
        [
            ("in_progress", SignalReport.Status.IN_PROGRESS),
            ("pending_input", SignalReport.Status.PENDING_INPUT),
            ("suppressed", SignalReport.Status.SUPPRESSED),
        ]
    )
    def test_a_report_that_is_not_ready_starts_no_run(self, _name: str, status: SignalReport.Status) -> None:
        SignalReport.objects.filter(id=self.report.id).update(status=status)

        self._emit()

        assert self._produced_events() == []

    def test_a_delivery_still_pending_keeps_the_claim(self) -> None:
        self.produce.return_value = self._pending_delivery()

        self._emit()
        self._emit()

        assert len(self._produced_events()) == 1

    @parameterized.expand(
        [
            ("rejected_on_produce", RuntimeError("broker down"), None),
            ("rejected_on_delivery", None, KafkaException("message timed out")),
        ]
    )
    def test_a_failed_publish_is_logged_and_the_sweep_sends_it_again(
        self, _name: str, produce_error: Exception | None, delivery_error: Exception | None
    ) -> None:
        failed_delivery = MagicMock()
        failed_delivery.get.side_effect = delivery_error
        self.produce.side_effect = [produce_error or failed_delivery, MagicMock()]

        with patch.object(workflow_events, "logger") as logger:
            self._emit()
        logger.exception.assert_called_once()
        self._sweep_after(timedelta(minutes=16))
        self._sweep_after(timedelta(hours=1))

        assert len(self._produced_events()) == 2

    def test_a_stale_unconfirmed_claim_is_emitted_again_as_the_same_event(self) -> None:
        self.produce.return_value = self._pending_delivery()
        self._emit()
        self.produce.return_value = MagicMock()

        self._sweep_after(timedelta(minutes=16))
        self._sweep_after(timedelta(hours=1))

        first, retry = self._produced_events()
        assert retry == first

    @parameterized.expand(
        [
            ("still_fresh", True, timedelta(minutes=5)),
            ("confirmed", False, timedelta(hours=1)),
        ]
    )
    def test_the_sweep_leaves_a_claim_alone(self, _name: str, pending: bool, delay: timedelta) -> None:
        if pending:
            self.produce.return_value = self._pending_delivery()
        self._emit()

        self._sweep_after(delay)

        assert len(self._produced_events()) == 1

    def test_the_sweep_gives_back_the_claim_of_a_report_that_is_no_longer_ready(self) -> None:
        self.produce.return_value = self._pending_delivery()
        self._emit()
        SignalReport.objects.filter(id=self.report.id).update(status=SignalReport.Status.IN_PROGRESS)

        self._sweep_after(timedelta(minutes=16))
        assert len(self._produced_events()) == 1

        SignalReport.objects.filter(id=self.report.id).update(status=SignalReport.Status.READY)
        self._emit()
        assert len(self._produced_events()) == 2

    def test_the_sweep_keeps_the_claim_of_a_report_that_settles_while_it_runs(self) -> None:
        self.produce.return_value = self._pending_delivery()
        self._emit()
        SignalReport.objects.filter(id=self.report.id).update(status=SignalReport.Status.IN_PROGRESS)
        release_stale_claim = workflow_events._release_stale_claim

        def settle_then_release(*args: Any) -> None:
            SignalReport.objects.filter(id=self.report.id).update(status=SignalReport.Status.READY)
            self._emit()
            release_stale_claim(*args)

        with patch.object(workflow_events, "_release_stale_claim", side_effect=settle_then_release):
            self._sweep_after(timedelta(minutes=16))
        self._sweep_after(timedelta(minutes=32))

        assert len(self._produced_events()) == 2

    def test_a_failed_retry_stays_claimed_for_the_next_sweep(self) -> None:
        self.produce.return_value = self._pending_delivery()
        self._emit()
        self.produce.side_effect = [RuntimeError("broker down"), MagicMock()]

        self._sweep_after(timedelta(minutes=16))
        self._sweep_after(timedelta(minutes=32))
        self._sweep_after(timedelta(hours=1))

        assert len(self._produced_events()) == 3
