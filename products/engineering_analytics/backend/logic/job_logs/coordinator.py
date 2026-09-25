"""Find failed CI jobs and jobs recovered by pytest retries, then fetch their diagnostic logs.

Per-job workflow id (``gh-logs-{team}-{job}``, reuse ``ALLOW_DUPLICATE_FAILED_ONLY``) means each
job's log is fetched and emitted at most once, re-running only after a failed attempt. Failed Depot
CI job attempts come from each Depot source's ``job_attempts`` table and run as
``depot-logs-{team}-{attempt}``. Only failed Depot attempts are fetched: the retry-recovered path
reads GitHub runner names.

Discovery queries the raw ``{prefix}github_workflow_jobs`` table (the curated read layer doesn't
expose jobs yet). The coordinator is registered on the schedule but no-ops until
``OTLP_LOGS_INGEST_ENDPOINT`` is set (see ``_discover_jobs_with_diagnostics``), so it activates automatically
once the Logs endpoint is deployed, regardless of deploy order.
"""

import re
import json
import dataclasses
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

from django.conf import settings

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.models.integration.github import _is_safe_github_repo_path
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow

from products.engineering_analytics.backend.logic.job_logs.activity import (
    FetchDepotJobLogInputs,
    FetchDepotJobLogWorkflow,
    FetchGithubJobLogWorkflow,
    FetchJobLogInputs,
)
from products.engineering_analytics.backend.logic.queries._test_spans import rerun_recovered_job_attempts
from products.engineering_analytics.backend.logic.sources import depot_source_job_attempts_table
from products.engineering_analytics.backend.logic.views.depot_ci import depot_github_run_id, depot_id_to_int
from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)

# How far back to look each tick. With the per-job workflow id (one fetch per job) this bounds
# re-scanning without a separate "already fetched" store. The window must exceed the warehouse's
# worst-case landing delay, not the job's age: discovery filters on completed_at, and rows reach the
# jobs table only as fast as the v3 load consumer drains its queue — during backlogs that's many
# hours, and a 2h window went blind (every row arrived already too old). The proper fix is a
# persisted high-water-mark cursor over landed rows (deferred).
DEFAULT_LOOKBACK = timedelta(hours=24)
_PREFIX = re.compile(r"^[A-Za-z0-9_]*$")  # warehouse source prefixes; guards the table identifier
# Cap total jobs returned per tick — the activity hands them back as one Temporal payload (~2 MiB
# limit), so an incident across many sources mustn't return an unbounded list.
MAX_DISCOVERED_JOBS = 2000


def _query_jobs_with_diagnostics(team: Team, prefix: str, cutoff_iso: str, repo: str) -> list[dict[str, Any]]:
    # Window on completed_at (when the job finished), not created_at: a queued or long-running job
    # can be created well before it fails, and a created_at window would miss it. completed_at is an
    # ISO-8601 string and is always set for a failed (completed) job, so a lexical comparison against
    # the cutoff is chronological. The table name is a trusted identifier (validated prefix + fixed
    # suffix); user values flow through the placeholder, never the f-string.
    table = f"{prefix}github_workflow_jobs"
    # The LIMIT must exceed any realistic burst of rows becoming visible between two ticks (deploy
    # transitions, warehouse catch-up dumps): already-started jobs keep occupying the newest-first
    # ranks every tick (dedup happens later, at child-workflow start), so a job pushed below the
    # limit can never rise back into view and would be silently dropped. Matches
    # MAX_DISCOVERED_JOBS; the high-water-mark cursor (deferred) removes the cap concern entirely.
    # Run, attempt, and runner restrict successful-job downloads to runners with retry evidence.
    recovered = rerun_recovered_job_attempts(
        scan_from=f"""
            SELECT min(parseDateTimeBestEffort(started_at))
            FROM {table}
            WHERE completed_at > {{cutoff}} AND conclusion = 'success'
        """
    )
    sql = f"""
        SELECT id AS job_id, run_id, head_branch AS branch, conclusion,
               name AS job_name, workflow_name, run_attempt, head_sha
        FROM {table}
        WHERE completed_at > {{cutoff}} AND (
            conclusion = 'failure'
            OR (
                conclusion = 'success'
                AND (toString(run_id), toString(run_attempt), runner_name) IN ({recovered})
            )
        )
        ORDER BY completed_at DESC
        LIMIT {MAX_DISCOVERED_JOBS}
    """
    with tags_context(product=Product.ENGINEERING_ANALYTICS, feature=Feature.QUERY, team_id=team.pk):
        response = execute_hogql_query(
            query=parse_select(
                sql,
                placeholders={"cutoff": ast.Constant(value=cutoff_iso), "repository": ast.Constant(value=repo)},
            ),
            team=team,
            query_type="GithubJobLogsDiscovery",
            # Trusted internal sweep with no request user: without this, HogQL's access-control build
            # marks the team's own warehouse tables denied and the query raises "You don't have access
            # to table" — so nothing is ever discovered. The query stays scoped to this team's table.
            bypass_warehouse_access_control=True,
        )
    return [dict(zip(response.columns or [], row)) for row in response.results]


