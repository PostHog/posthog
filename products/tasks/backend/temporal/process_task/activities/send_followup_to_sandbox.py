import json
import time
import threading
import contextvars
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, NoReturn

import structlog
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.dataclasses import frozen
from posthog.models.integration import Integration
from posthog.models.user_integration import ReauthorizationRequired, UserIntegration
from posthog.temporal.common.utils import close_db_connections
from posthog.temporal.oauth import PosthogMcpScopes

from products.tasks.backend.exceptions import CredentialUnavailableError
from products.tasks.backend.logic.services.agent_command import (
    FOLLOWUP_TIMEOUT_SECONDS,
    REFRESH_TIMEOUT_SECONDS,
    TURN_ENDED_WITHOUT_RESPONSE_ERROR,
    CommandResult,
    send_refresh_session,
    send_user_message,
    user_facing_agent_error,
)
from products.tasks.backend.logic.services.connection_token import create_sandbox_connection_token
from products.tasks.backend.logic.services.peer_messages import mark_peer_message_outcome, peer_message_id_from_context
from products.tasks.backend.logic.services.run_actor import slack_actor_state_updates, user_has_current_team_access
from products.tasks.backend.logic.services.staged_artifacts import get_task_run_artifacts_by_id
from products.tasks.backend.logic.stream.redis_stream import get_task_run_stream_key
from products.tasks.backend.metrics import observe_followup_denied_permission_stop, observe_followup_sandbox_stopped
from products.tasks.backend.models import AgentPeerMessage, TaskRun
from products.tasks.backend.redis import get_tasks_stream_redis_sync, run_uses_dedicated_stream
from products.tasks.backend.temporal.oauth import create_oauth_access_token_for_run
from products.tasks.backend.temporal.process_task.sandbox_credentials import (
    apply_github_credentials_to_sandbox,
    clear_github_credentials_from_sandbox,
    sandbox_credential_lock,
)
from products.tasks.backend.temporal.process_task.utils import (
    PrAuthorshipMode,
    get_actor_distinct_id,
    get_imported_mcp_server_configs,
    get_pr_authorship_mode,
    get_sandbox_github_token,
    get_sandbox_mcp_session_user,
    get_sandbox_ph_mcp_configs,
    get_task_run_credential_user,
    get_user_mcp_server_configs,
    is_slack_interaction_state,
    loop_mcp_installation_allowlist,
    mark_sandbox_github_identity,
    mark_sandbox_mcp_session,
    record_message_actor,
    sandbox_identity_scope,
    upgrade_run_to_user_authorship,
)

from ee.hogai.sandbox import STOP_REASON_END_TURN, TURN_COMPLETE_METHOD

logger = structlog.get_logger(__name__)


class SandboxRebindFailure(StrEnum):
    """Why a credential rebind could not be confirmed, so a failed run names the gate
    that rejected it rather than reporting one message for every cause."""

    TOKEN_MINT_FAILED = "token_mint_failed"
    NO_CONFIGS_ON_TRANSITION = "no_configs_on_transition"
    REFRESH_SESSION_FAILED = "refresh_session_failed"
    NO_SANDBOX_HANDLE = "no_sandbox_handle"
    SANDBOX_NOT_RUNNING = "sandbox_not_running"
    CREDENTIAL_LOCK_UNAVAILABLE = "credential_lock_unavailable"
    LOGOUT_ERRORED = "logout_errored"
    LOGOUT_UNCONFIRMED = "logout_unconfirmed"


REFRESH_RETRY_DELAY_SECONDS = 0.5

SANDBOX_STOPPED_MESSAGE = (
    "This run's sandbox has stopped, so your message wasn't delivered. Start a new run to continue."
)
PEER_SANDBOX_STOPPED_MESSAGE = "The recipient run's sandbox has stopped"
DENIED_PERMISSION_STOP_MESSAGE = (
    "Stopped after the denied action. Send a new message to continue with a different approach."
)
SLACK_PERMISSION_REJECTED_REQUEST_ID_KEY = "slack_permission_rejected_request_id"
DENIAL_BRAKE_CONSUMED_REQUEST_ID_KEY = "followup_denial_brake_request_id"

# Retries exist for attempt-level deaths (worker restart kills the in-flight
# attempt, detected via heartbeat timeout) and for delivery-unknown failures.
# Application failures that write an error sentinel raise non-retryable.
SEND_FOLLOWUP_MAX_ATTEMPTS = 3
SEND_FOLLOWUP_HEARTBEAT_INTERVAL_SECONDS = 15
STEER_DECLINED_OUTCOME = "steer_declined"
STEER_DECLINE_REASON_UNREPORTED = "unreported"
STEER_DECLINE_REASON_ACTOR_MISMATCH = "actor_mismatch"


