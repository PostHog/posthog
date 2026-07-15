"""Convert persisted task-run log entries (ACP JSONL) into an OTLP/HTTP logs payload.

Task-run logs are appended to object storage as one ACP notification envelope per line.
To dogfood the PostHog Logs product, entries can also be mirrored to a PostHog project's
OTLP logs endpoint (`/i/v1/logs`). This module is the pure translation layer: it maps each
entry to an OTLP log record with a run-scoped trace id so one run reads as one trace in the
Logs UI. Dispatch/transport live in `products.tasks.backend.tasks`.
"""

import json
import uuid
from datetime import datetime
from typing import Any

from django.conf import settings
from django.utils import timezone

# Bodies larger than this are truncated — huge tool-call payloads would otherwise blow the
# ingestion endpoint's 2 MB request cap and are useless for eyeballing runs anyway.
MAX_BODY_CHARS = 32_000

_SEVERITY_NUMBERS = {"debug": 5, "info": 9, "warn": 13, "error": 17}


def otlp_forwarding_configured() -> bool:
    return bool(settings.TASK_RUN_LOGS_OTLP_ENDPOINT and settings.TASK_RUN_LOGS_OTLP_TOKEN)


def otlp_forwarding_enabled(origin_product: str) -> bool:
    return otlp_forwarding_configured() and origin_product in settings.TASK_RUN_LOGS_OTLP_ORIGIN_PRODUCTS


def build_otlp_payload(
    entries: list[dict],
    *,
    team_id: int,
    task_id: str,
    run_id: str,
    origin_product: str,
) -> dict[str, Any] | None:
    """Build an OTLP `ExportLogsServiceRequest` JSON body from persisted log entries."""
    records = [_log_record(entry, run_id=run_id) for entry in entries if isinstance(entry, dict)]
    if not records:
        return None

    resource_attributes = [
        _attribute("service.name", origin_product),
        _attribute("team_id", str(team_id)),
        _attribute("task_id", task_id),
        _attribute("task_run_id", run_id),
    ]
    return {
        "resourceLogs": [
            {
                "resource": {"attributes": resource_attributes},
                "scopeLogs": [{"scope": {"name": "posthog.task_run"}, "logRecords": records}],
            }
        ]
    }


def _log_record(entry: dict, *, run_id: str) -> dict[str, Any]:
    raw_notification = entry.get("notification")
    notification: dict = raw_notification if isinstance(raw_notification, dict) else {}
    method = notification.get("method")
    update = _session_update(notification)
    session_update = update.get("sessionUpdate") if isinstance(update.get("sessionUpdate"), str) else None

    severity = _severity(notification, session_update)
    # Record-level copies of the run identity make the Logs UI attribute filters usable
    # without touching resource attributes.
    attributes = [_attribute("task_run_id", run_id)]
    if isinstance(method, str):
        attributes.append(_attribute("acp.method", method))
    if session_update:
        attributes.append(_attribute("acp.session_update", session_update))

    return {
        "timeUnixNano": str(_time_unix_nano(entry)),
        "severityText": severity,
        "severityNumber": _SEVERITY_NUMBERS[severity],
        "body": {"stringValue": _body(notification, session_update)},
        "attributes": attributes,
        # All records of a run share the run's uuid as trace id, so a run groups as one trace.
        "traceId": uuid.UUID(run_id).hex,
    }


def _session_update(notification: dict) -> dict:
    params = notification.get("params")
    if not isinstance(params, dict):
        return {}
    update = params.get("update")
    return update if isinstance(update, dict) else {}


def _severity(notification: dict, session_update: str | None) -> str:
    if notification.get("method") == "_posthog/error":
        return "error"
    if notification.get("method") == "_posthog/console":
        params = notification.get("params")
        level = params.get("level") if isinstance(params, dict) else None
        if level in _SEVERITY_NUMBERS:
            return level
    if session_update == "agent_thought_chunk":
        return "debug"
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


def _time_unix_nano(entry: dict) -> int:
    timestamp = entry.get("timestamp")
    parsed: datetime | None = None
    if isinstance(timestamp, str):
        try:
            parsed = datetime.fromisoformat(timestamp)
        except ValueError:
            parsed = None
    if parsed is None:
        parsed = timezone.now()
    return int(parsed.timestamp() * 1_000_000_000)


def _attribute(key: str, value: str) -> dict[str, Any]:
    return {"key": key, "value": {"stringValue": value}}
