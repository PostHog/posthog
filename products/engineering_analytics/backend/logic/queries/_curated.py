"""The curated read layer over a team's GitHub warehouse tables.

``CuratedGitHubSource`` binds one team to its resolved ``pull_requests`` / ``workflow_runs``
table names (see ``logic.sources``) and is the single object the query modules use: it hands
out the curated ``SELECT`` subqueries and the CI rollup CTE, and runs the assembled HogQL.
The resolved table names live inside it, so the query layer never threads or re-derives them.
The product reads its data privately this way — nothing is registered as a global HogQL view,
keeping it off the per-query catalog hot path.

Every SQL fragment is built from trusted constants and the resolved table identifiers (which
the resolver has validated to ``[A-Za-z_][A-Za-z0-9_]*``). User-supplied values must always
flow through ``ast.Constant`` placeholders in the calling query, never be string-substituted
into these fragments.
"""

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.engineering_analytics.backend.logic.sources import (
    GitHubTables,
    resolve_github_tables,
    resolve_trunk_merge_queue_table,
)
from products.engineering_analytics.backend.logic.views import (
    deployments,
    issue_events,
    job_costs,
    pull_requests,
    team_members,
    trunk_merge_queue,
    workflow_jobs,
    workflow_runs,
)

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl


@dataclass(frozen=True, kw_only=True)
class _IssueEventsWindow:
    """The observed issue-event range's edges as scalar subquery strings."""

    start: str
    end: str


@frozen
class DeploySources:
    """The curated deploy pair's ``SELECT`` subqueries, resolved and gated together."""

    deployments: str
    statuses: str


_READY_BY_PR_JOIN = "LEFT JOIN ready_by_pr AS re ON re.pr_number = pr.number"


@dataclass(frozen=True, kw_only=True)
class ReadyToMergeSql:
    """The SQL for reading per-PR ready-to-merge seconds (SPEC §6), in the three pieces a query
    substitutes. They are only valid together: ``cte`` belongs in the query's ``WITH`` list, ``join``
    in its ``FROM`` clause with the PR source aliased ``pr``, and ``expr`` reads the joined row.

    When the optional issue-events table isn't synced ``expr`` degrades to a constant NULL and the
    other two are empty, so a caller substitutes all three unconditionally rather than branching on
    whether the measure is observable.
    """

    cte: str
    join: str
    expr: str

    @property
    def observable(self) -> bool:
        """False when ``expr`` is the constant NULL, so a query whose only output is this measure
        can skip a scan that could return nothing else."""
        return bool(self.cte)

    @property
    def with_clause(self) -> str:
        """``cte`` as a whole ``WITH`` clause, for a query that has no other CTE."""
        return f"WITH {self.cte} " if self.cte else ""

    def median(self, *, scope: str) -> str:
        """The measure's p50 over the rows matching ``scope``. Unobservable degrades to the NULL
        expression itself, not a percentile over it: an aggregate needs a column type to work on,
        and a bare NULL literal has none."""
        return f"quantileIf(0.5)({self.expr}, {scope})" if self.observable else self.expr


_READY_TO_MERGE_UNOBSERVABLE = ReadyToMergeSql(cte="", join="", expr="NULL")


def _ready_to_merge_expr(window: _IssueEventsWindow) -> str:
    """Per-PR ready-to-merge seconds, read off the ``ready_by_pr`` join.

    Last transition is a ready -> merged_at minus it; no transition rows and the PR's whole
    open-to-merge life inside the observed window -> never left ready, so open-to-merge IS
    ready-to-merge; otherwise NULL (re-drafted, or unobservable). Both window bounds are load-
    bearing: created_at before the window means pre-window flips are possible, and merged_at past
    the window means the transitions may simply not have synced yet (every merge lands a `merged`
    issue event, so an in-range merge with no transition rows is proof of never drafting). The
    coalesce guards normalize a missed join, which lands NULL or 0 depending on join_use_nulls.
    """
    return f"""multiIf(
            pr.merged_at IS NULL, NULL,
            coalesce(re.last_is_ready, 0) = 1, dateDiff('second', re.last_transition_at, pr.merged_at),
            coalesce(re.pr_number, 0) = 0
                AND pr.created_at >= {window.start}
                AND pr.merged_at <= {window.end}, pr.open_to_merge_seconds,
            NULL
        )"""


