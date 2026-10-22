"""Measure what each input source adds to an activity summary. Nothing here writes a summary row.

Coverage runs the same reads and filters as the tick and keeps only counts, so no user text leaves
the process. Leave one source out calls the model once with all sources and once per removed
source, and returns the summaries for rating by hand.
"""

import random
import datetime
from collections import Counter
from collections.abc import Iterable, Sequence
from enum import StrEnum
from typing import Any

from posthog.dataclasses import frozen
from posthog.models import ActivityLog, Team

from products.signals.backend.activity_summary.inputs import TASK_ORIGIN_PRODUCTS, user_activity, user_tasks
from products.signals.backend.activity_summary.queue import ActivitySummaryPair
from products.signals.backend.activity_summary.render import (
    ACTIVITY_LINES,
    TASK_LINES,
    ActivityItem,
    Drop,
    RenderedInput,
    TaskItem,
    build_input,
    sampling_seed,
)
from products.signals.backend.activity_summary.summaries import (
    DEFAULT_MODEL,
    MODEL_PRICES,
    cost_usd,
    gateway_client,
    summarize,
)
from products.tasks.backend.facade.user_task_summaries import list_user_task_times

# Teams per pair query, so a run over a whole region reads in bounded batches.
TEAM_BATCH_SIZE = 500
PERCENTILES = (50, 90, 99)


class Coverage(StrEnum):
    """Which sources still have units after the filters and caps."""

    TASKS_ONLY = "tasks_only"
    ACTIVITY_ONLY = "activity_only"
    BOTH = "both"
    NEITHER = "neither"


class Variant(StrEnum):
    ALL = "all"
    WITHOUT_TASKS = "without_tasks"
    WITHOUT_ACTIVITY = "without_activity"


@frozen
class PairCoverage:
    coverage: Coverage
    raw_tasks: int
    raw_activity: int
    task_units: int
    activity_units: int
    task_chars: int
    activity_chars: int
    task_lines_capped: bool
    activity_lines_capped: bool
    sections_budget_capped: bool
    drops: dict[str, int]

    @property
    def units(self) -> int:
        return self.task_units + self.activity_units


@frozen
class CoverageReport:
    pairs: int
    coverage: dict[str, int]
    # Per metric, the value at each of `PERCENTILES`.
    percentiles: dict[str, dict[str, int]]
    caps: dict[str, int]
    drops: dict[str, int]
    min_units: int
    pass_min_units: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "pairs": self.pairs,
            "coverage": self.coverage,
            "percentiles": self.percentiles,
            "caps": self.caps,
            "drops": self.drops,
            "min_units": self.min_units,
            "pass_min_units": self.pass_min_units,
        }


def _classify(rendered: RenderedInput) -> Coverage:
    tasks = rendered.n_tasks > 0
    activity = rendered.n_activity_lines > 0
    if tasks and activity:
        return Coverage.BOTH
    if tasks:
        return Coverage.TASKS_ONLY
    if activity:
        return Coverage.ACTIVITY_ONLY
    return Coverage.NEITHER


def measure_pair(
    tasks: Sequence[TaskItem], activity: Sequence[ActivityItem], *, as_of: datetime.datetime, seed: int
) -> PairCoverage:
    rendered = build_input(tasks, activity, as_of=as_of, seed=seed)
    if rendered is None:
        return PairCoverage(
            coverage=Coverage.NEITHER,
            raw_tasks=len(tasks),
            raw_activity=len(activity),
            task_units=0,
            activity_units=0,
            task_chars=0,
            activity_chars=0,
            task_lines_capped=False,
            activity_lines_capped=False,
            sections_budget_capped=False,
            drops={},
        )
    return PairCoverage(
        coverage=_classify(rendered),
        raw_tasks=len(tasks),
        raw_activity=len(activity),
        task_units=rendered.n_tasks,
        activity_units=rendered.n_activity_lines,
        task_chars=rendered.task_chars,
        activity_chars=rendered.activity_chars,
        task_lines_capped=rendered.task_pool > TASK_LINES,
        activity_lines_capped=rendered.activity_pool > ACTIVITY_LINES,
        sections_budget_capped=Drop.SECTIONS_BUDGET in rendered.drops,
        drops=rendered.drops,
    )


