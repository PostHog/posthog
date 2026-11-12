from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING
from uuid import UUID

from posthog.dataclasses import frozen

from products.signals.backend.quota import SelfDrivingAdmission, prepare_self_driving_admission
from products.signals.backend.spend import refresh_task_spend
from products.signals.backend.trial.funding import TrialFunding
from products.signals.backend.trial.policy import TrialExecutionRefused, TrialRefused
from products.signals.backend.trial.reports import context_funding, report_funding
from products.tasks.backend.facade.api import get_task_run

if TYPE_CHECKING:
    from posthog.models import Team


SELF_DRIVING_ORIGINS = frozenset({"signal_report", "signals_scout"})


@frozen
class TaskTrialAdmission:
    admission: SelfDrivingAdmission

    def lock_report(self, report_id: UUID | None) -> None:
        from products.signals.backend.models import SignalReport  # noqa: PLC0415 -- Tasks model import cycle

        if report_id is not None:
            SignalReport.objects.select_for_update().get(team_id=self.admission.team.id, id=report_id)

    def bind(
        self, *, origin: str, stage: str, report_id: UUID | None, task_runtime: str, model_access: str
    ) -> dict[str, str | int]:
        funding = self.admission.bind(report_id=report_id if stage == "research" else None)
        if funding.funding == "trial" and (
            (task_runtime == "pi" and origin != "signals_scout") or model_access == "own-subscription"
        ):
            raise TrialExecutionRefused()
        return {**funding.as_dict(), "stage": "scout" if origin == "signals_scout" else stage}


@frozen
class PreparedTaskTrial:
    team_id: int
    origin: str
    report_id: str | None
    admission: TaskTrialAdmission | None


_prepared_task_trial: ContextVar[PreparedTaskTrial | None] = ContextVar("prepared_task_trial", default=None)


@contextmanager
def task_trial_admission(
    *,
    team: "Team",
    origin: str,
    report_id: UUID | str | None = None,
    continue_admitted_pipeline: bool = False,
) -> Iterator[None]:
    admission = prepare_task_trial(
        team=team,
        origin=origin,
        report_id=UUID(str(report_id)) if report_id else None,
        continue_admitted_pipeline=continue_admitted_pipeline,
    )
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
    *,
    team: "Team",
    origin: str,
    report_id: UUID | None = None,
    mode: str = "background",
    continue_admitted_pipeline: bool = False,
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
    parent = context_funding(team)
    if parent is None and report_id is not None and continue_admitted_pipeline:
        parent = report_funding(team, report_id) or TrialFunding(funding="existing")
    return TaskTrialAdmission(admission=prepare_self_driving_admission(team, parent=parent))


def start_task_trial(*, team: "Team", run_id: UUID) -> bool:
    run = get_task_run(run_id, team_id=team.id)
    funding = TrialFunding.from_dict(run.state.get("self_driving_funding")) if run else None
    if funding is None or funding.grant_id is None:
        return False
    if run is None or run.is_terminal:
        raise TrialRefused("operation_finished")
    refresh_task_spend(team_id=team.id, run_id=str(run_id), strict=True)
    return True


def refresh_trial_run_spend(*, team_id: int, run_id: UUID) -> bool:
    run = get_task_run(run_id, team_id=team_id)
    if run is None or run.is_terminal:
        return False
    funding = TrialFunding.from_dict(run.state.get("self_driving_funding"))
    if funding is None or funding.grant_id is None:
        return False
    refresh_task_spend(team_id=team_id, run_id=str(run_id), strict=True)
    return True
