"""Curated query: delivery and CI friction for one scope (an author or a GitHub team) against the repository.

Every figure is measured twice over the same window: over the scope's merged pull requests, and over
every merged pull request in the repository (bots and drafts excluded, the scope included). The
comparison is against the repository, not against the previous window: the question is "is this
friction unusual here", and a trend over time says nothing about that.

The SQL returns one row per merged PR and a handful of per-PR facts (ready time, approvals, pushes,
merge-queue attempts, cost); the medians and shares are computed in Python. A window of merged PRs
is small (thousands of rows at most), and folding in Python keeps the scope and repo figures on
exactly one definition.
"""

import math
import statistics
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import (
    DeliveryLeadTime,
    DeliverySummary,
    DurationDistribution,
    ScopeRepoDistribution,
    ScopeRepoFigure,
)
from products.engineering_analytics.backend.logic.cost import PRCostAggregate
from products.engineering_analytics.backend.logic.delivery_scope import DeliveryScope
from products.engineering_analytics.backend.logic.merge_queue import GATE_RUN_LOOKBACK, gate_attempt_expr
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    DECISIVE_FAILURE_CONCLUSIONS_SQL,
    run_started_floor_constant,
)
from products.engineering_analytics.backend.logic.queries.dora import DeployedPR, query_deployed_prs
from products.engineering_analytics.backend.logic.queries.pr_cost import query_pr_costs_since
from products.engineering_analytics.backend.logic.views.reviews import APPROVED_STATE

# How far before the window a merged PR's CI is still counted. A PR merged in the window usually
# ran its CI days before; older runs are left out so the runs and jobs scans stay bounded.
CI_LOOKBACK = timedelta(days=30)

_ROW_LIMIT = 100000

_MERGED_SELECT = f"""
    SELECT
        pr.number,
        (__SCOPE__) AS in_scope,
        pr.created_at,
        pr.merged_at,
        __READY_TO_MERGE__ AS ready_to_merge_seconds
    FROM __PR_SOURCE__ AS pr
    __READY_JOIN__
    WHERE pr.merged_at IS NOT NULL AND pr.merged_at >= {{date_from}} __DATE_TO__
        AND NOT pr.is_bot AND NOT pr.is_draft
    LIMIT {_ROW_LIMIT}
"""

# Open and draft counts are current state, so they ignore the window.
_SCOPE_COUNTS_SELECT = """
    SELECT
        countIf(pr.created_at >= {date_from} __DATE_TO__) AS opened,
        countIf(pr.state = 'open' AND NOT pr.is_draft) AS open_now,
        countIf(pr.state = 'open' AND pr.is_draft) AS drafts
    FROM __PR_SOURCE__ AS pr
    WHERE NOT pr.is_bot AND (__SCOPE__)
"""

_APPROVALS_SELECT = f"""
    SELECT pr_number, groupArray(submitted_at) AS approved_at
    FROM __REVIEWS_SOURCE__ AS rv
    WHERE state = '{APPROVED_STATE}' AND pr_number IN {{pr_numbers}}
    GROUP BY pr_number
    LIMIT {_ROW_LIMIT}
"""

# A push is a distinct head commit that triggered CI; gate runs are the queue's rebases, not pushes.
# The run's creation time is when the commit arrived: a queued run starts later.
_PUSHES_SELECT = f"""
    SELECT pr_number, groupArray(pushed_at) AS pushed_at
    FROM (
        SELECT pr_number, head_sha, min(created_at) AS pushed_at
        FROM __RUNS_SOURCE__ AS r
        WHERE pr_number IN {{pr_numbers}} AND NOT is_merge_queue AND run_started_at >= {{run_from}}
        GROUP BY pr_number, head_sha
    )
    GROUP BY pr_number
    LIMIT {_ROW_LIMIT}
"""

