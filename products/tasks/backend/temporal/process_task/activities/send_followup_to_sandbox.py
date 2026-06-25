import json
import time
from dataclasses import dataclass
from typing import Any

import structlog
from temporalio import activity

from posthog.temporal.common.utils import close_db_connections
from posthog.temporal.oauth import PosthogMcpScopes

from products.tasks.backend.logic.services.agent_command import (
    FOLLOWUP_TIMEOUT_SECONDS,
    REFRESH_TIMEOUT_SECONDS,
    CommandResult,
    send_refresh_session,
    send_user_message,
)
from products.tasks.backend.logic.services.connection_token import create_sandbox_connection_token
from products.tasks.backend.logic.services.staged_artifacts import get_task_run_artifacts_by_id
from products.tasks.backend.logic.stream.redis_stream import get_task_run_stream_key
from products.tasks.backend.models import TaskRun
from products.tasks.backend.redis import get_tasks_stream_redis_sync, run_uses_dedicated_stream
from products.tasks.backend.temporal.oauth import create_oauth_access_token_for_user, oauth_application_for_task
from products.tasks.backend.temporal.process_task.utils import (
    get_sandbox_ph_mcp_configs,
    get_user_mcp_server_configs,
    mark_mcp_token_issued,
    should_refresh_mcp_token,
)

from ee.hogai.sandbox import STOP_REASON_END_TURN, TURN_COMPLETE_METHOD

logger = structlog.get_logger(__name__)

REFRESH_RETRY_DELAY_SECONDS = 0.5


@dataclass
class SendFollowupToSandboxInput:
    run_id: str
    message: str | None = None
    posthog_mcp_scopes: PosthogMcpScopes = "read_only"
    artifact_ids: list[str] | None = None


@activity.defn
@close_db_connections
def send_followup_to_sandbox(input: SendFollowupToSandboxInput) -> None:
    """Send a follow-up user message to the sandbox and write result markers to Redis.

    Called by the workflow when it receives a send_followup_message signal from the
    web layer. Writes turn_complete on success or an error event on failure so the
    SSE stream terminates cleanly.
    """
    try:
        task_run = TaskRun.objects.select_related("task__created_by").get(id=input.run_id)
    except TaskRun.DoesNotExist:
        error_msg = "Task run not found"
        logger.warning("send_followup_run_not_found", run_id=input.run_id)
        _write_error_and_complete(input.run_id, error_msg)
        # Raise so the workflow can mark the run as failed. Without this,
        # background-mode runs hang until the inactivity timeout because
        raise RuntimeError(f"send_followup failed: {error_msg}")

    auth_token = None
    created_by = task_run.task.created_by
    if created_by and created_by.id:
        distinct_id = created_by.distinct_id or f"user_{created_by.id}"
        auth_token = create_sandbox_connection_token(task_run, user_id=created_by.id, distinct_id=distinct_id)

    # Push a fresh MCP config before the turn so the agent-server rebinds its
    # ACP session to a non-stale OAuth token. Non-fatal: if refresh fails we
    # still deliver the follow-up with the existing (possibly stale) creds.
    _refresh_sandbox_mcp(task_run, input.posthog_mcp_scopes, auth_token)
    artifacts = None
    artifact_ids = input.artifact_ids or []
    if artifact_ids:
        artifacts, missing_artifact_ids = get_task_run_artifacts_by_id(task_run, artifact_ids)
        if missing_artifact_ids:
            error_msg = f"Artifacts not found on this run: {', '.join(missing_artifact_ids)}"
            _write_error_and_complete(input.run_id, error_msg, run_uses_dedicated_stream(task_run.state))
            raise RuntimeError(f"send_followup failed: {error_msg}")

    result = send_user_message(
        task_run,
        input.message,
        artifacts=artifacts,
        auth_token=auth_token,
        timeout=FOLLOWUP_TIMEOUT_SECONDS,
    )
    logger.info(
        "send_followup_to_sandbox_attempted",
        run_id=input.run_id,
        has_message=bool(input.message),
        artifact_count=len(artifacts or []),
    )

    if result.success:
        _write_turn_complete(input.run_id, _get_stop_reason(result.data), run_uses_dedicated_stream(task_run.state))
        logger.info("send_followup_delivered", run_id=input.run_id)
    else:
        logger.warning(
            "send_followup_failed",
            run_id=input.run_id,
            error=result.error,
            status_code=result.status_code,
        )
        error_msg = result.error or "Failed to send message to sandbox"
        _write_error_and_complete(input.run_id, error_msg, run_uses_dedicated_stream(task_run.state))
        # Propagate failure to the workflow.
        raise RuntimeError(f"send_followup failed: {error_msg}")


def _refresh_sandbox_mcp(
    task_run: TaskRun,
    scopes: PosthogMcpScopes,
    auth_token: str | None,
) -> None:
    """Best-effort MCP refresh for the web-layer follow-up flow.

    Scopes the OAuth token to the task creator; the web-layer follow-up signal
    has no per-turn actor concept. The Slack follow-up path calls
    :func:`refresh_sandbox_mcp_for_user` directly so the live mentioner's
    identity is used.
    """
    created_by = task_run.task.created_by
    if not created_by:
        logger.info("refresh_mcp_skipped_no_user", run_id=str(task_run.id))
        return
    refresh_sandbox_mcp_for_user(task_run, created_by, scopes=scopes, auth_token=auth_token)


