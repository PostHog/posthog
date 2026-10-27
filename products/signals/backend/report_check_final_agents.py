from __future__ import annotations

import json
import time
from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Literal
from uuid import UUID

from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

import structlog
from pydantic import BaseModel, ConfigDict, Field, model_validator

from posthog.models import Team, User
from posthog.user_permissions import user_can_access_team

from products.signals.backend.facade.metric_access import metric_context_reader
from products.signals.backend.models import (
    SignalReport,
    SignalReportAgentEvaluation,
    SignalReportArtefact,
    SignalReportCheck,
    SignalReportMonitoringResult,
)
from products.signals.backend.report_check_agent import AGENT_CHECK_RESULT_WINDOW
from products.signals.backend.report_check_execution import CHECK_ERROR_RETRY_AFTER, resolve_check_query
from products.signals.backend.report_check_final_candidates import due_final_checks
from products.signals.backend.report_checks import (
    MAX_CONSECUTIVE_CHECK_ERRORS,
    AgentCheckConfig,
    MetricThresholdConfig,
    parse_check_config,
)
from products.signals.backend.report_content_gates import team_report_monitoring_enabled
from products.signals.backend.report_monitoring_attempts import check_definition_version, current_monitoring_attempt
from products.signals.backend.report_monitoring_results import (
    MONITORING_RESULT_ELIGIBLE_STATUSES,
    InvalidMonitoringResult,
    MonitoringEvaluation,
    MonitoringResultConflict,
    save_monitoring_result,
)
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.cancellation import cancel_task_run

logger = structlog.get_logger(__name__)
MAX_AGENT_DISPATCHES_PER_TICK = 50
MAX_AGENT_RECOVERIES_PER_TICK = 50
AGENT_SWEEP_SECONDS = 30
AGENT_RECOVERY_SECONDS = 10
AGENT_DRAIN_RETRY_AFTER = timedelta(minutes=1)
AGENT_DISPATCH_RETRY_AFTER = timedelta(minutes=1)


class AgentMonitoringResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    evidence_status: Literal["sufficient", "insufficient", "unsupported", "errored"]
    evidence_reason: str = Field(min_length=1, max_length=4000)
    expectation_matches: bool | None = Field(strict=True)
    explanation: str = Field(min_length=1, max_length=8000)
    evidence_refs: tuple[str, ...] = Field(default=(), max_length=50)

    @model_validator(mode="after")
    def validate_evidence(self) -> AgentMonitoringResult:
        if self.evidence_status == "sufficient" and self.expectation_matches is None:
            raise ValueError("Sufficient evidence requires an expectation verdict.")
        if self.evidence_status in {"unsupported", "errored"} and self.expectation_matches is not None:
            raise ValueError("An unsupported or errored evaluation cannot establish an expectation verdict.")
        if any(not ref.strip() or len(ref) > 2000 for ref in self.evidence_refs):
            raise ValueError("Evidence references must contain between 1 and 2000 characters.")
        return self


def _current_check(report: SignalReport, check_id: UUID, definition_version: str) -> SignalReportCheck:
    attempt = current_monitoring_attempt(report)
    if (
        report.status != SignalReport.Status.MONITORING
        or not team_report_monitoring_enabled(report.team_id)
        or attempt is None
        or attempt.check_versions.get(str(check_id)) != definition_version
    ):
        raise InvalidMonitoringResult("The Monitoring attempt is no longer eligible.")
    check = (
        SignalReportCheck.objects.for_team(report.team_id)
        .select_for_update()
        .filter(id=check_id, report_id=report.id)
        .first()
    )
    if (
        check is None
        or check.kind != SignalReportCheck.Kind.AGENT
        or check.status not in MONITORING_RESULT_ELIGIBLE_STATUSES
        or check_definition_version(check) != definition_version
        or check.soak_minutes is None
    ):
        raise InvalidMonitoringResult("The authored check no longer matches the attempt.")
    if timezone.now() < attempt.monitoring_started_at + timedelta(minutes=check.soak_minutes):
        raise InvalidMonitoringResult("The authored check's soak has not finished.")
    if not isinstance(parse_check_config(check.kind, check.config), AgentCheckConfig):
        raise InvalidMonitoringResult("The authored check needs an investigation configuration.")
    return check


