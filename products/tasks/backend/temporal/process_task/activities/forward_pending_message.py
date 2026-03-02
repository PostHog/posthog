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

    try:
        task_run = TaskRun.objects.select_related("task__created_by").get(id=run_id)
    except TaskRun.DoesNotExist:
        logger.warning("forward_pending_message_run_not_found", run_id=run_id)
        return

    state = task_run.state or {}
    pending_message = state.get("pending_user_message")
    if not pending_message:
        return

    auth_token = None
    created_by = task_run.task.created_by
    if created_by and created_by.id:
        distinct_id = created_by.distinct_id or f"user_{created_by.id}"
        auth_token = create_sandbox_connection_token(task_run, user_id=created_by.id, distinct_id=distinct_id)

    result = send_user_message(task_run, pending_message, auth_token=auth_token)
    if not result.success and result.retryable:
        result = send_user_message(task_run, pending_message, auth_token=auth_token, timeout=45)

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
            _post_pending_reply_to_slack(task_run, pending_message_ts, result.data)
        else:
            _post_pending_delivery_failure_to_slack(task_run, pending_message_ts, result.error)

    state.pop("pending_user_message", None)
    state.pop("pending_user_message_ts", None)
    task_run.state = state
    task_run.save(update_fields=["state", "updated_at"])

    if result.success:
        logger.info("forward_pending_message_delivered", run_id=run_id)
    else:
        logger.warning(
            "forward_pending_message_non_retryable_failure",
            run_id=run_id,
            error=result.error,
        )


def _post_pending_delivery_failure_to_slack(task_run: Any, user_message_ts: str | None, error: str | None) -> None:
    context = _get_slack_context_for_task_run(task_run, user_message_ts)
    if context is None:
        return

    from products.slack_app.backend.slack_thread import SlackThreadHandler

    handler = SlackThreadHandler(context)
    handler.update_reaction("x")
    error_suffix = f" ({error})" if error else ""
    handler.post_thread_message(f"I couldn't deliver your follow-up to the agent{error_suffix}. Please try again.")


def _post_pending_reply_to_slack(task_run: Any, user_message_ts: str | None, command_result_data: Any) -> None:
    context = _get_slack_context_for_task_run(task_run, user_message_ts)
    if context is None:
        return

    from products.slack_app.backend.slack_thread import SlackThreadHandler

    handler = SlackThreadHandler(context)
    reply_text = _extract_assistant_text_from_command_result(
        command_result_data
    ) or _extract_recent_assistant_text_from_logs(task_run)

    if not reply_text and _has_recent_question_tool_failure(task_run):
        reply_text = "I need clarification before continuing. Please reply in this thread with your preferred option."

    if not reply_text:
        return

    mention_prefix = f"<@{context.mentioning_slack_user_id}> " if context.mentioning_slack_user_id else ""
    handler.post_thread_message(f"{mention_prefix}{reply_text}")
    handler.update_reaction("white_check_mark")
    handler.delete_progress()


def _get_slack_context_for_task_run(task_run: Any, user_message_ts: str | None):
    from products.slack_app.backend.models import SlackThreadTaskMapping
    from products.slack_app.backend.slack_thread import SlackThreadContext

    mapping = SlackThreadTaskMapping.objects.filter(task_run=task_run).first()
    if not mapping:
        return None

    return SlackThreadContext(
        integration_id=mapping.integration_id,
        channel=mapping.channel,
        thread_ts=mapping.thread_ts,
        user_message_ts=user_message_ts,
        mentioning_slack_user_id=mapping.mentioning_slack_user_id,
    )


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

    raw_log_content = object_storage.read(task_run.log_url, missing_ok=True) or ""
    if isinstance(raw_log_content, bytes):
        log_content = raw_log_content.decode("utf-8", errors="ignore")
    else:
        log_content = str(raw_log_content)

    if not log_content.strip():
        return None

    latest_text: str | None = None
    latest_agent_timestamp: datetime | None = None
    latest_user_timestamp: datetime | None = None
    cutoff = datetime.utcnow() - timedelta(minutes=5)

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

        if session_update not in {"agent_message", "agent_message_chunk"}:
            continue

        content = update.get("content")
        text: str | None = None
        if isinstance(content, dict) and content.get("type") == "text" and isinstance(content.get("text"), str):
            candidate = content["text"].strip()
            text = candidate or None
        elif isinstance(update.get("message"), str):
            candidate = update["message"].strip()
            text = candidate or None

        if not text:
            continue

        if latest_agent_timestamp is None or (timestamp and timestamp >= latest_agent_timestamp):
            latest_agent_timestamp = timestamp
            latest_text = text

    if not latest_text:
        return None

    if latest_agent_timestamp and latest_user_timestamp and latest_agent_timestamp < latest_user_timestamp:
        return None

    return latest_text


def _has_recent_question_tool_failure(task_run: Any) -> bool:
    from posthog.storage import object_storage

    raw_log_content = object_storage.read(task_run.log_url, missing_ok=True) or ""
    if isinstance(raw_log_content, bytes):
        log_content = raw_log_content.decode("utf-8", errors="ignore")
    else:
        log_content = str(raw_log_content)

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
