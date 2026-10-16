from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from uuid import NAMESPACE_URL, UUID, uuid5

from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.trial_models import SignalTrialOperation
from products.signals.backend.trial_policy import TrialPolicy
from products.signals.backend.trial_reports import prepare_report_pass, report_trial_context, task_trial_context


def reserve_report(team: Team, run_id: UUID | None, emission_key: str) -> UUID | None:
    if run_id is None:
        return None
    policy = TrialPolicy(team)
    operation = (
        SignalTrialOperation.objects.for_team(policy.team_id, canonical=True)
        .filter(task_run_id=run_id, funding=SignalTrialOperation.Funding.TRIAL)
        .first()
    )
    if operation is None:
        return None
    report_id = uuid5(NAMESPACE_URL, f"signals-trial-report:{policy.team_id}:{emission_key}")
    policy.reserve_direct_report(operation.id, report_id)
    return report_id


@asynccontextmanager
async def trial_report_reservation(*, team: Team, run_id: UUID | None, emission_key: str) -> AsyncIterator[UUID | None]:
    report_id = await database_sync_to_async(reserve_report)(team, run_id, emission_key)
    token = task_trial_context.set((team.id, run_id) if run_id is not None else None)
    try:
        yield report_id
    finally:
        task_trial_context.reset(token)
        if report_id is not None:
            await database_sync_to_async(TrialPolicy(team).finish_direct_report_attempt)(report_id)


@contextmanager
def trial_report_reservation_sync(*, team: Team, run_id: UUID | None, emission_key: str) -> Iterator[UUID | None]:
    report_id = reserve_report(team, run_id, emission_key)
    token = task_trial_context.set((team.id, run_id) if run_id is not None else None)
    try:
        yield report_id
    finally:
        task_trial_context.reset(token)
        if report_id is not None:
            TrialPolicy(team).finish_direct_report_attempt(report_id)


def _finish_custom_report(team: Team, report_id: UUID) -> None:
    with TrialPolicy(team).publish_report(report_id, delivered=False):
        pass


@asynccontextmanager
async def custom_report_reservation(
    *, team: Team, run_id: UUID | None, emission_key: str
) -> AsyncIterator[UUID | None]:
    if run_id is not None:
        async with trial_report_reservation(team=team, run_id=run_id, emission_key=emission_key) as report_id:
            yield report_id
        return
    report_id = uuid5(NAMESPACE_URL, f"signals-custom-trial-report:{team.id}:{emission_key}")
    await database_sync_to_async(prepare_report_pass)(
        team=team, report_id=str(report_id), operation_key=f"custom-report:{report_id}"
    )
    token = report_trial_context.set((team.id, str(report_id)))
    try:
        yield report_id
    finally:
        report_trial_context.reset(token)
        await database_sync_to_async(_finish_custom_report)(team, report_id)
