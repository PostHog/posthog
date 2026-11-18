from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from uuid import NAMESPACE_URL, UUID, uuid5

from posthog.models import Team
from posthog.sync import database_sync_to_async_pool

from products.signals.backend.quota import prepare_self_driving_admission
from products.signals.backend.trial.funding import TrialFunding, direct_report_funding
from products.signals.backend.trial.reports import context_funding, task_funding, task_trial_context


def _report_funding(team: Team, run_id: UUID | None) -> TrialFunding:
    parent = (
        task_funding(team.id, run_id) or TrialFunding(funding="existing")
        if run_id is not None
        else context_funding(team)
    )
    return prepare_self_driving_admission(team, parent=parent).bind()


@contextmanager
def _funded_report(team: Team, run_id: UUID | None, emission_key: str, funding: TrialFunding) -> Iterator[UUID | None]:
    task_token = task_trial_context.set((team.id, run_id) if run_id is not None else None)
    funding_token = direct_report_funding.set((team.id, funding))
    try:
        # Accepted scouts and custom agents can publish after exhaustion. The report row,
        # once written, contributes to subsequent admission checks through first_visible_at.
        yield uuid5(NAMESPACE_URL, f"signals-funded-report:{team.id}:{emission_key}") if funding.grant_id else None
    finally:
        direct_report_funding.reset(funding_token)
        task_trial_context.reset(task_token)


@asynccontextmanager
async def funded_report(*, team: Team, run_id: UUID | None, emission_key: str) -> AsyncIterator[UUID | None]:
    funding = await database_sync_to_async_pool(_report_funding)(team, run_id)
    with _funded_report(team, run_id, emission_key, funding) as report_id:
        yield report_id


@contextmanager
def funded_report_sync(*, team: Team, run_id: UUID | None, emission_key: str) -> Iterator[UUID | None]:
    funding = _report_funding(team, run_id)
    with _funded_report(team, run_id, emission_key, funding) as report_id:
        yield report_id
