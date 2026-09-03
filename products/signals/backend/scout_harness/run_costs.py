"""Model spend per scout run, for the staff-only cost readout on the roster.

A scout run is a Tasks run, so the `$ai_generation` events it makes land in the internal AI
observability project stamped with `task_origin_product = 'signals_scout'` and the run's
`task_run_id`. That makes cost per run one grouped sum, which is what
`get_local_task_run_token_costs` does; this module batches a set of runs into one such sum,
caches each run's answer, and keeps "not attributed" distinct from "$0.00".
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from django.core.cache import cache

from posthog.clickhouse.query_tagging import Product
from posthog.dataclasses import frozen

from products.signals.backend.models import SignalScoutRun
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.billing import TaskTokenUsageUnavailable, get_local_task_run_token_costs

# A settled run's spend is final, so it outlives the roster's 60s poll — otherwise every poll
# re-sums runs whose answer cannot change. A live run keeps generating, so it is cached only long
# enough to absorb a burst of polls, and its number stays a lower bound until the run finishes.
SETTLED_RUN_COST_CACHE_TIMEOUT_SECONDS = 60 * 60
LIVE_RUN_COST_CACHE_TIMEOUT_SECONDS = 60
# Generations are stamped while the run works, so the read window opens at the earliest run in the
# batch. The margin absorbs clock skew between the run row and the generation events.
RUN_COST_LOOKBACK_MARGIN = timedelta(hours=1)
# A run whose status says it can still generate, so its cost is a running total, not a final one.
LIVE_RUN_STATUSES = frozenset(
    {
        tasks_facade.TaskRunStatus.NOT_STARTED,
        tasks_facade.TaskRunStatus.QUEUED,
        tasks_facade.TaskRunStatus.IN_PROGRESS,
    }
)


@frozen
class ScoutRunTokenCost:
    run_id: str
    # None when no generation is attributed to the run — a run that failed before its first model
    # call, or one whose events haven't landed yet. Deliberately not 0, which would read as "this
    # run was free".
    token_cost_usd: Decimal | None


@frozen
class ScoutRunTokenCosts:
    costs: list[ScoutRunTokenCost]
    # False when this deployment has no internal AI observability project to read, so every cost
    # is unknown rather than zero.
    available: bool


@frozen
class _RunToPrice:
    """What pricing a run needs: which run, which generations, when to look, and whether it's done."""

    run_id: str
    task_run_id: str
    created_at: datetime
    live: bool


def scout_run_token_costs(*, team_id: int, run_ids: Sequence[UUID]) -> ScoutRunTokenCosts:
    """Sum the model spend attributed to each of this team's scout runs.

    Runs belonging to another team, and run ids that don't exist, contribute nothing — the team
    filter is the tenant guard, so one stale id never fails the batch.
    """
    runs = [
        _RunToPrice(
            run_id=str(run_id),
            # `task_run` is a non-null 1:1, so every run has exactly one id to attribute against.
            task_run_id=str(task_run_id),
            created_at=created_at,
            live=status in LIVE_RUN_STATUSES,
        )
        for run_id, created_at, task_run_id, status in SignalScoutRun.objects.filter(
            team_id=team_id, id__in=run_ids
        ).values_list("id", "created_at", "task_run_id", "task_run__status")
    ]
    if not runs:
        return ScoutRunTokenCosts(costs=[], available=True)

    costs: dict[str, Decimal | None] = {}
    pending: list[_RunToPrice] = []
    for run in runs:
        cached = cache.get(_cache_key(team_id=team_id, task_run_id=run.task_run_id))
        if cached is None:
            pending.append(run)
            continue
        # An empty string holds a cached "nothing attributed": the cache can't tell a stored
        # `None` from a miss.
        costs[run.run_id] = Decimal(cached) if cached else None

    if pending:
        try:
            costs.update(_query_pending_costs(team_id=team_id, pending=pending))
        except TaskTokenUsageUnavailable:
            return ScoutRunTokenCosts(costs=[], available=False)

    return ScoutRunTokenCosts(
        costs=[ScoutRunTokenCost(run_id=run_id, token_cost_usd=cost) for run_id, cost in costs.items()],
        available=True,
    )


def _cache_key(*, team_id: int, task_run_id: str) -> str:
    return f"scout_run_token_cost:v1:{team_id}:{task_run_id}"


def _query_pending_costs(*, team_id: int, pending: list[_RunToPrice]) -> dict[str, Decimal | None]:
    by_task_run_id = get_local_task_run_token_costs(
        team_id=team_id,
        origin_product=tasks_facade.TaskOriginProduct.SIGNALS_SCOUT,
        task_run_ids=[UUID(run.task_run_id) for run in pending],
        generated_after=min(run.created_at for run in pending) - RUN_COST_LOOKBACK_MARGIN,
        product=Product.SIGNALS,
    )
    costs: dict[str, Decimal | None] = {}
    for run in pending:
        cost = by_task_run_id.get(run.task_run_id)
        costs[run.run_id] = cost
        cache.set(
            _cache_key(team_id=team_id, task_run_id=run.task_run_id),
            str(cost) if cost is not None else "",
            timeout=LIVE_RUN_COST_CACHE_TIMEOUT_SECONDS if run.live else SETTLED_RUN_COST_CACHE_TIMEOUT_SECONDS,
        )
    return costs
