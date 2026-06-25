"""Ship fetched GitHub Actions log content into the Logs product via OTLP.

The Logs product's only ingress is the OTLP endpoint (the dedicated ``capture-logs`` service at
``/i/v1/logs``); we emit through the OpenTelemetry SDK to that endpoint, with the destination team's
project token as the ``Authorization: Bearer`` header — the token is what routes records to that
team's Logs. The endpoint is supplied by the caller (``settings.OTLP_LOGS_INGEST_ENDPOINT``, the
in-cluster capture-logs address in prod), so there is no public-internet round-trip and no token in a
worker env var. One Logs record per CI log
**line** so each line is independently searchable, countable, and groupable in Logs — that's what
makes "count failing tests / patterns / flaky across branches" work; a whole-log blob would only
be openable one at a time. Each record carries the job's attributes (``job_id`` / ``run_id`` /
``branch`` / ``conclusion``), the line's own GitHub timestamp so build order is preserved, and a
severity derived from GitHub's ``##[error]`` / ``##[warning]`` markers (so a future warning-scout
is just a severity filter).

A Temporal activity is short-lived, so callers MUST ``flush()`` before returning (use the emitter
as a context manager) — the batch processor would otherwise drop buffered records.
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


class JobLogsEmitter:
    """Emits CI log lines into the Logs product, one record per line.

    Construct once per activity run (ideally via ``with JobLogsEmitter(...) as emitter:`` so the
    batch is flushed on exit). Pass ``endpoint`` + ``token`` for production export (the capture-logs
    URL and the destination team's project token); pass ``exporter`` in tests to capture records.
    With neither, the emitter is a safe no-op — harmless until the Logs lane is configured.
    """

    def __init__(
        self, *, endpoint: str | None = None, token: str | None = None, exporter: LogExporter | None = None
    ) -> None:
        self._provider = LoggerProvider(resource=Resource.create({"service.name": _SERVICE_NAME}))
        self._enabled = exporter is not None or bool(endpoint and token)
        if exporter is None and self._enabled:
            # Target the internal capture-logs endpoint; the project token routes to the team's Logs.
            exporter = OTLPLogExporter(endpoint=endpoint, headers={"authorization": f"Bearer {token}"})
        if self._enabled:
            self._provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
        else:
            logger.warning("github_ci_logs_emit_disabled", detail="no endpoint/token configured; skipping export")
        self._logger = self._provider.get_logger(_SERVICE_NAME)

    def emit_log_archive(self, archive_text: str, *, attributes: Mapping[str, str | int]) -> int:
        """Emit one Logs record per non-empty line. Returns the number of records emitted."""
        if not self._enabled:
            return 0
        attrs = {key: value for key, value in attributes.items() if isinstance(value, _SCALAR)}
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
                    severity_text=severity_text,
                    severity_number=severity_number,
                    body=body,
                    attributes=attrs,
                )
            )
            emitted += 1
        return emitted

    def flush(self, timeout_millis: int = 5000) -> None:
        self._provider.force_flush(timeout_millis=timeout_millis)

    def __enter__(self) -> "JobLogsEmitter":
        return self

    def __exit__(
        self, _exc_type: type[BaseException] | None, _exc: BaseException | None, _tb: TracebackType | None
    ) -> None:
        self.flush()
        self._provider.shutdown()
