from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.client import WorkflowHandle
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.client import async_connect

from products.hogbot.backend.temporal.workflow import HogbotWorkflow, HogbotWorkflowInput

logger = logging.getLogger(__name__)

READY_POLL_INTERVAL_SECONDS = 0.5
READY_POLL_TIMEOUT_SECONDS = 120
MAX_START_ATTEMPTS = 3
_CLOSING_PHASES = frozenset({"snapshotting", "cleaning_up", "completed", "failed"})


@dataclass(frozen=True)
class HogbotConnectionInfo:
    workflow_id: str
    run_id: str | None
    phase: str
    ready: bool
    sandbox_id: str | None
    server_url: str | None
    connect_token: str | None
    error: str | None = None


def hogbot_workflow_id(team_id: int) -> str:
    return f"hogbot-team-{team_id}"


def get_or_start_hogbot(
    team_id: int,
    user_id: int | None = None,
    server_command: str | None = None,
    repository: str | None = None,
    github_integration_id: int | None = None,
    branch: str | None = None,
) -> HogbotConnectionInfo:
    return async_to_sync(_get_or_start_hogbot)(
        team_id=team_id,
        user_id=user_id,
        server_command=server_command,
        repository=repository,
        github_integration_id=github_integration_id,
        branch=branch,
    )


def get_hogbot_connection(team_id: int) -> HogbotConnectionInfo | None:
    try:
        return async_to_sync(_get_hogbot_connection)(team_id=team_id)
    except Exception:
        logger.exception("Failed to query hogbot Temporal workflow connection info", extra={"team_id": team_id})
        return None


def start_or_restart_hogbot(
    team_id: int,
    user_id: int | None = None,
    server_command: str | None = None,
    repository: str | None = None,
    github_integration_id: int | None = None,
    branch: str | None = None,
) -> HogbotConnectionInfo:
    return get_or_start_hogbot(
        team_id=team_id,
        user_id=user_id,
        server_command=server_command,
        repository=repository,
        github_integration_id=github_integration_id,
        branch=branch,
    )



async def _get_or_start_hogbot(
    *,
    team_id: int,
    user_id: int | None,
    server_command: str | None,
    repository: str | None,
    github_integration_id: int | None,
    branch: str | None,
) -> HogbotConnectionInfo:
    client = await async_connect()
    workflow_input = HogbotWorkflowInput(
        team_id=team_id,
        user_id=user_id,
        server_command=server_command,
        repository=repository,
        github_integration_id=github_integration_id,
        branch=branch,
    )

    last_info: HogbotConnectionInfo | None = None

    for _ in range(MAX_START_ATTEMPTS):
        try:
            handle = await client.start_workflow(
                HogbotWorkflow.run,
                workflow_input,
                id=hogbot_workflow_id(team_id),
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except WorkflowAlreadyStartedError:
            handle = client.get_workflow_handle(hogbot_workflow_id(team_id))
        except Exception:
            logger.exception("Failed to start hogbot Temporal workflow", extra={"team_id": team_id})
            raise

        last_info = await _wait_for_connection_info(handle)
        if last_info.ready:
            return last_info

        if last_info.phase not in _CLOSING_PHASES:
            break

        try:
            await asyncio.wait_for(handle.result(), timeout=READY_POLL_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.warning(
                "Timed out waiting for existing hogbot workflow to finish before restart",
                extra={"team_id": team_id, "phase": last_info.phase},
            )
            break
        except Exception as e:
            logger.warning(
                "Existing hogbot workflow finished with an error before restart",
                extra={"team_id": team_id, "error": str(e), "phase": last_info.phase},
            )

    if last_info is None:
        raise RuntimeError("Failed to retrieve hogbot connection info")

    if last_info.ready:
        return last_info

    raise RuntimeError(
        f"Hogbot workflow did not become ready (phase={last_info.phase}, error={last_info.error or 'unknown'})"
    )


async def _get_hogbot_connection(*, team_id: int) -> HogbotConnectionInfo:
    client = await async_connect()
    handle = client.get_workflow_handle(hogbot_workflow_id(team_id))
    raw_info = await handle.query(HogbotWorkflow.get_connection_info)
    return HogbotConnectionInfo(**raw_info)


async def _wait_for_connection_info(handle: WorkflowHandle) -> HogbotConnectionInfo:
    deadline = asyncio.get_running_loop().time() + READY_POLL_TIMEOUT_SECONDS
    last_info: HogbotConnectionInfo | None = None
    last_error: Exception | None = None

    while asyncio.get_running_loop().time() < deadline:
        try:
            raw_info = await handle.query(HogbotWorkflow.get_connection_info)
            last_info = HogbotConnectionInfo(**raw_info)
        except Exception as e:
            last_error = e
        else:
            if last_info.ready or last_info.phase in _CLOSING_PHASES:
                return last_info

        await asyncio.sleep(READY_POLL_INTERVAL_SECONDS)

    if last_info is not None:
        return last_info
    if last_error is not None:
        raise last_error
    raise TimeoutError("Timed out waiting for hogbot workflow connection info")
