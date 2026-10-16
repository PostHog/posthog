from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING
from uuid import UUID

from django.conf import settings

from posthog.dataclasses import frozen

from products.signals.backend.trial_billing import paid_trial_continuation_authorized
from products.signals.backend.trial_models import SignalTrialOperation
from products.signals.backend.trial_policy import OperationAdmission, TrialFlagDecision, TrialPolicy, TrialRefused
from products.signals.backend.trial_reports import active_report_pass, report_trial_context, task_trial_context

if TYPE_CHECKING:
    from posthog.models import Team


SELF_DRIVING_ORIGINS = frozenset({"signal_report", "signals_scout", "scout_suggestions", "signals_chat"})


@frozen
class TaskTrialAdmission:
    team: "Team"
    decision: TrialFlagDecision
    paid_authorized: bool
    report_pass_id: UUID | None = None

    def bind(
        self, *, run_id: UUID, origin: str, stage: str, report_id: UUID | None, model: str, runtime: str
    ) -> dict[str, str | int]:
        resolved_stage = (
            SignalTrialOperation.Stage.SCOUT
            if origin == "signals_scout"
            else SignalTrialOperation.Stage(stage)
            if stage in SignalTrialOperation.Stage.values
            else SignalTrialOperation.Stage.GENERATION
        )
        policy = TrialPolicy(self.team)
        operation = policy.admit(
            OperationAdmission(
                operation_key=f"task:{run_id}",
                stage=resolved_stage,
                report_id=report_id,
                report_pass_id=self.report_pass_id,
                model=model,
                runtime=runtime,
            ),
            paid_authorized=self.paid_authorized,
            decision=self.decision,
        )
        operation.task_run_id = run_id
        if (
            operation.funding == SignalTrialOperation.Funding.TRIAL
            and resolved_stage != SignalTrialOperation.Stage.IMPLEMENTATION
        ):
            operation.model = settings.SELF_DRIVING_TRIAL_AGENT_MODEL
            operation.runtime = settings.SELF_DRIVING_TRIAL_AGENT_RUNTIME
        operation.save(update_fields=["task_run_id", "model", "runtime"])
        return {
            "operation_id": str(operation.id),
            "funding": operation.funding,
            "grant_id": str(operation.grant_id) if operation.grant_id else "",
            "policy_version": operation.policy_version,
            "model": operation.model,
            "runtime": operation.runtime,
        }


@frozen
class PreparedTaskTrial:
    team_id: int
    origin: str
    report_id: str | None
    admission: TaskTrialAdmission | None


_prepared_task_trial: ContextVar[PreparedTaskTrial | None] = ContextVar("prepared_task_trial", default=None)


@contextmanager
def task_trial_admission(*, team: "Team", origin: str, report_id: UUID | str | None = None) -> Iterator[None]:
    admission = prepare_task_trial(team=team, origin=origin, report_id=UUID(str(report_id)) if report_id else None)
    token = _prepared_task_trial.set(
        PreparedTaskTrial(
            team_id=team.id, origin=origin, report_id=str(report_id) if report_id else None, admission=admission
        )
    )
    try:
        yield
    finally:
        _prepared_task_trial.reset(token)


def prepare_task_trial(*, team: "Team", origin: str, report_id: UUID | None = None) -> TaskTrialAdmission | None:
    if origin not in SELF_DRIVING_ORIGINS:
        return None
    prepared = _prepared_task_trial.get()
    if (
        prepared is not None
        and prepared.team_id == team.id
        and prepared.origin == origin
        and prepared.report_id == (str(report_id) if report_id else None)
    ):
        return prepared.admission
    policy = TrialPolicy(team)
    parent = active_report_pass(team, report_id) if report_id else None
    report_context = report_trial_context.get()
    if report_context and report_context[0] == team.id:
        parent = active_report_pass(team, report_context[1])
        if parent is None:
            return None
    context = task_trial_context.get()
    if context and context[0] == team.id:
        parent = (
            SignalTrialOperation.objects.for_team(policy.team_id, canonical=True).filter(task_run_id=context[1]).first()
        )
        if parent is None:
            return None
    if parent is not None:
        return TaskTrialAdmission(
            team=team,
            decision=TrialFlagDecision(enabled=True, confirmed=True),
            paid_authorized=parent.funding == SignalTrialOperation.Funding.PAID,
            report_pass_id=parent.id,
        )
    decision = policy.flag_decision()
    if decision.enabled is not True:
        return None
    grant = policy.grant()
    if grant is None and not settings.SELF_DRIVING_TRIAL_V2_BILLING_READY:
        return None
    paid_authorized = False
    if grant is None or grant.exhausted_at is not None:
        try:
            paid_authorized = paid_trial_continuation_authorized(team)
        except Exception as error:
            raise TrialRefused("billing_unavailable") from error
    return TaskTrialAdmission(team=team, decision=decision, paid_authorized=paid_authorized)


def start_task_trial(*, team: "Team", run_id: UUID) -> bool:
    from products.signals.backend.models import (
        SignalScoutRun,  # noqa: PLC0415 -- facade imported during Task model loading
    )

    policy = TrialPolicy(team)
    operation = SignalTrialOperation.objects.for_team(policy.team_id, canonical=True).filter(task_run_id=run_id).first()
    if operation is None:
        return False
    if operation.grant_id and operation.stage == SignalTrialOperation.Stage.SCOUT:
        scout = (
            SignalScoutRun.objects.for_team(policy.team_id, canonical=True)
            .select_related("scout_config")
            .filter(task_run_id=run_id)
            .first()
        )
        if scout is None or not scout.scout_config or not scout.scout_config.enabled:
            raise TrialRefused("scout_disabled")
    operation = policy.start(operation.id)
    if operation.grant_id is None:
        return False
    return True


def check_trial_run_quota(*, team: "Team", run_id: UUID) -> str | None:
    from products.signals.backend.trial_tasks import (
        reconcile_trial_operation,  # noqa: PLC0415 -- cancellation imports Tasks workflows
    )

    team_id = team.parent_team_id or team.id
    operation = SignalTrialOperation.objects.for_team(team_id, canonical=True).filter(task_run_id=run_id).first()
    if operation is None or operation.grant_id is None:
        return None
    reconcile_trial_operation(team_id, str(operation.id))
    operation.refresh_from_db()
    return "cancelled" if operation.cancelled_at else "proceed"