def _queries_for_attempt(
    report: SignalReport, *, artefacts: Iterable[Mapping[str, object]] | None = None
) -> list[dict[str, object]]:
    attempt = current_monitoring_attempt(report)
    if attempt is None:
        raise InvalidMonitoringResult("The Monitoring attempt is no longer available.")
    queries: list[dict[str, object]] = []
    for check in SignalReportCheck.objects.for_team(report.team_id).filter(
        report_id=report.id, id__in=attempt.check_versions, kind=SignalReportCheck.Kind.METRIC_THRESHOLD
    ):
        if check_definition_version(check) != attempt.check_versions[str(check.id)]:
            raise InvalidMonitoringResult("The attempt's analytics context changed and cannot be safely reused.")
        config = parse_check_config(check.kind, check.config)
        if not isinstance(config, MetricThresholdConfig):
            raise InvalidMonitoringResult("The attempt's analytics context has no readable query definition.")
        queries.append(resolve_check_query(config, report))
    if artefacts is None:
        artefacts = SignalReportArtefact.objects.filter(
            team_id=report.team_id, report_id=report.id, type="impact_measurement_plan"
        ).values("type", "content")
    for artefact in artefacts:
        if artefact["type"] != "impact_measurement_plan":
            continue
        try:
            content = artefact["content"]
            plan = json.loads(content) if isinstance(content, str) else None
        except ValueError as error:
            raise InvalidMonitoringResult("The report's analytics attachment is unreadable.") from error
        if not isinstance(plan, dict) or not isinstance(plan.get("query"), dict):
            raise InvalidMonitoringResult("The report's analytics attachment has no readable query.")
        queries.append(plan["query"])
        if plan.get("eligibility_query") is not None:
            if not isinstance(plan["eligibility_query"], dict):
                raise InvalidMonitoringResult("The report's eligibility query is unreadable.")
            queries.append(plan["eligibility_query"])
    return queries


def _assert_user_access(report: SignalReport, user_id: int, *, queries: list[dict[str, object]] | None = None) -> None:
    team = Team.objects.get(id=report.team_id)
    user = User.objects.filter(id=user_id, is_active=True).first()
    if user is None or not user_can_access_team(user, team):
        raise InvalidMonitoringResult("The evaluation user no longer has access to the report environment.")
    if not metric_context_reader(team_id=report.team_id, user_id=user_id)(
        _queries_for_attempt(report) if queries is None else queries
    ):
        raise InvalidMonitoringResult("The evaluation user cannot read the attempt's analytics context.")


def claim_agent_evaluation(*, team_id: int, report_id: UUID, check_id: UUID) -> SignalReportAgentEvaluation | None:
    with transaction.atomic():
        report = SignalReport.objects.select_for_update(no_key=True).get(team_id=team_id, id=report_id)
        attempt = current_monitoring_attempt(report)
        if attempt is None or (version := attempt.check_versions.get(str(check_id))) is None:
            return None
        check = _current_check(report, check_id, version)
        assert check.soak_minutes is not None
        if (
            SignalReportMonitoringResult.objects.for_team(team_id)
            .filter(attempt_id=attempt.id, report_check_id=check_id)
            .exclude(evidence_status="errored")
            .exists()
        ):
            return None
        evaluations = SignalReportAgentEvaluation.objects.for_team(team_id).filter(
            attempt_id=attempt.id, report_check_id=check_id
        )
        previous = evaluations.order_by("-sequence").first()
        if previous is not None:
            if previous.state in {previous.State.PENDING, previous.State.RUNNING}:
                return previous
            if previous.state == previous.State.SUBMITTED:
                return None
            if (
                evaluations.filter(state=SignalReportAgentEvaluation.State.ERRORED).count()
                >= MAX_CONSECUTIVE_CHECK_ERRORS
            ):
                return None
            if previous.state == previous.State.ERRORED and (
                previous.completed_at is None or timezone.now() < previous.completed_at + CHECK_ERROR_RETRY_AFTER
            ):
                return None
        # A paused period may still have a sandbox draining; never overlap it after restore.
        for run_id in evaluations.filter(task_run_id__isnull=False).values_list("task_run_id", flat=True):
            assert run_id is not None
            run = tasks_facade.get_task_run(run_id, team_id=team_id)
            if run is not None and not run.is_terminal:
                return None
        from products.signals.backend.report_check_agent_runner import (
            agent_dispatch_refused,  # noqa: PLC0415 - keeps sandbox imports off result acceptance
        )

        if agent_dispatch_refused(check):
            return None
        return evaluations.create(
            team_id=team_id,
            report_id=report.id,
            attempt_id=attempt.id,
            report_check_id=check.id,
            definition_version=version,
            window_start=attempt.monitoring_started_at,
            window_end=attempt.monitoring_started_at + timedelta(minutes=check.soak_minutes),
            sequence=previous.sequence + 1 if previous else 1,
        )