_GATE_ATTEMPTS_SELECT = f"""
    SELECT
        r.pr_number AS pr_number,
        __GATE_ATTEMPT__ AS attempt,
        min(r.run_started_at) AS started_at,
        max(r.status = 'completed' AND r.conclusion IN ({DECISIVE_FAILURE_CONCLUSIONS_SQL})) AS failed
    FROM __RUNS_SOURCE__ AS r
    WHERE r.is_merge_queue AND r.pr_number IN {{pr_numbers}} AND r.run_started_at >= {{gate_from}}
    GROUP BY pr_number, attempt
    LIMIT 1000000
"""


@dataclass(frozen=True, kw_only=True)
class _GateAttempt:
    started_at: datetime
    failed: bool


@dataclass(frozen=True, kw_only=True)
class MergedPRFacts:
    """The per-PR facts behind every scope and repo figure."""

    number: int
    in_scope: bool
    created_at: datetime
    merged_at: datetime
    ready_to_merge_seconds: int | None
    approved_at: list[datetime]
    pushed_at: list[datetime]
    gate_attempts: list[_GateAttempt]
    cost: PRCostAggregate | None

    @property
    def ready_at(self) -> datetime | None:
        if self.ready_to_merge_seconds is None:
            return None
        return self.merged_at - timedelta(seconds=self.ready_to_merge_seconds)

    @property
    def first_approval_at(self) -> datetime | None:
        """The first approval after the PR went ready. An approval that landed while the PR was a
        draft counts as approved at ready: nobody waited on a reviewer after that point."""
        ready_at = self.ready_at
        if ready_at is None or not self.approved_at:
            return None
        after_ready = [at for at in self.approved_at if ready_at <= at <= self.merged_at]
        if after_ready:
            return min(after_ready)
        return ready_at if min(self.approved_at) < ready_at else None

    @property
    def pushes(self) -> int:
        return sum(1 for at in self.pushed_at if at <= self.merged_at)

    @property
    def landing_gate_attempts(self) -> list[_GateAttempt]:
        # Bisection probes after the merge are not attempts to land it.
        return [gate for gate in self.gate_attempts if gate.started_at <= self.merged_at]