def refresh_sandbox_mcp_for_user(
    task_run: TaskRun,
    user: Any,
    *,
    scopes: PosthogMcpScopes,
    auth_token: str | None,
    force: bool = False,
) -> CommandResult | None:
    """Mint a fresh OAuth token scoped to ``user`` and push updated MCP configs
    to the sandbox via ``send_refresh_session``.

    Retries once on failure, then logs and returns. Never raises — a failed
    refresh should not block an otherwise-valid follow-up.

    Rate-limited per ``(run_id, user_id)``: skipped if the same user already
    had a token issued within the ``MCP_TOKEN_REFRESH_INTERVAL_SECONDS`` window,
    unless ``force=True``. Cross-user transitions (Slack follow-ups by a
    teammate other than the task creator) pass ``force=True`` so the identity
    swap isn't blocked by a recent same-run refresh.

    Returns the last ``CommandResult`` from ``send_refresh_session``, or
    ``None`` when skipped (rate limit, no configs, mint failure).
    """
    run_id = str(task_run.id)
    rate_limit_key = f"{run_id}:{user.id}"
    if not force and not should_refresh_mcp_token(rate_limit_key):
        logger.info("refresh_mcp_skipped_within_interval", run_id=run_id, user_id=user.id)
        return None

    task = task_run.task
    try:
        access_token = create_oauth_access_token_for_user(
            user,
            task_run.team_id,
            scopes=scopes,
            application=oauth_application_for_task(task),
        )
    except Exception as e:
        logger.warning("refresh_mcp_token_mint_failed", run_id=run_id, user_id=user.id, error=str(e))
        return None

    mcp_configs = get_sandbox_ph_mcp_configs(
        token=access_token,
        project_id=task_run.team_id,
        scopes=scopes,
        interaction_origin=(task_run.state or {}).get("interaction_origin"),
        task_id=str(task_run.task_id),
    )
    user_mcp_configs = get_user_mcp_server_configs(
        token=access_token,
        team_id=task_run.team_id,
        user_id=user.id,
        interaction_origin=(task_run.state or {}).get("interaction_origin"),
    )
    if user_mcp_configs:
        mcp_configs = mcp_configs + user_mcp_configs

    if not mcp_configs:
        logger.info("refresh_mcp_skipped_no_configs", run_id=run_id, user_id=user.id)
        return None

    mcp_servers = [config.to_dict() for config in mcp_configs]

    result = send_refresh_session(
        task_run,
        mcp_servers,
        auth_token=auth_token,
        timeout=REFRESH_TIMEOUT_SECONDS,
    )
    if result.success:
        mark_mcp_token_issued(rate_limit_key)
        logger.info("refresh_mcp_delivered", run_id=run_id, user_id=user.id, attempts=1)
        return result

    logger.info(
        "refresh_mcp_retrying",
        run_id=run_id,
        user_id=user.id,
        error=result.error,
        status_code=result.status_code,
    )
    time.sleep(REFRESH_RETRY_DELAY_SECONDS)
    retry: CommandResult = send_refresh_session(
        task_run,
        mcp_servers,
        auth_token=auth_token,
        timeout=REFRESH_TIMEOUT_SECONDS,
    )
    if retry.success:
        mark_mcp_token_issued(rate_limit_key)
        logger.info("refresh_mcp_delivered", run_id=run_id, user_id=user.id, attempts=2)
        return retry

    logger.warning(
        "refresh_mcp_failed",
        run_id=run_id,
        user_id=user.id,
        error=retry.error,
        status_code=retry.status_code,
    )
    return retry


def _get_stop_reason(result_data: dict[str, Any] | None) -> str:
    if not isinstance(result_data, dict):
        return STOP_REASON_END_TURN

    result = result_data.get("result")
    if not isinstance(result, dict):
        return STOP_REASON_END_TURN

    stop_reason = result.get("stopReason")
    return stop_reason if isinstance(stop_reason, str) and stop_reason else STOP_REASON_END_TURN


def _write_turn_complete(run_id: str, stop_reason: str = STOP_REASON_END_TURN, use_dedicated: bool = False) -> None:
    """Write a synthetic turn_complete event to the Redis stream."""
    stream_key = get_task_run_stream_key(run_id)
    event = {
        "type": "notification",
        "notification": {
            "method": TURN_COMPLETE_METHOD,
            "params": {"source": "posthog", "stopReason": stop_reason},
        },
    }
    conn = get_tasks_stream_redis_sync(use_dedicated)
    conn.xadd(stream_key, {"data": json.dumps(event)}, maxlen=2000)


def _write_error_and_complete(run_id: str, error_message: str, use_dedicated: bool = False) -> None:
    """Write an error event followed by turn_complete to the Redis stream."""
    stream_key = get_task_run_stream_key(run_id)
    conn = get_tasks_stream_redis_sync(use_dedicated)

    error_event = {
        "type": "notification",
        "notification": {
            "method": "_posthog/error",
            "params": {"message": error_message},
        },
    }
    conn.xadd(stream_key, {"data": json.dumps(error_event)}, maxlen=2000)
    _write_turn_complete(run_id, use_dedicated=use_dedicated)
