from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from functools import wraps
from typing import Any, Protocol, TypeVar
from uuid import UUID

from django.conf import settings

from posthog.models import Team

from products.signals.backend.trial.billing import paid_trial_continuation_authorized
from products.signals.backend.trial.models import SignalTrialOperation, SignalTrialReportReservation
from products.signals.backend.trial.policy import OperationAdmission, TrialPolicy

report_trial_context: ContextVar[tuple[int, str] | None] = ContextVar("report_trial_context", default=None)
task_trial_context: ContextVar[tuple[int, UUID] | None] = ContextVar("task_trial_context", default=None)


class ReportInput(Protocol):
    @property
    def team_id(self) -> int: ...

    @property
    def report_id(self) -> str: ...


Input = TypeVar("Input", bound=ReportInput)
Result = TypeVar("Result")


def trial_report_activity(
    function: Callable[[Input], Coroutine[Any, Any, Result]],
) -> Callable[[Input], Coroutine[Any, Any, Result]]:
    @wraps(function)
    async def wrapped(input: Input) -> Result:
        token = report_trial_context.set((input.team_id, input.report_id))
        try:
            return await function(input)
        finally:
            report_trial_context.reset(token)

    return wrapped


def active_report_pass(team: Team, report_id: UUID | str) -> SignalTrialOperation | None:
    return (
        SignalTrialOperation.objects.for_team(team.parent_team_id or team.id, canonical=True)
        .filter(report_id=report_id, stage=SignalTrialOperation.Stage.REPORT_PASS, finished_at__isnull=True)
        .order_by("-admitted_at")
        .first()
    )


def requires_trial_accounting(team_id: int) -> bool:
    team = Team.objects.get(id=team_id)
    task_context = task_trial_context.get()
    if task_context and task_context[0] == team_id:
        parent = (
            SignalTrialOperation.objects.for_team(team.parent_team_id or team.id, canonical=True)
            .filter(task_run_id=task_context[1])
            .first()
        )
        return parent is not None and parent.funding == SignalTrialOperation.Funding.TRIAL
    context = report_trial_context.get()
    if context and context[0] == team_id:
        parent = active_report_pass(team, context[1])
        return parent is not None and parent.funding == SignalTrialOperation.Funding.TRIAL
    policy = TrialPolicy(team)
    grant = policy.grant()
    if policy.flag_decision().enabled is not True:
        return False
    if grant is not None and grant.exhausted_at is None:
        return True
    if grant is not None or settings.SELF_DRIVING_TRIAL_V2_BILLING_READY:
        # Refused work must reach accounted admission, even when a System One experiment is enabled.
        return not paid_trial_continuation_authorized(team)
    return False


def implementation_requires_trial_opt_in(team_id: int, report_id: str) -> bool:
    return SignalTrialReportReservation.objects.for_team(team_id).filter(
        report_id=report_id, status=SignalTrialReportReservation.Status.CONSUMED
    ).exists() or requires_trial_accounting(team_id)


def prepare_report_pass(*, team: Team, report_id: str, operation_key: str) -> None:
    from products.signals.backend.facade.trial import (
        prepare_task_trial,  # noqa: PLC0415 -- facade imports report-pass lookup
    )

    admission = prepare_task_trial(team=team, origin="signal_report")
    if admission is None:
        return
    TrialPolicy(team).admit(
        OperationAdmission(
            operation_key=operation_key,
            stage=SignalTrialOperation.Stage.REPORT_PASS,
            report_id=UUID(report_id),
        ),
        paid_authorized=admission.paid_authorized,
        decision=admission.decision,
    )
