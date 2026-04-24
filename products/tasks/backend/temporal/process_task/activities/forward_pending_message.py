import json
from datetime import datetime, timedelta
from typing import Any

from temporalio import activity

from posthog.temporal.common.logger import get_logger

logger = get_logger(__name__)


@activity.defn
def forward_pending_user_message(run_id: str) -> None:
    """Forward a pending user message stored in task run state to the sandbox agent.

    Called after the agent server is ready. Clears the message from state on
    successful delivery or non-retryable failure. Keeps it in state on retryable
    failure to preserve recoverability.
    """
    from products.tasks.backend.models import TaskRun
    from products.tasks.backend.services.agent_command import send_user_message
    from products.tasks.backend.services.connection_token import create_sandbox_connection_token
    from products.tasks.backend.services.staged_artifacts import get_task_run_artifacts_by_id

    try:
        task_run = TaskRun.objects.select_related("task__created_by").get(id=run_id)
    except TaskRun.DoesNotExist:
        logger.warning("forward_pending_message_run_not_found", run_id=run_id)
        return

    state = task_run.state or {}
    pending_message = state.get("pending_user_message")
    pending_user_artifact_ids = state.get("pending_user_artifact_ids") or []
    if not pending_message and not pending_user_artifact_ids:
        return

    pending_artifacts: list[dict[str, Any]] = []
    if pending_user_artifact_ids:
        pending_artifacts, missing_artifact_ids = get_task_run_artifacts_by_id(task_run, pending_user_artifact_ids)
        if missing_artifact_ids:
            logger.warning(
                "forward_pending_message_missing_artifacts",
                run_id=run_id,
                missing_artifact_ids=missing_artifact_ids,
            )
            missing_ids = ", ".join(missing_artifact_ids)
            raise RuntimeError(f"Pending task artifacts not found on this run: {missing_ids}")

    auth_token = None
    created_by = task_run.task.created_by
    if created_by and created_by.id:
        distinct_id = created_by.distinct_id or f"user_{created_by.id}"
        auth_token = create_sandbox_connection_token(task_run, user_id=created_by.id, distinct_id=distinct_id)

    result = send_user_message(
        task_run,
        pending_message,
        artifacts=pending_artifacts or None,
        auth_token=auth_token,
        timeout=90,
    )
    logger.info(
        "forward_pending_message_attempted",
        run_id=run_id,
        has_message=bool(pending_message),
        artifact_count=len(pending_artifacts),
    )
    if not result.success and result.retryable and result.status_code != 504:
        result = send_user_message(
            task_run,
            pending_message,
            artifacts=pending_artifacts or None,
            auth_token=auth_token,
            timeout=90,
        )

    if not result.success and result.retryable:
        logger.warning(
            "forward_pending_message_retryable_failure",
            run_id=run_id,
            error=result.error,
        )
        return

    pending_message_ts = state.get("pending_user_message_ts")

    if state.get("interaction_origin") == "slack":
        if result.success:
            _enqueue_pending_reply_relay(task_run, pending_message_ts, result.data)
        else:
            _enqueue_pending_delivery_failure_relay(task_run, pending_message_ts, result.error)

    TaskRun.update_state_atomic(
        run_id,
        remove_keys=["pending_user_message", "pending_user_artifact_ids", "pending_user_message_ts"],
    )

    if result.success:
        logger.info("forward_pending_message_delivered", run_id=run_id)
    else:
        logger.warning(
            "forward_pending_message_non_retryable_failure",
            run_id=run_id,
            error=result.error,
        )


def _enqueue_pending_delivery_failure_relay(task_run: Any, user_message_ts: str | None, error: str | None) -> None:
    from products.tasks.backend.temporal.client import execute_posthog_code_agent_relay_workflow

    error_suffix = f" ({error})" if error else ""
    try:
        execute_posthog_code_agent_relay_workflow(
            run_id=str(task_run.id),
            text=f"I couldn't deliver your follow-up to the agent{error_suffix}. Please try again.",
            user_message_ts=user_message_ts,
            reaction_emoji="x",
        )
    except Exception:
        logger.exception("forward_pending_message_relay_failure_enqueue_failed", run_id=str(task_run.id))


def _enqueue_pending_reply_relay(task_run: Any, user_message_ts: str | None, command_result_data: Any) -> None:
    from products.tasks.backend.temporal.client import execute_posthog_code_agent_relay_workflow

    reply_text = _extract_assistant_text_from_command_result(
        command_result_data
    ) or _extract_recent_assistant_text_from_logs(task_run)

    if not reply_text and _has_recent_question_tool_failure(task_run):
        reply_text = "I need clarification before continuing. Please reply in this thread with your preferred option."

    if not reply_text:
        reply_text = "I processed your message but couldn't fetch the reply text. Check the task logs for details."

    try:
        execute_posthog_code_agent_relay_workflow(
            run_id=str(task_run.id),
            text=reply_text,
            user_message_ts=user_message_ts,
        )
    except Exception:
        logger.exception("forward_pending_message_relay_enqueue_failed", run_id=str(task_run.id))


