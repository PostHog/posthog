from __future__ import annotations

import json
import time
import hashlib
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID

from django.db import transaction
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import MD5
from django.utils import timezone

import structlog
from pydantic import BaseModel, ConfigDict, Field, StrictBool, TypeAdapter, field_validator, model_validator
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.dataclasses import frozen

from products.signals.backend.models import (
    SignalReport,
    SignalReportCheck,
    SignalReportMonitoringResult,
    SignalScoutRun,
)
from products.signals.backend.report_charts import _unstorable_text
from products.signals.backend.report_check_agent import (
    CHECK_DISPATCH_DEFER_AFTER,
    _refuse_dispatch,
    resolve_check_skill_name,
)
from products.signals.backend.report_check_evidence import EvidenceStatus
from products.signals.backend.report_check_final_candidates import DueFinalCheck, collect_due_final_checks
from products.signals.backend.report_checks import AgentCheckConfig, parse_check_config
from products.signals.backend.report_content_gates import team_report_monitoring_enabled
from products.signals.backend.report_monitoring_attempts import check_definition_version, current_monitoring_attempt
from products.signals.backend.report_monitoring_results import (
    InvalidMonitoringResult,
    MonitoringEvaluation,
    MonitoringResultConflict,
    monitoring_result_check_eligible,
    save_monitoring_result,
)
from products.signals.backend.scout_harness.limits import STALE_RUN_CUTOFF_S, TRIGGERED_BY_MONITORING

logger = structlog.get_logger(__name__)

MONITORING_AGENT_DISPATCH_BACKOFF = CHECK_DISPATCH_DEFER_AFTER


@frozen
class MonitoringScoutCheck:
    team_id: int
    report_id: UUID
    attempt_id: UUID
    check_id: UUID
    submission_id: UUID
    definition_version: str
    window_start_iso: str
    window_end_iso: str

    @property
    def window_start(self) -> datetime:
        return datetime.fromisoformat(self.window_start_iso)

    @property
    def window_end(self) -> datetime:
        return datetime.fromisoformat(self.window_end_iso)

    def incomplete_evaluation(self, evaluated_at: datetime) -> MonitoringEvaluation:
        return MonitoringEvaluation(
            team_id=self.team_id,
            report_id=self.report_id,
            attempt_id=self.attempt_id,
            check_id=self.check_id,
            submission_id=self.submission_id,
            definition_version=self.definition_version,
            window_start=self.window_start,
            window_end=self.window_end,
            evaluated_at=evaluated_at,
            evidence_status="errored",
            evidence_reason="scout_run_incomplete",
            expectation_matches=None,
            explanation="The scout run ended without a valid Monitoring result.",
        )


class MonitoringScoutResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    evidence_status: EvidenceStatus
    evidence_reason: str = Field(min_length=1, max_length=2000)
    expectation_matches: StrictBool | None
    explanation: str = Field(min_length=1, max_length=16000)
    evidence_refs: list[str] = Field(max_length=50)

    @field_validator("evidence_reason", "explanation", "evidence_refs")
    @classmethod
    def content_must_be_storable(cls, value: str | list[str]) -> str | list[str]:
        if reason := _unstorable_text(value):
            raise ValueError(f"Monitoring results must not contain {reason}.")
        return value

    @model_validator(mode="after")
    def qualification_must_match_verdict(self) -> MonitoringScoutResult:
        if self.evidence_status == "sufficient" and self.expectation_matches is None:
            raise ValueError("Sufficient evidence requires a boolean expectation_matches.")
        if self.evidence_status in {"unsupported", "errored"} and self.expectation_matches is not None:
            raise ValueError("Unsupported or errored evidence requires expectation_matches=null.")
        if not self.evidence_reason.strip() or not self.explanation.strip():
            raise ValueError("Evidence qualification and explanation must not be blank.")
        if any(not reference.strip() for reference in self.evidence_refs):
            raise ValueError("Evidence references must not be blank.")
        return self


