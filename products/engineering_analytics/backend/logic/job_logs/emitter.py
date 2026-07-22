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

from posthog.security.outbound_proxy import internal_requests_session

from products.engineering_analytics.backend.logic.job_logs.constants import CI_LOGS_SERVICE_NAME as _SERVICE_NAME
from products.engineering_analytics.backend.logic.job_logs.thinning import ThinnedLine

logger = structlog.get_logger(__name__)

# GitHub prefixes every raw log line with an RFC3339 UTC timestamp, then the content:
#   2026-06-25T09:14:02.1234567Z ##[error]Process completed with exit code 1
_LINE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}T[0-9:.]+Z)\s?(?P<body>.*)$")


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
        # This resource must ALSO be passed to every hand-built LogRecord below: Logger.emit(record)
        # attaches only the instrumentation scope, and a record constructed without resource= defaults
        # to Resource.create({}) — i.e. the pod's OTEL_SERVICE_NAME/OTEL_RESOURCE_ATTRIBUTES env, which
        # on the worker is the k8s workload name. Records then land under that service.name and the
        # failure-logs read filter (service.name = github-ci-logs) never matches them.
        self._resource = Resource.create({"service.name": _SERVICE_NAME})
        self._provider = LoggerProvider(resource=self._resource)
        if exporter is None and endpoint and token:
            # capture-logs is in-cluster (a private ClusterIP). The worker's HTTP_PROXY/HTTPS_PROXY
            # point at the Smokescreen egress proxy, which denies private-range hosts (407) — so the
            # OTLP POST must bypass it. internal_requests_session sets trust_env=False; without it
            # every batch export silently 407s and nothing lands in Logs.
            exporter = OTLPLogExporter(
                endpoint=endpoint,
                headers={"authorization": f"Bearer {token}"},
                session=internal_requests_session(),
            )
        self._enabled = exporter is not None
        if exporter is not None:
            self._provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
        else:
            logger.warning("github_ci_logs_emit_disabled", detail="no endpoint/token configured; skipping export")
        # capture-logs stores the scope as "{name}@{version}"; without a version the stored value
        # ends in a dangling "@".
        self._logger = self._provider.get_logger(_SERVICE_NAME, version="1")

    def emit_log_archive(
        self,
        lines: list[ThinnedLine],
        *,
        attributes: Mapping[str, object],
        trace_id: str | int | None = 0,
        span_id: str | int | None = 0,
    ) -> int:
        """Emit one Logs record per non-empty thinned line. Returns the number of records emitted.

        ``trace_id``/``span_id`` map the GitHub run/job onto OTLP trace/span so the Logs UI can group
        a whole workflow run (trace) and isolate one job (span); unmappable ids fall back to 0
        (unset). They MUST be set: the encoder treats 0 as unset and calls ``int(trace_flags)``, so
        the SDK's None default would crash serialization of the whole batch and nothing would land.

        Each record carries ``seq`` (its 0-based position in the emitted output) and, for a kept line,
        ``orig_line`` (its 1-based line in the full pre-thinning log). ``seq`` is the read-side sort
        key — omission markers carry no timestamp, so timestamp can't order them; ``orig_line`` is the
        durable anchor back to the original (which isn't stored and expires).
        """
        if not self._enabled:
            return 0
        # Stringify every attribute value: the logs pipeline only indexes string-typed attributes into
        # the queryable map (logs34 stores them via JSONExtractString), so a numeric attribute would be
        # invisible to `attributes['...']` reads — and the failure-logs endpoint filters on exactly
        # these (run_id / job_id / seq / orig_line / orig_total).
        base_attrs: dict[str, str] = {
            key: str(value) for key, value in attributes.items() if isinstance(value, (str, int, float, bool))
        }
        trace, span = _otel_id(trace_id, 16), _otel_id(span_id, 8)
        emitted = 0
        for line in lines:
            match = _LINE.match(line.text)
            body, timestamp = (match.group("body"), _parse_ns(match.group("ts"))) if match else (line.text, None)
            if not body.strip():
                continue
            attrs: dict[str, str] = {**base_attrs, "seq": str(emitted)}
            if line.original_line_number is not None:
                attrs["orig_line"] = str(line.original_line_number)
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
                    resource=self._resource,
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
