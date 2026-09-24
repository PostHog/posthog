"""Curated query: delivery and CI friction for one scope against the repository. The SQL returns one
row of facts per merged PR, and ``scope_repo_figure`` folds them into medians and shares in Python.

The comparison is against the repository, not against the previous window: the question is "is this
friction unusual here", and a trend over time says nothing about that. A window of merged pull
requests is small, so folding in Python keeps the scope and the repo figures on one definition."""

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
    PullRequestReadyToMerge,
    ReadyToMergeMedians,
    ScopeRepoDistribution,
    ScopeRepoFigure,
)
from products.engineering_analytics.backend.logic.cost import PRCostAggregate
from products.engineering_analytics.backend.logic.delivery_scope import CI_LOOKBACK, DeliveryScope, SummaryScope
from products.engineering_analytics.backend.logic.merge_queue import GATE_RUN_LOOKBACK, GateAttempt, gate_attempts_sql
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource, push_rows_select
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    DECISIVE_FAILURE_CONCLUSIONS_SQL,
    UNPAGED_SCAN_LIMIT,
    date_to_filter_clause,
    run_started_floor_constant,
)
from products.engineering_analytics.backend.logic.queries.dora import DeployedPR, query_deployed_prs
from products.engineering_analytics.backend.logic.queries.pr_cost import query_pr_costs
from products.engineering_analytics.backend.logic.views.reviews import APPROVED_STATE

_MERGED_SELECT = f"""
    SELECT
        pr.number,
        pr.author_handle,
        (__SCOPE__) AS in_scope,
        pr.created_at,
        pr.merged_at,
        __READY_TO_MERGE__ AS ready_to_merge_seconds
    FROM __PR_SOURCE__ AS pr
    __READY_JOIN__
    WHERE pr.merged_at IS NOT NULL AND pr.merged_at >= {{date_from}} __DATE_TO__
        AND NOT pr.is_bot AND NOT pr.is_draft
    LIMIT {UNPAGED_SCAN_LIMIT}
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
    LIMIT {UNPAGED_SCAN_LIMIT}
"""

_PUSHES_SELECT = f"""
    SELECT pr_number, groupArray(pushed_at) AS pushed_at
    FROM (__PUSH_ROWS__)
    GROUP BY pr_number
    LIMIT {UNPAGED_SCAN_LIMIT}
"""


@dataclass(frozen=True, kw_only=True)
class MergedPRFacts:
    number: int
    author: str
    in_scope: bool
    created_at: datetime
    merged_at: datetime
    ready_to_merge_seconds: int | None
    approved_at: list[datetime]
    pushed_at: list[datetime]
    gate_attempts: list[GateAttempt]
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


def _median_ready_to_merge(facts: list[MergedPRFacts]) -> float | None:
    return quantile(_ready_seconds(facts), 0.5)


def _p90_ready_to_merge(facts: list[MergedPRFacts]) -> float | None:
    return quantile(_ready_seconds(facts), 0.9)


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


def _median_ready_to_first_approval(facts: list[MergedPRFacts]) -> float | None:
    return quantile([split.before_seconds for split in _approval_splits(facts)], 0.5)


def _median_first_approval_to_merge(facts: list[MergedPRFacts]) -> float | None:
    return quantile([split.after_seconds for split in _approval_splits(facts)], 0.5)


def _before_approval_share(facts: list[MergedPRFacts]) -> float | None:
    splits = _approval_splits(facts)
    total = sum(split.before_seconds + split.after_seconds for split in splits)
    return sum(split.before_seconds for split in splits) / total if total else None


def ready_to_merge_medians(facts: list[MergedPRFacts]) -> ReadyToMergeMedians:
    return ReadyToMergeMedians(
        merged_pr_count=len(facts),
        ready_to_merge_seconds=quantile(_ready_seconds(facts), 0.5),
        p90_ready_to_merge_seconds=quantile(_ready_seconds(facts), 0.9),
        ready_to_first_approval_seconds=_median_ready_to_first_approval(facts),
        first_approval_to_merge_seconds=_median_first_approval_to_merge(facts),
        before_first_approval_share=_before_approval_share(facts),
    )


def pull_request_ready_to_merge(fact: MergedPRFacts) -> PullRequestReadyToMerge:
    split = next(iter(_approval_splits([fact])), None)
    return PullRequestReadyToMerge(
        number=fact.number,
        ready_to_merge_seconds=fact.ready_to_merge_seconds,
        ready_to_first_approval_seconds=split.before_seconds if split else None,
        first_approval_to_merge_seconds=split.after_seconds if split else None,
        before_first_approval_share=_before_approval_share([fact]),
    )


def _pushes_after_approval(facts: list[MergedPRFacts]) -> float | None:
    counts = []
    for fact in facts:
        approved_at = fact.first_approval_at
        if approved_at is None:
            continue
        counts.append(sum(1 for at in fact.pushed_at if approved_at < at <= fact.merged_at))
    return statistics.fmean(counts) if counts else None


