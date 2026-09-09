"""Model spend per scout over a window, for the staff-only cost readout on the roster.

`run_costs.py` prices a named set of runs, which answers "what did this run cost". This module
answers the question next to it: what a scout costs over a span, and what it produced for that
spend. Both numbers come from the same place — the run rows in Postgres, joined by `task_run_id` to
the `$ai_generation` sums in the internal AI observability project. The join has to happen here
rather than in the events, because a team-authored scout's generations all carry the same
`ai_stage`, so the events alone cannot name it.

The response is facts, not ratios: spend, how many runs, how many of those were priced, and how
many reports the scout touched. Cost per day, per run, and per report are derived from those four
numbers where they are rendered, so the definitions live in one place.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone

from posthog.clickhouse.query_tagging import Product
from posthog.dataclasses import frozen

from products.signals.backend.models import SignalScoutRun
from products.signals.backend.scout_harness.run_costs import RUN_COST_LOOKBACK_MARGIN
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.billing import TaskTokenUsageUnavailable, get_local_task_run_token_costs

# The window the roster's fleet headline already spans, so every number on the page describes one
# span. It also bounds the per-team read on the largest fleets.
SCOUT_COST_WINDOW_DAYS = 7
# The window's trailing edge moves and the newest runs may still be settling, so this is a roughly
# current number, not a live one. Fifteen minutes keeps a page open on the roster off the events
# read while still tracking the day's spend.
SCOUT_COSTS_CACHE_TIMEOUT_SECONDS = 15 * 60


@frozen
class ScoutCost:
    skill_name: str
    # Sum over the scout's runs that had spend attributed. Zero when none did, which
    # `priced_run_count` tells apart from a scout that really spent nothing.
    spend_usd: Decimal
    run_count: int
    priced_run_count: int
    # Distinct inbox reports the scout filed or added to. A report authored in one run and edited in
    # three counts once.
    reports_touched: int


@frozen
class ScoutCosts:
    window_days: int
    scouts: list[ScoutCost]
    # False when this deployment has no internal AI observability project to read, so every spend is
    # unknown rather than zero.
    available: bool


def scout_costs(*, team_id: int, window_days: int) -> ScoutCosts:
    """Sum this team's scout spend and output per scout over the last `window_days`."""
    cache_key = f"scout_costs:v1:{team_id}:{window_days}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    window_start = timezone.now() - timedelta(days=window_days)
    task_run_ids_by_skill: dict[str, list[str]] = defaultdict(list)
    report_ids_by_skill: dict[str, set[str]] = defaultdict(set)
    for skill_name, task_run_id, emitted_report_ids, edited_report_ids in SignalScoutRun.objects.filter(
        team_id=team_id, created_at__gte=window_start
    ).values_list("skill_name", "task_run_id", "emitted_report_ids", "edited_report_ids"):
        task_run_ids_by_skill[skill_name].append(str(task_run_id))
        report_ids_by_skill[skill_name].update(str(report_id) for report_id in (emitted_report_ids or []))
        report_ids_by_skill[skill_name].update(str(report_id) for report_id in (edited_report_ids or []))

    if not task_run_ids_by_skill:
        return ScoutCosts(window_days=window_days, scouts=[], available=True)

    try:
        spend_by_task_run_id = get_local_task_run_token_costs(
            team_id=team_id,
            origin_product=tasks_facade.TaskOriginProduct.SIGNALS_SCOUT.value,
            # No id list: the team filter and the window bound the read, and a per-team list would
            # be tens of thousands of ids on the largest fleets. The margin absorbs clock skew
            # between a run row and the generations stamped against it.
            generated_after=window_start - RUN_COST_LOOKBACK_MARGIN,
            product=Product.SIGNALS,
        )
    except TaskTokenUsageUnavailable:
        return ScoutCosts(window_days=window_days, scouts=[], available=False)

    costs = ScoutCosts(
        window_days=window_days,
        scouts=[
            _scout_cost(
                skill_name=skill_name,
                task_run_ids=task_run_ids,
                report_ids=report_ids_by_skill[skill_name],
                spend_by_task_run_id=spend_by_task_run_id,
            )
            for skill_name, task_run_ids in sorted(task_run_ids_by_skill.items())
        ],
        available=True,
    )
    cache.set(cache_key, costs, timeout=SCOUT_COSTS_CACHE_TIMEOUT_SECONDS)
    return costs


def _scout_cost(
    *,
    skill_name: str,
    task_run_ids: list[str],
    report_ids: set[str],
    spend_by_task_run_id: dict[str, Decimal],
) -> ScoutCost:
    priced = [spend_by_task_run_id[task_run_id] for task_run_id in task_run_ids if task_run_id in spend_by_task_run_id]
    return ScoutCost(
        skill_name=skill_name,
        spend_usd=sum(priced, Decimal(0)),
        run_count=len(task_run_ids),
        priced_run_count=len(priced),
        reports_touched=len(report_ids),
    )
