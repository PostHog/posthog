from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from dataclasses import replace
from functools import wraps
from typing import Any, Protocol, TypeVar
from uuid import UUID

from django.db import transaction

from posthog.models import Team

from products.signals.backend.daily_limit import check_daily_report_admission
from products.signals.backend.quota import SelfDrivingAdmission, prepare_self_driving_admission
from products.signals.backend.trial.funding import TrialFunding, direct_report_funding, signal_funding
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
    return (
        parent.grant_id is not None
        if parent is not None
        else prepare_self_driving_admission(team).trial_accounting_required
    )


def implementation_requires_trial_opt_in(team_id: int, report_id: str) -> bool:
    team = Team.objects.get(id=team_id)
    funding = report_funding(team, report_id)
    # A later grant must not add an opt-in gate to a pipeline accepted before trials.
    return funding is not None and funding.funding == "trial"


def report_pass_admission(
    *, team: Team, report_id: str, operation_key: str, signal_id: str | None = None, operator_rerun: bool = False
) -> SelfDrivingAdmission:
    from products.signals.backend.models import SignalReport, SignalSpend  # noqa: PLC0415 -- model registration cycle

    report = (
        SignalReport.objects.filter(team_id=team.id, id=report_id)
        .values("self_driving_funding", "billing_exempt_reason")
        .first()
    )
    previous = TrialFunding.from_dict(report["self_driving_funding"] if report else None)
    parent: TrialFunding | None
    if previous is not None and previous.report_pass_key == operation_key:
        parent = previous
    elif operator_rerun:
        parent = TrialFunding(funding="operator")
    elif report is not None and report["billing_exempt_reason"]:
        parent = TrialFunding(funding="existing")
    else:
        receipt = (
            SignalSpend.objects.for_team(team.id)
            .filter(
                signal_id=signal_id,
                kind=SignalSpend.Kind.AD_HOC,
                finalization_requested_at__isnull=True,
                finalized_at__isnull=True,
            )
            .only("trial_grant_id", "billing_exempt")
            .first()
        )
        parent = None
        if receipt is not None:
            # An open receipt means accepted work, regardless of billing exemption.
            # Exempt signals retain the customer report's funding; they cannot make it free.
            grant_id = receipt.trial_grant_id
            if receipt.billing_exempt and grant_id is None:
                if previous is not None and previous.funding != "operator":
                    parent = previous
                else:
                    grant = TrialPolicy(team).active_grant()
                    grant_id = grant.id if grant else None
            if parent is None and grant_id is not None:
                parent = TrialFunding(funding="trial", grant_id=grant_id)
            if parent is None:
                from products.signals.backend.free_trial import (  # noqa: PLC0415 -- legacy gate reads report funding
                    self_driving_free_trial_enabled,
                )

                parent = TrialFunding(
                    funding="existing", implementation_allowed=not self_driving_free_trial_enabled(team)
                )
    if parent is None:
        check_daily_report_admission(team, report_id=report_id)
    return prepare_self_driving_admission(team, parent=parent)


def prepare_report_pass(
    *,
    team: Team,
    report_id: str,
    operation_key: str,
    admission: SelfDrivingAdmission | None = None,
    signal_id: str | None = None,
    operator_rerun: bool = False,
) -> None:
    from products.signals.backend.models import SignalReport  # noqa: PLC0415 -- model registration cycle

    admission = admission or report_pass_admission(
        team=team, report_id=report_id, operation_key=operation_key, signal_id=signal_id, operator_rerun=operator_rerun
    )
    with transaction.atomic():
        report = SignalReport.objects.select_for_update().get(team_id=team.id, id=report_id)
        previous = TrialFunding.from_dict(report.self_driving_funding)
        if previous is not None and previous.report_pass_key == operation_key:
            return
        if previous is not None and report.status == SignalReport.Status.IN_PROGRESS:
            raise TrialRefused("report_pass_in_progress")
        funding = admission.bind(report_id=report.id, report_pass_key=operation_key)
        SignalReport.objects.filter(team_id=team.id, id=report.id).update(
            self_driving_funding=replace(funding, report_pass_key=operation_key).as_dict()
        )