@dataclass
class SendFollowupToSandboxInput:
    run_id: str
    message: str | None = None
    posthog_mcp_scopes: PosthogMcpScopes = "read_only"
    artifact_ids: list[str] | None = None
    message_id: str | None = None
    # Sender of this message; None (older senders, pre-rollout histories)
    # falls back to the run-state actor.
    actor_user_id: int | None = None
    # Signal context, passed through from PendingFollowup.
    context: dict[str, Any] | None = None
    steer: bool = False
    max_attempts: int = SEND_FOLLOWUP_MAX_ATTEMPTS


@activity.defn
@close_db_connections
def send_followup_to_sandbox(input: SendFollowupToSandboxInput) -> str | None:
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
        return _deliver_followup(input)
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=2)


def _current_attempt() -> int:
    try:
        return activity.info().attempt
    except Exception:
        return 1


def _fail_rebind_closed(
    run_id: str, event: str, reason: SandboxRebindFailure, actor_user: Any, message: str
) -> NoReturn:
    """Log and raise for a rebind that could not be confirmed. Both gates report the
    same way, so the reason reaches the log and the reply from one place."""
    logger.warning(
        event,
        run_id=run_id,
        reason=reason,
        actor_user_id=actor_user.id if actor_user is not None else None,
    )
    raise RuntimeError(f"send_followup failed: {message} ({reason})")


def _fail_when_sandbox_stopped(
    run_id: str,
    state: dict[str, Any] | None,
    actor_user: Any,
    *,
    task_run: TaskRun | None = None,
    peer_message_id: str | None = None,
) -> None:
    """Stop a delivery the control plane says can never land, before anything else reports it.

    Both credential gates reach the sandbox over its saved URL, so a stopped sandbox fails
    whichever runs first and the run gets that gate's wording. Asking the control plane up
    front is what makes the reply name the sandbox, and it covers the runs neither gate would
    have reported: a bot-authored run skips the GitHub gate entirely.
    """
    if not (state or {}).get("sandbox_id"):
        return
    if not _resolve_live_sandbox(state).stopped:
        return
    observe_followup_sandbox_stopped(task_run, detected_by="preflight")
    logger.warning(
        "send_followup_sandbox_stopped",
        run_id=run_id,
        actor_user_id=actor_user.id if actor_user is not None else None,
        sandbox_id=(state or {}).get("sandbox_id"),
    )
    if peer_message_id is not None:
        _mark_peer_delivery_outcome(
            peer_message_id,
            AgentPeerMessage.Outcome.DELIVERY_FAILED,
            "sandbox_stopped",
            PEER_SANDBOX_STOPPED_MESSAGE,
        )
        raise ApplicationError(f"peer message delivery failed: {PEER_SANDBOX_STOPPED_MESSAGE}", non_retryable=True)
    raise ApplicationError(SANDBOX_STOPPED_MESSAGE, non_retryable=True)


def _is_denied_permission_stop(run_id: str, error: str | None, *, steer: bool = False) -> bool:
    """Whether the turn ended on a user message because the actor denied a permission
    request, rather than the steer race the same diagnostic also reports.

    Both end the turn identically, so the run's recorded denial is what tells them apart.
    A denied turn must not be redelivered: the retry would re-ask the question the actor
    just refused. Slack keys on the same pairing (see post_slack_update.py).

    Two things make that pairing unreliable on its own. The denial is recorded by another
    activity while this one is blocked inside the turn it ends, so the state read before
    delivery predates it — hence the fresh read here. And the run-level flag is never
    cleared, so on its own it would brake every later steer race for the rest of the run
    and drop those messages. Braking once per rejected request keeps both cases right.

    A steer joins the live turn that the denial ends, so a base delivery and a steer
    routinely fail together on this same diagnostic. Only the base delivery can re-ask the
    refused permission, so a steer never brakes: leaving both eligible lets row-lock order
    decide which of the two is dropped. Claiming stays one locked read-modify-write so that
    deliveries arriving on the same denial brake once per rejected request.
    """
    if steer or not error or TURN_ENDED_WITHOUT_RESPONSE_ERROR not in error:
        return False

    claimed = False

    def claim_denial(state: dict[str, Any]) -> None:
        nonlocal claimed
        if not state.get("slack_permission_rejected"):
            return
        request_id = state.get(SLACK_PERMISSION_REJECTED_REQUEST_ID_KEY)
        if request_id is None:
            # A denial recorded before the request id was tracked carries nothing to claim, so
            # it brakes every racer. Re-asking a question the actor refused is worse than a
            # message they are told was not delivered.
            claimed = True
            return
        if state.get(DENIAL_BRAKE_CONSUMED_REQUEST_ID_KEY) == request_id:
            return
        state[DENIAL_BRAKE_CONSUMED_REQUEST_ID_KEY] = request_id
        claimed = True

    try:
        TaskRun.mutate_state_atomic(run_id, claim_denial)
    except Exception:
        logger.warning("send_followup_denial_state_read_failed", run_id=run_id, exc_info=True)
        return False
    return claimed


