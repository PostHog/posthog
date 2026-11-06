from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from dataclasses import replace
from functools import wraps
from typing import Any, Protocol, TypeVar
from uuid import UUID

from django.db import transaction

from posthog.models import Team

from products.signals.backend.trial.billing import paid_trial_continuation_authorized
from products.signals.backend.trial.funding import TrialFunding, direct_report_funding, signal_funding
from products.signals.backend.trial.models import SignalTrialReportReservation
from products.signals.backend.trial.policy import TrialPolicy, TrialRefused
from products.tasks.backend.facade.api import get_task_run

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


def task_funding(team_id: int, run_id: UUID) -> TrialFunding | None:
    run = get_task_run(run_id, team_id=team_id)
    return TrialFunding.from_dict(run.state.get("self_driving_funding")) if run else None


def report_funding(team: Team, report_id: UUID | str) -> TrialFunding | None:
    from products.signals.backend.models import SignalReport  # noqa: PLC0415 -- model registration cycle

    report = (
        SignalReport.objects.filter(team_id=team.id, id=report_id)
        .values("self_driving_funding", "billing_exempt_reason")
        .first()
    )
    if report is None:
        return None
    if report["billing_exempt_reason"] and (report["self_driving_funding"] or {}).get("funding") != "operator":
        return TrialFunding(funding="existing")
    return TrialFunding.from_dict(report["self_driving_funding"])


def context_funding(team: Team) -> TrialFunding | None:
    task_context = task_trial_context.get()
    if task_context and task_context[0] == team.id:
        return task_funding(team.id, task_context[1]) or TrialFunding(funding="existing")
    direct_context = direct_report_funding.get()
    if direct_context and direct_context[0] == team.id:
        return direct_context[1]
    context = report_trial_context.get()
    if context and context[0] == team.id:
        return report_funding(team, context[1]) or TrialFunding(funding="existing")
    return None


def requires_trial_accounting(team_id: int, signal_id: str | None = None) -> bool:
    team = Team.objects.get(id=team_id)
    parent = context_funding(team)
    if parent is not None and parent.funding == "operator":
        return False
    parent = signal_funding(team_id, signal_id) or parent
    if parent is not None:
        return parent.grant_id is not None
    grant = TrialPolicy(team).admission_grant()
    if grant is not None and grant.exhausted_at is None:
        return True
    if grant is not None:
        return not paid_trial_continuation_authorized(team)
    return False


def implementation_requires_trial_opt_in(team_id: int, report_id: str) -> bool:
    team = Team.objects.get(id=team_id)
    funding = report_funding(team, report_id)
    if funding is not None:
        return funding.funding == "trial"
    if not TrialPolicy(team).enabled():
        return False
    return SignalTrialReportReservation.objects.for_team(team_id).filter(
        report_id=report_id, status=SignalTrialReportReservation.Status.CONSUMED
    ).exists() or requires_trial_accounting(team_id)


def report_pass_paid_authorized(
    *, team: Team, report_id: str, operation_key: str, signal_id: str | None = None
) -> bool:
    from products.signals.backend.models import SignalReport  # noqa: PLC0415 -- model registration cycle

    policy = TrialPolicy(team)
    report = (
        SignalReport.objects.filter(team_id=team.id, id=report_id)
        .values("self_driving_funding", "billing_exempt_reason")
        .first()
    )
    if report is not None and report["billing_exempt_reason"]:
        return False
    previous = TrialFunding.from_dict(report["self_driving_funding"] if report else None)
    if previous is not None and previous.report_pass_key == operation_key:
        return False
    if signal_funding(team.id, signal_id, for_report=True) is not None:
        return False
    grant = policy.admission_grant()
    return bool(grant and grant.exhausted_at and paid_trial_continuation_authorized(team))


def prepare_report_pass(
    *,
    team: Team,
    report_id: str,
    operation_key: str,
    paid_authorized: bool = False,
    signal_id: str | None = None,
    operator_rerun: bool = False,
) -> None:
    from products.signals.backend.models import SignalReport  # noqa: PLC0415 -- model registration cycle

    policy = TrialPolicy(team)
    with transaction.atomic():
        report = SignalReport.objects.select_for_update().get(team_id=team.id, id=report_id)
        previous = TrialFunding.from_dict(report.self_driving_funding)
        if previous is not None and previous.report_pass_key == operation_key:
            return
        if previous is not None and report.status == SignalReport.Status.IN_PROGRESS:
            raise TrialRefused("report_pass_in_progress")
        # Operator repairs are free for this pipeline, not for later automatic refreshes.
        if operator_rerun:
            funding = TrialFunding(funding="operator")
        elif report.billing_exempt_reason:
            funding = TrialFunding(funding="existing")
        else:
            funding = policy.admit(
                paid_authorized=paid_authorized,
                report_id=report.id,
                parent=signal_funding(team.id, signal_id, for_report=True),
            )
        SignalReport.objects.filter(team_id=team.id, id=report.id).update(
            self_driving_funding=replace(funding, report_pass_key=operation_key).as_dict()
        )
