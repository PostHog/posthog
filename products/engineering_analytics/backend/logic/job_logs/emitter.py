"""Ship fetched CI log content into Logs via OTLP — one record per line so each line is
independently searchable, countable, and groupable. Emits through the OpenTelemetry SDK to the
internal ``capture-logs`` endpoint (``/i/v1/logs``) with the destination team's project token as the
``Authorization: Bearer`` — the token is what routes records to that team's Logs, so there's no
public-internet round-trip. Each record carries the job attributes, the line's GitHub timestamp, and
a severity from GitHub's ``##[error]`` / ``##[warning]`` markers.

A Temporal activity is short-lived, so callers MUST ``flush()`` before returning (use the context
manager) — the batch processor would otherwise drop buffered records.
"""

import re
from collections.abc import Mapping
from datetime import datetime
from types import TracebackType

import structlog
from opentelemetry._logs import SeverityNumber
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LogRecord
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, LogExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import TraceFlags

logger = structlog.get_logger(__name__)

_SERVICE_NAME = "github-ci-logs"

# GitHub prefixes every raw log line with an RFC3339 UTC timestamp, then the content:
#   2026-06-25T09:14:02.1234567Z ##[error]Process completed with exit code 1
_LINE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}T[0-9:.]+Z)\s?(?P<body>.*)$")
_SCALAR = (str, int, float, bool)


def _parse_ns(ts: str) -> int | None:
    """RFC3339 with GitHub's 7-digit fraction + ``Z`` → epoch nanoseconds, or None if unparseable.

    ``fromisoformat`` accepts at most 6 fractional digits, so trim GitHub's extra precision first.
    """
    try:
        normalized = re.sub(r"(\.\d{6})\d+Z$", r"\1Z", ts).replace("Z", "+00:00")
        return int(datetime.fromisoformat(normalized).timestamp() * 1_000_000_000)
    except (ValueError, OverflowError):
        return None


def _severity(body: str) -> tuple[str, SeverityNumber]:
    lowered = body.lower()
    if "##[error]" in lowered:
        return "ERROR", SeverityNumber.ERROR
    if "##[warning]" in lowered:
        return "WARN", SeverityNumber.WARN
    return "INFO", SeverityNumber.INFO


def _otel_id(value: str | int | None, n_bytes: int) -> int:
    """A GitHub run/job id packed as an OTLP trace/span id — an int the encoder serializes into
    ``n_bytes``. GitHub ids arrive as int or numeric string (warehouse columns are nullable strings),
    so coerce; return 0 (OTLP "unset") when missing, non-numeric, or out of range. Never None — the
    SDK default — and never a str: either would crash serialization of the whole batch.
    """
    if value is None:
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if 0 < parsed < (1 << (n_bytes * 8)) else 0


class JobLogsEmitter:
    """One record per line into Logs. Use as a context manager so the batch flushes on exit. Pass
    ``endpoint`` + ``token`` for production, ``exporter`` in tests; with neither it's a safe no-op
    (harmless until the Logs lane is configured).
    """

    def __init__(
        self, *, endpoint: str | None = None, token: str | None = None, exporter: LogExporter | None = None
    ) -> None:
        self._provider = LoggerProvider(resource=Resource.create({"service.name": _SERVICE_NAME}))
        if exporter is None and endpoint and token:
            exporter = OTLPLogExporter(endpoint=endpoint, headers={"authorization": f"Bearer {token}"})
        self._enabled = exporter is not None
        if exporter is not None:
            self._provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
        else:
            logger.warning("github_ci_logs_emit_disabled", detail="no endpoint/token configured; skipping export")
        self._logger = self._provider.get_logger(_SERVICE_NAME)

    def emit_log_archive(
        self,
        archive_text: str,
        *,
        attributes: Mapping[str, object],
        trace_id: str | int | None = 0,
        span_id: str | int | None = 0,
    ) -> int:
        """Emit one Logs record per non-empty line. Returns the number of records emitted.

        ``trace_id``/``span_id`` map the GitHub run/job onto OTLP trace/span so the Logs UI can group
        a whole workflow run (trace) and isolate one job (span); unmappable ids fall back to 0
        (unset). They MUST be set: the encoder treats 0 as unset and calls ``int(trace_flags)``, so
        the SDK's None default would crash serialization of the whole batch and nothing would land.
        """
        if not self._enabled:
            return 0
        attrs = {key: value for key, value in attributes.items() if isinstance(value, _SCALAR)}
        trace, span = _otel_id(trace_id, 16), _otel_id(span_id, 8)
        emitted = 0
        for raw in archive_text.splitlines():
            match = _LINE.match(raw)
            body, timestamp = (match.group("body"), _parse_ns(match.group("ts"))) if match else (raw, None)
            if not body.strip():
                continue
            severity_text, severity_number = _severity(body)
            self._logger.emit(
                LogRecord(
                    timestamp=timestamp,
                    observed_timestamp=timestamp,
                    trace_id=trace,
                    span_id=span,
                    trace_flags=TraceFlags(TraceFlags.DEFAULT),
                    severity_text=severity_text,
                    severity_number=severity_number,
                    body=body,
                    attributes=attrs,
                )
            )
            emitted += 1
        return emitted

    def flush(self, timeout_millis: int = 5000) -> None:
        # Best-effort. BatchLogRecordProcessor.force_flush returns False even on success in our SDK
        # version, so its bool is not a reliable failure signal — don't gate on it (gating would
        # fail every job). OTLP emission is fire-and-forget; downstream Kafka gives at-least-once.
        self._provider.force_flush(timeout_millis=timeout_millis)

    def __enter__(self) -> "JobLogsEmitter":
        return self

    def __exit__(
        self, _exc_type: type[BaseException] | None, _exc: BaseException | None, _tb: TracebackType | None
    ) -> None:
        self.flush()
        self._provider.shutdown()