def _percentile(sorted_values: Sequence[int], percent: int) -> int:
    """Nearest rank, so the value is one that a pair has."""
    if not sorted_values:
        return 0
    rank = max(1, -(-percent * len(sorted_values) // 100))
    return sorted_values[rank - 1]


def coverage_report(pairs: Iterable[PairCoverage], *, min_units: int) -> CoverageReport:
    coverage: Counter[str] = Counter()
    caps: Counter[str] = Counter()
    drops: Counter[str] = Counter()
    metrics: dict[str, list[int]] = {
        "raw_tasks": [],
        "raw_activity": [],
        "task_units": [],
        "activity_units": [],
        "task_chars": [],
        "activity_chars": [],
    }
    count = 0
    passed = 0
    for pair in pairs:
        count += 1
        coverage[pair.coverage] += 1
        caps["task_lines"] += pair.task_lines_capped
        caps["activity_lines"] += pair.activity_lines_capped
        caps["sections_budget"] += pair.sections_budget_capped
        drops.update(pair.drops)
        passed += pair.units >= min_units
        for name, values in metrics.items():
            values.append(getattr(pair, name))
    return CoverageReport(
        pairs=count,
        coverage={str(kind): coverage[kind] for kind in Coverage},
        percentiles={
            name: {f"p{percent}": _percentile(sorted(values), percent) for percent in PERCENTILES}
            for name, values in metrics.items()
        },
        caps=dict(caps),
        drops=dict(sorted(drops.items())),
        min_units=min_units,
        pass_min_units=passed,
    )


def scope_team_ids(organization_id: str | None, team_id: int | None) -> list[int]:
    teams = Team.objects.all()
    if organization_id is not None:
        teams = teams.filter(organization_id=organization_id)
    if team_id is not None:
        teams = teams.filter(id=team_id)
    return list(teams.order_by("id").values_list("id", flat=True))


def candidate_pairs(
    team_ids: Sequence[int], start: datetime.datetime, end: datetime.datetime
) -> list[ActivitySummaryPair]:
    """Every (team, user) pair with a task or an activity log row of their own in [start, end).

    The same row filters as `inputs.py`. The render filters are not applied here, so a pair whose
    rows all drop counts as `Coverage.NEITHER`."""
    pairs: set[ActivitySummaryPair] = set()
    for offset in range(0, len(team_ids), TEAM_BATCH_SIZE):
        batch = list(team_ids[offset : offset + TEAM_BATCH_SIZE])
        rows = (
            ActivityLog.objects.filter(
                team_id__in=batch, user_id__isnull=False, created_at__gte=start, created_at__lt=end
            )
            .exclude(is_system=True)
            .exclude(was_impersonated=True)
            .values_list("team_id", "user_id")
            .distinct()
        )
        pairs.update(ActivitySummaryPair(team_id=team, user_id=user) for team, user in rows if team is not None)
        pairs.update(
            ActivitySummaryPair(team_id=task.team_id, user_id=task.user_id)
            for task in list_user_task_times(team_ids=batch, start=start, end=end, origin_products=TASK_ORIGIN_PRODUCTS)
        )
    return sorted(pairs)


def sample_pairs(
    pairs: Sequence[ActivitySummaryPair], sample: int | None, seed: int | None
) -> list[ActivitySummaryPair]:
    if sample is None or sample >= len(pairs):
        return list(pairs)
    return sorted(random.Random(seed).sample(list(pairs), sample))


def measure_coverage(
    pairs: Iterable[ActivitySummaryPair], *, start: datetime.datetime, now: datetime.datetime
) -> Iterable[PairCoverage]:
    """One pair at a time, so memory holds the rows of one pair only."""
    for pair in pairs:
        yield measure_pair(
            user_tasks(pair.team_id, pair.user_id, start, now),
            user_activity(pair.team_id, pair.user_id, start, now),
            as_of=now,
            seed=sampling_seed(now.date().isoformat(), pair.team_id, pair.user_id),
        )


def leave_one_out_inputs(
    tasks: Sequence[TaskItem], activity: Sequence[ActivityItem], *, as_of: datetime.datetime, seed: int
) -> dict[Variant, RenderedInput]:
    """The full input, and one input per source that has units in it. A variant with no units left is omitted."""
    full = build_input(tasks, activity, as_of=as_of, seed=seed)
    if full is None:
        return {}
    variants = {Variant.ALL: full}
    if full.n_tasks:
        without_tasks = build_input([], activity, as_of=as_of, seed=seed)
        if without_tasks is not None:
            variants[Variant.WITHOUT_TASKS] = without_tasks
    if full.n_activity_lines:
        without_activity = build_input(tasks, [], as_of=as_of, seed=seed)
        if without_activity is not None:
            variants[Variant.WITHOUT_ACTIVITY] = without_activity
    return variants


def leave_one_out_pair(
    pair: ActivitySummaryPair, *, start: datetime.datetime, now: datetime.datetime, min_units: int
) -> list[dict[str, Any]]:
    """One record per variant. With no previous summary, so each summary reflects its input only."""
    variants = leave_one_out_inputs(
        user_tasks(pair.team_id, pair.user_id, start, now),
        user_activity(pair.team_id, pair.user_id, start, now),
        as_of=now,
        seed=sampling_seed(now.date().isoformat(), pair.team_id, pair.user_id),
    )
    if Variant.ALL not in variants or variants[Variant.ALL].units < min_units:
        return []
    client = gateway_client(pair.team_id, pair.user_id, now.date())
    records: list[dict[str, Any]] = []
    for variant, rendered in variants.items():
        outcome = summarize(
            client, rendered_input=rendered.text, previous_summary=None, model=DEFAULT_MODEL, as_of=now.date()
        )
        records.append(
            {
                "team_id": pair.team_id,
                "user_id": pair.user_id,
                "variant": str(variant),
                "tasks": rendered.n_tasks,
                "activity_lines": rendered.n_activity_lines,
                "input_chars": rendered.input_chars,
                "tokens_in": outcome.tokens_in,
                "tokens_out": outcome.tokens_out,
                "cost_usd": cost_usd(outcome.tokens_in, outcome.tokens_out, MODEL_PRICES.get(DEFAULT_MODEL)),
                "latency_ms": outcome.latency_ms,
                "error": outcome.error,
                "summary": outcome.summary,
            }
        )
    return records


def leave_one_out_totals(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, float]]:
    totals: dict[str, dict[str, float]] = {}
    for record in records:
        total = totals.setdefault(
            record["variant"], {"calls": 0, "ok": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
        )
        total["calls"] += 1
        total["ok"] += record["summary"] is not None
        total["tokens_in"] += record["tokens_in"] or 0
        total["tokens_out"] += record["tokens_out"] or 0
        total["cost_usd"] += record["cost_usd"] or 0.0
    return totals
