"""Find recently-failed CI jobs and fan out one idempotent log-fetch workflow per job.

Per-job workflow id (``gh-logs-{team}-{job}``, reuse ``ALLOW_DUPLICATE_FAILED_ONLY``) means each
job's log is fetched and emitted at most once, re-running only after a failed attempt.

NOT WIRED LIVE: discovery works (it queries the raw ``{prefix}github_workflow_jobs`` table, since the
curated read layer doesn't expose jobs yet), but the schedule and worker stay unregistered until the
Logs lane is confirmed — ``OTLP_LOGS_INGEST_ENDPOINT`` set and the destination team trusted/unsampled.
No end-to-end test yet.
"""

import re
import json
import dataclasses
from datetime import timedelta
from typing import Any

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.integration import _is_safe_github_repo_path
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow

from products.engineering_analytics.backend.logic.job_logs.activity import FetchGithubJobLogWorkflow, FetchJobLogInputs
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)

# How far back to look each tick. With the per-job workflow id (one fetch per job) this bounds
# re-scanning without a separate "already fetched" store.
DEFAULT_LOOKBACK = timedelta(hours=2)
_PREFIX = re.compile(r"^[A-Za-z0-9_]*$")  # warehouse source prefixes; guards the table identifier
# Cap total jobs returned per tick — the activity hands them back as one Temporal payload (~2 MiB
# limit), so an incident across many sources mustn't return an unbounded list.
MAX_DISCOVERED_JOBS = 2000


def _query_failed_jobs(team: Team, prefix: str, cutoff_iso: str) -> list[dict[str, Any]]:
    # created_at is an ISO-8601 string column, so a lexical comparison against the cutoff is
    # chronological for GitHub's fixed format. The table name is a trusted identifier (validated
    # prefix + fixed suffix); user values flow through the placeholder, never the f-string.
    table = f"{prefix}github_workflow_jobs"
    sql = f"""
        SELECT id AS job_id, run_id, head_branch AS branch, conclusion
        FROM {table}
        WHERE conclusion = 'failure' AND created_at > {{cutoff}}
        ORDER BY created_at DESC
        LIMIT 500
    """
    with tags_context(product=Product.ENGINEERING_ANALYTICS, feature=Feature.QUERY, team_id=team.pk):
        response = execute_hogql_query(
            query=parse_select(sql, placeholders={"cutoff": ast.Constant(value=cutoff_iso)}),
            team=team,
            query_type="GithubJobLogsDiscovery",
        )
    return [dict(zip(response.columns or [], row)) for row in response.results]


def _github_source_params(source: ExternalDataSource) -> tuple[int, str] | None:
    """``(integration_id, repo)`` from a GitHub source's job_inputs, or None if unusable.

    job_inputs is team-writable, so guard its shape: a non-dict ``auth_method`` or a repo that isn't a
    plain ``owner/repo`` (which would steer the authenticated fetch elsewhere) yields None, not a crash.
    """
    job_inputs = source.job_inputs or {}
    auth_method = job_inputs.get("auth_method")
    auth = auth_method if isinstance(auth_method, dict) else {}
    integration_id = auth.get("github_integration_id")
    repo = job_inputs.get("repository")
    if not integration_id or not isinstance(repo, str) or not _is_safe_github_repo_path(repo):
        return None
    try:
        return int(integration_id), repo
    except (TypeError, ValueError):
        return None


def _discover_failed_jobs(cutoff_iso: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    sources = (
        ExternalDataSource.objects.filter(source_type=ExternalDataSourceType.GITHUB)
        .exclude(deleted=True)
        .select_related("team")
    )
    for source in sources.iterator():
        params = _github_source_params(source)
        prefix = source.prefix or ""
        if params is None or not _PREFIX.match(prefix):
            continue
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
                        )
                    )
                )
                if len(found) >= MAX_DISCOVERED_JOBS:
                    logger.warning("github_job_logs_discovery_capped", cap=MAX_DISCOVERED_JOBS)
                    return found
        except Exception:
            # A source whose jobs table isn't synced (most teams don't enable the workflow_jobs
            # schema) or a transient query error shouldn't fail the whole sweep — skip it.
            logger.warning("github_job_logs_discovery_skipped_source", source_id=str(source.id), exc_info=True)
            continue
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