def _live_sources(source_type: ExternalDataSourceType) -> Iterator[ExternalDataSource]:
    """Every team's non-deleted sources of ``source_type``, with the team, for the cross-team sweep."""
    sources = ExternalDataSource.objects.filter(source_type=source_type).exclude(deleted=True).select_related("team")
    return sources.iterator()


def _github_source_params(job_inputs: dict[str, Any] | None) -> tuple[int, str] | None:
    """``(integration_id, repo)`` from a GitHub source's ``job_inputs``, or None if unusable.

    job_inputs is team-writable, so guard its shape: a non-dict ``auth_method`` or a repo that isn't a
    plain ``owner/repo`` (which would steer the authenticated fetch elsewhere) yields None, not a crash.
    """
    # job_inputs is an EncryptedJSONField and can hold any JSON value; a non-dict (list/str/None)
    # would crash the .get below, outside the per-source try — skip it instead.
    if not isinstance(job_inputs, dict):
        return None
    auth_method = job_inputs.get("auth_method")
    auth = auth_method if isinstance(auth_method, dict) else {}
    # Accept both source-config shapes: nested ({"auth_method": {"github_integration_id": ...}}) and
    # flat ({"auth_method": "oauth", "github_integration_id": ...}). The isinstance guard keeps a
    # non-dict auth_method from crashing; the fallback reads the flat top-level id.
    integration_id = auth.get("github_integration_id") or job_inputs.get("github_integration_id")
    repo = job_inputs.get("repository")
    # PAT-auth sources have no github_integration_id and fall through to None here — intentionally
    # skipped: the worker fetches under the App installation token + per-installation egress budget,
    # which PAT has no equivalent for. Supporting PAT would need a separate fetch path (deferred).
    if not integration_id or not isinstance(repo, str) or not _is_safe_github_repo_path(repo):
        return None
    try:
        return int(integration_id), repo
    except (TypeError, ValueError):
        return None


def _discover_jobs_with_diagnostics(cutoff_iso: str) -> list[dict[str, Any]]:
    if not settings.OTLP_LOGS_INGEST_ENDPOINT:
        # No Logs sink configured yet (charts sets the endpoint per region): discover nothing so the
        # registered schedule is inert until the sink exists, then activates automatically. Mirrors
        # the activity's fail-closed guard, but here it also skips the per-source warehouse queries.
        return []
    found: list[dict[str, Any]] = []
    eligible_sources = 0
    skipped_sources = 0
    for source in _live_sources(ExternalDataSourceType.GITHUB):
        params = _github_source_params(source.job_inputs)
        prefix = source.prefix or ""
        if params is None or not _PREFIX.match(prefix):
            continue
        eligible_sources += 1
        integration_id, repo = params
        try:
            # Row handling stays inside the try so a single bad row (e.g. a null job_id) skips this
            # source rather than failing discovery for every team.
            for row in _query_jobs_with_diagnostics(source.team, prefix, cutoff_iso, repo):
                job_id = row.get("job_id")
                if job_id is None:
                    continue
                found.append(
                    dataclasses.asdict(
                        FetchJobLogInputs(
                            team_id=source.team_id,
                            integration_id=integration_id,
                            repo=repo,
                            job_id=int(job_id),
                            run_id=row.get("run_id"),
                            branch=row.get("branch"),
                            conclusion=row.get("conclusion"),
                            job_name=row.get("job_name"),
                            workflow_name=row.get("workflow_name"),
                            run_attempt=row.get("run_attempt"),
                            head_sha=row.get("head_sha"),
                        )
                    )
                )
                if len(found) >= MAX_DISCOVERED_JOBS:
                    logger.warning("github_job_logs_discovery_capped", cap=MAX_DISCOVERED_JOBS)
                    break  # inner loop only; the outer break below stops the sweep so the cap holds
        except Exception as e:
            # A source whose jobs table isn't synced or a transient query error shouldn't fail the
            # whole sweep — skip it. Most teams never enable the workflow_jobs schema, so a missing
            # table is the expected common case (log at debug); anything else is a real error (warn).
            skipped_sources += 1
            if isinstance(e, QueryError) and "Unknown table" in str(e):
                logger.debug("github_job_logs_discovery_source_not_synced", source_id=str(source.id))
            else:
                logger.warning("github_job_logs_discovery_skipped_source", source_id=str(source.id), exc_info=True)
            continue
        if len(found) >= MAX_DISCOVERED_JOBS:
            break  # stop the sweep at the cap, but fall through to the summary log below
    # One summary line per tick so coverage stays observable even though per-source "not synced" skips
    # log at debug: a sweep that suddenly skips everything (e.g. a mistyped prefix or a dropped table)
    # is visible here instead of silently emitting nothing.
    logger.info(
        "github_job_logs_discovery_complete",
        eligible_sources=eligible_sources,
        skipped_sources=skipped_sources,
        jobs_found=len(found),
    )
    return found