def monitoring_scout_check(due: DueFinalCheck) -> MonitoringScoutCheck:
    member = due.member
    return MonitoringScoutCheck(
        team_id=member.check.team_id,
        report_id=member.check.report_id,
        attempt_id=member.attempt_id,
        check_id=member.check.id,
        submission_id=due.submission_id,
        definition_version=member.definition_version,
        window_start_iso=member.window_start.isoformat(),
        window_end_iso=member.window_end.isoformat(),
    )


def ready_monitoring_scout_check(binding: MonitoringScoutCheck, *, allow_submitted: bool = False) -> SignalReportCheck:
    check = (
        SignalReportCheck.objects.for_team(binding.team_id)
        .select_related("report", "report__team")
        .get(id=binding.check_id, report_id=binding.report_id)
    )
    report = check.report
    attempt = current_monitoring_attempt(report)
    if (
        report.status != SignalReport.Status.MONITORING
        or report.team.parent_team_id is not None
        or not team_report_monitoring_enabled(binding.team_id)
        or attempt is None
        or attempt.id != binding.attempt_id
        or attempt.monitoring_started_at != binding.window_start
        or attempt.check_versions.get(str(check.id)) != binding.definition_version
        or check_definition_version(check) != binding.definition_version
        or check.kind != SignalReportCheck.Kind.AGENT
        or not monitoring_result_check_eligible(check, binding.attempt_id)
        or check.soak_minutes is None
        or binding.window_end != binding.window_start + timedelta(minutes=check.soak_minutes)
        or binding.window_end > timezone.now()
    ):
        raise InvalidMonitoringResult("The authored check is no longer eligible for this Monitoring evaluation.")
    if not allow_submitted and (
        SignalReportMonitoringResult.objects.for_team(binding.team_id)
        .filter(attempt_id=binding.attempt_id, report_check_id=binding.check_id)
        .exclude(evidence_status="errored")
        .exists()
    ):
        raise InvalidMonitoringResult("The authored check already has a final evaluation.")
    return check


def build_monitoring_run_note(binding: MonitoringScoutCheck, check: SignalReportCheck) -> str:
    config = AgentCheckConfig.model_validate(check.config)
    return json.dumps(
        {
            "submission_id": str(binding.submission_id),
            "team_id": binding.team_id,
            "report_id": str(binding.report_id),
            "attempt_id": str(binding.attempt_id),
            "check_id": str(binding.check_id),
            "definition_version": binding.definition_version,
            "window_start": binding.window_start.isoformat(),
            "window_end": binding.window_end.isoformat(),
            "check": check.title,
            "rationale": check.rationale,
            "expectation": config.instructions,
            "probe_hints": config.probe_hints,
        },
        sort_keys=True,
    )


def bound_monitoring_scout_run(canonical_team_id: int, run_note: str) -> SignalScoutRun | None:
    # Briefs can exceed btree key limits; the digest locates candidates and full equality binds the run.
    return (
        SignalScoutRun.objects.for_team(canonical_team_id)
        .select_related("task_run")
        .alias(_run_note_digest=MD5(KeyTextTransform("run_note", "metadata")))
        .filter(
            _run_note_digest=hashlib.md5(run_note.encode(), usedforsecurity=False).hexdigest(),
            metadata__triggered_by=TRIGGERED_BY_MONITORING,
            metadata__run_note=run_note,
        )
        .order_by("created_at", "id")
        .first()
    )