def _extract_assistant_text_from_command_result(command_result_data: Any) -> str | None:
    if not isinstance(command_result_data, dict):
        return None

    result = command_result_data.get("result")
    if isinstance(result, dict):
        direct_text = result.get("assistant_message") or result.get("output_text")
        if isinstance(direct_text, str) and direct_text.strip():
            return direct_text.strip()

        messages = result.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    continue
                text = _extract_text_from_message_payload(message)
                if text:
                    return text

        if result.get("role") == "assistant":
            return _extract_text_from_message_payload(result)

    return None


def _extract_text_from_message_payload(message: dict[str, Any]) -> str | None:
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()

    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                text = part["text"].strip()
                if text:
                    text_parts.append(text)
        if text_parts:
            return "\n".join(text_parts)

    text_value = message.get("text")
    if isinstance(text_value, str) and text_value.strip():
        return text_value.strip()

    return None


def _extract_recent_assistant_text_from_logs(task_run: Any) -> str | None:
    from posthog.storage import object_storage

    log_content = object_storage.read(task_run.log_url, missing_ok=True) or ""

    if not log_content.strip():
        return None

    _AGENT_MSG_TYPES = {"agent_message", "agent_message_chunk"}
    cutoff = datetime.utcnow() - timedelta(minutes=5)
    latest_user_timestamp: datetime | None = None
    latest_agent_timestamp: datetime | None = None

    parsed_updates: list[tuple[dict, datetime | None]] = []

    for line in log_content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        notification = entry.get("notification")
        if not isinstance(notification, dict) or notification.get("method") != "session/update":
            continue

        params = notification.get("params")
        update = params.get("update") if isinstance(params, dict) else None
        if not isinstance(update, dict):
            continue

        timestamp = _parse_iso_datetime(entry.get("timestamp"))
        if timestamp and timestamp < cutoff:
            continue

        session_update = update.get("sessionUpdate")
        if session_update in {"user_message", "user_message_chunk"}:
            if timestamp and (latest_user_timestamp is None or timestamp >= latest_user_timestamp):
                latest_user_timestamp = timestamp
            continue

        parsed_updates.append((update, timestamp))

        if session_update in _AGENT_MSG_TYPES and timestamp:
            if latest_agent_timestamp is None or timestamp >= latest_agent_timestamp:
                latest_agent_timestamp = timestamp

    # Walk backwards: find last agent_message, then collect all consecutive agent messages
    # TODO: improve this, fine for now but not efficient
    trailing_parts: list[str] = []
    found_agent_msg = False
    for update, _ in reversed(parsed_updates):
        is_agent_msg = update.get("sessionUpdate") in _AGENT_MSG_TYPES
        if not found_agent_msg:
            if is_agent_msg:
                found_agent_msg = True
            else:
                continue
        if found_agent_msg and not is_agent_msg:
            break
        text = _extract_text_from_update(update)
        if text:
            trailing_parts.append(text)

    trailing_parts.reverse()
    latest_text = "".join(trailing_parts) if trailing_parts else None

    if not latest_text:
        return None

    if latest_agent_timestamp and latest_user_timestamp and latest_agent_timestamp < latest_user_timestamp:
        return None

    return latest_text


def _extract_text_from_update(update: dict[str, Any]) -> str | None:
    content = update.get("content")
    if isinstance(content, dict) and content.get("type") == "text" and isinstance(content.get("text"), str):
        candidate = content["text"].strip()
        if candidate:
            return candidate
    message = update.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return None


def _has_recent_question_tool_failure(task_run: Any) -> bool:
    from posthog.storage import object_storage

    log_content = object_storage.read(task_run.log_url, missing_ok=True) or ""

    if not log_content.strip():
        return False

    cutoff = datetime.utcnow() - timedelta(minutes=5)

    for line in log_content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        timestamp = _parse_iso_datetime(entry.get("timestamp"))
        if timestamp and timestamp < cutoff:
            continue

        notification = entry.get("notification")
        if not isinstance(notification, dict) or notification.get("method") != "session/update":
            continue

        params = notification.get("params")
        update = params.get("update") if isinstance(params, dict) else None
        if not isinstance(update, dict):
            continue

        if update.get("sessionUpdate") not in {"tool_call", "tool_call_update"}:
            continue

        status = str(update.get("status") or "").lower()
        if status not in {"failed", "error"}:
            continue

        title = update.get("title")
        tool_name = ""
        if isinstance(title, str):
            tool_name = title

        meta = update.get("_meta")
        if isinstance(meta, dict):
            claude_code = meta.get("claudeCode")
            if isinstance(claude_code, dict) and isinstance(claude_code.get("toolName"), str):
                tool_name = claude_code["toolName"]

        normalized = tool_name.replace(" ", "").lower()
        if "askuserquestion" in normalized or "question" in normalized:
            return True

    return False


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None

    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is not None:
        return parsed.replace(tzinfo=None)
    return parsed
