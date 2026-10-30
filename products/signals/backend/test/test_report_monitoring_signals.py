import json
from datetime import timedelta
from uuid import uuid4

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
    SignalReportCheck,
    SignalReportMonitoringAttempt,
    SignalReportMonitoringResult,
)
from products.signals.backend.report_monitoring_signals import (
    MONITORING_EVIDENCE_MAX_CHARS,
    emit_monitoring_research,
    monitoring_research_evidence,
)
from products.signals.backend.tasks import sweep_monitoring_research_requests
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

    def test_query_protected_measurements_stay_out_of_persisted_prompt_inputs(self) -> None:
        value = 7319.25
        explanation = f"The measured value was {value}."
        check = SignalReportCheck.objects.for_team(self.team.id).create(
            team=self.team,
            report=self.report,
            kind=SignalReportCheck.Kind.METRIC_THRESHOLD,
            title="Completed checkouts",
            config={},
            next_run_at=self.now,
            expires_at=self.now + timedelta(days=1),
        )
        SignalReportMonitoringAttempt.objects.for_team(self.team.id).filter(id=self.attempt.id).update(
            aggregation_reason=explanation
        )
        result = SignalReportMonitoringResult.objects.for_team(self.team.id).create(
            team=self.team,
            report=self.report,
            attempt=self.attempt,
            report_check=check,
            submission_id=uuid4(),
            definition_version="a" * 64,
            window_start=self.attempt.monitoring_started_at,
            window_end=self.now,
            evaluated_at=self.now,
            outcome="failed",
            evidence_status="sufficient",
            evidence_reason=explanation,
            evidence_refs=[explanation],
            explanation=explanation,
        )
        for kind in (
            SignalReportArtefact.ArtefactType.CHECK_RESULT,
            SignalReportArtefact.ArtefactType.CHECK_OBSERVATION,
            SignalReportArtefact.ArtefactType.IMPACT_MEASUREMENT_PLAN,
        ):
            SignalReportArtefact.objects.create(
                team=self.team,
                report=self.report,
                type=kind,
                content=json.dumps(
                    {
                        "check_id": str(check.id),
                        "kind": check.kind,
                        "title": check.title,
                        "outcome": "failed",
                        "explanation": explanation,
                        "observed_value": value,
                        "baseline_value": value,
                        "monitoring_started_at": str(self.attempt.monitoring_started_at),
                        "measured_at": str(self.now),
                        "query": {"kind": "HogQLQuery", "query": "SELECT 7319.25"},
                    }
                ),
            )
        self.emit()
        signal = self.emitted()[0].signal
        payload = MonitoringUnresolvedSignalExtra.model_validate(signal.extra)
        serialized = monitoring_research_evidence(team_id=self.team.id, payload=payload)
        assert str(value) not in serialized + signal.description + json.dumps(signal.extra)
        evidence = json.loads(serialized)
        assert evidence["artefacts"] == []
        assert evidence["results"][0]["id"] == str(result.id)
        assert evidence["results"][0]["outcome"] == "failed"
        assert "inbox-report-artefacts-list" in evidence["history"]

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
        assert "reason_excerpt" not in evidence["requested_attempt"]
        assert reason not in serialized
        assert str(self.attempt.id) == evidence["requested_attempt"]["id"]
        assert "inbox-report-artefacts-list" in evidence["history"]
        assert "affected population" in evidence["artefacts"][0]["content_excerpt"]
        assert "affected population" not in self.emitted()[0].signal.description
        self.attempt.refresh_from_db()
        assert self.attempt.aggregation_reason == reason