class CuratedGitHubSource:
    """A team's curated GitHub read layer, bound to its resolved warehouse tables.

    Construct once per request with ``for_team`` — it resolves the table names and raises
    ``GitHubSourceNotConnectedError`` when the team has no connected GitHub source, so the
    "is a source connected" decision lives in exactly one place (the resolver). The query
    modules then ask the returned instance for the curated subqueries and run HogQL through it.
    """

    def __init__(
        self, *, team: Team, tables: GitHubTables, user_access_control: "UserAccessControl | None" = None
    ) -> None:
        self._team = team
        self._tables = tables
        self._user_access_control = user_access_control
        self._trunk_table: str | None = None
        self._trunk_table_resolved = False

    @property
    def team(self) -> Team:
        """The team this handle reads for — query builders need it for timezone-aware date parsing."""
        return self._team

    @property
    def repository(self) -> str:
        """The selected source's ``owner/name`` identity for reads outside the warehouse."""
        return self._tables.repository

    @classmethod
    def for_team(
        cls,
        team: Team,
        *,
        source_id: str | None = None,
        repo: str | None = None,
        user_access_control: "UserAccessControl | None" = None,
    ) -> "CuratedGitHubSource":
        return cls(
            team=team,
            tables=resolve_github_tables(
                team=team, source_id=source_id, repo=repo, user_access_control=user_access_control
            ),
            user_access_control=user_access_control,
        )

    def pr_source(self) -> str:
        """Curated pull-requests ``SELECT``, parenthesised for use as a subquery."""
        return f"({pull_requests.build_query(self._tables.pull_requests)})"

    def run_source(self, *, started_floor: bool = False) -> str:
        """Curated workflow-runs ``SELECT``, parenthesised for use as a subquery. ``started_floor``
        adds the raw-string scan floor — callers must register {run_started_floor} (see
        run_started_floor_constant)."""
        query = workflow_runs.build_query(
            self._tables.workflow_runs,
            pull_requests_table=self._tables.pull_requests,
            started_floor=started_floor,
        )
        return f"({query})"

    def jobs_source(self, *, created_floor: bool = False) -> str | None:
        """Curated workflow-jobs ``SELECT`` subquery, or None when the optional jobs table isn't synced.

        ``created_floor`` adds the raw-string scan floor inside the builder — callers must register
        {job_created_floor} (see run_started_floor_constant). A windowed caller needs it: the builder's
        ``is_rerun_copy`` window blocks an outer ``created_at_raw`` predicate from pruning the scan."""
        if not self._tables.workflow_jobs:
            return None
        return f"({workflow_jobs.build_query(self._tables.workflow_jobs, created_floor=created_floor)})"

    def trunk_merge_queue_source(self) -> str | None:
        """Curated Trunk merge-queue ``SELECT`` subquery, or None when no TrunkIo source has the
        opt-in merge-queue endpoint synced (the normal state) or the requesting user can't access
        one; either way consumers degrade to the GitHub-derived proxy. Resolved lazily on first
        call and cached, so probing stays as cheap as the sibling sources."""
        if not self._trunk_table_resolved:
            self._trunk_table = resolve_trunk_merge_queue_table(self._team, self._user_access_control)
            self._trunk_table_resolved = True
        if self._trunk_table is None:
            return None
        return f"({trunk_merge_queue.build_query(self._trunk_table)})"

    def members_source(self) -> str | None:
        """Curated team-membership ``SELECT`` subquery, or None when the optional table isn't synced."""
        if not self._tables.team_members:
            return None
        return f"({team_members.build_query(self._tables.team_members)})"

    def issue_events_source(self) -> str | None:
        """Curated PR draft/ready transitions ``SELECT`` subquery, or None when the optional
        issue-events table isn't synced."""
        if not self._tables.issue_events:
            return None
        return f"({issue_events.build_query(self._tables.issue_events)})"

    def deploy_sources(self) -> "DeploySources | None":
        """The curated deploy ``SELECT`` subqueries, or None when the optional deploy pair isn't
        fully synced. Gated on BOTH tables in one place: a deployment's outcome lives on its
        status rows, so one table without the other can't serve an honest read."""
        if not (self._tables.deployments and self._tables.deployment_statuses):
            return None
        return DeploySources(
            deployments=f"({deployments.build_deployments_query(self._tables.deployments)})",
            statuses=f"({deployments.build_deployment_statuses_query(self._tables.deployment_statuses)})",
        )

    def ready_to_merge_sql(self) -> ReadyToMergeSql:
        """SQL for the per-PR ready-to-merge measure, off the PR source aliased ``pr``. Degrades to
        a constant NULL when the optional issue-events table isn't synced, so every consumer reads
        the measure the same way."""
        window = self._issue_events_window()
        cte = self._ready_by_pr_cte()
        if window is None or cte is None:
            return _READY_TO_MERGE_UNOBSERVABLE
        return ReadyToMergeSql(cte=cte, join=_READY_BY_PR_JOIN, expr=_ready_to_merge_expr(window))

    def _issue_events_window(self) -> "_IssueEventsWindow | None":
        """Scalar subqueries bounding the observed issue-event range, or None when the table
        isn't synced. The desc walk lands a contiguous range, so the min and max landed
        timestamps are its edges; both are NULL over an empty table, so comparisons against
        them are never-true."""
        if not self._tables.issue_events:
            return None
        return _IssueEventsWindow(
            start=f"({issue_events.build_window_start_query(self._tables.issue_events)})",
            end=f"({issue_events.build_window_end_query(self._tables.issue_events)})",
        )

    def _ready_by_pr_cte(self) -> str | None:
        """CTE: each PR's last observed draft-state transition, or None when the table isn't synced.

        Only the LAST switch counts: for a merged PR the newest transition is necessarily the ready
        that preceded the merge (a draft can't merge); an open PR goes false while re-drafted. The
        event id breaks same-second ties (GitHub timestamps are second-coarse). Keyed on
        ``pr_number`` alone, unlike ``runs_by_pr``: a run's association can list the fork network's
        PRs (which is why that rollup needs the repo qualifier), whereas every row of a resolved
        issue-events table belongs to that one repo by table construction.
        """
        source = self.issue_events_source()
        if source is None:
            return None
        return f"""
            ready_by_pr AS (
                SELECT
                    pr_number,
                    argMax(event, tuple(created_at, id)) = '{issue_events.READY_FOR_REVIEW_EVENT}' AS last_is_ready,
                    max(created_at) AS last_transition_at
                FROM {source} AS se
                GROUP BY pr_number
            )
        """

    def job_cost_source(self, *, created_floor: bool = False) -> str | None:
        """Per-job cost ``SELECT`` subquery — the same view body ``engineering_analytics_job_costs``
        exposes, but with the endpoint-only run pass-through columns (``run_started_at`` /
        ``run_head_branch``). None when the jobs table isn't synced, exactly like ``jobs_source``.

        This is the single cost-computation path: ``provider`` / ``os`` / ``vcpu`` / ``billable_seconds``
        / ``estimated_cost_usd`` are rendered from ``logic.cost`` in ClickHouse, so every endpoint cost
        query aggregates the same per-job figures the exposed view (and the parity test) do — there is
        no separate Python cost rollup to drift.

        ``created_floor`` adds the raw-string scan floor inside the jobs builder — callers must
        register {job_created_floor} (see run_windowed_job_created_floor_constant, the right slack for
        the run-windowed predicates every cost query uses). Every windowed caller wants it: the cost
        source's window predicates read the RUN's columns and so can never prune the jobs scan, which
        the ``is_rerun_copy`` window would otherwise sort in full on every call.
        """
        if not self._tables.workflow_jobs:
            return None
        query = job_costs.build_query(
            jobs_table=self._tables.workflow_jobs,
            runs_table=self._tables.workflow_runs,
            include_run_columns=True,
            created_floor=created_floor,
        )
        return f"({query})"

    def runs_cte(self) -> str:
        """CTE materializing the curated workflow-runs source once.

        ``ci_rollup`` and ``runs_by_pr`` both derive from the same runs source; reading them from
        this shared CTE keeps the (JSON- and timestamp-parsing) source to a single scan per query
        instead of inlining — and re-parsing — it once per rollup.
        """
        return f"runs AS {self.run_source()}"

    def ci_rollup_cte(self) -> str:
        """CTE collapsing each head SHA's workflow runs into pass/fail/pending counts.

        Takes the latest run per ``(head_sha, workflow_name)`` via ``argMax`` (a PR's CI status
        is its newest run per workflow), then aggregates per SHA. Reads the shared ``runs`` CTE
        (see ``runs_cte``); ``head_sha`` is the only link between a PR and its CI.
        """
        return f"""
            ci_rollup AS (
                SELECT
                    head_sha,
                    count() AS runs,
                    countIf(s = 'completed' AND c = 'success') AS passing,
                    countIf(s = 'completed' AND c IN ('failure', 'timed_out')) AS failing,
                    -- s IS NULL: run_started_at parses to NULL on a bad/missing timestamp, and argMax
                    -- over an all-NULL group returns NULL — count those as pending, not vanished.
                    countIf(s IS NULL OR s != 'completed') AS pending,
                    -- The names behind `failing`, sorted for a stable order — the UI shows what is
                    -- failing under the CI tag instead of a bare count.
                    arraySort(groupArrayIf(workflow_name, s = 'completed' AND c IN ('failure', 'timed_out'))) AS failing_workflows
                FROM (
                    SELECT
                        head_sha,
                        workflow_name,
                        argMax(status, run_started_at) AS s,
                        argMax(conclusion, run_started_at) AS c
                    FROM runs AS r
                    GROUP BY head_sha, workflow_name
                )
                GROUP BY head_sha
            )
        """

    def pr_rollup_query(self, select: str) -> str:
        """Compose a pull-requests query that reads ``FROM __PR_SOURCE__ AS pr LEFT JOIN ci_rollup``.

        Prefixes ``select`` with the CI rollup CTE and fills its ``__PR_SOURCE__`` placeholder
        with the curated pull-requests source — the two steps the cards and PR-list queries always
        do together.
        """
        return self._compose_pr_query([self.runs_cte(), self.ci_rollup_cte()], select)

    def runs_by_pr_cte(self) -> str:
        """CTE: per-PR activity from the workflow runs attributed to each PR.

        A run records the PR(s) it ran for in ``pull_requests``; the curated run source surfaces
        the first as ``pr_number``. ``pushes`` counts the distinct head SHAs that triggered CI
        (CI triggers), ``rerun_cycles`` the runs that were a 2nd+ attempt. Fork-PR runs have no
        association (``pr_number = 0``) and are excluded.

        Merge-queue gate runs are excluded too, even though the runs builder credits them to the PR
        they were landing. This rollup measures what the *author* did to the PR, and a gate branch's
        head SHA is a rebase the queue made — counting it would report a push nobody made, once per
        merge attempt. Cost and CI-health surfaces keep the gate run; they measure spend and outcomes,
        not authoring activity.

        Keyed on ``(repo_owner, repo_name, pr_number)``, not ``pr_number`` alone: PR numbers
        restart per repository, so the PR-list join is qualified by repo to stay correct — as
        repo-safe as the head-SHA join in ``ci_rollup_cte``. A resolved source is a single repo
        today (the warehouse GitHub source syncs one ``owner/repo``), so the qualifier is a no-op
        now; it keeps the rollup correct if a source ever spans repos, instead of silently
        cross-attributing runs to a same-numbered PR in another repo.
        """
        return f"""
            runs_by_pr AS (
                SELECT
                    repo_owner,
                    repo_name,
                    pr_number,
                    count(DISTINCT head_sha) AS pushes,
                    countIf(run_attempt > 1) AS rerun_cycles
                FROM runs AS r
                WHERE pr_number > 0 AND NOT is_merge_queue
                GROUP BY repo_owner, repo_name, pr_number
            )
        """

    def pr_list_rollup_query(self, select: str) -> str:
        """``pr_rollup_query`` plus the per-PR runs rollup and, when it is observable, the
        ``ready_by_pr`` rollup ``ready_to_merge_sql`` reads."""
        ctes = [self.runs_cte(), self.ci_rollup_cte(), self.runs_by_pr_cte()]
        ready_cte = self.ready_to_merge_sql().cte
        if ready_cte:
            ctes.append(ready_cte)
        return self._compose_pr_query(ctes, select)

    def _compose_pr_query(self, ctes: list[str], select: str) -> str:
        """Prefix ``select`` with the given CTEs and fill its ``__PR_SOURCE__`` placeholder with the PR source."""
        return f"WITH {', '.join(ctes)} {select}".replace("__PR_SOURCE__", self.pr_source())

    def run(
        self,
        sql: str,
        *,
        query_type: str,
        placeholders: dict[str, ast.Expr] | None = None,
        workload: Workload = Workload.DEFAULT,
    ) -> HogQLQueryResponse:
        """Parse + execute a curated HogQL query for this team.

        Mirrors the two paths the data warehouse team intends for ``hogql-warehouse-access-control``
        (#61686). Request-driven reads (the common case — the views thread the requesting user through)
        forward that user so HogQL honors the per-table warehouse ACL: access is enforced twice over —
        the resolver (``for_team``) already filtered the source to what this user may read, and now the
        table-level ACL is honored too, so a user denied a backing ``DataWarehouseTable`` is blocked
        rather than let through. The facade also documents a userless path (``user_access_control=None``)
        for system / Temporal / CLI contexts; that build has no user to honor the ACL with and would fail
        closed (strip every warehouse table), so those reads bypass it — the warehouse team's sanctioned
        escape hatch for userless callers.

        ``workload`` routes the read to a non-default ClickHouse cluster (e.g. ``Workload.LOGS`` for the
        ``logs`` table). The warehouse-ACL reasoning above governs warehouse tables only and is a no-op
        for such reads — those tables carry no per-table ACL, so the ``team_id`` scope is their boundary.
        """
        uac = self._user_access_control
        with tags_context(product=Product.ENGINEERING_ANALYTICS, feature=Feature.QUERY, team_id=self._team.pk):
            return execute_hogql_query(
                query=parse_select(sql, placeholders=placeholders),
                team=self._team,
                query_type=query_type,
                # The logs table lives on a separate ClickHouse cluster (Workload.LOGS); warehouse
                # reads use the default. Callers pass the workload that matches the tables they query.
                workload=workload,
                # Forward the real user, not just the access control: a userless build drops the access
                # control and fails closed (see _compute_system_table_access_decision), so the user is what
                # lets HogQL honor the per-table warehouse ACL.
                user=uac.user if uac is not None else None,
                user_access_control=uac,
                # No user means a system / Temporal / CLI caller (the facade's documented userless path).
                # There is no principal to honor the ACL with, so bypass it rather than fail closed and
                # strip the tables — bypass is set ONLY in this genuinely userless case.
                bypass_warehouse_access_control=uac is None,
            )


def opt_float(value: float | None) -> float | None:
    """ClickHouse aggregate → optional float: quantile/avg over an empty set returns NaN, nullIf None."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)