def _locked_evaluation(team_id: int, evaluation_id: UUID) -> SignalReportAgentEvaluation:
    reference = SignalReportAgentEvaluation.objects.for_team(team_id).get(id=evaluation_id)
    report = SignalReport.objects.select_for_update(no_key=True).get(team_id=team_id, id=reference.report_id)
    _current_check(report, reference.report_check_id, reference.definition_version)
    attempt = current_monitoring_attempt(report)
    if attempt is None or attempt.id != reference.attempt_id:
        raise InvalidMonitoringResult("The evaluation belongs to an earlier implementation attempt.")
    return SignalReportAgentEvaluation.objects.for_team(team_id).select_for_update().get(id=evaluation_id)


def bind_agent_run(*, team_id: int, evaluation_id: UUID, task_run_id: UUID, user_id: int) -> None:
    with transaction.atomic():
        evaluation = _locked_evaluation(team_id, evaluation_id)
        if (
            evaluation.task_run_id == task_run_id
            and evaluation.user_id == user_id
            and evaluation.state == evaluation.State.RUNNING
        ):
            return
        if (
            evaluation.state != evaluation.State.PENDING
            or evaluation.task_run_id is not None
            or evaluation.created_at + AGENT_CHECK_RESULT_WINDOW <= timezone.now()
        ):
            raise InvalidMonitoringResult("This evaluation already has a run or was stopped.")
        _assert_user_access(evaluation.report, user_id)
        from products.signals.backend.report_check_agent_runner import (
            agent_dispatch_refused,  # noqa: PLC0415 - avoids the runner import cycle
        )

        if agent_dispatch_refused(evaluation.report_check, evaluation_id=evaluation.id):
            raise InvalidMonitoringResult("Monitoring verification is paused by its execution controls.")
        run = tasks_facade.get_task_run(task_run_id, team_id=team_id)
        if run is None or run.is_terminal or run.created_by_id != user_id:
            raise InvalidMonitoringResult("The run does not belong to the report environment.")
        evaluation.task_id = run.task_id
        evaluation.task_run_id = task_run_id
        evaluation.bound_at = timezone.now()
        evaluation.user_id = user_id
        evaluation.state = evaluation.State.RUNNING
        evaluation.save(update_fields=["task_id", "task_run_id", "bound_at", "user_id", "state"])