def _monitoring_binding_for_run(run: SignalScoutRun) -> MonitoringScoutCheck:
    if not isinstance(run.metadata, dict) or run.metadata.get("triggered_by") != TRIGGERED_BY_MONITORING:
        raise InvalidMonitoringResult("Only an authored Monitoring scout can submit this result.")
    try:
        data = json.loads(run.metadata["run_note"])
        binding = TypeAdapter(MonitoringScoutCheck).validate_python(
            {**data, "window_start_iso": data["window_start"], "window_end_iso": data["window_end"]}
        )
        if timezone.is_naive(binding.window_start) or timezone.is_naive(binding.window_end):
            raise ValueError("Monitoring windows must have timezones.")
    except (KeyError, TypeError, ValueError) as error:
        raise InvalidMonitoringResult("The run has no valid Monitoring assignment.") from error
    if binding.team_id != run.team_id:
        raise InvalidMonitoringResult("The assignment must belong to the run's environment.")
    return binding


def _ready_monitoring_run(run: SignalScoutRun, binding: MonitoringScoutCheck, *, allow_submitted: bool = False) -> None:
    check = ready_monitoring_scout_check(binding, allow_submitted=allow_submitted)
    note = build_monitoring_run_note(binding, check)
    if not isinstance(run.metadata, dict) or run.metadata.get("run_note") != note:
        raise InvalidMonitoringResult("The run's Monitoring assignment changed.")
    bound = bound_monitoring_scout_run(run.team_id, note)
    if bound is None or bound.id != run.id:
        raise InvalidMonitoringResult("The result must come from the dispatched Monitoring run.")


def monitoring_scout_can_submit(*, team_id: int, task_id: UUID, task_run_id: UUID | str) -> bool:
    try:
        identifier = UUID(str(task_run_id))
    except ValueError:
        return False
    run = (
        SignalScoutRun.objects.for_team(team_id)
        .select_related("task_run")
        .filter(task_run_id=identifier, task_run__task_id=task_id, metadata__triggered_by=TRIGGERED_BY_MONITORING)
        .only("id", "team_id", "metadata", "task_run_id", "task_run__status")
        .first()
    )
    if run is None or run.task_run.status not in {"queued", "in_progress"}:
        return False
    try:
        _ready_monitoring_run(run, _monitoring_binding_for_run(run), allow_submitted=True)
    except (InvalidMonitoringResult, SignalReportCheck.DoesNotExist):
        return False
    return True


def submit_monitoring_scout_result(run: SignalScoutRun, payload: MonitoringScoutResult) -> SignalReportMonitoringResult:
    with transaction.atomic():
        run = (
            SignalScoutRun.objects.for_team(run.team_id)
            .select_for_update(of=("self",))
            .select_related("task_run")
            .get(id=run.id)
        )
        binding = _monitoring_binding_for_run(run)
        previous = (
            SignalReportMonitoringResult.objects.for_team(binding.team_id)
            .filter(
                attempt_id=binding.attempt_id, report_check_id=binding.check_id, submission_id=binding.submission_id
            )
            .first()
        )
        evaluated_at = previous.evaluated_at if previous is not None else timezone.now()
        evaluation = replace(
            binding.incomplete_evaluation(evaluated_at),
            evidence_status=payload.evidence_status,
            evidence_reason=payload.evidence_reason,
            expectation_matches=payload.expectation_matches,
            explanation=payload.explanation,
            evidence_refs=tuple(payload.evidence_refs),
        )
        if previous is not None:
            if not evaluation.matches(previous):
                raise MonitoringResultConflict("This Monitoring submission already records a different result.")
            return previous
        if run.task_run.status != "in_progress":
            raise InvalidMonitoringResult("Submit the Monitoring result while its scout run is in progress.")
        _ready_monitoring_run(run, binding)
        return _save_scout_evaluation(evaluation)


def _save_scout_evaluation(evaluation: MonitoringEvaluation) -> SignalReportMonitoringResult:
    with transaction.atomic():
        result = save_monitoring_result(evaluation)
        SignalReportCheck.objects.for_team(evaluation.team_id).filter(id=evaluation.check_id).update(
            monitoring_dispatch_after=None
        )
        return result


