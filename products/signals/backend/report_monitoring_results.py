from __future__ import annotations

from datetime import datetime, timedelta
from functools import partial
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.dataclasses import frozen

from products.signals.backend.models import SignalReport, SignalReportCheck, SignalReportMonitoringResult
from products.signals.backend.report_check_evidence import EvidenceStatus
from products.signals.backend.report_content_gates import team_report_monitoring_enabled
from products.signals.backend.report_monitoring_attempts import check_definition_version, current_monitoring_attempt
from products.signals.backend.report_monitoring_outcomes import aggregate_monitoring_attempt_safely

MONITORING_RESULT_ELIGIBLE_STATUSES = (
    *SignalReportCheck.OPEN_STATUSES,
    SignalReportCheck.Status.ERRORED,
    SignalReportCheck.Status.EXPIRED,
)
LEGACY_MONITORING_TERMINAL_STATUSES = (
    SignalReportCheck.Status.PASSED,
    SignalReportCheck.Status.FAILED,
    SignalReportCheck.Status.INCONCLUSIVE,
)


def monitoring_result_check_eligible(check: SignalReportCheck, attempt_id: UUID) -> bool:
    return check.status in MONITORING_RESULT_ELIGIBLE_STATUSES or (
        check.kind == SignalReportCheck.Kind.AGENT
        and check.status in LEGACY_MONITORING_TERMINAL_STATUSES
        and check.legacy_monitoring_attempt_id == attempt_id
    )


class InvalidMonitoringResult(ValueError):
    pass


class MonitoringResultConflict(ValueError):
    pass


@frozen
class MonitoringEvaluation:
    team_id: int
    report_id: UUID
    attempt_id: UUID
    check_id: UUID
    submission_id: UUID
    definition_version: str
    window_start: datetime
    window_end: datetime
    evaluated_at: datetime
    evidence_status: EvidenceStatus
    evidence_reason: str
    expectation_matches: bool | None
    explanation: str
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if any(timezone.is_naive(value) for value in (self.window_start, self.window_end, self.evaluated_at)):
            raise ValueError("Evaluation timestamps must be timezone-aware.")
        if self.window_end < self.window_start or self.evaluated_at < self.window_end:
            raise ValueError("Evaluation must follow an ordered evidence window.")
        if self.evidence_status not in {"sufficient", "insufficient", "unsupported", "errored"}:
            raise ValueError("Unknown evidence qualification.")
        if self.expectation_matches is not None and not isinstance(self.expectation_matches, bool):
            raise ValueError("An expectation match must be a boolean or absent.")
        if self.evidence_status == "sufficient" and self.expectation_matches is None:
            raise ValueError("Sufficient evidence needs an expectation match.")
        if self.evidence_status in {"unsupported", "errored"} and self.expectation_matches is not None:
            raise ValueError("Unsupported or errored evaluation cannot establish an expectation match.")
        if not self.explanation.strip() or not self.evidence_reason.strip():
            raise ValueError("An evaluation needs an explanation and evidence qualification reason.")
        if any(not reference.strip() for reference in self.evidence_refs):
            raise ValueError("Evidence references must not be empty.")

    @property
    def outcome(self) -> SignalReportCheck.Outcome:
        if self.evidence_status == "errored":
            return SignalReportCheck.Outcome.ERRORED
        if self.evidence_status != "sufficient":
            return SignalReportCheck.Outcome.INCONCLUSIVE
        return SignalReportCheck.Outcome.PASSED if self.expectation_matches else SignalReportCheck.Outcome.FAILED

    def matches(self, result: SignalReportMonitoringResult) -> bool:
        return (
            result.definition_version == self.definition_version
            and result.window_start == self.window_start
            and result.window_end == self.window_end
            and result.evaluated_at == self.evaluated_at
            and result.evidence_status == self.evidence_status
            and result.evidence_reason == self.evidence_reason
            and result.expectation_matches == self.expectation_matches
            and result.explanation == self.explanation
            and result.evidence_refs == list(self.evidence_refs)
        )


def save_monitoring_result(evaluation: MonitoringEvaluation) -> SignalReportMonitoringResult:
    with transaction.atomic():
        # Cancellation writes an artefact FK while holding the check row, so permit report key-share locks.
        report = (
            SignalReport.objects.select_for_update(no_key=True)
            .filter(team_id=evaluation.team_id, id=evaluation.report_id)
            .first()
        )
        results = SignalReportMonitoringResult.objects.for_team(evaluation.team_id).filter(
            report_id=evaluation.report_id, attempt_id=evaluation.attempt_id, report_check_id=evaluation.check_id
        )
        previous = results.filter(submission_id=evaluation.submission_id).first()
        if previous is not None:
            if not evaluation.matches(previous):
                raise MonitoringResultConflict("The submission ID already records a different evaluation.")
            return previous
        if report is None or report.status != SignalReport.Status.MONITORING:
            raise InvalidMonitoringResult("The report is not Monitoring.")
        attempt = current_monitoring_attempt(report)
        if attempt is None or attempt.id != evaluation.attempt_id:
            raise InvalidMonitoringResult("The implementation attempt is no longer current.")
        if attempt.check_versions.get(str(evaluation.check_id)) != evaluation.definition_version:
            raise InvalidMonitoringResult("The check and definition version must belong to the attempt snapshot.")
        check = (
            SignalReportCheck.objects.for_team(evaluation.team_id)
            .select_for_update()
            .filter(id=evaluation.check_id, report_id=report.id)
            .first()
        )
        now = timezone.now()
        if not team_report_monitoring_enabled(evaluation.team_id):
            raise InvalidMonitoringResult("Monitoring is disabled.")
        if check is None or not monitoring_result_check_eligible(check, attempt.id):
            raise InvalidMonitoringResult("The check was cancelled or already completed.")
        if check_definition_version(check) != evaluation.definition_version:
            raise InvalidMonitoringResult("The authored definition changed.")
        if check.soak_minutes is None:
            raise InvalidMonitoringResult("The check needs an explicit soak.")
        end = attempt.monitoring_started_at + timedelta(minutes=check.soak_minutes)
        if evaluation.window_start != attempt.monitoring_started_at or evaluation.window_end != end:
            raise InvalidMonitoringResult("The evidence window must match the fixed Monitoring window.")
        if now < end or evaluation.evaluated_at > now:
            raise InvalidMonitoringResult("The soak must finish before evaluation and acceptance.")
        if results.filter(outcome__in=[SignalReportCheck.Outcome.PASSED, SignalReportCheck.Outcome.FAILED]).exists():
            raise MonitoringResultConflict("The check already has an accepted verdict for this attempt.")
        result = results.create(
            team_id=evaluation.team_id,
            report_id=report.id,
            attempt_id=attempt.id,
            report_check_id=check.id,
            submission_id=evaluation.submission_id,
            definition_version=evaluation.definition_version,
            window_start=evaluation.window_start,
            window_end=evaluation.window_end,
            evaluated_at=evaluation.evaluated_at,
            outcome=evaluation.outcome,
            evidence_status=evaluation.evidence_status,
            evidence_reason=evaluation.evidence_reason,
            expectation_matches=evaluation.expectation_matches,
            explanation=evaluation.explanation,
            evidence_refs=list(evaluation.evidence_refs),
        )
        transaction.on_commit(
            partial(
                aggregate_monitoring_attempt_safely,
                team_id=evaluation.team_id,
                report_id=evaluation.report_id,
                attempt_id=evaluation.attempt_id,
            )
        )
        return result
