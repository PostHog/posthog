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
from pydantic import BaseModel, ConfigDict, Field, StrictBool, TypeAdapter, field_validator
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
    MONITORING_RESULT_ELIGIBLE_STATUSES,
    InvalidMonitoringResult,
    MonitoringEvaluation,
    MonitoringResultConflict,
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


def ready_monitoring_scout_check(binding: MonitoringScoutCheck) -> SignalReportCheck:
    check = (
        SignalReportCheck.objects.for_team(binding.team_id)
        .select_related("report", "report__team")
        .get(id=binding.check_id, report_id=binding.report_id)
    )
    report = check.report
    attempt = current_monitoring_attempt(report)
    if (
        report.status != SignalReport.Status.MONITORING
        or not team_report_monitoring_enabled(binding.team_id)
        or attempt is None
        or attempt.id != binding.attempt_id
        or attempt.monitoring_started_at != binding.window_start
        or attempt.check_versions.get(str(check.id)) != binding.definition_version
        or check_definition_version(check) != binding.definition_version
        or check.kind != SignalReportCheck.Kind.AGENT
        or check.status not in MONITORING_RESULT_ELIGIBLE_STATUSES
        or check.soak_minutes is None
        or binding.window_end != binding.window_start + timedelta(minutes=check.soak_minutes)
        or binding.window_end > timezone.now()
    ):
        raise InvalidMonitoringResult("The authored check is no longer eligible for this Monitoring evaluation.")
    if (
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


def monitoring_environment_for_task_run(*, team_id: int, task_id: UUID, run_id: UUID | str) -> int | None:
    try:
        task_run_id = UUID(str(run_id))
    except ValueError:
        return None
    run = (
        SignalScoutRun.objects.for_team(team_id)
        .filter(task_run_id=task_run_id, task_run__task_id=task_id, metadata__triggered_by=TRIGGERED_BY_MONITORING)
        .first()
    )
    if run is None or not isinstance(run.metadata, dict):
        return None
    note = run.metadata.get("run_note")
    if not isinstance(note, str):
        return None
    try:
        data = json.loads(note)
        binding = TypeAdapter(MonitoringScoutCheck).validate_python(
            {**data, "window_start_iso": data["window_start"], "window_end_iso": data["window_end"]}
        )
        check = ready_monitoring_scout_check(binding)
        if (check.report.team.parent_team_id or check.team_id) != team_id:
            return None
        if note != build_monitoring_run_note(binding, check):
            return None
        return binding.team_id if binding.team_id != team_id else None
    except (KeyError, TypeError, ValueError, SignalReportCheck.DoesNotExist):
        return None


def _save_scout_evaluation(evaluation: MonitoringEvaluation) -> None:
    with transaction.atomic():
        save_monitoring_result(evaluation)
        SignalReportCheck.objects.for_team(evaluation.team_id).filter(id=evaluation.check_id).update(
            monitoring_dispatch_after=None
        )


def save_monitoring_scout_result(
    binding: MonitoringScoutCheck,
    *,
    canonical_team_id: int,
    skill_name: str,
    run_note: str,
    run_id: str | None,
    failed: bool = False,
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
        if (
            run.task_run.status in {"queued", "in_progress"}
            and (timezone.now() - run.created_at).total_seconds() < STALE_RUN_CUTOFF_S
        ):
            return
        evaluated_at = max(run.updated_at or run.created_at, binding.window_end)
        evaluation = binding.incomplete_evaluation(evaluated_at)
        try:
            if run.task_run.status != "completed":
                raise ValueError("The scout did not complete.")
            payload = MonitoringScoutResult.model_validate_json(run.summary)
            evaluation = replace(
                evaluation,
                evidence_status=payload.evidence_status,
                evidence_reason=payload.evidence_reason,
                expectation_matches=payload.expectation_matches,
                explanation=payload.explanation,
                evidence_refs=tuple(payload.evidence_refs),
            )
        except ValueError:
            pass
        _save_scout_evaluation(evaluation)
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
