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
from products.tasks.backend.logic.services.run_actor import slack_actor_state_updates
from products.tasks.backend.logic.services.staged_artifacts import get_task_run_artifacts_by_id
from products.tasks.backend.logic.stream.redis_stream import get_task_run_stream_key
from products.tasks.backend.models import TaskRun
from products.tasks.backend.redis import get_tasks_stream_redis_sync, run_uses_dedicated_stream
from products.tasks.backend.temporal.oauth import create_oauth_access_token_for_run
from products.tasks.backend.temporal.process_task.utils import (
    get_actor_distinct_id,
    get_imported_mcp_server_configs,
    get_sandbox_mcp_session_user,
    get_sandbox_ph_mcp_configs,
    get_task_run_credential_user,
    get_user_mcp_server_configs,
    is_slack_interaction_state,
    mark_sandbox_mcp_session,
    record_message_actor,
    sandbox_identity_scope,
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
    # Idempotency key, stable across retries and redeliveries; the
    # agent-server drops a duplicate it already accepted.
    message_id: str | None = None
    # Sender of this message; None (older senders, pre-rollout histories)
    # falls back to the run-state actor.
    actor_user_id: int | None = None
    # Signal context, passed through from PendingFollowup.
    context: dict[str, Any] | None = None


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
        task_run = TaskRun.objects.select_related("task__created_by", "task__team").get(id=input.run_id)
    except TaskRun.DoesNotExist:
        error_msg = "Task run not found"
        logger.warning("send_followup_run_not_found", run_id=input.run_id)
        _write_error_and_complete(input.run_id, error_msg)
        # Raise so the workflow can mark the run as failed. Without this,
        # background-mode runs hang until the inactivity timeout because
        raise ApplicationError(f"send_followup failed: {error_msg}", non_retryable=True)

    # Resolve credentials against this message's sender, not the run-state
    # actor a concurrent follow-up may have overwritten since queueing. Local
    # overlay; the resolver still enforces team access (see run_actor.py).
    raw_actor_slack_user_id = (input.context or {}).get("actor_slack_user_id")
    actor_slack_user_id = raw_actor_slack_user_id if isinstance(raw_actor_slack_user_id, str) else None

    state = task_run.state
    if input.actor_user_id is not None:
        state = {**(state or {}), "slack_actor_user_id": input.actor_user_id}
        if is_slack_interaction_state(state):
            # Deliveries are serialized by the workflow, so stamping here
            # moves the durable actor at turn boundaries — between-turn
            # consumers (reply tagging, permission broker) see the executing
            # turn's actor. Skipped when already current.
            updates = slack_actor_state_updates(user_id=input.actor_user_id, slack_user_id=actor_slack_user_id)
            current = task_run.state or {}
            if any(current.get(key) != value for key, value in updates.items()):
                try:
                    TaskRun.update_state_atomic(task_run.id, updates=updates)
                except Exception:
                    logger.warning("send_followup_actor_stamp_failed", run_id=input.run_id, exc_info=True)

    auth_token = None
    actor_user = get_task_run_credential_user(task_run.task, state)
    if is_slack_interaction_state(state) and actor_user is None:
        error_msg = "Slack actor unavailable for this run"
        _write_error_and_complete(input.run_id, error_msg, run_uses_dedicated_stream(task_run.state))
        raise RuntimeError(f"send_followup failed: {error_msg}")
    if actor_user and actor_user.id:
        auth_token = create_sandbox_connection_token(
            task_run, user_id=actor_user.id, distinct_id=get_actor_distinct_id(actor_user)
        )

    # Rebind the sandbox's MCP session to this actor before the turn. On an
    # actor transition this must rebind or clear the prior session; if it can't,
    # fail closed rather than run the turn under the previous actor's creds.
    # Same-actor and first-bind refreshes stay best-effort.
    if not _refresh_sandbox_mcp(task_run, input.posthog_mcp_scopes, auth_token, actor_user=actor_user, state=state):
        error_msg = "Could not rebind sandbox MCP credentials for the follow-up actor"
        raise RuntimeError(f"send_followup failed: {error_msg}")
    artifacts = None
    artifact_ids = input.artifact_ids or []
    if artifact_ids:
        artifacts, missing_artifact_ids = get_task_run_artifacts_by_id(task_run, artifact_ids)
        if missing_artifact_ids:
            error_msg = f"Artifacts not found on this run: {', '.join(missing_artifact_ids)}"
            _write_error_and_complete(input.run_id, error_msg, run_uses_dedicated_stream(task_run.state))
            raise ApplicationError(f"send_followup failed: {error_msg}", non_retryable=True)

    if input.message_id and actor_slack_user_id:
        record_message_actor(input.run_id, input.message_id, actor_slack_user_id)

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
    *,
    actor_user: Any,
    state: dict[str, Any] | None,
) -> bool:
    """Rebind the sandbox's MCP session to this message's actor.

    Returns ``True`` when the session is safe to use (unchanged actor or a
    successful rebind) and ``False`` when a rebind could not be confirmed — the
    caller then fails the follow-up closed. A rebind is unconfirmed whenever the
    mint or refresh fails and the binding is not known to be this actor's,
    including an *unknown* binding: the marker self-expires at half the token
    lifetime, so an absent marker can mean the previous actor's session is still
    live, not that the sandbox is fresh. Retries the refresh once before giving
    up.
    """
    run_id = str(task_run.id)
    if actor_user is None:
        # Without a credential user the mint is guaranteed to fail; skip
        # quietly rather than warn on every message.
        return True

    scope = sandbox_identity_scope(run_id, state)
    bound_user_id = get_sandbox_mcp_session_user(scope)
    if bound_user_id == actor_user.id:
        logger.info("refresh_mcp_skipped_within_interval", run_id=run_id, user_id=actor_user.id)
        return True
    is_transition = bound_user_id is not None
    if is_transition:
        logger.info(
            "refresh_mcp_identity_transition",
            run_id=run_id,
            previous_user_id=bound_user_id,
            user_id=actor_user.id,
        )

    try:
        access_token = create_oauth_access_token_for_run(task_run.task, state, scopes=scopes)
    except Exception as e:
        logger.warning("refresh_mcp_token_mint_failed", run_id=run_id, error=str(e))
        return False  # rebind unconfirmed → fail closed (unknown binding may hide a live session)

    mcp_configs = get_sandbox_ph_mcp_configs(
        token=access_token,
        project_id=task_run.team_id,
        scopes=scopes,
        interaction_origin=(state or {}).get("interaction_origin"),
        task_id=str(task_run.task_id),
    )
    user_mcp_configs = get_user_mcp_server_configs(
        token=access_token,
        team_id=task_run.team_id,
        user_id=actor_user.id,
        interaction_origin=(state or {}).get("interaction_origin"),
    )
    if user_mcp_configs:
        mcp_configs = mcp_configs + user_mcp_configs

    # refresh_session replaces the session's server list wholesale, so the
    # run's imported servers must ride along or they vanish mid-run.
    imported_mcp_configs = get_imported_mcp_server_configs(task_run, {config.name for config in mcp_configs})
    if imported_mcp_configs:
        mcp_configs = mcp_configs + imported_mcp_configs

    if not mcp_configs:
        if is_transition:
            # The new actor resolves no MCP configs, and an empty-list refresh is
            # a notification-only no-op on the agent-server (see
            # send_refresh_session) — it cannot tear down the previous actor's
            # live session. So we neither send nor rebind: leave the binding on
            # the previous actor, which accurately describes the live session,
            # and re-attempt on their next message. Only reachable on deployments
            # without a resolvable MCP URL (get_sandbox_ph_mcp_configs is
            # otherwise never empty), so best-effort delivery is acceptable.
            logger.info("refresh_mcp_no_configs_on_transition", run_id=run_id, previous_user_id=bound_user_id)
            return True
        # First bind for this sandbox and the actor has no MCP configs: there is
        # no prior session to tear down, so just record the binding.
        mark_sandbox_mcp_session(scope, actor_user.id)
        logger.info("refresh_mcp_skipped_no_configs", run_id=run_id)
        return True

    mcp_servers = [config.to_dict() for config in mcp_configs]

    result = send_refresh_session(
        task_run,
        mcp_servers,
        auth_token=auth_token,
        timeout=REFRESH_TIMEOUT_SECONDS,
    )
    if result.success:
        mark_sandbox_mcp_session(scope, actor_user.id)
        logger.info("refresh_mcp_delivered", run_id=run_id, attempts=1)
        return True

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
        mark_sandbox_mcp_session(scope, actor_user.id)
        logger.info("refresh_mcp_delivered", run_id=run_id, attempts=2)
        return True

    logger.warning(
        "refresh_mcp_failed",
        run_id=run_id,
        error=retry.error,
        status_code=retry.status_code,
    )
    return False  # rebind never confirmed → fail closed (unknown binding may hide a live session)


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
