from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from dataclasses import replace
from functools import wraps
from typing import Any, Protocol, TypeVar
from uuid import UUID

from django.db import transaction

from posthog.models import Team

from products.signals.backend.quota import prepare_self_driving_admission
from products.signals.backend.trial.funding import TrialFunding, direct_report_funding
from products.signals.backend.trial.policy import TrialRefused
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

    snapshot = (
        SignalReport.objects.filter(team_id=team.id, id=report_id)
        .values_list("self_driving_funding", flat=True)
        .first()
    )
    return TrialFunding.from_dict(snapshot)


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


def requires_trial_accounting(team_id: int) -> bool:
    team = Team.objects.get(id=team_id)
    return prepare_self_driving_admission(team, parent=context_funding(team)).bind().grant_id is not None


def implementation_requires_trial_opt_in(team_id: int, report_id: str) -> bool:
    team = Team.objects.get(id=team_id)
    funding = report_funding(team, report_id)
    if funding is not None:
        return funding.funding == "trial"
    return requires_trial_accounting(team_id)


def prepare_report_pass(*, team: Team, report_id: str, operation_key: str) -> None:
    from products.signals.backend.models import SignalReport  # noqa: PLC0415 -- model registration cycle

    snapshot = (
        SignalReport.objects.filter(team_id=team.id, id=report_id)
        .values_list("self_driving_funding", flat=True)
        .first()
    )
    previous = TrialFunding.from_dict(snapshot)
    if previous is not None and previous.report_pass_key == operation_key:
        return
    admission = prepare_self_driving_admission(team)
    with transaction.atomic():
        report = SignalReport.objects.select_for_update().get(team_id=team.id, id=report_id)
        previous = TrialFunding.from_dict(report.self_driving_funding)
        if previous is not None and previous.report_pass_key == operation_key:
            return
        if previous is not None and report.status == SignalReport.Status.IN_PROGRESS:
            raise TrialRefused("report_pass_in_progress")
        funding = admission.bind(report_id=report.id)
        SignalReport.objects.filter(team_id=team.id, id=report.id).update(
            self_driving_funding=replace(funding, report_pass_key=operation_key).as_dict()
        )
