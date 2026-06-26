"""Coordinator: find recently-failed CI jobs and fan out one log-fetch workflow per job.

Scans each connected team's ``github_workflow_jobs`` warehouse metadata for ``conclusion='failure'``
jobs in a recent window and starts an idempotent per-job ``FetchGithubJobLogWorkflow`` (id = the job
id, reuse = ``ALLOW_DUPLICATE_FAILED_ONLY``) so each job's log is fetched and emitted at most once —
re-running only if a prior attempt failed. That single-fetch guarantee is also what keeps duplicate
records out of the Logs product.

NOT YET WIRED LIVE: the ``github_workflow_jobs`` metadata table is synced and queryable — discovery
runs against the raw warehouse table by name (not the curated read layer, which doesn't expose jobs
yet), so this coordinator finds real failed jobs today. What's deliberately deferred is *activation*:
the schedule is NOT registered in ``posthog/temporal/schedule.py`` and these workflows/activities are
NOT added to the worker until the Logs lane is confirmed — the internal capture-logs endpoint
configured (``settings.OTLP_LOGS_INGEST_ENDPOINT``) and the destination team marked unsampled/trusted
with the agreed retention. This discovery path therefore has no end-to-end test yet.
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
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow

from products.engineering_analytics.backend.logic.job_logs.activity import FetchGithubJobLogWorkflow, FetchJobLogInputs
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)

DEFAULT_MAX_CONCURRENT = 50
# How far back to look each tick. With the per-job workflow id (one fetch per job) this bounds
# re-scanning without a separate "already fetched" store.
DEFAULT_LOOKBACK = timedelta(hours=2)
_PREFIX = re.compile(r"^[A-Za-z0-9_]*$")  # warehouse source prefixes; guards the table identifier


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


def _discover_failed_jobs(cutoff_iso: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    sources = ExternalDataSource.objects.filter(source_type=ExternalDataSourceType.GITHUB).exclude(deleted=True)
    for source in sources.iterator():
        auth = (source.job_inputs or {}).get("auth_method") or {}
        integration_id = auth.get("github_integration_id")
        repo = (source.job_inputs or {}).get("repository")
        prefix = source.prefix or ""
        if not integration_id or not repo or not _PREFIX.match(prefix):
            continue
        try:
            team = Team.objects.get(id=source.team_id)
            rows = _query_failed_jobs(team, prefix, cutoff_iso)
        except Exception:
            # A source whose jobs table isn't synced (most teams don't enable the workflow_jobs
            # schema) or a transient query error shouldn't fail the whole sweep — skip it.
            logger.warning("github_job_logs_discovery_skipped_source", source_id=str(source.id), exc_info=True)
            continue
        for row in rows:
            found.append(
                dataclasses.asdict(
                    FetchJobLogInputs(
                        team_id=source.team_id,
                        integration_id=int(integration_id),
                        repo=repo,
                        job_id=int(row["job_id"]),
                        run_id=row.get("run_id"),
                        branch=row.get("branch"),
                        conclusion=row.get("conclusion"),
                    )
                )
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
        for index in range(0, len(jobs), DEFAULT_MAX_CONCURRENT):
            for job in jobs[index : index + DEFAULT_MAX_CONCURRENT]:
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
                    # Already fetched (a prior tick succeeded) — the reuse policy coalesces it.
                    continue
        return {"jobs_discovered": len(jobs), "workflows_started": started}