def _is_duplicate_delivery(result_data: dict[str, Any] | None) -> bool:
    if not isinstance(result_data, dict):
        return False
    result = result_data.get("result")
    return isinstance(result, dict) and result.get("duplicate") is True


def _is_steered(result_data: dict[str, Any] | None) -> bool:
    if not isinstance(result_data, dict):
        return False
    result = result_data.get("result")
    return isinstance(result, dict) and result.get("steered") is True


def _is_steer_declined(result_data: dict[str, Any] | None) -> bool:
    if not isinstance(result_data, dict):
        return False
    result = result_data.get("result")
    return isinstance(result, dict) and result.get("steered") is False


def _steer_decline_reason(result_data: dict[str, Any] | None) -> str:
    if not isinstance(result_data, dict):
        return STEER_DECLINE_REASON_UNREPORTED
    result = result_data.get("result")
    if not isinstance(result, dict):
        return STEER_DECLINE_REASON_UNREPORTED
    reason = result.get("reason")
    return reason if isinstance(reason, str) and reason else STEER_DECLINE_REASON_UNREPORTED


def _deliver_followup(input: SendFollowupToSandboxInput) -> str | None:
    peer_message_id = peer_message_id_from_context(input.context)
    try:
        task_run = TaskRun.objects.select_related("task__created_by", "task__team").get(id=input.run_id)
    except TaskRun.DoesNotExist:
        error_msg = "Task run not found"
        logger.warning("send_followup_run_not_found", run_id=input.run_id)
        if peer_message_id is not None:
            # Peer failures never write the recipient's stream sentinels; the row
            # carries the outcome and the workflow's isolation keeps the run healthy.
            _mark_peer_delivery_outcome(
                peer_message_id, AgentPeerMessage.Outcome.DELIVERY_FAILED, "run_not_found", error_msg
            )
            raise ApplicationError(f"peer message delivery failed: {error_msg}", non_retryable=True)
        _write_error_and_complete(input.run_id, error_msg)
        # Raise so the workflow can mark the run as failed. Without this,
        # background-mode runs hang until the inactivity timeout because
        raise ApplicationError(f"send_followup failed: {error_msg}", non_retryable=True)

    if peer_message_id is not None:
        return _deliver_peer_message(input, task_run, peer_message_id)

    # Resolve credentials against this message's sender, not the run-state
    # actor a concurrent follow-up may have overwritten since queueing. Local
    # overlay; the resolver still enforces team access (see run_actor.py).
    raw_actor_slack_user_id = (input.context or {}).get("actor_slack_user_id")
    actor_slack_user_id = raw_actor_slack_user_id if isinstance(raw_actor_slack_user_id, str) else None

    state = task_run.state
    if input.actor_user_id is not None:
        state = {**(state or {}), "slack_actor_user_id": input.actor_user_id}

    actor_user = get_task_run_credential_user(task_run.task, state)
    if is_slack_interaction_state(state) and actor_user is None:
        error_msg = "Slack actor unavailable for this run"
        logger.warning(
            "send_followup_slack_actor_unavailable",
            run_id=input.run_id,
            actor_user_id=input.actor_user_id,
            run_state_actor_user_id=(task_run.state or {}).get("slack_actor_user_id"),
            task_created_by_id=task_run.task.created_by_id,
        )
        _write_error_and_complete(input.run_id, error_msg, run_uses_dedicated_stream(task_run.state))
        raise RuntimeError(f"send_followup failed: {error_msg}")

    if input.steer:
        bound_user_id = get_sandbox_mcp_session_user(sandbox_identity_scope(str(task_run.id), task_run.state))
        if (
            input.actor_user_id is None
            or actor_user is None
            or actor_user.id != input.actor_user_id
            or bound_user_id != input.actor_user_id
        ):
            logger.info(
                "send_followup_steer_actor_mismatch",
                run_id=input.run_id,
                actor_user_id=input.actor_user_id,
                resolved_user_id=actor_user.id if actor_user is not None else None,
                bound_user_id=bound_user_id,
            )
            logger.info(
                "send_followup_steer_declined",
                run_id=input.run_id,
                reason=STEER_DECLINE_REASON_ACTOR_MISMATCH,
            )
            return STEER_DECLINED_OUTCOME

    if input.actor_user_id is not None and is_slack_interaction_state(state):
        # Deliveries are serialized by the workflow, so stamping here moves
        # the durable actor only after an active steer passes its identity gate.
        updates = slack_actor_state_updates(user_id=input.actor_user_id, slack_user_id=actor_slack_user_id)
        current = task_run.state or {}
        if any(current.get(key) != value for key, value in updates.items()):
            try:
                TaskRun.update_state_atomic(task_run.id, updates=updates)
            except Exception:
                logger.warning("send_followup_actor_stamp_failed", run_id=input.run_id, exc_info=True)

    auth_token = None
    if actor_user and actor_user.id:
        auth_token = create_sandbox_connection_token(
            task_run, user_id=actor_user.id, distinct_id=get_actor_distinct_id(actor_user)
        )

    _fail_when_sandbox_stopped(input.run_id, state, actor_user, task_run=task_run)

    # Rebind the sandbox's MCP session to this actor before the turn. On an
    # actor transition this must rebind or clear the prior session; if it can't,
    # fail closed rather than run the turn under the previous actor's creds.
    # A steer joins the active turn, so it cannot interrupt that turn with a
    # session refresh.
    if not input.steer:
        mcp_failure = _refresh_sandbox_mcp(
            task_run,
            input.posthog_mcp_scopes,
            auth_token,
            actor_user=actor_user,
            state=state,
        )
        if mcp_failure is not None:
            _fail_rebind_closed(
                input.run_id,
                "send_followup_mcp_rebind_failed",
                mcp_failure,
                actor_user,
                "Could not rebind sandbox MCP credentials for the follow-up actor",
            )

    # Bind the sandbox's GitHub credentials to this actor: rebind if they have
    # access, otherwise log out so the previous actor's identity can't be used.
    # Fail closed only if we can't even clear the prior credentials.
    github_failure = _refresh_sandbox_github(task_run, actor_user, state)
    if github_failure == SandboxRebindFailure.SANDBOX_NOT_RUNNING:
        observe_followup_sandbox_stopped(task_run, detected_by="github_rebind")
        logger.warning(
            "send_followup_sandbox_stopped",
            run_id=input.run_id,
            actor_user_id=actor_user.id if actor_user is not None else None,
            sandbox_id=(state or {}).get("sandbox_id"),
        )
        raise ApplicationError(SANDBOX_STOPPED_MESSAGE, non_retryable=True)
    if github_failure is not None:
        _fail_rebind_closed(
            input.run_id,
            "send_followup_github_rebind_failed",
            github_failure,
            actor_user,
            "Could not rebind or clear sandbox GitHub credentials for the follow-up actor",
        )
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
        steer=input.steer,
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
            return None
        if _is_steered(result.data):
            logger.info("send_followup_steered", run_id=input.run_id)
            return None
        if input.steer and _is_steer_declined(result.data):
            logger.info(
                "send_followup_steer_declined",
                run_id=input.run_id,
                reason=_steer_decline_reason(result.data),
            )
            return STEER_DECLINED_OUTCOME
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
    elif result.retryable and input.message_id:
        if _is_denied_permission_stop(input.run_id, result.error, steer=input.steer):
            observe_followup_denied_permission_stop(task_run)
            logger.warning(
                "send_followup_denied_permission_stop",
                run_id=input.run_id,
                error=result.error,
            )
            _write_error_and_complete(
                input.run_id, DENIED_PERMISSION_STOP_MESSAGE, run_uses_dedicated_stream(task_run.state)
            )
            raise ApplicationError(f"send_followup failed: {result.error}", non_retryable=True)
        # Retry transport failures and known transient agent errors. message_id
        # prevents duplicate turns when delivery is uncertain, and the agent-server
        # releases the id when a delivered turn fails before completion.
        attempt = _current_attempt()
        failure_kind = "delivery unknown" if result.status_code == 504 else "retryable failure"
        if attempt < input.max_attempts:
            logger.warning(
                "send_followup_retrying",
                run_id=input.run_id,
                attempt=attempt,
                error=result.error,
                status_code=result.status_code,
            )
            raise ApplicationError(f"send_followup {failure_kind}: {result.error}")
        error_msg = user_facing_agent_error(result.error)
        logger.warning(
            "send_followup_failed",
            run_id=input.run_id,
            error=result.error,
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
        error_msg = user_facing_agent_error(result.error)
        _write_error_and_complete(input.run_id, error_msg, run_uses_dedicated_stream(task_run.state))
        # Propagate failure to the workflow.
        raise ApplicationError(f"send_followup failed: {error_msg}", non_retryable=True)

    return None


def _mark_peer_delivery_outcome(peer_message_id: str, outcome: str, phase: str = "", detail: str = "") -> None:
    """Best-effort audit-row bookkeeping — a marking failure must never change how
    delivery itself is reported."""
    try:
        mark_peer_message_outcome(peer_message_id, outcome, failure_phase=phase, failure_detail=detail)
    except Exception:
        logger.warning("peer_message_outcome_mark_failed", peer_message_id=peer_message_id, exc_info=True)


def _resolve_peer_credential_actor(task_run: TaskRun) -> tuple[Any, str]:
    """The user a peer turn may execute as, or ``(None, reason)`` to fail delivery closed.

    The ONLY credential-actor source in peer delivery mode is the sandbox's own
    bound identity — never the message input, never task-state actor overlays — and
    the binding is honored only when it is the task creator with current active
    team access. v1 peer authorization is creator-to-creator (see
    visible_peer_runs), so the creator is the sole authority a peer message can
    carry. Everything else fails closed: an expired binding marker can hide a
    still-live prior session (the marker lives half the token lifetime), and a
    binding left by a teammate (e.g. a Slack interaction) must never lend their
    credentials to a turn they did not send.
    """
    bound_user_id = get_sandbox_mcp_session_user(sandbox_identity_scope(str(task_run.id), task_run.state))
    if bound_user_id is None:
        return None, "the sandbox's bound credential identity is unconfirmed"
    creator = task_run.task.created_by
    if creator is None or bound_user_id != creator.id:
        return None, "the sandbox is bound to a different user than the task creator"
    if not user_has_current_team_access(creator, task_run.task.team):
        return None, "the task creator no longer has active access to this team"
    return creator, ""


def _deliver_peer_message(input: SendFollowupToSandboxInput, task_run: TaskRun, peer_message_id: str) -> str | None:
    """Deliver an agent peer message (see logic/services/peer_messages.py).

    Deviations from the user follow-up path, each load-bearing for the delivery
    contract:
    - Credentials: delivery fails closed unless the sandbox's bound identity is
      confirmed to be the task creator with current team access (see
      _resolve_peer_credential_actor); refreshes then run strictly via that
      identity. A peer message can never mint or rebind credentials for anyone
      else, and never runs a turn on unconfirmed residual credentials.
    - Failures record the outcome on the message row and raise non-retryably
      WITHOUT stream error sentinels: no user turn is dangling, and the workflow's
      failure isolation keeps the recipient run healthy.
    - Steer is never honored; peer messages always queue as non-steer turns.
    """
    state = task_run.state
    actor_user, identity_error = _resolve_peer_credential_actor(task_run)
    if actor_user is None:
        error_msg = f"Peer delivery requires a confirmed credential identity: {identity_error}"
        _mark_peer_delivery_outcome(
            peer_message_id, AgentPeerMessage.Outcome.DELIVERY_FAILED, "credential_identity", error_msg
        )
        raise ApplicationError(f"peer message delivery failed: {error_msg}", non_retryable=True)

    auth_token = create_sandbox_connection_token(
        task_run, user_id=actor_user.id, distinct_id=get_actor_distinct_id(actor_user)
    )
    _fail_when_sandbox_stopped(input.run_id, state, actor_user, task_run=task_run, peer_message_id=peer_message_id)
    mcp_failure = _refresh_sandbox_mcp(
        task_run, input.posthog_mcp_scopes, auth_token, actor_user=actor_user, state=state
    )
    if mcp_failure is not None:
        error_msg = "Could not refresh sandbox MCP credentials via the bound identity"
        _mark_peer_delivery_outcome(
            peer_message_id, AgentPeerMessage.Outcome.DELIVERY_FAILED, "credential_refresh", error_msg
        )
        raise ApplicationError(f"peer message delivery failed: {error_msg}", non_retryable=True)
    github_failure = _refresh_sandbox_github(task_run, actor_user, state)
    if github_failure is not None:
        error_msg = (
            "The recipient run's sandbox has stopped"
            if github_failure == SandboxRebindFailure.SANDBOX_NOT_RUNNING
            else "Could not refresh sandbox GitHub credentials via the bound identity"
        )
        _mark_peer_delivery_outcome(
            peer_message_id, AgentPeerMessage.Outcome.DELIVERY_FAILED, "credential_refresh", error_msg
        )
        raise ApplicationError(f"peer message delivery failed: {error_msg}", non_retryable=True)

    artifacts = None
    if input.artifact_ids:
        artifacts, missing_artifact_ids = get_task_run_artifacts_by_id(task_run, input.artifact_ids)
        if missing_artifact_ids:
            error_msg = f"Peer attachments missing from the target run: {', '.join(missing_artifact_ids)}"
            _mark_peer_delivery_outcome(
                peer_message_id, AgentPeerMessage.Outcome.DELIVERY_FAILED, "artifacts_missing", error_msg
            )
            raise ApplicationError(f"peer message delivery failed: {error_msg}", non_retryable=True)

    result = send_user_message(
        task_run,
        input.message,
        artifacts=artifacts,
        auth_token=auth_token,
        timeout=FOLLOWUP_TIMEOUT_SECONDS,
        message_id=input.message_id,
        steer=False,
    )
    logger.info(
        "peer_message_delivery_attempted",
        run_id=input.run_id,
        peer_message_id=peer_message_id,
        artifact_count=len(artifacts or []),
    )

    if result.success:
        if _is_duplicate_delivery(result.data):
            # The sandbox already recorded this message_id: a prior attempt
            # delivered it, so the accurate audit outcome is delivered — and that
            # attempt owns the turn bookkeeping.
            _mark_peer_delivery_outcome(peer_message_id, AgentPeerMessage.Outcome.DELIVERED)
            return None
        _mark_peer_delivery_outcome(peer_message_id, AgentPeerMessage.Outcome.DELIVERED)
        _write_turn_complete(input.run_id, _get_stop_reason(result.data), run_uses_dedicated_stream(task_run.state))
        return None
    if result.turn_in_flight:
        # The read timeout means the message reached the sandbox and the turn is
        # simply still running (see the user path for why this is not a failure).
        _mark_peer_delivery_outcome(peer_message_id, AgentPeerMessage.Outcome.DELIVERED)
        return None
    if result.retryable and input.message_id and _current_attempt() < input.max_attempts:
        # Row stays signaled; a retried delivery is deduped by message_id and the
        # final attempt terminalizes below.
        raise ApplicationError(f"peer message delivery retryable failure: {result.error}")
    error_msg = user_facing_agent_error(result.error)
    logger.warning(
        "peer_message_delivery_failed",
        run_id=input.run_id,
        peer_message_id=peer_message_id,
        error=result.error,
        status_code=result.status_code,
    )
    _mark_peer_delivery_outcome(
        peer_message_id, AgentPeerMessage.Outcome.DELIVERY_FAILED, "sandbox_delivery", error_msg
    )
    raise ApplicationError(f"peer message delivery failed: {error_msg}", non_retryable=True)


def _refresh_sandbox_mcp(
    task_run: TaskRun,
    scopes: PosthogMcpScopes,
    auth_token: str | None,
    *,
    actor_user: Any,
    state: dict[str, Any] | None,
) -> SandboxRebindFailure | None:
    """Rebind the sandbox's MCP session to this message's actor.

    Returns ``None`` when the session is safe to use (unchanged actor or a
    successful rebind) and a short reason code when a rebind could not be
    confirmed — the caller then fails the follow-up closed and surfaces the code,
    so a failed run says which gate rejected it. A rebind is unconfirmed whenever
    the mint or refresh fails and the binding is not known to be this actor's,
    including an *unknown* binding: the marker self-expires at half the token
    lifetime, so an absent marker can mean the previous actor's session is still
    live, not that the sandbox is fresh. Retries the refresh once before giving
    up.
    """
    run_id = str(task_run.id)
    if actor_user is None:
        # Without a credential user the mint is guaranteed to fail; skip
        # quietly rather than warn on every message.
        return None

    scope = sandbox_identity_scope(run_id, state)
    bound_user_id = get_sandbox_mcp_session_user(scope)
    is_built_in_agent_task = task_run.task.mcp_builtin_agent_key is not None
    if bound_user_id == actor_user.id and not is_built_in_agent_task:
        logger.info("refresh_mcp_skipped_within_interval", run_id=run_id, user_id=actor_user.id)
        return None
    is_transition = bound_user_id is not None and bound_user_id != actor_user.id
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
        logger.warning(
            "refresh_mcp_token_mint_failed",
            run_id=run_id,
            error=str(e),
            error_type=type(e).__name__,
            user_id=actor_user.id,
            exc_info=True,
        )
        return (
            SandboxRebindFailure.TOKEN_MINT_FAILED
        )  # rebind unconfirmed → fail closed (unknown binding may hide a live session)

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
        include_personal=not task_run.task.internal,
        interaction_origin=(state or {}).get("interaction_origin"),
        allowed_installation_ids=loop_mcp_installation_allowlist(state),
        origin_product=task_run.task.origin_product,
        task_agent_key=task_run.task.mcp_builtin_agent_key,
        credential_owner_id=task_run.task.mcp_credential_owner_id,
        allowed_gateway_server_ids=task_run.task.mcp_gateway_server_allowlist,
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
            # A prior actor holds the live session and this actor resolves no MCP
            # configs, so an empty-list refresh (a no-op on the agent-server)
            # can neither rebind it nor tear it down. Fail closed rather than run
            # the turn against the previous actor's retained session.
            logger.warning(
                "refresh_mcp_no_configs_on_transition_fail_closed",
                run_id=run_id,
                previous_user_id=bound_user_id,
                user_id=actor_user.id,
            )
            return SandboxRebindFailure.NO_CONFIGS_ON_TRANSITION
        # No recorded prior actor and no MCP configs to establish a session:
        # there is nothing to leak, so let the turn run rather than block the
        # agent just because MCP is unavailable. Record the binding so a later
        # actor transition is still detected.
        mark_sandbox_mcp_session(scope, actor_user.id)
        logger.info("refresh_mcp_skipped_no_configs", run_id=run_id)
        return None

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
        return None

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
        return None

    logger.warning(
        "refresh_mcp_failed",
        run_id=run_id,
        error=retry.error,
        status_code=retry.status_code,
        user_id=actor_user.id,
        previous_user_id=bound_user_id,
        server_count=len(mcp_servers),
    )
    return (
        SandboxRebindFailure.REFRESH_SESSION_FAILED
    )  # rebind never confirmed → fail closed (unknown binding may hide a live session)


@frozen
class LiveSandboxLookup:
    """The running Sandbox handle for a run, or why there isn't one.

    ``stopped`` separates "the control plane says this sandbox is gone" from "we could
    not find out" (no id recorded yet, or the lookup itself failed). Both block the turn,
    but only the first is terminal, and the two need different replies.
    """

    sandbox: Any = None
    stopped: bool = False


def _resolve_live_sandbox(state: dict[str, Any] | None) -> LiveSandboxLookup:
    """Look up the run's sandbox handle.

    GitHub credentials are written into the sandbox directly (git remote + env
    file), so the gate needs the handle. When there is none, the periodic
    credential-refresh loop reconciles identity instead.
    """
    sandbox_id = (state or {}).get("sandbox_id")
    if not sandbox_id:
        return LiveSandboxLookup()
    from products.tasks.backend.logic.services.sandbox import (
        get_sandbox_class_for_sandbox_id,  # noqa: PLC0415 — keep the sandbox service off the import path
    )

    try:
        sandbox = get_sandbox_class_for_sandbox_id(sandbox_id).get_by_id(sandbox_id)
        if sandbox.is_running():
            return LiveSandboxLookup(sandbox=sandbox)
    except Exception:
        logger.warning("resolve_live_sandbox_failed", sandbox_id=sandbox_id, exc_info=True)
        return LiveSandboxLookup()
    return LiveSandboxLookup(stopped=True)


def _refresh_sandbox_github(
    task_run: TaskRun, actor_user: Any, state: dict[str, Any] | None
) -> SandboxRebindFailure | None:
    """Bind the sandbox's in-place GitHub credentials to this message's actor.

    Runs on every turn, for every actor: re-inject the acting user's token if they
    have usable access, otherwise log the sandbox out (strip the token from the git
    remote and env). Someone can connect or disconnect their GitHub between any two
    messages, so the sandbox is never assumed to still reflect the last turn — and a
    follow-up actor can never inherit the previous actor's identity.

    Only USER-authored runs carry per-actor identity — BOT runs share one
    installation token, so every actor is already the same identity. This
    enforces the transition boundary; the periodic credential-refresh loop
    keeps a continuous actor's token rotated between transitions.

    Returns ``None`` when the sandbox safely reflects this actor (rebound, logged
    out, or nothing to do) and a short reason code when we could neither rebind nor
    even clear — the caller surfaces the code so a failed run says which gate
    rejected it. That is fail-closed for everyone, including an actor who revoked
    their own connection: deleting a `UserIntegration` does not revoke the token
    GitHub already issued, so an unconfirmed clear can leave it usable in the sandbox.
    """
    if actor_user is None:
        return None

    run_id = str(task_run.id)
    task = task_run.task
    # A run that started before its actor connected GitHub is bot-authored, and the agent may
    # have been the one that asked them to connect. Promote it so the turn that follows the
    # connection is the one that gets their identity.
    promoted_state = upgrade_run_to_user_authorship(task_run, actor_user, state)
    if promoted_state is not None:
        state = promoted_state

    scope = sandbox_identity_scope(run_id, state)
    if get_pr_authorship_mode(task, state) != PrAuthorshipMode.USER:
        return None

    # Re-established every turn rather than skipped when the actor is unchanged: they can connect
    # or disconnect their GitHub between any two messages, and the sandbox can lose its token to a
    # resume or snapshot restore. Apply the token whenever one resolves, clear it when none does.
    lookup = _resolve_live_sandbox(state)
    if lookup.sandbox is None:
        reason = SandboxRebindFailure.SANDBOX_NOT_RUNNING if lookup.stopped else SandboxRebindFailure.NO_SANDBOX_HANDLE
        logger.warning(
            "refresh_github_no_sandbox_handle_fail_closed",
            run_id=run_id,
            user_id=actor_user.id,
            sandbox_id=(state or {}).get("sandbox_id"),
            reason=reason,
        )
        return reason

    sandbox = lookup.sandbox

    repository = task.repository
    token: str | None = None
    try:
        token = get_sandbox_github_token(
            task.github_integration_id,
            run_id=run_id,
            state=state,
            task=task,
            actor_user=actor_user,
            repository=repository,
        )
    except (
        ReauthorizationRequired,
        CredentialUnavailableError,
        Integration.DoesNotExist,
        UserIntegration.DoesNotExist,
    ) as e:
        # The new actor has no usable GitHub credential for this repo: needs reauthorization,
        # no repo access, or the integration was disconnected mid-run. Log the sandbox out
        # rather than run under the prior actor's creds, matching the scheduled refresh's
        # handling. A transient error (network, timeout) is deliberately not caught here so it
        # propagates and the activity retries.
        logger.info(
            "refresh_github_actor_credential_unavailable",
            run_id=run_id,
            user_id=actor_user.id,
            repository=repository,
            error_type=type(e).__name__,
            reason=str(e),
        )
        token = None

    # Hold the per-sandbox lock across the write and the marker update so a concurrent owner-scoped
    # refresh or propagation cannot interleave and land the owner's token after this actor's — the
    # owner writers acquire the same lock and re-check the marker this block advances.
    with sandbox_credential_lock(sandbox.id) as acquired:
        if not acquired:
            logger.warning(
                "refresh_github_lock_unavailable_fail_closed",
                run_id=run_id,
                user_id=actor_user.id,
                sandbox_id=sandbox.id,
            )
            return SandboxRebindFailure.CREDENTIAL_LOCK_UNAVAILABLE

        if token:
            applied = False
            try:
                applied = apply_github_credentials_to_sandbox(sandbox, repository, token)
            except Exception:
                logger.warning(
                    "refresh_github_apply_failed",
                    run_id=run_id,
                    user_id=actor_user.id,
                    repository=repository,
                    exc_info=True,
                )
            if applied:
                # Record the new actor only on a fully-confirmed rebind. A partial write leaves one
                # credential location on the prior actor's token, so fall through to logout instead.
                mark_sandbox_github_identity(scope, actor_user.id)
                logger.info("refresh_github_rebound", run_id=run_id, user_id=actor_user.id)
                return None
            logger.warning("refresh_github_apply_incomplete", run_id=run_id, user_id=actor_user.id)

        # No usable rebind (no token, or the rebind write could not be confirmed): log the sandbox
        # out. Fail closed only if even the clear can't be confirmed — the previous actor's
        # credentials might still be live. The sandbox exec can raise (it stopped between the
        # is_running() check and here, or timed out), so guard it like the rebind above and fail
        # closed on the exception rather than letting it escape uncontrolled.
        try:
            cleared = clear_github_credentials_from_sandbox(sandbox, repository)
        except Exception:
            logger.warning("refresh_github_logout_errored", run_id=run_id, user_id=actor_user.id, exc_info=True)
            return SandboxRebindFailure.LOGOUT_ERRORED
        if cleared:
            # Still record the actor: the marker tells owner-scoped refreshes that this sandbox is
            # bound away from the run owner, and clearing it would let the scheduled refresh inject
            # the owner's token into this actor's session. It does not gate the rebind — every turn
            # re-establishes — so a reconnect is still picked up.
            mark_sandbox_github_identity(scope, actor_user.id)
            logger.info("refresh_github_logged_out", run_id=run_id, user_id=actor_user.id)
            return None
        logger.warning("refresh_github_logout_failed", run_id=run_id, user_id=actor_user.id, had_token=bool(token))
        return SandboxRebindFailure.LOGOUT_UNCONFIRMED


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
