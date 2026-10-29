from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

from posthog.dataclasses import frozen

from products.signals.backend.spend import refresh_task_spend
from products.signals.backend.trial.billing import paid_trial_continuation_authorized
from products.signals.backend.trial.funding import TrialFunding
from products.signals.backend.trial.policy import TrialPolicy, TrialRefused
from products.signals.backend.trial.reports import active_report_pass, context_funding, task_funding
from products.tasks.backend.facade.api import get_task_run

if TYPE_CHECKING:
    from posthog.models import Team


SELF_DRIVING_ORIGINS = frozenset({"signal_report", "signals_scout"})


@frozen
class TaskTrialAdmission:
    team: "Team"
    paid_authorized: bool
    parent: TrialFunding | None = None

    def bind(self, *, origin: str, stage: str, report_id: UUID | None) -> dict[str, str | int]:
        from products.signals.backend.models import SignalReport  # noqa: PLC0415 -- Tasks model import cycle

        policy = TrialPolicy(self.team)
        with transaction.atomic():
            if report_id is not None:
                SignalReport.objects.select_for_update().get(team_id=self.team.id, id=report_id)
            funding = policy.admit(
                paid_authorized=self.paid_authorized,
                parent=self.parent,
                report_id=report_id if stage == "research" else None,
            )
        return {**funding.as_dict(), "stage": "scout" if origin == "signals_scout" else stage}


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


def prepare_task_trial(
    *, team: "Team", origin: str, report_id: UUID | None = None, mode: str = "background"
) -> TaskTrialAdmission | None:
    if mode != "background" or origin not in SELF_DRIVING_ORIGINS:
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
    parent = context_funding(team) or (active_report_pass(team, report_id) if report_id else None)
    if parent is not None:
        return TaskTrialAdmission(team=team, paid_authorized=parent.funding == "paid", parent=parent)
    grant = policy.active_grant()
    if grant is None:
        return None
    paid_authorized = False
    if grant.exhausted_at is not None:
        try:
            paid_authorized = paid_trial_continuation_authorized(team)
        except Exception as error:
            raise TrialRefused("billing_unavailable") from error
    return TaskTrialAdmission(team=team, paid_authorized=paid_authorized)


def start_task_trial(*, team: "Team", run_id: UUID) -> bool:
    from products.signals.backend.models import (
        SignalScoutRun,  # noqa: PLC0415 -- facade imported during Task model loading
    )

    policy = TrialPolicy(team)
    if not policy.enabled():
        return False
    funding = task_funding(team.id, run_id)
    if funding is None or funding.grant_id is None:
        return False
    run = get_task_run(run_id, team_id=team.id)
    if run is None or run.is_terminal:
        raise TrialRefused("operation_finished")
    stage = run.state["self_driving_funding"]["stage"]
    if stage == "scout":
        scout = (
            SignalScoutRun.objects.for_team(policy.team_id, canonical=True)
            .select_related("scout_config")
            .filter(task_run_id=run_id)
            .first()
        )
        if scout is None or not scout.scout_config or not scout.scout_config.enabled:
            raise TrialRefused("scout_disabled")
    refresh_task_spend(team_id=team.id, run_id=str(run_id), strict=True)
    policy.check_funding(
        funding,
        finishing_research=stage == "research" and run.state.get("sandbox_provisioning_started") is True,
    )
    return True


def check_trial_run_quota(*, team: "Team", run_id: UUID) -> str | None:
    from products.signals.backend.trial.tasks import cancel_trial_run  # noqa: PLC0415 -- task workflow imports

    policy = TrialPolicy(team)
    if not policy.enabled():
        return None
    funding = task_funding(team.id, run_id)
    if funding is None or funding.grant_id is None:
        return None
    run = get_task_run(run_id, team_id=team.id)
    if run is None or run.is_terminal:
        return "stop_checking"
    refresh_task_spend(team_id=team.id, run_id=str(run_id), strict=True)
    grant = policy.grant()
    if grant is not None and grant.exhaustion_reason == "cost_limit" and cancel_trial_run(run):
        return "cancelled"
    return "proceed"
