import json
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
    MONITORING_EVIDENCE_MAX_CHARS,
    monitoring_research_evidence,
)
from products.signals.backend.tasks import emit_monitoring_research_request, sweep_monitoring_research_requests
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
        emit_monitoring_research_request.apply(
            kwargs={"team_id": self.team.id, "report_id": str(self.report.id), "attempt_id": str(self.attempt.id)},
            throw=True,
        )

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
        sweep_monitoring_research_requests.apply(throw=True)
        assert self.emitted() == []
        with time_machine.travel(self.now + timedelta(minutes=6), tick=False):
            sweep_monitoring_research_requests.apply(throw=True)
        assert len(self.emitted()) == 1
        target = SignalReport.objects.create(team=self.team, status="ready")
        SignalEmissionRecord.objects.filter(team=self.team, source_id=str(self.attempt.id)).update(
            report_id=str(target.id)
        )
        with time_machine.travel(self.now + timedelta(minutes=12), tick=False):
            sweep_monitoring_research_requests.apply(throw=True)
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

    @parameterized.expand([("brief", 1, 1), ("long_history", 1000, 40)])
    def test_research_loads_saved_evidence_without_putting_it_in_the_signal(
        self, _name: str, repetitions: int, history_rows: int
    ) -> None:
        assert self.attempt.aggregation_reason is not None
        reason = self.attempt.aggregation_reason * repetitions
        SignalReportMonitoringAttempt.objects.for_team(self.team.id).filter(id=self.attempt.id).update(
            aggregation_reason=reason
        )
        for _ in range(history_rows):
            SignalReportArtefact.add_log(
                team_id=self.team.id,
                report_id=str(self.report.id),
                content=NoteArtefact(
                    note="Assessment could not establish whether the deployment reached the affected population. "
                    * repetitions
                ),
                attribution=ArtefactAttribution.system(),
            )
        self.emit()
        payload = MonitoringUnresolvedSignalExtra.model_validate(self.emitted()[0].signal.extra)
        serialized = monitoring_research_evidence(team_id=self.team.id, payload=payload)
        assert len(serialized) <= MONITORING_EVIDENCE_MAX_CHARS
        evidence = json.loads(serialized)
        assert evidence["original_report"]["summary"] == self.report.summary
        assert reason.startswith(evidence["requested_attempt"]["reason_excerpt"])
        assert str(self.attempt.id) == evidence["requested_attempt"]["id"]
        assert "inbox-report-artefacts-list" in evidence["history"]
        assert len(payload.explanation) <= 1000
        assert "affected population" in evidence["artefacts"][0]["content_excerpt"]
        assert "affected population" not in self.emitted()[0].signal.description
        self.attempt.refresh_from_db()
        assert self.attempt.aggregation_reason == reason
