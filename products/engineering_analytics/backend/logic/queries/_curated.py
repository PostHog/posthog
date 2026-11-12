"""The curated read layer over a team's resolved GitHub warehouse tables.

Every SQL fragment is built from trusted constants and resolved table identifiers. User-supplied
values must go through ``ast.Constant`` placeholders, never string substitution.
"""

import math
import hashlib
import threading
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING, Literal

from django.conf import settings
from django.core.cache import cache
from django.db import connections

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

from products.engineering_analytics.backend.facade.contracts import CIDataFreshness, QueryWorkLimitExceededError
from products.engineering_analytics.backend.logic import merge_queue
from products.engineering_analytics.backend.logic.materialized_ci import MaterializedCI, ci_tables
from products.engineering_analytics.backend.logic.queries._workflow_filters import DECISIVE_FAILURE_CONCLUSIONS_SQL
from products.engineering_analytics.backend.logic.sources import (
    GitHubTables,
    TrunkQuarantineSource,
    resolve_ci_data_freshness,
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
_GITHUB_RUN_IDS = "ea_github_run_ids"
_DEPOT_RUN_IDS = "ea_depot_run_ids"


def _scope_github_table(table: str, column: Literal["id", "run_id"], *, scoped: bool) -> str:
    if not scoped:
        return table
    # The bounds let the Parquet scan prune, which the IN set alone cannot do.
    bounds = f"{column} >= arrayMin({_GITHUB_RUN_IDS}) AND {column} <= arrayMax({_GITHUB_RUN_IDS})"
    membership = f"{column} IN (SELECT arrayJoin({_GITHUB_RUN_IDS}))"
    # Rows with a NULL id stay, so the prefilter never discards a row the builders could attribute.
    return f"(SELECT * FROM {table} WHERE (({bounds} AND {membership}) OR {column} IS NULL))"


@dataclass(frozen=True, kw_only=True)
class _IssueEventsWindow:
    """The observed issue-event range's edges as scalar subquery strings."""

    start: str
    end: str


@frozen
class DeploySources:
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
    """The SQL for per-PR ready-to-merge seconds, in three pieces that are valid only together.

    ``cte`` goes in the ``WITH`` list, ``join`` in the ``FROM`` clause with the PR source aliased
    ``pr``, and ``expr`` reads the joined row. When the issue-events table isn't synced, ``expr`` is
    a constant NULL and the other two are empty, so a caller can substitute all three unconditionally.
    """

    cte: str
    join: str
    expr: str

    @property
    def observable(self) -> bool:
        """False when ``expr`` is the constant NULL."""
        return bool(self.cte)

    @property
    def with_clause(self) -> str:
        """``cte`` as a whole ``WITH`` clause, for a query that has no other CTE."""
        return f"WITH {self.cte} " if self.cte else ""

    def median(self, *, scope: str) -> str:
        """The measure's p50 over the rows matching ``scope``, or the bare NULL when unobservable,
        because an aggregate cannot type a NULL literal."""
        return f"quantileIf(0.5)({self.expr}, {scope})" if self.observable else self.expr


READY_TO_MERGE_UNOBSERVABLE = ReadyToMergeSql(cte="", join="", expr="NULL")


def _ready_to_merge_expr(window: _IssueEventsWindow) -> str:
    """Per-PR ready-to-merge seconds, read off the ``ready_by_pr`` join.

    A PR with no transition rows was never a draft only when its whole open-to-merge span lies
    inside the observed window. A PR created before the window may have changed state unobserved,
    and one merged after it may have transitions that have not synced. A missed join lands NULL or
    0 depending on join_use_nulls, so the coalesce accepts both.
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
    """A team's curated GitHub read layer, bound to its resolved warehouse tables. Construct it once
    per request with ``for_team``, which raises when the team has no connected GitHub source."""

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
        self._materialized_ci: MaterializedCI | None = None
        self._materialized_ci_resolved = False
        # Guards the query budget, the catalog and the lazily resolved sources, which concurrent reads share.
        self._lock = threading.Lock()

    @property
    def team(self) -> Team:
        return self._team

    @property
    def repository(self) -> str:
        """The selected source's ``owner/name``."""
        return self._tables.repository

    @property
    def source_id(self) -> str:
        """The selected source, which the resolver already filtered by the caller's access.
        A read that needs a GitHub credential must take it from this source."""
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
        return f"({pull_requests.build_query(self._tables.pull_requests)})"

    def run_source(
        self,
        *,
        started_floor: bool = False,
        since: datetime | None = None,
        live: bool = False,
        scoped: bool = False,
    ) -> str:
        """Curated workflow-runs ``SELECT``, parenthesised for use as a subquery.

        ``started_floor`` adds the raw-string scan floor, and the caller must register
        {run_started_floor} (see ``run_started_floor_constant``). ``since`` is the read's window
        start: the stored rows serve the read only when they cover it, and never when it is None.
        ``live`` always reads the raw tables. ``scoped`` bounds every raw CI scan to the runs the
        query names, and the caller must wrap the query in ``scoped_to_run`` or
        ``scoped_to_pr_history``."""
        if not live and (stored := self._stored_ci_covering(since)):
            return f"({stored.runs(started_floor=started_floor)})"
        query = workflow_runs.build_query(
            self._runs_table(scoped=scoped),
            pull_requests_table=self._tables.pull_requests,
            started_floor=started_floor,
        )
        return f"({query})"

    def jobs_source(
        self,
        *,
        created_floor: bool = False,
        since: datetime | None = None,
        include_steps: bool = False,
        scoped: bool = False,
    ) -> str | None:
        """Curated workflow-jobs ``SELECT`` subquery, or None when the optional jobs table isn't synced.

        ``created_floor`` adds the raw-string scan floor, and the caller must register
        {job_created_floor} (see ``job_created_floor_constant``). A windowed caller needs it, because
        nothing else bounds the builder's ``is_rerun_copy`` duplicate scan. ``since`` and ``scoped``
        work as for ``run_source``. ``include_steps`` appends the raw ``steps`` JSON column and
        always reads the raw tables."""
        if not self._tables.workflow_jobs:
            return None
        if not include_steps and (stored := self._stored_ci_covering(since)):
            return f"({stored.jobs(created_floor=created_floor)})"
        query = workflow_jobs.build_query(
            self._jobs_table(self._tables.workflow_jobs, scoped=scoped),
            created_floor=created_floor,
            include_steps=include_steps,
        )
        return f"({query})"

    def _depot_job_attempts(self, *, scoped: bool = False) -> depot_ci.DepotJobAttempts | None:
        """The repository's synced Depot CI job attempts, or None."""
        with self._lock:
            if not self._depot_job_attempts_resolved:
                depot_tables = resolve_depot_job_attempts_tables(self._team, self._user_access_control)
                self._depot_job_attempts_table = depot_tables.get(self.repository.casefold())
                self._depot_job_attempts_resolved = True
            depot = self._depot_job_attempts_table
        if depot is None or not scoped:
            return depot
        # The scope keeps whole native runs, because the builders link a run's jobs and workflows.
        return replace(
            depot,
            table=f"(SELECT * FROM {depot.table} "
            f"WHERE run_id IN (SELECT arrayJoin({_DEPOT_RUN_IDS})) OR run_id IS NULL)",
        )

    def _runs_table(self, *, scoped: bool = False) -> str:
        runs = _scope_github_table(self._tables.workflow_runs, "id", scoped=scoped)
        jobs = (
            _scope_github_table(self._tables.workflow_jobs, "run_id", scoped=scoped)
            if self._tables.workflow_jobs is not None
            else None
        )
        return depot_ci.with_depot_runs(
            runs,
            self._depot_job_attempts(scoped=scoped),
            self._tables.pull_requests,
            jobs,
            optional_columns=self._tables.workflow_runs_optional_columns,
            prescoped=scoped,
        )

    def ci_read_scope(self) -> str:
        """Names the tables a CI read of this handle uses, for a cache key. It includes the Depot table,
        so a caller with no access to the Depot source never gets an answer cached from Depot rows."""
        depot = self._depot_job_attempts()
        scope = f"{self._tables.workflow_runs}|{self._tables.workflow_jobs or ''}|{depot.table if depot else ''}"
        stored = self._stored_ci()
        return f"{scope}|{stored.cache_scope}" if stored else scope

    def may_read_ci_tables(self) -> bool:
        """Whether this reader's catalog grants every table a CI read uses. A caller must check this
        before it serves a cached CI answer, which skips the query that applies the permissions."""
        catalog = self._catalog()
        return all(
            catalog.has_table(table) and not catalog.is_table_access_denied(table)
            for table in ci_tables(self._tables, self._depot_job_attempts())
        )

    def ci_data_freshness(self) -> CIDataFreshness:
        """When the runs and jobs this handle reads were last synced from their sources."""
        if stored := self._stored_ci():
            return stored.freshness
        return resolve_ci_data_freshness(
            team=self._team, tables=self._tables, user_access_control=self._user_access_control
        )

    def _stored_ci_covering(self, since: datetime | None) -> MaterializedCI | None:
        # An unbounded read cannot use the stored rows, so it skips the database lookup that resolves them.
        if since is None:
            return None
        stored = self._stored_ci()
        return stored if stored is not None and stored.covers(since) else None

    def _stored_ci(self) -> MaterializedCI | None:
        catalog = self._catalog()
        depot = self._depot_job_attempts()
        with self._lock:
            if not self._materialized_ci_resolved:
                self._materialized_ci = MaterializedCI.resolve(
                    team=self._team, tables=self._tables, depot=depot, catalog=catalog
                )
                self._materialized_ci_resolved = True
            return self._materialized_ci

    def _run_scope_ctes(self, github_run_ids: str, depot_runs_where: str) -> list[str]:
        """The run sets a ``scoped`` source reads. ``github_run_ids`` selects one array of raw GitHub
        run ids, and ``depot_runs_where`` picks the raw Depot attempts whose native runs stay.
        The sets are conservative, and the builders still decide exact PR and queue attribution."""
        ctes = [f"({github_run_ids}) AS {_GITHUB_RUN_IDS}"]
        if depot := self._depot_job_attempts():
            ctes.append(
                f"(SELECT groupUniqArray(run_id) FROM {depot.table} WHERE {depot_runs_where}) AS {_DEPOT_RUN_IDS}"
            )
        return ctes

    def scoped_to_run(self, sql: str) -> str:
        """Bound the ``scoped`` sources of ``sql`` to the run {run_id}, which the caller registers."""
        run_head_sha = f"SELECT head_sha FROM {self._tables.workflow_runs} WHERE id = {{run_id}}"
        ctes = self._run_scope_ctes(
            "SELECT [{run_id}]",
            f"{depot_ci.github_run_id_expr()} = {{run_id}} OR {depot_ci.head_sha_expr()} IN ({run_head_sha})",
        )
        return f"WITH {', '.join(ctes)} {sql}"

    def scoped_to_pr_history(self, sql: str) -> str:
        """Bound the ``scoped`` sources of ``sql`` to the CI of {pr_numbers}, which the caller registers.

        The sets have no date bound, because CI associated with a PR can predate the PR's creation."""
        # toInt keeps the set Int64, so a set of small numbers does not narrow the compared column.
        numbers = "SELECT arrayJoin(arrayMap(number -> toInt(number), {pr_numbers}))"
        association = workflow_runs.ASSOCIATION_PR_NUMBER
        github_runs = _scope_github_table(self._tables.workflow_runs, "id", scoped=True)
        gate_source_pr = merge_queue.source_pr_number_expr(
            "JSONExtractString(ifNull(head, '{}'), 'ref')",
            queue_actor_column="JSONExtractString(ifNull(user, '{}'), 'login')",
        )
        # A Depot gate run's ref names the queue's throwaway PR. The PR snapshot maps it to the PR being
        # landed, and the GitHub gate run's association names it before that snapshot row syncs.
        ctes = self._run_scope_ctes(
            f"""SELECT groupUniqArray(id) FROM {self._tables.workflow_runs}
                WHERE {association} IN ({numbers}) OR {workflow_runs.MERGE_QUEUE_PR_NUMBER} IN ({numbers})""",
            f"""{depot_ci.ref_pr_number_expr("ref")} IN (
                {numbers}
                UNION ALL
                SELECT number FROM {self._tables.pull_requests} WHERE {gate_source_pr} IN ({numbers})
                UNION ALL
                SELECT {association} FROM {github_runs} WHERE {association} > 0
            )""",
        )
        return f"WITH {', '.join(ctes)} {sql}"

    def _jobs_table(self, workflow_jobs_table: str, *, scoped: bool = False) -> workflow_jobs.JobsTable:
        jobs = _scope_github_table(workflow_jobs_table, "run_id", scoped=scoped)
        runs = _scope_github_table(self._tables.workflow_runs, "id", scoped=scoped)
        return depot_ci.with_depot_jobs(jobs, self._depot_job_attempts(scoped=scoped), runs, prescoped=scoped)

    def trunk_merge_queue_source(self) -> str | None:
        """Curated Trunk merge-queue ``SELECT`` subquery, or None when no TrunkIo source has the
        merge-queue endpoint synced or the requesting user can't access one."""
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
        the QuarantinedTests endpoint synced or the requesting user can't access one."""
        source = self._trunk_quarantine()
        if source is None:
            return None
        return f"({trunk_quarantined_tests.build_query(source.table, v2_shape=source.v2_shape)})"

    def trunk_org_url_slug(self) -> str | None:
        """The TrunkIo source's org slug, for links into the Trunk app; None when unsynced or unset."""
        source = self._trunk_quarantine()
        return source.org_url_slug if source else None

    def trunk_quarantined_tests_v2_shape(self) -> bool:
        """Whether the synced quarantined-tests table holds the v2 API shape, which carries each
        test's Trunk URL; False when unsynced."""
        source = self._trunk_quarantine()
        return source.v2_shape if source else False

    def members_source(self) -> str | None:
        """Curated team-membership ``SELECT`` subquery, or None when the optional table isn't synced."""
        if not self._tables.team_members:
            return None
        return f"({team_members.build_query(self._tables.team_members)})"

    def issue_events_source(self, *, created_floor: bool = False) -> str | None:
        """Curated PR draft and ready transitions ``SELECT`` subquery, or None when the issue-events
        table isn't synced. ``created_floor`` adds the raw-string scan floor, and the caller must
        register {event_created_floor} (see ``run_started_floor_constant``)."""
        if not self._tables.issue_events:
            return None
        return f"({issue_events.build_query(self._tables.issue_events, created_floor=created_floor)})"

    def team_review_requests_source(self, *, created_floor: bool = False) -> str | None:
        """Curated team review requests ``SELECT`` subquery, or None when the issue events hold none.
        ``created_floor`` works as in ``issue_events_source``."""
        if not (self._tables.issue_events and self._tables.issue_events_team_requests):
            return None
        query = issue_events.build_team_review_requests_query(self._tables.issue_events, created_floor=created_floor)
        return f"({query})"

    def reviews_source(self) -> str | None:
        """Curated submitted-reviews ``SELECT`` subquery, or None when the reviews table isn't synced."""
        if not self._tables.reviews:
            return None
        return f"({reviews.build_query(self._tables.reviews)})"

    def deploy_sources(self) -> "DeploySources | None":
        """The curated deploy ``SELECT`` subqueries, or None unless both deploy tables are synced.
        A deployment's outcome lives on its status rows, so one table alone cannot serve a read."""
        if not (self._tables.deployments and self._tables.deployment_statuses):
            return None
        return DeploySources(
            deployments=f"({deployments.build_deployments_query(self._tables.deployments)})",
            statuses=f"({deployments.build_deployment_statuses_query(self._tables.deployment_statuses)})",
        )

    def ready_to_merge_sql(self) -> ReadyToMergeSql:
        """SQL for the per-PR ready-to-merge measure, ``READY_TO_MERGE_UNOBSERVABLE`` when the
        issue-events table isn't synced."""
        window = self._issue_events_window()
        cte = self.ready_by_pr_cte()
        if window is None or cte is None:
            return READY_TO_MERGE_UNOBSERVABLE
        return ReadyToMergeSql(cte=cte, join=_READY_BY_PR_JOIN, expr=_ready_to_merge_expr(window))

    def _issue_events_window(self) -> "_IssueEventsWindow | None":
        """Scalar subqueries bounding the observed issue-event range, or None when the table
        isn't synced. Both are NULL over an empty table, so a comparison against them is never true."""
        if not self._tables.issue_events:
            return None
        return _IssueEventsWindow(
            start=f"({issue_events.build_window_start_query(self._tables.issue_events)})",
            end=f"({issue_events.build_window_end_query(self._tables.issue_events)})",
        )

    def ready_by_pr_cte(self, *, created_floor: bool = False) -> str | None:
        """CTE: each PR's last observed draft-state transition and last ready event, or None when the
        table isn't synced. ``created_floor`` works as in ``issue_events_source``.

        Only the last transition counts, with the event id breaking same-second ties. A resolved
        issue-events table holds one repo, so ``pr_number`` alone is the key.

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

    def job_cost_source(
        self, *, created_floor: bool = False, since: datetime | None = None, scoped: bool = False
    ) -> str | None:
        """Per-job cost ``SELECT`` subquery: the rows ``engineering_analytics_job_costs`` exposes, plus
        run columns such as ``run_started_at`` and ``run_head_branch``. None when the jobs table
        isn't synced.

        ``created_floor`` adds the raw-string scan floor, and the caller must register
        {job_created_floor} (see ``run_windowed_job_created_floor_constant``). Every windowed caller
        needs it, because the window predicates read the run's columns and cannot prune the jobs
        scan. ``since`` and ``scoped`` work as for ``run_source``.
        """
        if not self._tables.workflow_jobs:
            return None
        if stored := self._stored_ci_covering(since):
            query = job_costs.build_attributed_query(
                costed_jobs=stored.jobs(created_floor=created_floor, with_cost=True),
                runs=stored.runs(include_shells=True),
            )
            return f"({query})"
        query = job_costs.build_query(
            jobs_table=self._jobs_table(self._tables.workflow_jobs, scoped=scoped),
            runs_table=self._runs_table(scoped=scoped),
            created_floor=created_floor,
        )
        return f"({query})"

    def runs_cte(self, *, scoped: bool = False) -> str:
        """CTE naming the live workflow-runs source ``runs``, for ``ci_rollup``. ClickHouse inlines a
        CTE at every reference, so each extra reader of ``runs`` scans the whole runs source again."""
        return f"runs AS {self.run_source(live=True, scoped=scoped)}"

    def _pr_scope_cte(
        self, pr_scope_where: str, *, order_by: str | None = None, limit: int | None = None, offset: int = 0
    ) -> str:
        """CTE: the number and head SHA of PRs matching ``pr_scope_where``, a predicate over
        unqualified curated PR columns. The CI rollup prefilters its runs scan to this set, because
        aggregating the team's whole run history runs out of memory."""
        paging = ""
        if order_by is not None and limit is not None:
            paging = f" ORDER BY {order_by} LIMIT {limit} OFFSET {offset}"
        return f"pr_scope AS (SELECT number, head_sha FROM {self.pr_source()} AS pr WHERE {pr_scope_where}{paging})"

    def ci_rollup_cte(self) -> str:
        """CTE collapsing each head SHA's workflow runs into pass/fail/pending counts.

        A SHA's status is its newest run per workflow. The composing query must also add the
        ``runs`` and ``pr_scope`` CTEs (see ``runs_cte`` and ``_pr_scope_cte``).
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
        self,
        select: str,
        *,
        pr_scope_where: str,
        ready: ReadyToMergeSql = READY_TO_MERGE_UNOBSERVABLE,
        pr_scope_order_by: str | None = None,
        pr_scope_limit: int | None = None,
        pr_scope_offset: int = 0,
    ) -> str:
        """Compose a pull-requests query that reads ``FROM __PR_SOURCE__ AS pr LEFT JOIN ci_rollup``.

        ``pr_scope_where`` must keep every PR that ``select`` reads CI for, because a PR outside it
        joins as if it had no runs. Pass ``ready`` when ``select`` reads the ready-to-merge measure.

        ``pr_scope_limit`` makes ``pr_scope`` the page itself, and the runs scan reads only that page's
        commits. ``pr_scope_where`` and ``pr_scope_order_by`` must then select and order exactly the rows
        ``select`` does, over PR columns alone.
        """
        if pr_scope_limit is not None:
            page_head_shas = "SELECT head_sha FROM pr_scope"
            # The scope is by head SHA, because the rollup joins on it and another PR's CI can share the commit.
            ctes = [
                self._pr_scope_cte(
                    pr_scope_where, order_by=pr_scope_order_by, limit=pr_scope_limit, offset=pr_scope_offset
                ),
                *self._run_scope_ctes(
                    f"SELECT groupUniqArray(id) FROM {self._tables.workflow_runs} WHERE head_sha IN ({page_head_shas})",
                    f"{depot_ci.head_sha_expr()} IN ({page_head_shas})",
                ),
                self.runs_cte(scoped=True),
                self.ci_rollup_cte(),
            ]
        else:
            ctes = [self.runs_cte(), self._pr_scope_cte(pr_scope_where), self.ci_rollup_cte()]
        if ready.cte:
            ctes.append(ready.cte)
        return self._compose_pr_query(ctes, select)

    def _compose_pr_query(self, ctes: list[str], select: str) -> str:
        return f"WITH {', '.join(ctes)} {select}".replace("__PR_SOURCE__", self.pr_source())

    @contextmanager
    def concurrent_reads(self) -> Iterator["ConcurrentReads"]:
        """Run the reads submitted inside the block concurrently when it exits. Read each result
        after the block."""
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
        """Read every row of ``sql``, past the per-query result cap. ``page_key`` lists the
        (column, row index) pairs of an immutable unique key."""
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

        ``sql`` is the query ``load`` runs, before its placeholders. Its hash names the cache. A cached
        value is served only when this reader's catalog grants every table the query reads."""
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
        """Parse and execute a HogQL query for this team.

        With a ``user_access_control``, HogQL applies that user's per-table warehouse access. Without
        one (system, Temporal and CLI callers) the read bypasses it, because HogQL would otherwise
        strip every warehouse table. ``workload`` must match the cluster of the tables the query
        reads, such as ``Workload.LOGS`` for ``logs``. Raises ``QueryWorkLimitExceededError`` when the
        handle's query budget is spent.
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
    """Each worker closes the Postgres connections it opens. Under TEST the reads run inline, because a
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
            [partial(_closing_connections, work) for work in self._work],
            thread_name_prefix="engineering_analytics",
        )


def _closing_connections(work: Callable[[], None]) -> None:
    try:
        work()
    finally:
        # A routed read can open a connection on another alias, so the worker closes all of them.
        connections.close_all()


def opt_float(value: float | None) -> float | None:
    """None for NaN, which a ClickHouse quantile or avg over an empty set returns."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)
