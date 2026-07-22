"""Find recently-failed CI jobs and fan out one idempotent log-fetch workflow per job.

Per-job workflow id (``gh-logs-{team}-{job}``, reuse ``ALLOW_DUPLICATE_FAILED_ONLY``) means each
job's log is fetched and emitted at most once, re-running only after a failed attempt.

Discovery queries the raw ``{prefix}github_workflow_jobs`` table (the curated read layer doesn't
expose jobs yet). The coordinator is registered on the schedule but no-ops until
``OTLP_LOGS_INGEST_ENDPOINT`` is set (see ``_discover_failed_jobs``), so it activates automatically
once the Logs endpoint is deployed, regardless of deploy order.
"""

import re
import json
import dataclasses
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
from posthog.models.integration import _is_safe_github_repo_path
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow

from products.engineering_analytics.backend.logic.job_logs.activity import FetchGithubJobLogWorkflow, FetchJobLogInputs
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


def _query_failed_jobs(team: Team, prefix: str, cutoff_iso: str) -> list[dict[str, Any]]:
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
    sql = f"""
        SELECT id AS job_id, run_id, head_branch AS branch, conclusion,
               name AS job_name, workflow_name, run_attempt, head_sha
        FROM {table}
        WHERE conclusion = 'failure' AND completed_at > {{cutoff}}
        ORDER BY completed_at DESC
        LIMIT {MAX_DISCOVERED_JOBS}
    """
    with tags_context(product=Product.ENGINEERING_ANALYTICS, feature=Feature.QUERY, team_id=team.pk):
        response = execute_hogql_query(
            query=parse_select(sql, placeholders={"cutoff": ast.Constant(value=cutoff_iso)}),
            team=team,
            query_type="GithubJobLogsDiscovery",
            # Trusted internal sweep with no request user: without this, HogQL's access-control build
            # marks the team's own warehouse tables denied and the query raises "You don't have access
            # to table" — so nothing is ever discovered. The query stays scoped to this team's table.
            bypass_warehouse_access_control=True,
        )
    return [dict(zip(response.columns or [], row)) for row in response.results]


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


def _discover_failed_jobs(cutoff_iso: str) -> list[dict[str, Any]]:
    if not settings.OTLP_LOGS_INGEST_ENDPOINT:
        # No Logs sink configured yet (charts sets the endpoint per region): discover nothing so the
        # registered schedule is inert until the sink exists, then activates automatically. Mirrors
        # the activity's fail-closed guard, but here it also skips the per-source warehouse queries.
        return []
    found: list[dict[str, Any]] = []
    eligible_sources = 0
    skipped_sources = 0
    sources = (
        ExternalDataSource.objects.filter(source_type=ExternalDataSourceType.GITHUB)
        .exclude(deleted=True)
        .select_related("team")
    )
    for source in sources.iterator():
        params = _github_source_params(source.job_inputs)
        prefix = source.prefix or ""
        if params is None or not _PREFIX.match(prefix):
            continue
        eligible_sources += 1
        integration_id, repo = params
        try:
            # Row handling stays inside the try so a single bad row (e.g. a null job_id) skips this
            # source rather than failing discovery for every team.
            for row in _query_failed_jobs(source.team, prefix, cutoff_iso):
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


@activity.defn
async def discover_failed_jobs_activity(cutoff_iso: str) -> list[dict[str, Any]]:
    """Failed CI jobs across teams with a connected GitHub source, as FetchJobLogInputs dicts."""
    return await database_sync_to_async(_discover_failed_jobs, thread_sensitive=False)(cutoff_iso)


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
        return {"jobs_discovered": len(jobs), "workflows_started": started}
