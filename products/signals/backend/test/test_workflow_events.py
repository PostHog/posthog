import json
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from confluent_kafka import KafkaException
from parameterized import parameterized

from products.cdp.backend.internal_events import INBOX_REPORT_READY_EVENT
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.signal_metadata import ReportSignalMeta
from products.signals.backend.workflow_events import emit_inbox_report_ready_event


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
        source_products = patch(
            "products.signals.backend.workflow_events.fetch_source_products_for_reports",
            return_value={
                str(self.report.id): ReportSignalMeta(
                    source_products=["error_tracking", "session_replay"], scout_name=None
                )
            },
        )
        self.fetch_source_products: MagicMock = source_products.start()
        self.addCleanup(source_products.stop)
        producer = patch("products.signals.backend.workflow_events.produce_internal_event")
        self.produce: MagicMock = producer.start()
        self.addCleanup(producer.stop)

    def _emit(self) -> None:
        emit_inbox_report_ready_event(team_id=self.team.id, report_id=str(self.report.id))

    def _produced_events(self) -> list[Any]:
        return [call.args[1] for call in self.produce.call_args_list]

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

    def test_a_failed_source_lookup_still_starts_the_run(self) -> None:
        self.fetch_source_products.side_effect = RuntimeError("clickhouse timeout")

        self._emit()

        [event] = self._produced_events()
        assert event.properties["source_products"] == []

    @parameterized.expand(
        [
            ("rejected_on_produce", RuntimeError("broker down"), None),
            ("rejected_on_delivery", None, KafkaException("message timed out")),
        ]
    )
    def test_a_failed_publish_raises_and_lets_a_retry_emit(
        self, _name: str, produce_error: Exception | None, delivery_error: Exception | None
    ) -> None:
        failed_delivery = MagicMock()
        failed_delivery.get.side_effect = delivery_error
        self.produce.side_effect = [produce_error or failed_delivery, MagicMock()]

        with pytest.raises(type(produce_error or delivery_error)):
            self._emit()
        self._emit()

        assert len(self._produced_events()) == 2