def _queue_attempts(facts: list[MergedPRFacts]) -> float | None:
    counts = [len(f.gate_attempts) for f in facts if f.gate_attempts]
    return statistics.fmean(counts) if counts else None


def _failed_queue_share(facts: list[MergedPRFacts]) -> float | None:
    queued = [f for f in facts if f.gate_attempts]
    if not queued:
        return None
    return sum(1 for f in queued if any(gate.failed for gate in f.gate_attempts)) / len(queued)


def scope_repo_figure(
    scope_facts: list[MergedPRFacts],
    facts: list[MergedPRFacts],
    measure: Callable[[list[MergedPRFacts]], float | None],
) -> ScopeRepoFigure:
    """Applies one measure to the PRs in scope and to every PR, so the scope and the repo can never be
    measured two different ways."""
    return ScopeRepoFigure(scope=measure(scope_facts), repo=measure(facts))


def _lead_time(
    curated: CuratedGitHubSource,
    *,
    scope: SummaryScope,
    date_from: datetime,
    date_to: datetime | None,
    scope_merged_count: int,
) -> DeliveryLeadTime:
    deployed = query_deployed_prs(
        curated=curated,
        date_from=date_from,
        date_to=date_to,
        scope_predicate=scope.pr_predicate(curated, prefix=""),
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

    repo_rows = [
        row for row in deployed.rows if in_window(row.merged_at) and (date_to is None or row.deployed_at <= date_to)
    ]
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
        deployed_merged_pr_count=len(scope_rows),
        open_to_deploy=pair(lambda row: row.open_to_deploy_seconds),
        open_to_merge=pair(lambda row: row.open_to_merge_seconds),
        merge_to_deploy=pair(lambda row: row.merge_to_deploy_seconds),
    )


@dataclass(frozen=True, kw_only=True)
class _MergedRow:
    number: int
    author: str
    in_scope: bool
    created_at: datetime
    merged_at: datetime
    ready_to_merge_seconds: int | None


def _query_merged_rows(
    curated: CuratedGitHubSource, *, scope: DeliveryScope, date_from: datetime, date_to: datetime | None
) -> list[_MergedRow]:
    placeholders: dict[str, ast.Expr] = {"date_from": ast.Constant(value=date_from), **scope.placeholders()}
    ready = curated.ready_to_merge_sql()
    sql = ready.with_clause + (
        _MERGED_SELECT.replace("__SCOPE__", scope.pr_predicate(curated))
        .replace("__READY_TO_MERGE__", ready.expr)
        .replace("__READY_JOIN__", ready.join)
        .replace("__DATE_TO__", date_to_filter_clause(date_to, placeholders, column="pr.merged_at"))
        .replace("__PR_SOURCE__", curated.pr_source())
    )
    response = curated.run(sql, query_type="engineering_analytics.delivery_summary_merged", placeholders=placeholders)
    return [
        _MergedRow(
            number=int(number),
            author=author or "",
            in_scope=bool(in_scope),
            created_at=created_at,
            merged_at=merged_at,
            ready_to_merge_seconds=int(ready_seconds) if ready_seconds is not None else None,
        )
        for number, author, in_scope, created_at, merged_at, ready_seconds in response.results or []
        if created_at is not None and merged_at is not None
    ]


def _query_approvals(curated: CuratedGitHubSource, numbers: ast.Constant) -> dict[int, list[datetime]]:
    reviews_source = curated.reviews_source()
    if reviews_source is None:
        return {}
    response = curated.run(
        _APPROVALS_SELECT.replace("__REVIEWS_SOURCE__", reviews_source),
        query_type="engineering_analytics.delivery_summary_approvals",
        placeholders={"pr_numbers": numbers},
    )
    return {int(number): list(times) for number, times in response.results or []}


def _merged_facts(
    row: _MergedRow,
    *,
    approved_at: list[datetime],
    pushed_at: list[datetime] | None = None,
    gate_attempts: list[GateAttempt] | None = None,
    cost: PRCostAggregate | None = None,
) -> MergedPRFacts:
    return MergedPRFacts(
        number=row.number,
        author=row.author,
        in_scope=row.in_scope,
        created_at=row.created_at,
        merged_at=row.merged_at,
        ready_to_merge_seconds=row.ready_to_merge_seconds,
        approved_at=approved_at,
        pushed_at=pushed_at or [],
        gate_attempts=gate_attempts or [],
        cost=cost,
    )


def query_ready_to_merge_facts(
    curated: CuratedGitHubSource, *, scope: DeliveryScope, date_from: datetime, date_to: datetime | None
) -> list[MergedPRFacts]:
    """The merged PRs with only the facts the ready-to-merge medians read: no CI, queue or cost reads."""
    rows = _query_merged_rows(curated, scope=scope, date_from=date_from, date_to=date_to)
    if not rows:
        return []
    approvals = _query_approvals(curated, ast.Constant(value=sorted({row.number for row in rows})))
    return [_merged_facts(row, approved_at=approvals.get(row.number, [])) for row in rows]