def stage_agent_result(*, team_id: int, evaluation_id: UUID, task_run_id: UUID, result: AgentMonitoringResult) -> None:
    with transaction.atomic():
        previous = SignalReportAgentEvaluation.objects.for_team(team_id).get(id=evaluation_id)
        if previous.task_run_id != task_run_id:
            raise InvalidMonitoringResult("Only the bound run can submit this evaluation.")
        if previous.output is not None:
            if previous.output != result.model_dump(mode="json"):
                raise MonitoringResultConflict("The run already submitted a different evaluation.")
            return
        evaluation = _locked_evaluation(team_id, evaluation_id)
        if evaluation.task_run_id != task_run_id or evaluation.state not in {
            evaluation.State.RUNNING,
            evaluation.State.SUBMITTED,
            evaluation.State.ERRORED,
        }:
            raise InvalidMonitoringResult("Only the bound run can submit this evaluation.")
        if evaluation.user_id is None:
            raise InvalidMonitoringResult("The evaluation has no authorized user.")
        run = tasks_facade.get_task_run(task_run_id, team_id=team_id)
        if (
            run is None
            or run.status in {tasks_facade.TaskRunStatus.CANCELLED, tasks_facade.TaskRunStatus.FAILED}
            or evaluation.created_at + AGENT_CHECK_RESULT_WINDOW <= timezone.now()
        ):
            raise InvalidMonitoringResult("The bound verification run stopped or exceeded its result window.")
        _assert_user_access(evaluation.report, evaluation.user_id)
        output = result.model_dump(mode="json")
        if evaluation.output is not None:
            if evaluation.output != output:
                raise MonitoringResultConflict("The run already submitted a different evaluation.")
            return
        evaluation.output = output
        evaluation.completed_at = timezone.now()
        evaluation.save(update_fields=["output", "completed_at"])


def deliver_agent_result(*, team_id: int, evaluation_id: UUID) -> None:
    with transaction.atomic():
        previous = SignalReportAgentEvaluation.objects.for_team(team_id).get(id=evaluation_id)
        if previous.state in {previous.State.SUBMITTED, previous.State.ERRORED}:
            return
        evaluation = _locked_evaluation(team_id, evaluation_id)
        if evaluation.output is None or evaluation.completed_at is None:
            return
        if evaluation.state in {evaluation.State.SUBMITTED, evaluation.State.ERRORED}:
            return
        if evaluation.state == evaluation.State.ABANDONED:
            raise InvalidMonitoringResult("The evaluation was stopped.")
        result = AgentMonitoringResult.model_validate(evaluation.output)
        if evaluation.user_id is not None:
            _assert_user_access(evaluation.report, evaluation.user_id)
        if evaluation.window_start == evaluation.window_end and result.evidence_status == "sufficient":
            result = result.model_copy(
                update={
                    "evidence_status": "insufficient",
                    "expectation_matches": None,
                    "evidence_reason": "The fixed verification window is empty.",
                }
            )
        save_monitoring_result(
            MonitoringEvaluation(
                team_id=team_id,
                report_id=evaluation.report_id,
                attempt_id=evaluation.attempt_id,
                check_id=evaluation.report_check_id,
                submission_id=evaluation.id,
                definition_version=evaluation.definition_version,
                window_start=evaluation.window_start,
                window_end=evaluation.window_end,
                evaluated_at=evaluation.completed_at,
                evidence_status=result.evidence_status,
                evidence_reason=result.evidence_reason,
                expectation_matches=result.expectation_matches,
                explanation=result.explanation,
                evidence_refs=(*result.evidence_refs, f"task-run:{evaluation.task_run_id}")
                if evaluation.task_run_id
                else result.evidence_refs,
            )
        )
        evaluation.state = (
            evaluation.State.ERRORED if result.evidence_status == "errored" else evaluation.State.SUBMITTED
        )
        evaluation.save(update_fields=["state"])


def fail_agent_evaluation(*, team_id: int, evaluation_id: UUID) -> None:
    with transaction.atomic():
        evaluation = _locked_evaluation(team_id, evaluation_id)
        if evaluation.state not in {evaluation.State.PENDING, evaluation.State.RUNNING}:
            return
        if evaluation.output is None:
            evaluation.output = AgentMonitoringResult(
                evidence_status="errored",
                evidence_reason="The verification run did not return a usable result.",
                expectation_matches=None,
                explanation="The authored check could not be evaluated because its run failed or did not finish.",
            ).model_dump(mode="json")
            evaluation.completed_at = timezone.now()
            evaluation.save(update_fields=["output", "completed_at"])
    deliver_agent_result(team_id=team_id, evaluation_id=evaluation_id)


