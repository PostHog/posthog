"""Per-job activity + workflow: fetch one GitHub Actions job log under the shared egress budget and
emit it into the Logs product.

The activity resolves a fresh installation token, gates the fetch on the shared GitHub installation
budget (raising on denial so Temporal retries with backoff rather than blocking a worker), fetches
the log, and emits it line-by-line. It returns only small counts — the log content never flows back
through the workflow (which would hit Temporal's payload limit).
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

from posthog.models.integration import GitHubIntegration, Integration
from posthog.rate_limiting.github import acquire_github_installation
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow

from products.engineering_analytics.backend.logic.job_logs.emitter import JobLogsEmitter
from products.engineering_analytics.backend.logic.job_logs.fetcher import fetch_job_log
from products.engineering_analytics.backend.logic.job_logs.thinning import thin_log

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


def _resolve_credentials(team_id: int, integration_id: int) -> tuple[str, str, str]:
    """Return ``(github_access_token, installation_id, log_ingest_token)`` for the source's team.

    ``log_ingest_token`` is the owning team's project API token — the OTLP Bearer that routes the
    emitted CI logs into that team's Logs. The GitHub token refresh is a low-frequency App-level call
    (a new installation token lasts ~1h), so it's not gated by the per-installation log-fetch budget.
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
    github_token, installation_id, log_ingest_token = await database_sync_to_async(
        _resolve_credentials, thread_sensitive=False
    )(inputs.team_id, inputs.integration_id)
    if not await acquire_github_installation(installation_id):
        # Over the shared GitHub budget — hand back to Temporal's retry (with backoff) instead of
        # blocking a worker; the per-job workflow id coalesces duplicate attempts.
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
    }

    # Failures-only today, so always thin with the failure preset; when all-jobs ingestion lands,
    # pass a different ThinningConfig here for non-failure logs.
    thinned = thin_log(archive)

    def _emit() -> int:
        with JobLogsEmitter(endpoint=settings.OTLP_LOGS_INGEST_ENDPOINT, token=log_ingest_token) as emitter:
            return emitter.emit_log_archive(thinned, attributes=attributes)

    lines = await asyncio.to_thread(_emit)
    log.info("github_job_log_emitted", lines=lines, raw_lines=archive.count("\n") + 1)
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
            retry_policy=RetryPolicy(
                maximum_attempts=5,
                initial_interval=timedelta(seconds=30),
                maximum_interval=timedelta(minutes=5),
            ),
        )