def _query_merged_facts(
    curated: CuratedGitHubSource, *, scope: SummaryScope, date_from: datetime, date_to: datetime | None
) -> list[MergedPRFacts]:
    rows = _query_merged_rows(curated, scope=scope, date_from=date_from, date_to=date_to)
    pr_numbers = sorted({row.number for row in rows})
    if not pr_numbers:
        return []

    run_from = date_from - CI_LOOKBACK
    numbers = ast.Constant(value=pr_numbers)
    approvals = _query_approvals(curated, numbers)

    runs_source = curated.run_source(started_floor=True)
    push_rows = push_rows_select(
        runs_source=runs_source,
        run_filter="pr_number IN {pr_numbers} AND run_started_at >= {run_from}",
    )
    pushes_response = curated.run(
        _PUSHES_SELECT.replace("__PUSH_ROWS__", push_rows),
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
        gate_attempts_sql(
            runs_source=runs_source,
            pull_requests_source=curated.pr_source(),
            pull_request_filter="pr.number IN {pr_numbers} AND pr.merged_at IS NOT NULL",
            decisive_failure_conclusions_sql=DECISIVE_FAILURE_CONCLUSIONS_SQL,
        )
        + f"\nLIMIT {UNPAGED_SCAN_LIMIT}",
        query_type="engineering_analytics.delivery_summary_gate_attempts",
        placeholders={
            "pr_numbers": numbers,
            "gate_from": ast.Constant(value=gate_from),
            "run_started_floor": run_started_floor_constant(gate_from),
        },
    )
    gates: dict[int, list[GateAttempt]] = defaultdict(list)
    for number, attempt, started_at, completed_at, unfinished, failed, _merged_at in gates_response.results or []:
        if started_at is not None:
            gates[int(number)].append(
                GateAttempt(
                    started_at=started_at,
                    completed_at=None if unfinished else completed_at,
                    attempt=attempt or "",
                    failed=bool(failed),
                )
            )

    # A resolved source is one repository's tables, so dropping the owner and name cannot collide two
    # pull requests. The timelines read keeps the full key, because it shows the repository per row.
    costs = {
        number: cost
        for (_, _, number), cost in query_pr_costs(curated=curated, pr_numbers=pr_numbers, run_from=run_from).items()
    }

    return [
        _merged_facts(
            row,
            approved_at=approvals.get(row.number, []),
            pushed_at=pushes.get(row.number, []),
            gate_attempts=gates.get(row.number, []),
            cost=costs.get(row.number),
        )
        for row in rows
    ]


def query_delivery_summary(
    *, curated: CuratedGitHubSource, scope: SummaryScope, date_from: datetime, date_to: datetime | None
) -> DeliverySummary:
    facts = _query_merged_facts(curated, scope=scope, date_from=date_from, date_to=date_to)
    scope_facts = [fact for fact in facts if fact.in_scope]

    placeholders: dict[str, ast.Expr] = {"date_from": ast.Constant(value=date_from), **scope.placeholders()}
    counts = curated.run(
        _SCOPE_COUNTS_SELECT.replace("__SCOPE__", scope.pr_predicate(curated))
        .replace("__DATE_TO__", date_to_filter_clause(date_to, placeholders, column="pr.created_at"))
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
        cost_per_merged_pr_usd=scope_repo_figure(scope_facts, facts, _median_cost),
        billable_minutes_per_merged_pr=scope_repo_figure(scope_facts, facts, _median_billable_minutes),
        cost_per_push_usd=scope_repo_figure(scope_facts, facts, _cost_per_push),
        total_cost_usd=sum(cost.estimated_cost_usd for cost in costed if cost.estimated_cost_usd is not None)
        if costed
        else None,
        total_billable_minutes=sum(f.cost.billable_seconds for f in scope_facts if f.cost) / 60
        if jobs_available
        else None,
        push_count=sum(f.pushes for f in scope_facts),
        median_ready_to_merge_seconds=scope_repo_figure(scope_facts, facts, _median_ready_to_merge),
        p90_ready_to_merge_seconds=scope_repo_figure(scope_facts, facts, _p90_ready_to_merge),
        median_ready_to_first_approval_seconds=scope_repo_figure(scope_facts, facts, _median_ready_to_first_approval),
        median_first_approval_to_merge_seconds=scope_repo_figure(scope_facts, facts, _median_first_approval_to_merge),
        before_first_approval_share=scope_repo_figure(scope_facts, facts, _before_approval_share),
        pushes_after_approval_per_merged_pr=scope_repo_figure(scope_facts, facts, _pushes_after_approval),
        merge_queue_attempts_per_merged_pr=scope_repo_figure(scope_facts, facts, _queue_attempts),
        failed_merge_queue_share=scope_repo_figure(scope_facts, facts, _failed_queue_share),
        lead_time=_lead_time(
            curated, scope=scope, date_from=date_from, date_to=date_to, scope_merged_count=len(scope_facts)
        ),
    )
