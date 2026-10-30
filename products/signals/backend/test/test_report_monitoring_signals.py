import json
import time
from datetime import timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from parameterized import parameterized

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import NoteArtefact
from products.signals.backend.contracts import MonitoringUnresolvedSignalExtra
from products.signals.backend.enums import SignalSourceProduct, SignalSourceType
from products.signals.backend.models import (
    SignalEmissionRecord,
    SignalReport,
    SignalReportArtefact,
    SignalReportMonitoringAttempt,
)
from products.signals.backend.report_monitoring_signals import (
    emit_due_monitoring_research,
    emit_monitoring_research,
    monitoring_research_evidence,
)
from products.signals.backend.temporal.emitter import SignalEmitterInput


class TestMonitoringSignals(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.now = timezone.now()
        self.enterContext(time_machine.travel(self.now, tick=False))
        self.flag = self.enterContext(
            patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True)
        )
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.report = SignalReport.objects.create(
            team=self.team,
            status="closed",
            title="Checkout recovery",
            summary="Checkout completion remains unverified.",
            monitoring_started_at=self.now - timedelta(hours=1),
        )
        self.attempt = SignalReportMonitoringAttempt.objects.for_team(self.team.id).create(
            team=self.team,
            report=self.report,
            monitoring_started_at=self.now - timedelta(hours=1),
            check_versions={},
            aggregation_state="failed",
            aggregation_reason="A check failed with sufficient evidence.",
            research_requested_at=self.now,
        )
        self.temporal_client = AsyncMock()
        self.enterContext(
            patch("products.signals.backend.facade.api.async_connect", new=AsyncMock(return_value=self.temporal_client))
        )

    def emit(self) -> None:
        emit_monitoring_research(team_id=self.team.id, report_id=self.report.id, attempt_id=self.attempt.id)

    def emitted(self) -> list[SignalEmitterInput]:
        return [
            call.args[1]
            for call in self.temporal_client.start_workflow.call_args_list
            if isinstance(call.args[1], SignalEmitterInput)
        ]

    def test_monitoring_request_uses_the_normal_emitter_with_stable_identity(self) -> None:
        self.emit()
        self.emit()
        signals = [item.signal for item in self.emitted()]
        assert len(signals) == 2
        assert signals[0].signal_id == signals[1].signal_id
        assert signals[0].source_product == SignalSourceProduct.SIGNALS_CHECK
        assert signals[0].source_type == SignalSourceType.MONITORING_UNRESOLVED
        assert signals[0].source_id == str(self.attempt.id)
        assert signals[0].weight == 1.0
        assert signals[0].extra["report_id"] == str(self.report.id)
        assert signals[0].extra["attempt_id"] == str(self.attempt.id)
        assert "Uncertainty does not establish an implementation defect" in signals[0].description
        assert (
            SignalEmissionRecord.objects.filter(
                team=self.team, source_id=str(self.attempt.id), report_id__isnull=True
            ).count()
            == 1
        )
        self.report.refresh_from_db()
        self.attempt.refresh_from_db()
        assert self.report.status == "closed"
        assert self.attempt.research_requested_at == self.now

    def test_missed_emission_recovers_after_backoff_and_stops_when_grouped(self) -> None:
        self.temporal_client.start_workflow.side_effect = RuntimeError("Temporal unavailable")
        with self.assertRaisesRegex(RuntimeError, "Temporal unavailable"):
            self.emit()
        self.temporal_client.start_workflow.side_effect = None
        emit_due_monitoring_research(deadline=time.monotonic() + 10, limit=1)
        assert self.emitted() == []
        with time_machine.travel(self.now + timedelta(minutes=6), tick=False):
            emit_due_monitoring_research(deadline=time.monotonic() + 10, limit=1)
        assert len(self.emitted()) == 1
        target = SignalReport.objects.create(team=self.team, status="ready")
        SignalEmissionRecord.objects.filter(team=self.team, source_id=str(self.attempt.id)).update(
            report_id=str(target.id)
        )
        with time_machine.travel(self.now + timedelta(minutes=12), tick=False):
            emit_due_monitoring_research(deadline=time.monotonic() + 10, limit=1)
        assert len(self.emitted()) == 1

    def test_disabled_monitoring_preserves_the_request_until_enabled(self) -> None:
        self.flag.return_value = False
        self.emit()
        assert self.emitted() == []
        self.attempt.refresh_from_db()
        assert self.attempt.research_requested_at == self.now
        self.flag.return_value = True
        self.emit()
        assert len(self.emitted()) == 1

    @parameterized.expand([("brief", 1), ("long_assessment", 1000)])
    def test_research_loads_saved_evidence_without_putting_it_in_the_signal(self, _name: str, repetitions: int) -> None:
        assert self.attempt.aggregation_reason is not None
        reason = self.attempt.aggregation_reason * repetitions
        SignalReportMonitoringAttempt.objects.for_team(self.team.id).filter(id=self.attempt.id).update(
            aggregation_reason=reason
        )
        SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=NoteArtefact(
                note="Assessment could not establish whether the deployment reached the affected population."
            ),
            attribution=ArtefactAttribution.system(),
        )
        self.emit()
        payload = MonitoringUnresolvedSignalExtra.model_validate(self.emitted()[0].signal.extra)
        evidence = json.loads(monitoring_research_evidence(team_id=self.team.id, payload=payload))
        assert evidence["original_report"]["summary"] == self.report.summary
        assert evidence["attempts"][0]["aggregation_reason"] == reason
        assert len(payload.explanation) <= 1000
        assert "affected population" in evidence["artefacts"][0]["content"]
        assert "affected population" not in self.emitted()[0].signal.description
