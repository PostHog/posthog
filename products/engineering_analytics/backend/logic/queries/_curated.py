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
import hashlib
import threading
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.cache import cache
from django.db import connection

import structlog

from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.metadata import get_table_names
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.hogql_queries.utils.parallel import run_in_parallel_threads
from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import QueryWorkLimitExceededError
from products.engineering_analytics.backend.logic.queries._workflow_filters import DECISIVE_FAILURE_CONCLUSIONS_SQL
from products.engineering_analytics.backend.logic.sources import (
    GitHubTables,
    TrunkQuarantineSource,
    resolve_depot_job_attempts_tables,
    resolve_github_tables,
    resolve_trunk_merge_queue_table,
    resolve_trunk_quarantined_tests_source,
)
from products.engineering_analytics.backend.logic.views import (
    deployments,
    depot_ci,
    issue_events,
    job_costs,
    pull_requests,
    reviews,
    team_members,
    trunk_merge_queue,
    trunk_quarantined_tests,
    workflow_jobs,
    workflow_runs,
)

if TYPE_CHECKING:
    from posthog.models.user import User

    from products.access_control.backend.facade.user_access_control import UserAccessControl

logger = structlog.get_logger(__name__)

_QUERY_PAGE_SIZE = 5000


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
_PUSH_RUN_PREDICATE = "pr_number > 0 AND NOT is_merge_queue"


def push_rows_select(*, runs_source: str, run_filter: str) -> str:
    """One row per authored commit that reached CI. Skipped workflows still prove the push."""
    return f"""
        SELECT pr_number, head_sha, min(coalesce(created_at, run_started_at)) AS pushed_at
        FROM {runs_source} AS r
        WHERE {_PUSH_RUN_PREDICATE} AND ({run_filter})
        GROUP BY pr_number, head_sha
    """


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