def run_due_agent_evaluations(*, deadline: float | None = None) -> int:
    # Keep Temporal imports off the API and model startup paths.
    from posthog.temporal.common.client import sync_connect  # noqa: PLC0415

    from products.signals.backend.temporal.agentic.monitoring_agents import start_monitoring_agent  # noqa: PLC0415

    deadline = (
        min(deadline, time.monotonic() + AGENT_SWEEP_SECONDS)
        if deadline is not None
        else time.monotonic() + AGENT_SWEEP_SECONDS
    )
    recovery_deadline = min(deadline, time.monotonic() + AGENT_RECOVERY_SECONDS)
    started = 0
    recovered = 0
    now = timezone.now()
    if time.monotonic() >= deadline:
        return 0
    for evaluation in (
        SignalReportAgentEvaluation.objects.unscoped()
        .filter(
            Q(state__in=["abandoned", "errored"]) | Q(state="running", created_at__lte=now - AGENT_CHECK_RESULT_WINDOW),
            task_run_id__isnull=False,
            drained_at__isnull=True,
            state__in=["abandoned", "errored", "running"],
        )
        .filter(Q(last_drain_attempt_at__isnull=True) | Q(last_drain_attempt_at__lte=now - AGENT_DRAIN_RETRY_AFTER))
        .order_by(F("last_drain_attempt_at").asc(nulls_first=True), "created_at", "id")[:MAX_AGENT_RECOVERIES_PER_TICK]
    ):
        if time.monotonic() >= recovery_deadline:
            break
        SignalReportAgentEvaluation.objects.for_team(evaluation.team_id).filter(id=evaluation.id).update(
            last_drain_attempt_at=now
        )
        try:
            _stop_bound_run(evaluation)
        except Exception:
            logger.exception(
                "signals.monitoring_agent.cancel_failed", team_id=evaluation.team_id, evaluation_id=str(evaluation.id)
            )
    pending = (
        SignalReportAgentEvaluation.objects.unscoped()
        .filter(
            Q(state="pending")
            | Q(state="running", output__isnull=False)
            | Q(state="running", created_at__lte=now - AGENT_CHECK_RESULT_WINDOW),
            report__status=SignalReport.Status.MONITORING,
            attempt__monitoring_started_at=F("report__monitoring_started_at"),
            state__in=["pending", "running"],
        )
        .filter(Q(last_dispatch_at__isnull=True) | Q(last_dispatch_at__lte=now - AGENT_DISPATCH_RETRY_AFTER))
        .order_by(F("last_dispatch_at").asc(nulls_first=True), "created_at", "id")[:MAX_AGENT_RECOVERIES_PER_TICK]
    )
    for evaluation in pending:
        if time.monotonic() >= recovery_deadline:
            break
        SignalReportAgentEvaluation.objects.for_team(evaluation.team_id).filter(id=evaluation.id).update(
            last_dispatch_at=now
        )
        try:
            if not team_report_monitoring_enabled(evaluation.team_id):
                continue
            if evaluation.output is not None:
                deliver_agent_result(team_id=evaluation.team_id, evaluation_id=evaluation.id)
                recovered += 1
            elif evaluation.created_at + AGENT_CHECK_RESULT_WINDOW <= now:
                _stop_bound_run(evaluation)
                fail_agent_evaluation(team_id=evaluation.team_id, evaluation_id=evaluation.id)
                recovered += 1
            elif start_monitoring_agent(sync_connect(), team_id=evaluation.team_id, evaluation_id=str(evaluation.id)):
                started += 1
        except (InvalidMonitoringResult, MonitoringResultConflict, ValueError):
            continue
        except Exception:
            logger.exception(
                "signals.monitoring_agent.recovery_failed", team_id=evaluation.team_id, evaluation_id=str(evaluation.id)
            )

    if started >= MAX_AGENT_DISPATCHES_PER_TICK or time.monotonic() >= deadline:
        return started + recovered
    candidates = due_final_checks(SignalReportCheck.Kind.AGENT, now)
    evaluations = SignalReportAgentEvaluation.objects.unscoped().filter(
        team_id=OuterRef("team_id"), attempt_id=OuterRef("_attempt_id"), report_check_id=OuterRef("id")
    )
    results = SignalReportMonitoringResult.objects.unscoped().filter(
        team_id=OuterRef("team_id"), attempt_id=OuterRef("_attempt_id"), report_check_id=OuterRef("id")
    )
    errors = evaluations.filter(state="errored")
    candidates = (
        candidates.annotate(
            _settled=Exists(results.exclude(evidence_status="errored")),
            _inflight=Exists(evaluations.filter(state__in=["pending", "running", "submitted"])),
            _error_count=Coalesce(
                Subquery(errors.order_by().values("report_check_id").annotate(total=Count("id")).values("total")[:1]),
                Value(0),
            ),
            _last_error_at=Subquery(errors.order_by("-sequence").values("completed_at")[:1]),
        )
        .filter(_settled=False, _inflight=False, _error_count__lt=MAX_CONSECUTIVE_CHECK_ERRORS)
        .filter(Q(_error_count=0) | Q(_last_error_at__lte=now - CHECK_ERROR_RETRY_AFTER))
        .order_by("_window_end", "id")
    )
    for check in candidates.iterator(chunk_size=MAX_AGENT_DISPATCHES_PER_TICK):
        if started >= MAX_AGENT_DISPATCHES_PER_TICK or time.monotonic() >= deadline:
            break
        if not team_report_monitoring_enabled(check.team_id):
            continue
        try:
            due_evaluation = claim_agent_evaluation(team_id=check.team_id, report_id=check.report_id, check_id=check.id)
            if due_evaluation is None:
                continue
            SignalReportAgentEvaluation.objects.for_team(check.team_id).filter(id=due_evaluation.id).update(
                last_dispatch_at=now
            )
            if start_monitoring_agent(sync_connect(), team_id=check.team_id, evaluation_id=str(due_evaluation.id)):
                started += 1
        except (InvalidMonitoringResult, MonitoringResultConflict, ValueError):
            continue
        except Exception:
            logger.exception("signals.monitoring_agent.dispatch_failed", team_id=check.team_id, check_id=str(check.id))
    return started + recovered


