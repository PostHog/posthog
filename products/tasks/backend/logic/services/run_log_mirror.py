"""Mirror persisted task-run log entries into the PostHog Logs product via stdout.

Task-run logs are appended to object storage as one ACP notification envelope per line.
In every PostHog cluster an OTel collector daemonset already tails container stdout and
ships JSON log lines into the region's internal PostHog project's Logs product, parsing
each JSON key into a queryable log attribute, `level` into severity, and `request_id`
into a trace id (see `argocd/otel-collector` in the charts repo; `otel-collector-config.dev.yaml`
does the same for local dev). So dogfooding scout-run logs needs no transport of its own:
emitting one structured stdout line per persisted entry is enough.

Each mirrored line carries the run's uuid as `request_id`, so a whole run groups as one
trace in the Logs UI and can be pulled up with a `task_run_id` attribute filter.
"""

import json
from typing import Any

from django.conf import settings

import structlog

logger = structlog.get_logger(__name__)

# The collector truncates whole log lines at 100 KB (`max_log_size`); cap the body well
# below that so run identity attributes and JSON overhead never push a line over.
MAX_BODY_CHARS = 8_000

# Defensive budget per append: origin_product is user-settable on task creation, so a
# hostile append_log request must not be able to flood stdout/the collector with an
# arbitrarily long entry list. Real scout appends are small batches, far below this.
MAX_ENTRIES_PER_CALL = 200

_LOG_METHOD_NAMES = {"info": "info", "warn": "warning", "error": "error"}


def mirroring_enabled(origin_product: str) -> bool:
    return origin_product in settings.TASK_RUN_LOGS_MIRROR_ORIGIN_PRODUCTS


def mirror_entries(
    entries: list[dict],
    *,
    team_id: int,
    task_id: str,
    run_id: str,
    origin_product: str,
) -> None:
    """Emit one structured stdout log line per persisted entry."""
    if len(entries) > MAX_ENTRIES_PER_CALL:
        logger.warning(
            "task_run_log_mirror_truncated",
            task_run_id=run_id,
            dropped=len(entries) - MAX_ENTRIES_PER_CALL,
        )
        entries = entries[:MAX_ENTRIES_PER_CALL]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_notification = entry.get("notification")
        notification: dict = raw_notification if isinstance(raw_notification, dict) else {}
        update = _session_update(notification)
        session_update = update.get("sessionUpdate") if isinstance(update.get("sessionUpdate"), str) else None
        severity = _severity(notification)

        fields: dict[str, Any] = {
            # `request_id` becomes the record's trace id in the collector, grouping the run.
            "request_id": run_id,
            "task_run_id": run_id,
            "task_id": task_id,
            "team_id": team_id,
            "origin_product": origin_product,
            "body": _body(notification, session_update),
        }
        method = notification.get("method")
        if isinstance(method, str):
            fields["acp_method"] = method
        if session_update:
            fields["acp_session_update"] = session_update
        entry_timestamp = entry.get("timestamp")
        if isinstance(entry_timestamp, str):
            fields["entry_timestamp"] = entry_timestamp

        getattr(logger, _LOG_METHOD_NAMES[severity])("task_run_log", **fields)


def _session_update(notification: dict) -> dict:
    params = notification.get("params")
    if not isinstance(params, dict):
        return {}
    update = params.get("update")
    return update if isinstance(update, dict) else {}


def _severity(notification: dict) -> str:
    if notification.get("method") == "_posthog/error":
        return "error"
    if notification.get("method") == "_posthog/console":
        params = notification.get("params")
        level = params.get("level") if isinstance(params, dict) else None
        if level in ("warn", "error"):
            return level
    # No "debug" mapping for thought chunks or debug console lines: the root stdlib log
    # level is INFO in production, so a debug line would be filtered before it ever
    # reaches stdout and the collector.
    return "info"


def _body(notification: dict, session_update: str | None) -> str:
    raw_params = notification.get("params")
    params: dict = raw_params if isinstance(raw_params, dict) else {}
    update = _session_update(notification)

    body: str | None = None
    if session_update:
        text = _extract_text(update.get("content"))
        if text is not None:
            body = f"[{session_update}] {text}"
        elif session_update in ("tool_call", "tool_call_update"):
            title = update.get("title") or update.get("toolCallId") or ""
            status = update.get("status")
            body = f"[{session_update}] {title}" + (f" ({status})" if status else "")
    elif notification.get("method") in ("_posthog/console", "_posthog/error"):
        message = params.get("message")
        if isinstance(message, str):
            body = message
    elif notification.get("method") == "_posthog/sandbox_output":
        stdout = params.get("stdout") or ""
        stderr = params.get("stderr") or ""
        body = f"[sandbox_output exit={params.get('exitCode')}] {stdout}" + (f"\nstderr: {stderr}" if stderr else "")
    elif isinstance(notification.get("result"), dict):
        stop_reason = notification["result"].get("stopReason")
        if isinstance(stop_reason, str):
            body = f"[turn_end] {stop_reason}"

    if body is None:
        body = json.dumps(notification)
    return body[:MAX_BODY_CHARS]


def _extract_text(content: Any) -> str | None:
    """Pull plain text out of an ACP content block (single block or list of blocks)."""
    if isinstance(content, dict):
        text = content.get("text")
        return text if isinstance(text, str) else None
    if isinstance(content, list):
        parts = [t for t in (_extract_text(block) for block in content) if t]
        return "\n".join(parts) if parts else None
    return None
