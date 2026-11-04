from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from uuid import NAMESPACE_URL, UUID, uuid5

from posthog.models import Team
from posthog.sync import database_sync_to_async, database_sync_to_async_pool

from products.signals.backend.trial.billing import paid_trial_continuation_authorized
from products.signals.backend.trial.funding import TrialFunding, direct_report_funding
from products.signals.backend.trial.policy import TrialPolicy
from products.signals.backend.trial.reports import task_funding, task_trial_context


def reserve_report(team: Team, run_id: UUID | None, emission_key: str) -> UUID | None:
    if run_id is None:
        return None
    policy = TrialPolicy(team)
    if not policy.enabled():
        return None
    funding = task_funding(team.id, run_id)
    if funding is None or funding.grant_id is None:
        return None
    report_id = uuid5(NAMESPACE_URL, f"signals-trial-report:{policy.team_id}:{emission_key}")
    policy.reserve_direct_report(funding, report_id, run_id=run_id)
    return report_id


@asynccontextmanager
async def trial_report_reservation(*, team: Team, run_id: UUID | None, emission_key: str) -> AsyncIterator[UUID | None]:
    report_id = await database_sync_to_async(reserve_report)(team, run_id, emission_key)
    token = None
    funding_token = None
    try:
        token = task_trial_context.set((team.id, run_id) if run_id is not None else None)
        funding = await database_sync_to_async(task_funding)(team.id, run_id) if run_id else None
        funding_token = direct_report_funding.set((team.id, funding) if funding else None)
        yield report_id
    finally:
        if token is not None:
            task_trial_context.reset(token)
        if funding_token is not None:
            direct_report_funding.reset(funding_token)
        if report_id is not None:
            await database_sync_to_async(TrialPolicy(team).finish_direct_report_attempt)(report_id, run_id=run_id)


@contextmanager
def trial_report_reservation_sync(*, team: Team, run_id: UUID | None, emission_key: str) -> Iterator[UUID | None]:
    report_id = reserve_report(team, run_id, emission_key)
    token = None
    funding_token = None
    try:
        token = task_trial_context.set((team.id, run_id) if run_id is not None else None)
        funding = task_funding(team.id, run_id) if run_id else None
        funding_token = direct_report_funding.set((team.id, funding) if funding else None)
        yield report_id
    finally:
        if token is not None:
            task_trial_context.reset(token)
        if funding_token is not None:
            direct_report_funding.reset(funding_token)
        if report_id is not None:
            TrialPolicy(team).finish_direct_report_attempt(report_id, run_id=run_id)


def _reserve_custom_report(team: Team, report_id: UUID) -> TrialFunding:
    policy = TrialPolicy(team)
    grant = policy.active_grant()
    paid_authorized = paid_trial_continuation_authorized(team) if grant and grant.exhausted_at else False
    funding = policy.admit(paid_authorized=paid_authorized)
    policy.reserve_direct_report(funding, report_id)
    return funding


@asynccontextmanager
async def custom_report_reservation(
    *, team: Team, run_id: UUID | None, emission_key: str
) -> AsyncIterator[UUID | None]:
    if run_id is not None:
        async with trial_report_reservation(team=team, run_id=run_id, emission_key=emission_key) as report_id:
            yield report_id
        return
    if not await database_sync_to_async(TrialPolicy(team).enabled)():
        yield None
        return
    report_id = uuid5(NAMESPACE_URL, f"signals-custom-trial-report:{team.id}:{emission_key}")
    funding = await database_sync_to_async_pool(_reserve_custom_report)(team, report_id)
    token = direct_report_funding.set((team.id, funding))
    try:
        yield report_id
    finally:
        direct_report_funding.reset(token)
        if funding.grant_id is not None:
            await database_sync_to_async(TrialPolicy(team).finish_direct_report_attempt)(report_id)
