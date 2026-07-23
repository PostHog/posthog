"""Mirror persisted task-run log entries into the PostHog Logs product via stdout.

Task-run logs are appended to object storage as one ACP notification envelope per line.
In every PostHog cluster an OTel collector daemonset already tails container stdout and
ships JSON log lines into the region's internal PostHog project's Logs product, parsing
each JSON key into a queryable log attribute, `level` into severity, and `request_id`
into a trace id (see `argocd/otel-collector` in the charts repo). So in production
dogfooding scout-run logs needs no transport of its own: emitting one structured stdout
line per persisted entry is enough.

A direct OTLP leg (`TASK_RUN_LOGS_MIRROR_OTLP_URL` + `_TOKEN`) additionally ships each
batch straight to a logs ingest endpoint. The token pins the destination to PostHog's own
internal logs project: scout runs execute for customer teams, and their mirrored
transcripts must never land in — or bill — a customer's project. It is also the only
delivery path in local dev, where `append_log` runs in the host Django process whose
stdout the dev collector (docker containers only) never tails.

Each mirrored line carries the run's uuid as `request_id` (and as the OTLP trace id on
the direct leg), so a whole run groups as one trace in the Logs UI and can be pulled up
with a `task_run_id` attribute filter.
"""

import json
import time
from datetime import datetime
from typing import Any

from django.conf import settings

import structlog

from posthog.security.outbound_proxy import internal_requests

logger = structlog.get_logger(__name__)

# The collector truncates whole log lines at 100 KB (`max_log_size`); cap the body well
# below that so run identity attributes and JSON overhead never push a line over.
MAX_BODY_CHARS = 8_000

# Defensive budget per append: origin_product is user-settable on task creation, so a
# hostile append_log request must not be able to flood stdout/the collector with an
# arbitrarily long entry list. Real scout appends are small batches, far below this.
MAX_ENTRIES_PER_CALL = 200

_LOG_METHOD_NAMES = {"info": "info", "warn": "warning", "error": "error"}

_OTLP_SEVERITIES = {"info": ("INFO", 9), "warn": ("WARN", 13), "error": ("ERROR", 17)}

_OTLP_SERVICE_NAME = "task-run-log-mirror"

_OTLP_TIMEOUT_SECONDS = 3


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
    records: list[tuple[str, dict[str, Any]]] = []
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
        records.append((severity, fields))

    _post_otlp(records, run_id=run_id)


def _post_otlp(records: list[tuple[str, dict[str, Any]]], *, run_id: str) -> None:
    """Ship the batch straight to the configured logs OTLP endpoint.

    The token routes the records, so the destination is always the internal logs
    project the settings point at — never the run's (customer) team. Best-effort:
    a delivery failure is logged and never raises into the run.
    """
    url = settings.TASK_RUN_LOGS_MIRROR_OTLP_URL
    token = settings.TASK_RUN_LOGS_MIRROR_OTLP_TOKEN
    if not url or not token or not records:
        return

    # The run uuid without dashes is a valid 16-byte hex trace id, matching the
    # request_id -> trace id mapping the production collector applies.
    trace_id = run_id.replace("-", "")
    log_records = []
    for severity, fields in records:
        severity_text, severity_number = _OTLP_SEVERITIES[severity]
        log_records.append(
            {
                "timeUnixNano": str(_time_unix_nano(fields.get("entry_timestamp"))),
                "severityText": severity_text,
                "severityNumber": severity_number,
                "body": {"stringValue": fields["body"]},
                **({"traceId": trace_id} if len(trace_id) == 32 else {}),
                "attributes": [
                    {"key": key, "value": _otlp_attribute_value(value)}
                    for key, value in fields.items()
                    if key != "body"
                ],
            }
        )
    payload = {
        "resourceLogs": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": _OTLP_SERVICE_NAME}}]},
                "scopeLogs": [{"scope": {"name": __name__}, "logRecords": log_records}],
            }
        ]
    }
    try:
        response = internal_requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=_OTLP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except Exception as e:
        logger.warning("task_run_log_mirror_otlp_failed", task_run_id=run_id, error=str(e))


def _otlp_attribute_value(value: Any) -> dict[str, Any]:
    # OTLP JSON encodes 64-bit ints as strings.
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    return {"stringValue": str(value)}


def _time_unix_nano(entry_timestamp: Any) -> int:
    if isinstance(entry_timestamp, str):
        try:
            return int(datetime.fromisoformat(entry_timestamp.replace("Z", "+00:00")).timestamp() * 1_000_000_000)
        except (ValueError, OverflowError):
            pass
    return time.time_ns()


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