@frozen
class DepotAttemptCursor:
    """The last failed attempt of a full discovery page, in ``(finished_at, attempt_id)`` order."""

    finished_at: str
    attempt_id: str


@frozen
class DepotDiscoveryInputs:
    cutoff_iso: str
    cursors: dict[str, DepotAttemptCursor]


@frozen
class DepotDiscovery:
    attempts: list[FetchDepotJobLogInputs]
    cursors: dict[str, DepotAttemptCursor]


def _query_failed_depot_attempts(
    team: Team, table: str, cutoff_iso: str, after: DepotAttemptCursor | None, limit: int
) -> list[dict[str, Any]]:
    # attempt_finished_at is an ISO-8601 string like completed_at above, so the lexical comparison
    # against the cutoff is chronological. The table name comes from the source's synced schema.
    after = after or DepotAttemptCursor(finished_at=cutoff_iso, attempt_id="")
    sql = f"""
        SELECT run_id, run_workflow_count, workflow_id, attempt_id, attempt, repo, head_sha, workflow_name,
               job_display_name, job_key, attempt_finished_at
        FROM {table}
        WHERE attempt_status = 'failed' AND attempt_finished_at > {{cutoff}} AND (
            attempt_finished_at > {{after_finished_at}}
            OR (attempt_finished_at = {{after_finished_at}} AND attempt_id > {{after_attempt_id}})
        )
        ORDER BY attempt_finished_at, attempt_id
        LIMIT {limit}
    """
    placeholders: dict[str, ast.Expr] = {
        "cutoff": ast.Constant(value=cutoff_iso),
        "after_finished_at": ast.Constant(value=after.finished_at),
        "after_attempt_id": ast.Constant(value=after.attempt_id),
    }
    with tags_context(product=Product.ENGINEERING_ANALYTICS, feature=Feature.QUERY, team_id=team.pk):
        response = execute_hogql_query(
            query=parse_select(sql, placeholders=placeholders),
            team=team,
            query_type="DepotJobLogsDiscovery",
            bypass_warehouse_access_control=True,
        )
    return [dict(zip(response.columns or [], row)) for row in response.results]


def _depot_attempt_inputs(source: ExternalDataSource, row: dict[str, Any]) -> FetchDepotJobLogInputs | None:
    # The same run id the runs view gives this workflow, so the logs join it. A push run's id carries
    # a prefix outside the Depot id alphabet, so it has no integer run id for its logs to join on.
    run_id = depot_github_run_id(row["run_id"] or "", row["workflow_id"] or "", row["run_workflow_count"] or 0)
    job_id = depot_id_to_int(row["attempt_id"] or "")
    if run_id is None or job_id is None:
        return None
    return FetchDepotJobLogInputs(
        team_id=source.team_id,
        source_id=str(source.id),
        attempt_id=row["attempt_id"],
        run_id=run_id,
        job_id=job_id,
        repo=row["repo"] or "",
        workflow_name=row["workflow_name"] or "",
        job_name=row["job_display_name"] or row["job_key"] or "",
        run_attempt=row["attempt"] or 0,
        head_sha=row["head_sha"] or "",
    )


