"""Fetch one GitHub Actions job log under the shared egress budget and emit it into Logs.

Returns small counts only; the log content never flows back through the workflow (Temporal's payload
limit). A budget denial raises so Temporal retries with backoff instead of blocking a worker.
"""

import json
import asyncio
import dataclasses
from datetime import timedelta
from typing import Any

from django.conf import settings

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.egress.github.limiter import acquire_github_installation
from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration, Integration
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow

from products.engineering_analytics.backend.logic.job_logs.emitter import JobLogsEmitter
from products.engineering_analytics.backend.logic.job_logs.fetcher import fetch_job_log
from products.engineering_analytics.backend.logic.job_logs.thinning import thin_log_lines

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class FetchJobLogInputs:
    team_id: int
    integration_id: int
    repo: str
    job_id: int
    run_id: int | None = None
    branch: str | None = None
    conclusion: str | None = None
    job_name: str | None = None
    workflow_name: str | None = None
    run_attempt: int | None = None
    head_sha: str | None = None


def _resolve_credentials(team_id: int, integration_id: int) -> tuple[str, str, str]:
    """Return ``(github_access_token, installation_id, log_ingest_token)``. ``log_ingest_token`` is
    the owning team's project API token — the OTLP Bearer that routes emitted logs to that team's Logs.
    """
    integration = Integration.objects.get(id=integration_id, team_id=team_id, kind="github")
    github = GitHubIntegration(integration)
    if github.access_token_expired():
        github.refresh_access_token()
    if not integration.access_token:
        raise ValueError(f"No GitHub access token for integration {integration_id}")
    return integration.access_token, str(github.github_installation_id), integration.team.api_token


@activity.defn
async def fetch_and_emit_job_log_activity(inputs: FetchJobLogInputs) -> dict[str, Any]:
    log = logger.bind(job_id=inputs.job_id, repo=inputs.repo, team_id=inputs.team_id)
    if not settings.OTLP_LOGS_INGEST_ENDPOINT:
        # No Logs sink configured: don't fetch (wastes the egress budget) and don't mark the job done
        # (a no-op emit would never retry). Raise so Temporal retries once the endpoint is set.
        raise ApplicationError("Logs export endpoint not configured", type="LogsExportDisabled")
    github_token, installation_id, log_ingest_token = await database_sync_to_async(
        _resolve_credentials, thread_sensitive=False
    )(inputs.team_id, inputs.integration_id)
    # Deferrable bulk: BATCH is shed first as the installation's budget fills, and the raise below
    # hands the retry to Temporal.
    if not await acquire_github_installation(installation_id, priority=Priority.BATCH, source="job_logs"):
        # Over budget — raise so Temporal retries with backoff instead of blocking a worker.
        raise ApplicationError("GitHub egress budget exhausted", type="GithubEgressBudgetExhausted")
    archive = await asyncio.to_thread(fetch_job_log, inputs.repo, inputs.job_id, github_token)
    if archive is None:
        log.info("github_job_log_unavailable")
        return {"status": "log_unavailable", "job_id": inputs.job_id, "lines": 0}
    attributes: dict[str, str | int] = {
        "job_id": inputs.job_id,
        "run_id": inputs.run_id or 0,
        "repo": inputs.repo,
        "branch": inputs.branch or "",
        "conclusion": inputs.conclusion or "",
        # job_name/workflow_name make records readable in the Logs UI without a warehouse join;
        # run_attempt disambiguates re-runs (all attempts share run_id, i.e. one trace); head_sha
        # is the per-commit anchor (SPEC §7 — precision key only, never the attribution key).
        "job_name": inputs.job_name or "",
        "workflow_name": inputs.workflow_name or "",
        "run_attempt": inputs.run_attempt or 0,
        "head_sha": inputs.head_sha or "",
        # Total lines in the full log before thinning — the denominator for each line's orig_line.
        "orig_total": len(archive.splitlines()),
    }

    # CI failure logs are team-level operational data: they ride the owning team's project Logs
    # (visible to any logs:read holder) by design and intentionally do NOT inherit the GitHub
    # source's resource-level access control. Don't emit anything a logs:read holder shouldn't see.
    def _thin_and_emit() -> int:
        # Failures-only today; pass a different ThinningConfig once all-jobs ingestion lands.
        thinned = thin_log_lines(archive)
        with JobLogsEmitter(endpoint=settings.OTLP_LOGS_INGEST_ENDPOINT, token=log_ingest_token) as emitter:
            # run_id→trace, job_id→span so the Logs UI can group a whole run and isolate one job.
            return emitter.emit_log_archive(
                thinned, attributes=attributes, trace_id=inputs.run_id, span_id=inputs.job_id
            )

    lines = await asyncio.to_thread(_thin_and_emit)
    log.info("github_job_log_emitted", lines=lines)
    return {"status": "emitted", "job_id": inputs.job_id, "lines": lines}


@workflow.defn(name="fetch-github-job-log")
class FetchGithubJobLogWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> FetchJobLogInputs:
        return FetchJobLogInputs(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, inputs: FetchJobLogInputs) -> dict[str, Any]:
        return await workflow.execute_activity(
            fetch_and_emit_job_log_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=5),
            # The BATCH lane can stay shed for the remainder of an hourly budget window, so the
            # retry horizon must outlive a worst-case shed — otherwise the job's logs are dropped
            # forever (the workflow_job webhook never refires).
            retry_policy=RetryPolicy(
                maximum_attempts=10,
                initial_interval=timedelta(seconds=30),
                maximum_interval=timedelta(minutes=15),
            ),
        )