def monitoring_agent_start_refusal(task_id: str, team_id: int, user_id: int | None) -> str | None:
    evaluation = SignalReportAgentEvaluation.objects.for_team(team_id).filter(task_id=task_id).first()
    if evaluation is None:
        return None
    try:
        with transaction.atomic():
            evaluation = _locked_evaluation(team_id, evaluation.id)
            if (
                evaluation.state != evaluation.State.RUNNING
                or evaluation.user_id != user_id
                or user_id is None
                or evaluation.task_run_id is None
            ):
                return "Monitoring verification is no longer authorized."
            if evaluation.created_at + AGENT_CHECK_RESULT_WINDOW <= timezone.now():
                return "Monitoring verification exceeded its execution window."
            _assert_user_access(evaluation.report, user_id)
            run = tasks_facade.get_task_run(evaluation.task_run_id, team_id=team_id)
            if run is None or run.is_terminal:
                return "This verification run already ended."
            from products.signals.backend.report_check_agent_runner import (
                agent_dispatch_refused,  # noqa: PLC0415 - avoids the runner import cycle
            )

            if agent_dispatch_refused(evaluation.report_check, evaluation_id=evaluation.id):
                return "Monitoring verification is paused by its execution controls."
    except (InvalidMonitoringResult, ValueError):
        return "Monitoring verification is no longer eligible."
    return None


def _stop_bound_run(evaluation: SignalReportAgentEvaluation) -> None:
    if evaluation.task_run_id is None:
        return
    run = tasks_facade.get_task_run(evaluation.task_run_id, team_id=evaluation.team_id)
    if run is None or run.is_terminal:
        SignalReportAgentEvaluation.objects.for_team(evaluation.team_id).filter(id=evaluation.id).update(
            drained_at=timezone.now()
        )
        return
    if run is not None and not run.is_terminal:
        cancel_task_run(
            run.id,
            run.task_id,
            evaluation.team_id,
            reason="Monitoring verification stopped.",
            source="monitoring_check",
        )