def finalize_monitoring_scout_run(
    binding: MonitoringScoutCheck,
    *,
    canonical_team_id: int,
    skill_name: str,
    run_note: str,
    run_id: str | None,
    failed: bool = False,
    execution_finished: bool = False,
) -> None:
    previous = (
        SignalReportMonitoringResult.objects.for_team(binding.team_id)
        .filter(
            report_id=binding.report_id,
            attempt_id=binding.attempt_id,
            report_check_id=binding.check_id,
            submission_id=binding.submission_id,
        )
        .first()
    )
    if previous is not None:
        return
    try:
        check = ready_monitoring_scout_check(binding)
        if (check.report.team.parent_team_id or binding.team_id) != canonical_team_id:
            raise InvalidMonitoringResult("The scout must belong to the check's project.")
        if run_note != build_monitoring_run_note(binding, check):
            raise InvalidMonitoringResult("The scout brief does not match the authored check.")
        run = bound_monitoring_scout_run(canonical_team_id, run_note)
        if run is None:
            if failed:
                _save_scout_evaluation(binding.incomplete_evaluation(max(timezone.now(), binding.window_end)))
            return
        if (run_id is not None and str(run.id) != run_id) or run.skill_name != skill_name:
            raise InvalidMonitoringResult("The result must come from the dispatched scout run.")
        # A recovered live run can still submit; finished scout execution needs no TaskRun status update.
        if (
            not execution_finished
            and run.task_run.status in {"queued", "in_progress"}
            and (timezone.now() - run.created_at).total_seconds() < STALE_RUN_CUTOFF_S
        ):
            return
        _save_scout_evaluation(binding.incomplete_evaluation(max(timezone.now(), binding.window_end)))
    except (InvalidMonitoringResult, MonitoringResultConflict, SignalReportCheck.DoesNotExist):
        return


@frozen
class FinalAgentSummary:
    dispatched: int = 0
    deferred: int = 0


def run_due_final_agents(*, now: datetime, deadline: float, limit: int) -> FinalAgentSummary:
    from posthog.temporal.common.client import (
        sync_connect,  # noqa: PLC0415 -- keeps the Temporal client off the API import path
    )

    from products.signals.backend.temporal.agentic.scout_scheduler import (
        start_monitoring_signals_scout_run,  # noqa: PLC0415 -- breaks the scheduler import cycle
    )

    dispatched = deferred = 0
    for due in collect_due_final_checks(now, kind=SignalReportCheck.Kind.AGENT, limit=limit, deadline=deadline):
        if time.monotonic() >= deadline:
            break
        SignalReportCheck.objects.for_team(due.member.check.team_id).filter(
            id=due.member.check.id,
            report__monitoring_started_at=due.member.window_start,
            report__status=SignalReport.Status.MONITORING,
        ).update(monitoring_dispatch_after=now + MONITORING_AGENT_DISPATCH_BACKOFF)
        try:
            binding = monitoring_scout_check(due)
            check = ready_monitoring_scout_check(binding)
            canonical_team_id = check.report.team.parent_team_id or check.team_id
            config = parse_check_config(check.kind, check.config)
            assert isinstance(config, AgentCheckConfig)
            skill_name = resolve_check_skill_name(config, canonical_team_id)
            note = build_monitoring_run_note(binding, check)
            previous = bound_monitoring_scout_run(canonical_team_id, note)
            if previous is None and _refuse_dispatch(skill_name, canonical_team_id) is not None:
                deferred += 1
                continue
            start_monitoring_signals_scout_run(
                sync_connect(),
                team_id=canonical_team_id,
                skill_name=previous.skill_name if previous is not None else skill_name,
                run_note=note,
                binding=binding,
            )
            dispatched += 1
        except (InvalidMonitoringResult, WorkflowAlreadyStartedError):
            deferred += 1
        except Exception:
            logger.exception("signals.monitoring.agent_dispatch_failed", check_id=str(due.member.check.id))
            deferred += 1
    return FinalAgentSummary(dispatched=dispatched, deferred=deferred)