def quantile(values: list[float], q: float) -> float | None:
    """Linear-interpolation quantile (numpy's default), None over an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def duration_distribution(values: list[float]) -> DurationDistribution:
    return DurationDistribution(
        pr_count=len(values),
        min_seconds=min(values) if values else None,
        p05_seconds=quantile(values, 0.05),
        p25_seconds=quantile(values, 0.25),
        p50_seconds=quantile(values, 0.5),
        mean_seconds=statistics.fmean(values) if values else None,
        p75_seconds=quantile(values, 0.75),
        p95_seconds=quantile(values, 0.95),
        max_seconds=max(values) if values else None,
    )


def _median_cost(facts: list[MergedPRFacts]) -> float | None:
    return quantile([f.cost.estimated_cost_usd for f in facts if f.cost and f.cost.estimated_cost_usd is not None], 0.5)


def _median_billable_minutes(facts: list[MergedPRFacts]) -> float | None:
    return quantile([f.cost.billable_seconds / 60 for f in facts if f.cost and f.cost.costed_jobs], 0.5)


def _cost_per_push(facts: list[MergedPRFacts]) -> float | None:
    costed = [f for f in facts if f.cost and f.cost.estimated_cost_usd is not None and f.pushes]
    pushes = sum(f.pushes for f in costed)
    if not pushes:
        return None
    return sum(f.cost.estimated_cost_usd for f in costed if f.cost and f.cost.estimated_cost_usd is not None) / pushes


def _ready_seconds(facts: list[MergedPRFacts]) -> list[float]:
    return [float(f.ready_to_merge_seconds) for f in facts if f.ready_to_merge_seconds is not None]


@dataclass(frozen=True, kw_only=True)
class _ApprovalSplit:
    before_seconds: float
    after_seconds: float


def _approval_splits(facts: list[MergedPRFacts]) -> list[_ApprovalSplit]:
    splits = []
    for fact in facts:
        ready_at, approved_at = fact.ready_at, fact.first_approval_at
        if ready_at is None or approved_at is None or fact.ready_to_merge_seconds is None:
            continue
        before = min(max((approved_at - ready_at).total_seconds(), 0.0), float(fact.ready_to_merge_seconds))
        splits.append(_ApprovalSplit(before_seconds=before, after_seconds=fact.ready_to_merge_seconds - before))
    return splits


def _before_approval_share(facts: list[MergedPRFacts]) -> float | None:
    splits = _approval_splits(facts)
    total = sum(split.before_seconds + split.after_seconds for split in splits)
    return sum(split.before_seconds for split in splits) / total if total else None


def _pushes_after_approval(facts: list[MergedPRFacts]) -> float | None:
    counts = []
    for fact in facts:
        approved_at = fact.first_approval_at
        if approved_at is None:
            continue
        counts.append(sum(1 for at in fact.pushed_at if approved_at < at <= fact.merged_at))
    return statistics.fmean(counts) if counts else None


def _queue_attempts(facts: list[MergedPRFacts]) -> float | None:
    counts = [len(f.landing_gate_attempts) for f in facts if f.landing_gate_attempts]
    return statistics.fmean(counts) if counts else None


def _failed_queue_share(facts: list[MergedPRFacts]) -> float | None:
    queued = [f for f in facts if f.landing_gate_attempts]
    if not queued:
        return None
    return sum(1 for f in queued if any(gate.failed for gate in f.landing_gate_attempts)) / len(queued)


class DeliverySummaryAggregator:
    """Folds the per-PR facts into scope and repo figures. Every figure applies one measure to both
    populations, so the scope and the repo can never be measured two different ways."""

    def __init__(self, facts: list[MergedPRFacts]) -> None:
        self._repo = facts
        self._scope = [fact for fact in facts if fact.in_scope]

    @property
    def scope_facts(self) -> list[MergedPRFacts]:
        return self._scope

    def _figure(self, measure: Callable[[list[MergedPRFacts]], float | None]) -> ScopeRepoFigure:
        return ScopeRepoFigure(scope=measure(self._scope), repo=measure(self._repo))

    def cost_per_merged_pr(self) -> ScopeRepoFigure:
        return self._figure(_median_cost)

    def billable_minutes_per_merged_pr(self) -> ScopeRepoFigure:
        return self._figure(_median_billable_minutes)

    def cost_per_push(self) -> ScopeRepoFigure:
        return self._figure(_cost_per_push)

    def ready_to_merge(self, q: float) -> ScopeRepoFigure:
        return self._figure(lambda facts: quantile(_ready_seconds(facts), q))

    def median_ready_to_first_approval(self) -> ScopeRepoFigure:
        return self._figure(lambda facts: quantile([split.before_seconds for split in _approval_splits(facts)], 0.5))

    def median_first_approval_to_merge(self) -> ScopeRepoFigure:
        return self._figure(lambda facts: quantile([split.after_seconds for split in _approval_splits(facts)], 0.5))

    def before_first_approval_share(self) -> ScopeRepoFigure:
        return self._figure(_before_approval_share)

    def pushes_after_approval(self) -> ScopeRepoFigure:
        return self._figure(_pushes_after_approval)

    def merge_queue_attempts(self) -> ScopeRepoFigure:
        return self._figure(_queue_attempts)

    def failed_merge_queue_share(self) -> ScopeRepoFigure:
        return self._figure(_failed_queue_share)


def _lead_time(
    curated: CuratedGitHubSource,
    *,
    scope: DeliveryScope,
    date_from: datetime,
    date_to: datetime | None,
    scope_merged_count: int,
) -> DeliveryLeadTime:
    deployed = query_deployed_prs(
        curated=curated,
        date_from=date_from,
        date_to=date_to,
        scope_predicate=scope.pr_predicate(members_source=curated.members_source(), prefix=""),
        scope_placeholders=scope.placeholders(),
    )
    empty = duration_distribution([])
    if deployed is None:
        empty_pair = ScopeRepoDistribution(scope=empty, repo=empty)
        return DeliveryLeadTime(
            deploy_data_available=False,
            environment_scope="",
            merged_pr_count=scope_merged_count,
            deployed_merged_pr_count=0,
            open_to_deploy=empty_pair,
            open_to_merge=empty_pair,
            merge_to_deploy=empty_pair,
        )

    def in_window(at: datetime) -> bool:
        return at >= date_from and (date_to is None or at <= date_to)

    repo_rows = [row for row in deployed.rows if in_window(row.deployed_at)]
    scope_rows = [row for row in repo_rows if row.in_scope]

    def pair(stage: Callable[[DeployedPR], float]) -> ScopeRepoDistribution:
        return ScopeRepoDistribution(
            scope=duration_distribution([stage(row) for row in scope_rows]),
            repo=duration_distribution([stage(row) for row in repo_rows]),
        )

    return DeliveryLeadTime(
        deploy_data_available=True,
        environment_scope=deployed.environment_scope,
        merged_pr_count=scope_merged_count,
        deployed_merged_pr_count=sum(1 for row in deployed.rows if row.in_scope and in_window(row.merged_at)),
        open_to_deploy=pair(lambda row: (row.deployed_at - row.created_at).total_seconds()),
        open_to_merge=pair(lambda row: (row.merged_at - row.created_at).total_seconds()),
        merge_to_deploy=pair(lambda row: (row.deployed_at - row.merged_at).total_seconds()),
    )


def _query_merged_facts(
    curated: CuratedGitHubSource, *, scope: DeliveryScope, date_from: datetime, date_to: datetime | None
) -> list[MergedPRFacts]:
    placeholders: dict[str, ast.Expr] = {"date_from": ast.Constant(value=date_from), **scope.placeholders()}
    date_to_clause = ""
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)
        date_to_clause = "AND pr.merged_at <= {date_to}"
    ready = curated.ready_to_merge_sql()
    sql = ready.with_clause + (
        _MERGED_SELECT.replace("__SCOPE__", scope.pr_predicate(members_source=curated.members_source()))
        .replace("__READY_TO_MERGE__", ready.expr)
        .replace("__READY_JOIN__", ready.join)
        .replace("__DATE_TO__", date_to_clause)
        .replace("__PR_SOURCE__", curated.pr_source())
    )
    merged_rows = curated.run(
        sql, query_type="engineering_analytics.delivery_summary_merged", placeholders=placeholders
    )
    rows = [row for row in merged_rows.results or [] if row[2] is not None and row[3] is not None]
    pr_numbers = sorted({int(row[0]) for row in rows})
    if not pr_numbers:
        return []

    run_from = date_from - CI_LOOKBACK
    numbers = ast.Constant(value=pr_numbers)
    approvals: dict[int, list[datetime]] = {}
    reviews_source = curated.reviews_source()
    if reviews_source is not None:
        response = curated.run(
            _APPROVALS_SELECT.replace("__REVIEWS_SOURCE__", reviews_source),
            query_type="engineering_analytics.delivery_summary_approvals",
            placeholders={"pr_numbers": numbers},
        )
        approvals = {int(number): list(times) for number, times in response.results or []}

    runs_source = curated.run_source(started_floor=True)
    pushes_response = curated.run(
        _PUSHES_SELECT.replace("__RUNS_SOURCE__", runs_source),
        query_type="engineering_analytics.delivery_summary_pushes",
        placeholders={
            "pr_numbers": numbers,
            "run_from": ast.Constant(value=run_from),
            "run_started_floor": run_started_floor_constant(run_from),
        },
    )
    pushes = {int(number): [at for at in times if at is not None] for number, times in pushes_response.results or []}

    gate_from = date_from - GATE_RUN_LOOKBACK
    gates_response = curated.run(
        _GATE_ATTEMPTS_SELECT.replace("__RUNS_SOURCE__", runs_source).replace(
            "__GATE_ATTEMPT__", gate_attempt_expr("r.head_branch")
        ),
        query_type="engineering_analytics.delivery_summary_gate_attempts",
        placeholders={
            "pr_numbers": numbers,
            "gate_from": ast.Constant(value=gate_from),
            "run_started_floor": run_started_floor_constant(gate_from),
        },
    )
    gates: dict[int, list[_GateAttempt]] = defaultdict(list)
    for number, _attempt, started_at, failed in gates_response.results or []:
        if started_at is not None:
            gates[int(number)].append(_GateAttempt(started_at=started_at, failed=bool(failed)))

    costs = query_pr_costs_since(curated=curated, pr_numbers=pr_numbers, run_from=run_from)

    return [
        MergedPRFacts(
            number=int(number),
            in_scope=bool(in_scope),
            created_at=created_at,
            merged_at=merged_at,
            ready_to_merge_seconds=int(ready_seconds) if ready_seconds is not None else None,
            approved_at=approvals.get(int(number), []),
            pushed_at=pushes.get(int(number), []),
            gate_attempts=gates.get(int(number), []),
            cost=costs.get(int(number)),
        )
        for number, in_scope, created_at, merged_at, ready_seconds in rows
    ]


def query_delivery_summary(
    *, curated: CuratedGitHubSource, scope: DeliveryScope, date_from: datetime, date_to: datetime | None
) -> DeliverySummary:
    facts = _query_merged_facts(curated, scope=scope, date_from=date_from, date_to=date_to)
    aggregator = DeliverySummaryAggregator(facts)
    scope_facts = aggregator.scope_facts

    placeholders: dict[str, ast.Expr] = {"date_from": ast.Constant(value=date_from), **scope.placeholders()}
    date_to_clause = ""
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)
        date_to_clause = "AND pr.created_at <= {date_to}"
    counts = curated.run(
        _SCOPE_COUNTS_SELECT.replace("__SCOPE__", scope.pr_predicate(members_source=curated.members_source()))
        .replace("__DATE_TO__", date_to_clause)
        .replace("__PR_SOURCE__", curated.pr_source()),
        query_type="engineering_analytics.delivery_summary_counts",
        placeholders=placeholders,
    )
    opened, open_now, drafts = counts.results[0] if counts.results else (0, 0, 0)

    jobs_available = curated.jobs_source() is not None
    costed = [f.cost for f in scope_facts if f.cost and f.cost.estimated_cost_usd is not None]
    return DeliverySummary(
        scope_kind=scope.kind,
        scope=scope.label,
        has_membership_data=curated.members_source() is not None,
        jobs_available=jobs_available,
        review_data_available=curated.reviews_source() is not None,
        ready_data_available=curated.ready_to_merge_sql().observable,
        opened_pr_count=int(opened or 0),
        merged_pr_count=len(scope_facts),
        open_pr_count=int(open_now or 0),
        draft_pr_count=int(drafts or 0),
        cost_per_merged_pr_usd=aggregator.cost_per_merged_pr(),
        billable_minutes_per_merged_pr=aggregator.billable_minutes_per_merged_pr(),
        cost_per_push_usd=aggregator.cost_per_push(),
        total_cost_usd=sum(cost.estimated_cost_usd for cost in costed if cost.estimated_cost_usd is not None)
        if costed
        else None,
        total_billable_minutes=sum(f.cost.billable_seconds for f in scope_facts if f.cost) / 60
        if jobs_available
        else None,
        push_count=sum(f.pushes for f in scope_facts),
        median_ready_to_merge_seconds=aggregator.ready_to_merge(0.5),
        p90_ready_to_merge_seconds=aggregator.ready_to_merge(0.9),
        median_ready_to_first_approval_seconds=aggregator.median_ready_to_first_approval(),
        median_first_approval_to_merge_seconds=aggregator.median_first_approval_to_merge(),
        before_first_approval_share=aggregator.before_first_approval_share(),
        pushes_after_approval_per_merged_pr=aggregator.pushes_after_approval(),
        merge_queue_attempts_per_merged_pr=aggregator.merge_queue_attempts(),
        failed_merge_queue_share=aggregator.failed_merge_queue_share(),
        lead_time=_lead_time(
            curated, scope=scope, date_from=date_from, date_to=date_to, scope_merged_count=len(scope_facts)
        ),
    )
