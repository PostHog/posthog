import json
import time
import threading
import contextvars
from dataclasses import dataclass
from typing import Any

import structlog
from temporalio import activity
from temporalio.exceptions import ApplicationError

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
from products.tasks.backend.temporal.oauth import create_oauth_access_token
from products.tasks.backend.temporal.process_task.utils import (
    get_sandbox_ph_mcp_configs,
    get_user_mcp_server_configs,
    mark_mcp_token_issued,
    should_refresh_mcp_token,
)

from ee.hogai.sandbox import STOP_REASON_END_TURN, TURN_COMPLETE_METHOD

logger = structlog.get_logger(__name__)

REFRESH_RETRY_DELAY_SECONDS = 0.5

# Retries exist for attempt-level deaths (worker restart kills the in-flight
# attempt, detected via heartbeat timeout) and for delivery-unknown failures.
# Application failures that write an error sentinel raise non-retryable.
SEND_FOLLOWUP_MAX_ATTEMPTS = 3
SEND_FOLLOWUP_HEARTBEAT_INTERVAL_SECONDS = 15


@dataclass
class SendFollowupToSandboxInput:
    run_id: str
    message: str | None = None
    posthog_mcp_scopes: PosthogMcpScopes = "read_only"
    artifact_ids: list[str] | None = None
    # Workflow-generated idempotency key. Stable across activity retries, so
    # the agent-server can drop a redelivery of a message it already accepted.
    message_id: str | None = None


@activity.defn
@close_db_connections
def send_followup_to_sandbox(input: SendFollowupToSandboxInput) -> None:
    """Send a follow-up user message to the sandbox and write result markers to Redis.

    Called by the workflow when it receives a send_followup_message signal from the
    web layer. Writes turn_complete on success or an error event on failure so the
    SSE stream terminates cleanly.

    Heartbeats from a side thread while the delivery call blocks (the sync
    /command response can legitimately take up to FOLLOWUP_TIMEOUT_SECONDS),
    so a worker restart is detected within the heartbeat timeout instead of
    the 35-minute start_to_close.
    """
    stop_heartbeat = threading.Event()
    heartbeat_ctx = contextvars.copy_context()

    def _heartbeat_loop() -> None:
        while not stop_heartbeat.wait(SEND_FOLLOWUP_HEARTBEAT_INTERVAL_SECONDS):
            try:
                activity.heartbeat()
            except Exception:
                return

    heartbeat_thread = threading.Thread(target=lambda: heartbeat_ctx.run(_heartbeat_loop), daemon=True)
    heartbeat_thread.start()
    try:
        _deliver_followup(input)
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=2)


def _current_attempt() -> int:
    try:
        return activity.info().attempt
    except Exception:
        return 1


def _is_duplicate_delivery(result_data: dict[str, Any] | None) -> bool:
    if not isinstance(result_data, dict):
        return False
    result = result_data.get("result")
    return isinstance(result, dict) and result.get("duplicate") is True