def _discover_failed_depot_attempts(inputs: DepotDiscoveryInputs) -> DepotDiscovery:
    """Failed attempts oldest first, at most ``MAX_DISCOVERED_JOBS`` across all sources.

    A source whose page fills the remaining cap gets a cursor, and the next tick reads on from it.
    A source whose page does not fill it gets none, so the next tick reads its window from the start
    again and finds rows that landed late.
    """
    if not settings.OTLP_LOGS_INGEST_ENDPOINT:
        return DepotDiscovery(attempts=[], cursors={})
    attempts: list[FetchDepotJobLogInputs] = []
    cursors: dict[str, DepotAttemptCursor] = {}
    for source in _live_sources(ExternalDataSourceType.DEPOT):
        source_id = str(source.id)
        cursor = inputs.cursors.get(source_id)
        limit = MAX_DISCOVERED_JOBS - len(attempts)
        table = depot_source_job_attempts_table(source.team, source)
        if table is None:
            continue
        if limit <= 0:
            if cursor is not None:
                cursors[source_id] = cursor
            continue
        try:
            rows = _query_failed_depot_attempts(source.team, table, inputs.cutoff_iso, cursor, limit)
        except Exception:
            logger.warning("depot_job_logs_discovery_skipped_source", source_id=source_id, exc_info=True)
            if cursor is not None:
                cursors[source_id] = cursor
            continue
        attempts.extend(found for row in rows if (found := _depot_attempt_inputs(source, row)) is not None)
        if len(rows) == limit:
            cursors[source_id] = DepotAttemptCursor(
                finished_at=rows[-1]["attempt_finished_at"], attempt_id=rows[-1]["attempt_id"]
            )
    return DepotDiscovery(attempts=attempts, cursors=cursors)


@activity.defn
async def discover_failed_jobs_activity(cutoff_iso: str) -> list[dict[str, Any]]:
    """Failed or retry-recovered CI jobs with a connected GitHub source, as FetchJobLogInputs dicts."""
    return await database_sync_to_async(_discover_jobs_with_diagnostics, thread_sensitive=False)(cutoff_iso)


@activity.defn
async def discover_failed_depot_attempts_activity(inputs: DepotDiscoveryInputs) -> DepotDiscovery:
    return await database_sync_to_async(_discover_failed_depot_attempts, thread_sensitive=False)(inputs)


def _previous_depot_cursors() -> dict[str, DepotAttemptCursor]:
    # A schedule gives each run the result of the last run that completed. The cursors in it let a
    # backlog larger than one tick's cap page forward across ticks, instead of each tick reading the
    # same first page again while older attempts leave the lookback window without a fetch.
    previous = workflow.get_last_completion_result()
    cursors = previous.get("depot_cursors") if isinstance(previous, dict) else None
    return {source_id: DepotAttemptCursor(**cursor) for source_id, cursor in (cursors or {}).items()}


@workflow.defn(name="github-job-logs-coordinator")
class GithubJobLogsCoordinatorWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> dict[str, Any]:
        return json.loads(inputs[0]) if inputs else {}

    @workflow.run
    async def run(self, _state: dict[str, Any] | None = None) -> dict[str, Any]:
        cutoff_iso = (workflow.now() - DEFAULT_LOOKBACK).isoformat()
        jobs = await workflow.execute_activity(
            discover_failed_jobs_activity,
            cutoff_iso,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        started = 0
        for job in jobs:
            inputs = FetchJobLogInputs(**job)
            try:
                await workflow.start_child_workflow(
                    FetchGithubJobLogWorkflow.run,
                    inputs,
                    id=f"gh-logs-{inputs.team_id}-{inputs.job_id}",
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    execution_timeout=timedelta(minutes=15),
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                )
                started += 1
            except WorkflowAlreadyStartedError:
                # Already started by a prior tick — reuse policy coalesces it.
                continue
        depot = DepotDiscovery(attempts=[], cursors={})
        if workflow.patched("depot-job-logs-2026-09"):
            depot = await workflow.execute_activity(
                discover_failed_depot_attempts_activity,
                DepotDiscoveryInputs(cutoff_iso=cutoff_iso, cursors=_previous_depot_cursors()),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        for attempt in depot.attempts:
            try:
                # No execution timeout, because the retry policy bounds the child. While the child
                # waits out Depot's Retry-After, its id stays taken, so a later tick cannot fetch early.
                await workflow.start_child_workflow(
                    FetchDepotJobLogWorkflow.run,
                    attempt,
                    id=f"depot-logs-{attempt.team_id}-{attempt.attempt_id}",
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                )
                started += 1
            except WorkflowAlreadyStartedError:
                continue
        return {
            "jobs_discovered": len(jobs) + len(depot.attempts),
            "workflows_started": started,
            "depot_cursors": depot.cursors,
        }