READY_TO_MERGE_UNOBSERVABLE = ReadyToMergeSql(cte="", join="", expr="NULL")


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
        self,
        *,
        team: Team,
        tables: GitHubTables,
        user_access_control: "UserAccessControl | None" = None,
        query_limit: int | None = None,
    ) -> None:
        self._team = team
        self._tables = tables
        self._user_access_control = user_access_control
        self._queries_remaining = query_limit
        self._trunk_table: str | None = None
        self._trunk_table_resolved = False
        self._trunk_quarantine_source: TrunkQuarantineSource | None = None
        self._trunk_quarantine_resolved = False
        self._depot_job_attempts_table: depot_ci.DepotJobAttempts | None = None
        self._depot_job_attempts_resolved = False
        self._database: Database | None = None
        # Guards the query budget, the catalog and the lazily resolved sources, which concurrent reads share.
        self._lock = threading.Lock()

    @property
    def team(self) -> Team:
        """The team this handle reads for — query builders need it for timezone-aware date parsing."""
        return self._team

    @property
    def repository(self) -> str:
        """The selected source's ``owner/name`` identity for reads outside the warehouse."""
        return self._tables.repository

    @property
    def source_id(self) -> str:
        """The selected source, which the resolver already filtered by the caller's access.

        A read outside the warehouse that needs a GitHub credential takes it from this source, so
        it never reads with a credential of a source the caller is not allowed to use.
        """
        return self._tables.source_id

    @classmethod
    def for_team(
        cls,
        team: Team,
        *,
        source_id: str | None = None,
        repo: str | None = None,
        user_access_control: "UserAccessControl | None" = None,
        query_limit: int | None = None,
    ) -> "CuratedGitHubSource":
        return cls(
            team=team,
            tables=resolve_github_tables(
                team=team, source_id=source_id, repo=repo, user_access_control=user_access_control
            ),
            user_access_control=user_access_control,
            query_limit=query_limit,
        )

    def pr_source(self) -> str:
        """Curated pull-requests ``SELECT``, parenthesised for use as a subquery."""
        return f"({pull_requests.build_query(self._tables.pull_requests)})"

    def run_source(self, *, started_floor: bool = False) -> str:
        """Curated workflow-runs ``SELECT``, parenthesised for use as a subquery. ``started_floor``
        adds the raw-string scan floor — callers must register {run_started_floor} (see
        run_started_floor_constant)."""
        query = workflow_runs.build_query(
            self._runs_table(),
            pull_requests_table=self._tables.pull_requests,
            started_floor=started_floor,
        )
        return f"({query})"

    def jobs_source(self, *, created_floor: bool = False) -> str | None:
        """Curated workflow-jobs ``SELECT`` subquery, or None when the optional jobs table isn't synced.

        ``created_floor`` adds the raw-string scan floor inside the builder — callers must register
        {job_created_floor} (see run_started_floor_constant). A windowed caller needs it: the builder's
        ``is_rerun_copy`` duplicate scan reads no ``created_at_raw``, so only the floor bounds it."""
        if not self._tables.workflow_jobs:
            return None
        return (
            f"({workflow_jobs.build_query(self._jobs_table(self._tables.workflow_jobs), created_floor=created_floor)})"
        )

    def _depot_job_attempts(self) -> depot_ci.DepotJobAttempts | None:
        """The repository's synced Depot CI job attempts, or None. Resolved lazily and cached like the
        Trunk tables, so a read that never touches CI pays no lookup."""
        with self._lock:
            if not self._depot_job_attempts_resolved:
                depot_tables = resolve_depot_job_attempts_tables(self._team, self._user_access_control)
                self._depot_job_attempts_table = depot_tables.get(self.repository.casefold())
                self._depot_job_attempts_resolved = True
            return self._depot_job_attempts_table

    def _runs_table(self) -> str:
        return depot_ci.with_depot_runs(
            self._tables.workflow_runs,
            self._depot_job_attempts(),
            self._tables.pull_requests,
            self._tables.workflow_jobs,
        )

    def _jobs_table(self, workflow_jobs_table: str) -> workflow_jobs.JobsTable:
        return depot_ci.with_depot_jobs(workflow_jobs_table, self._depot_job_attempts(), self._tables.workflow_runs)

    def trunk_merge_queue_source(self) -> str | None:
        """Curated Trunk merge-queue ``SELECT`` subquery, or None when no TrunkIo source has the
        opt-in merge-queue endpoint synced (the normal state) or the requesting user can't access
        one; either way consumers degrade to the GitHub-derived proxy. Resolved lazily on first
        call and cached, so probing stays as cheap as the sibling sources."""
        with self._lock:
            if not self._trunk_table_resolved:
                self._trunk_table = resolve_trunk_merge_queue_table(self._team, self._user_access_control)
                self._trunk_table_resolved = True
        if self._trunk_table is None:
            return None
        return f"({trunk_merge_queue.build_query(self._trunk_table)})"

    def _trunk_quarantine(self) -> "TrunkQuarantineSource | None":
        with self._lock:
            if not self._trunk_quarantine_resolved:
                self._trunk_quarantine_source = resolve_trunk_quarantined_tests_source(
                    self._team, self.repository, self._user_access_control
                )
                self._trunk_quarantine_resolved = True
            return self._trunk_quarantine_source

    def trunk_quarantined_tests_source(self) -> str | None:
        """Curated Trunk quarantined-tests ``SELECT`` subquery, or None when no TrunkIo source has
        the QuarantinedTests endpoint synced or the requesting user can't access one; consumers
        degrade to ``available: false``. Lazily resolved and cached like the merge-queue sibling."""
        source = self._trunk_quarantine()
        if source is None:
            return None
        return f"({trunk_quarantined_tests.build_query(source.table)})"

    def trunk_org_url_slug(self) -> str | None:
        """The TrunkIo source's org slug, for links into the Trunk app; None when unsynced or unset."""
        source = self._trunk_quarantine()
        return source.org_url_slug if source else None

    def members_source(self) -> str | None:
        """Curated team-membership ``SELECT`` subquery, or None when the optional table isn't synced."""
        if not self._tables.team_members:
            return None
        return f"({team_members.build_query(self._tables.team_members)})"

    def issue_events_source(self, *, created_floor: bool = False) -> str | None:
        """Curated PR draft/ready transitions ``SELECT`` subquery, or None when the optional
        issue-events table isn't synced. ``created_floor`` adds the raw-string scan floor, so callers
        must register {event_created_floor} (see ``run_started_floor_constant``)."""
        if not self._tables.issue_events:
            return None
        return f"({issue_events.build_query(self._tables.issue_events, created_floor=created_floor)})"

    def team_review_requests_source(self, *, created_floor: bool = False) -> str | None:
        """Curated team review requests ``SELECT`` subquery, or None when the issue events hold none.
        ``created_floor`` adds the raw-string scan floor; callers must then register {event_created_floor}
        (see run_started_floor_constant)."""
        if not (self._tables.issue_events and self._tables.issue_events_team_requests):
            return None
        query = issue_events.build_team_review_requests_query(self._tables.issue_events, created_floor=created_floor)
        return f"({query})"

    def reviews_source(self) -> str | None:
        """Curated submitted-reviews ``SELECT`` subquery, or None when the optional reviews table
        isn't synced."""
        if not self._tables.reviews:
            return None
        return f"({reviews.build_query(self._tables.reviews)})"

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
        cte = self.ready_by_pr_cte()
        if window is None or cte is None:
            return READY_TO_MERGE_UNOBSERVABLE
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

    def ready_by_pr_cte(self, *, created_floor: bool = False) -> str | None:
        """CTE: each PR's last observed draft-state transition and last ready event, or None when the
        table isn't synced. ``created_floor`` works as in ``issue_events_source``.

        Only the LAST switch counts: for a merged PR the newest transition is necessarily the ready
        that preceded the merge (a draft can't merge); an open PR goes false while re-drafted. The
        event id breaks same-second ties (GitHub timestamps are second-coarse). Keyed on
        ``pr_number`` alone, unlike the push-activity query in ``pull_request_list``: a run's association
        can list the fork network's PRs (which is why that query needs the repo qualifier), whereas every row of a resolved
        issue-events table belongs to that one repo by table construction.

        The events table and the pull requests table sync independently, so a timestamp here can run
        ahead of what a PR's own row reports. A consumer that compares one against a PR's end must
        bound it. ``last_ready_at`` is safe against ``merged_at`` alone, because a draft cannot merge.
        """
        source = self.issue_events_source(created_floor=created_floor)
        if source is None:
            return None
        return f"""
            ready_by_pr AS (
                SELECT
                    pr_number,
                    argMax(event, tuple(created_at, id)) = '{issue_events.READY_FOR_REVIEW_EVENT}' AS last_is_ready,
                    max(created_at) AS last_transition_at,
                    -- OrNull, not maxIf: a plain maxIf falls back to the epoch default when no row
                    -- matches, and that default would pass the caller's last_ready_at IS NOT NULL
                    -- filter as if it were a real event (see dora.py's deploys CTE for the same hazard).
                    maxOrNullIf(created_at, event = '{issue_events.READY_FOR_REVIEW_EVENT}') AS last_ready_at
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
        source's window predicates read the RUN's columns and so can never prune the jobs scan, and
        the ``is_rerun_copy`` duplicate scan would otherwise aggregate the full history on every call.
        """
        if not self._tables.workflow_jobs:
            return None
        query = job_costs.build_query(
            jobs_table=self._jobs_table(self._tables.workflow_jobs),
            runs_table=self._runs_table(),
            include_run_columns=True,
            created_floor=created_floor,
        )
        return f"({query})"

    def runs_cte(self) -> str:
        """CTE naming the curated workflow-runs source for ``ci_rollup``.

        ClickHouse inlines a CTE at every reference, so each extra reader of ``runs`` scans and
        parses the whole runs source again.
        """
        return f"runs AS {self.run_source()}"

    def _pr_scope_cte(self, pr_scope_where: str) -> str:
        """CTE: the number and head SHA of PRs matching ``pr_scope_where`` (a predicate over
        unqualified curated PR columns).

        The CI rollup only ever joins back to PRs the consuming query keeps, so it
        prefilters the runs scan to this set. Unscoped, it aggregates the team's whole
        run history — millions of ``(head_sha, workflow)`` groups on a busy repo — and
        the query runs out of memory before the join discards almost all of it.
        """
        return f"pr_scope AS (SELECT number, head_sha FROM {self.pr_source()} AS scope_pr WHERE {pr_scope_where})"

    def ci_rollup_cte(self) -> str:
        """CTE collapsing each head SHA's workflow runs into pass/fail/pending counts.

        Takes the latest run per ``(head_sha, workflow_name)`` via ``argMax`` (a PR's CI status
        is its newest run per workflow), then aggregates per SHA. Reads the shared ``runs`` CTE
        (see ``runs_cte``); ``head_sha`` is the only link between a PR and its CI. Scoped to the
        ``pr_scope`` CTE the composing query adds (see ``_pr_scope_cte``).
        """
        return f"""
            ci_rollup AS (
                SELECT
                    head_sha,
                    count() AS runs,
                    countIf(s = 'completed' AND c = 'success') AS passing,
                    countIf(s = 'completed' AND c IN ({DECISIVE_FAILURE_CONCLUSIONS_SQL})) AS failing,
                    -- s IS NULL: run_started_at parses to NULL on a bad/missing timestamp, and argMax
                    -- over an all-NULL group returns NULL — count those as pending, not vanished.
                    countIf(s IS NULL OR s != 'completed') AS pending,
                    -- Completes the partition, so an all-cancelled PR is not read as passing.
                    countIf(
                        s = 'completed'
                        AND ifNull(c, '') NOT IN ('success', {DECISIVE_FAILURE_CONCLUSIONS_SQL})
                    ) AS inconclusive,
                    -- The names behind `failing`, sorted for a stable order — the UI shows what is
                    -- failing under the CI tag instead of a bare count.
                    arraySort(groupArrayIf(workflow_name, s = 'completed' AND c IN ({DECISIVE_FAILURE_CONCLUSIONS_SQL}))) AS failing_workflows
                FROM (
                    SELECT
                        head_sha,
                        workflow_name,
                        argMax(status, run_started_at) AS s,
                        argMax(conclusion, run_started_at) AS c
                    FROM runs AS r
                    WHERE head_sha IN (SELECT head_sha FROM pr_scope)
                    GROUP BY head_sha, workflow_name
                )
                GROUP BY head_sha
            )
        """

    def pr_rollup_query(
        self, select: str, *, pr_scope_where: str, ready: ReadyToMergeSql = READY_TO_MERGE_UNOBSERVABLE
    ) -> str:
        """Compose a pull-requests query that reads ``FROM __PR_SOURCE__ AS pr LEFT JOIN ci_rollup``.

        Prefixes ``select`` with the ``pr_scope`` and CI rollup CTEs, and the CTE of the ``ready``
        measure when ``select`` reads it, and fills its ``__PR_SOURCE__`` placeholder with the
        curated pull-requests source. The cards and PR-list queries always do these steps together.
        ``pr_scope_where`` must keep every PR the ``select`` reads CI for (it prunes the rollup scan,
        see ``_pr_scope_cte``); a PR outside it joins as if it had no runs.
        """
        ctes = [self.runs_cte(), self._pr_scope_cte(pr_scope_where), self.ci_rollup_cte()]
        if ready.cte:
            ctes.append(ready.cte)
        return self._compose_pr_query(ctes, select)

    def _compose_pr_query(self, ctes: list[str], select: str) -> str:
        """Prefix ``select`` with the given CTEs and fill its ``__PR_SOURCE__`` placeholder with the PR source."""
        return f"WITH {', '.join(ctes)} {select}".replace("__PR_SOURCE__", self.pr_source())

    @contextmanager
    def concurrent_reads(self) -> Iterator["ConcurrentReads"]:
        """Run the reads submitted inside the block together when it exits, so a request waits for
        its slowest read instead of the sum of all of them. Read each result after the block."""
        reads = ConcurrentReads()
        yield reads
        reads.run()

    def run_paged(
        self,
        sql: str,
        *,
        page_key: tuple[tuple[str, int], ...],
        query_type: str,
        placeholders: dict[str, ast.Expr],
    ) -> list[tuple]:
        """Read every row by an immutable unique key, without the per-query result cap."""
        rows: list[tuple] = []
        cursor: tuple[object, ...] | None = None
        key_columns = [column for column, _index in page_key]
        order_by = ", ".join(key_columns)
        while True:
            cursor_filter = ""
            page_placeholders = placeholders
            if cursor is not None:
                cursor_names = [f"paged_after_{index}" for index in range(len(cursor))]
                left = key_columns[0] if len(key_columns) == 1 else f"({', '.join(key_columns)})"
                right = (
                    f"{{{cursor_names[0]}}}"
                    if len(cursor_names) == 1
                    else f"({', '.join(f'{{{name}}}' for name in cursor_names)})"
                )
                cursor_filter = f"WHERE {left} > {right}"
                page_placeholders = {
                    **placeholders,
                    **{name: ast.Constant(value=value) for name, value in zip(cursor_names, cursor, strict=True)},
                }
            response = self.run(
                f"SELECT * FROM ({sql}) AS paged\n{cursor_filter}\nORDER BY {order_by}\nLIMIT {_QUERY_PAGE_SIZE}",
                query_type=query_type,
                placeholders=page_placeholders,
            )
            page = list(response.results or [])
            rows.extend(page)
            if len(page) < _QUERY_PAGE_SIZE:
                return rows
            cursor = tuple(page[-1][index] for _column, index in page_key)

    @property
    def _user(self) -> "User | None":
        return self._user_access_control.user if self._user_access_control is not None else None

    @property
    def _bypass_warehouse_access_control(self) -> bool:
        return self._user_access_control is None

    def _catalog(self) -> Database:
        with self._lock:
            if self._database is None:
                self._database = Database.create_for(
                    team=self._team,
                    user=self._user,
                    user_access_control=self._user_access_control,
                    modifiers=create_default_modifiers_for_team(self._team),
                    bypass_warehouse_access_control=self._bypass_warehouse_access_control,
                    trigger="engineering_analytics",
                )
            return self._database

    def read_through[V](
        self, *, sql: str, keys: Sequence[int], load: Callable[[list[int]], dict[int, V]], ttl_seconds: int
    ) -> dict[int, V]:
        """``load``'s value for every key, reusing values another request computed in the last
        ``ttl_seconds``. ``load`` gets the keys with no cached value and must return one for each.

        ``sql`` is the query ``load`` runs, before its placeholders. Its hash names the cache, so a
        change to that query, the prices it renders or the tables it resolves starts a fresh one. A
        cached value is served only when this reader's catalog grants every table that query reads,
        the decision the query itself would get. A cache that fails to answer loads every key.
        """
        prefix = f"engineering_analytics:{self._team.pk}:{hashlib.sha256(sql.encode()).hexdigest()}"
        cache_keys = {key: f"{prefix}:{key}" for key in keys}
        cached: dict[str, V] = {}
        if self._may_read_every_table_in(sql):
            try:
                cached = cache.get_many(list(cache_keys.values()))
            except Exception:
                logger.warning("engineering_analytics_cache_read_failed", exc_info=True)
        values = {key: cached[cache_key] for key, cache_key in cache_keys.items() if cache_key in cached}
        missing = [key for key in keys if key not in values]
        if not missing:
            return values
        loaded = load(missing)
        try:
            cache.set_many({cache_keys[key]: value for key, value in loaded.items()}, timeout=ttl_seconds)
        except Exception:
            logger.warning("engineering_analytics_cache_write_failed", exc_info=True)
        return {**values, **loaded}

    def _may_read_every_table_in(self, sql: str) -> bool:
        # The rule HogQL's own query cache applies: posthog/hogql/ACCESS_CONTROL.md, "Query cache partitioning".
        catalog = self._catalog()
        return all(
            catalog.has_table(table) and not catalog.is_table_access_denied(table)
            for table in get_table_names(parse_select(sql))
        )

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
        with self._lock:
            if self._queries_remaining is not None:
                if self._queries_remaining <= 0:
                    raise QueryWorkLimitExceededError
                self._queries_remaining -= 1
        uac = self._user_access_control
        user = self._user
        bypass_warehouse_access_control = self._bypass_warehouse_access_control
        database = self._catalog()
        with tags_context(product=Product.ENGINEERING_ANALYTICS, feature=Feature.QUERY, team_id=self._team.pk):
            return execute_hogql_query(
                query=parse_select(sql, placeholders=placeholders),
                team=self._team,
                query_type=query_type,
                # The logs table lives on a separate ClickHouse cluster (Workload.LOGS); warehouse
                # reads use the default. Callers pass the workload that matches the tables they query.
                workload=workload,
                user=user,
                user_access_control=uac,
                bypass_warehouse_access_control=bypass_warehouse_access_control,
                context=HogQLContext(
                    team_id=self._team.pk,
                    user=user,
                    user_access_control=uac,
                    bypass_warehouse_access_control=bypass_warehouse_access_control,
                    database=database,
                ),
            )


class ConcurrentReads:
    """Each worker closes the Postgres connection it opens. Under TEST the reads run inline, because a
    worker's connection cannot see the test transaction."""

    def __init__(self) -> None:
        self._work: list[Callable[[], None]] = []

    def submit[T](self, read: Callable[[], T]) -> "Future[T]":
        future: Future[T] = Future()

        def run_read() -> None:
            try:
                future.set_result(read())
            except Exception as error:
                future.set_exception(error)
                raise

        self._work.append(run_read)
        return future

    def run(self) -> None:
        if settings.TEST:
            errors: list[Exception] = []
            for work in self._work:
                try:
                    work()
                except Exception as error:
                    errors.append(error)
            if errors:
                raise errors[0]
            return
        run_in_parallel_threads(
            [partial(_closing_connection, work) for work in self._work],
            thread_name_prefix="engineering_analytics",
        )


def _closing_connection(work: Callable[[], None]) -> None:
    try:
        work()
    finally:
        connection.close()


def opt_float(value: float | None) -> float | None:
    """ClickHouse aggregate → optional float: quantile/avg over an empty set returns NaN, nullIf None."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)