def _deliver_followup(input: SendFollowupToSandboxInput) -> None:
    try:
        task_run = TaskRun.objects.select_related("task__created_by").get(id=input.run_id)
    except TaskRun.DoesNotExist:
        error_msg = "Task run not found"
        logger.warning("send_followup_run_not_found", run_id=input.run_id)
        _write_error_and_complete(input.run_id, error_msg)
        # Raise so the workflow can mark the run as failed. Without this,
        # background-mode runs hang until the inactivity timeout because
        raise ApplicationError(f"send_followup failed: {error_msg}", non_retryable=True)

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
            raise ApplicationError(f"send_followup failed: {error_msg}", non_retryable=True)

    result = send_user_message(
        task_run,
        input.message,
        artifacts=artifacts,
        auth_token=auth_token,
        timeout=FOLLOWUP_TIMEOUT_SECONDS,
        message_id=input.message_id,
    )
    logger.info(
        "send_followup_to_sandbox_attempted",
        run_id=input.run_id,
        has_message=bool(input.message),
        artifact_count=len(artifacts or []),
    )

    if result.success:
        if _is_duplicate_delivery(result.data):
            logger.info(
                "send_followup_duplicate_delivery",
                run_id=input.run_id,
                attempt=_current_attempt(),
            )
            return
        _write_turn_complete(input.run_id, _get_stop_reason(result.data), run_uses_dedicated_stream(task_run.state))
        logger.info("send_followup_delivered", run_id=input.run_id)
    elif result.turn_in_flight:
        # A read timeout means the message reached the sandbox and the turn is
        # simply still running — FOLLOWUP_TIMEOUT_SECONDS caps how long this
        # activity waits for the synchronous ack, not how long a turn may
        # take. Don't fail the run or write a sentinel: the sandbox broadcasts
        # _posthog/turn_complete through the event stream when the turn
        # actually ends, and run liveness stays governed by heartbeats plus the
        # workflow inactivity timeout. Failing here used to destroy healthy
        # sandboxes mid-work on any turn longer than 30 minutes.
        logger.info(
            "send_followup_turn_still_running",
            run_id=input.run_id,
            timeout_seconds=FOLLOWUP_TIMEOUT_SECONDS,
        )
    elif result.status_code == 504:
        # A 504 *response* (Modal tunnel gateway timeout) leaves delivery
        # unknown: the message may or may not have reached the agent-server.
        # The message_id idempotency key makes redelivery safe, so retry
        # instead of guessing; only the final attempt writes the sentinel.
        attempt = _current_attempt()
        if attempt < SEND_FOLLOWUP_MAX_ATTEMPTS:
            logger.warning(
                "send_followup_delivery_unknown_retrying",
                run_id=input.run_id,
                attempt=attempt,
                error=result.error,
            )
            raise ApplicationError(f"send_followup delivery unknown: {result.error}")
        error_msg = result.error or "Failed to send message to sandbox"
        logger.warning(
            "send_followup_failed",
            run_id=input.run_id,
            error=error_msg,
            status_code=result.status_code,
        )
        _write_error_and_complete(input.run_id, error_msg, run_uses_dedicated_stream(task_run.state))
        raise ApplicationError(f"send_followup failed: {error_msg}", non_retryable=True)
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
        raise ApplicationError(f"send_followup failed: {error_msg}", non_retryable=True)


def _refresh_sandbox_mcp(
    task_run: TaskRun,
    scopes: PosthogMcpScopes,
    auth_token: str | None,
) -> None:
    """Mint a fresh OAuth token and push updated MCP configs to the sandbox.

    Best-effort: retries once on failure, then logs and returns. Never raises
    — a failed refresh should not block an otherwise-valid follow-up.

    Skipped entirely if a token was issued for this run within the last
    MCP_TOKEN_REFRESH_INTERVAL_SECONDS — the in-sandbox token is still fresh.
    """
    run_id = str(task_run.id)
    if not should_refresh_mcp_token(run_id):
        logger.info("refresh_mcp_skipped_within_interval", run_id=run_id)
        return

    task = task_run.task
    try:
        access_token = create_oauth_access_token(task, scopes=scopes)
    except Exception as e:
        logger.warning("refresh_mcp_token_mint_failed", run_id=run_id, error=str(e))
        return

    mcp_configs = get_sandbox_ph_mcp_configs(
        token=access_token,
        project_id=task_run.team_id,
        scopes=scopes,
        interaction_origin=(task_run.state or {}).get("interaction_origin"),
        task_id=str(task_run.task_id),
    )
    if task.created_by_id:
        user_mcp_configs = get_user_mcp_server_configs(
            token=access_token,
            team_id=task_run.team_id,
            user_id=task.created_by_id,
            interaction_origin=(task_run.state or {}).get("interaction_origin"),
        )
        if user_mcp_configs:
            mcp_configs = mcp_configs + user_mcp_configs

    if not mcp_configs:
        logger.info("refresh_mcp_skipped_no_configs", run_id=run_id)
        return

    mcp_servers = [config.to_dict() for config in mcp_configs]

    result = send_refresh_session(
        task_run,
        mcp_servers,
        auth_token=auth_token,
        timeout=REFRESH_TIMEOUT_SECONDS,
    )
    if result.success:
        mark_mcp_token_issued(run_id)
        logger.info("refresh_mcp_delivered", run_id=run_id, attempts=1)
        return

    logger.info(
        "refresh_mcp_retrying",
        run_id=run_id,
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
        mark_mcp_token_issued(run_id)
        logger.info("refresh_mcp_delivered", run_id=run_id, attempts=2)
        return

    logger.warning(
        "refresh_mcp_failed",
        run_id=run_id,
        error=retry.error,
        status_code=retry.status_code,
    )


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
