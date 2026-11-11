"""Emit CI log lines into Logs over OTLP, one record per line.

The records go to the internal ``capture-logs`` endpoint. The destination team's project token is
the Bearer token, and it routes the records to that team's Logs.
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

# A GitHub log line is an RFC3339 UTC timestamp, then the content:
#   2026-06-25T09:14:02.1234567Z ##[error]Process completed with exit code 1
_LINE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}T[0-9:.]+Z)\s?(?P<body>.*)$")


def _parse_ns(ts: str) -> int | None:
    try:
        # fromisoformat accepts at most 6 fractional digits, and GitHub sends 7.
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
    """A run or job id as an OTLP trace or span id of ``n_bytes``, or 0 (OTLP "unset") when the id
    is missing, non-numeric, or out of range.

    The result is always an int, because None or a str crashes serialization of the whole batch.
    """
    if value is None:
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if 0 < parsed < (1 << (n_bytes * 8)) else 0


class JobLogsEmitter:
    """Use as a context manager, because the batch processor drops buffered records that are not
    flushed before a Temporal activity returns.

    Pass ``endpoint`` and ``token`` in production and ``exporter`` in tests. With neither, the
    emitter emits nothing.
    """

    def __init__(
        self, *, endpoint: str | None = None, token: str | None = None, exporter: LogExporter | None = None
    ) -> None:
        # Every hand-built LogRecord must also carry this resource. Logger.emit attaches only the
        # instrumentation scope, so a record without resource= takes the pod's OTEL_SERVICE_NAME,
        # and the failure-logs read filter on service.name never matches it.
        self._resource = Resource.create({"service.name": _SERVICE_NAME})
        self._provider = LoggerProvider(resource=self._resource)
        if exporter is None and endpoint and token:
            # capture-logs is in-cluster, and the worker's egress proxy denies private-range hosts.
            # internal_requests_session bypasses the proxy. Without it every export fails silently.
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
        """Emit one record per non-empty line and return the number emitted.

        Each record carries ``seq``, its 0-based position in the emitted output, and a kept line
        also carries ``orig_line``, its 1-based line in the full log. ``seq`` is the read-side sort
        key, because omission markers have no timestamp.
        """
        if not self._enabled:
            return 0
        # The logs pipeline indexes only string attributes into the queryable map, and the
        # failure-logs read filters on these attributes.
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
        # The result is ignored because BatchLogRecordProcessor.force_flush can return False on success.
        self._provider.force_flush(timeout_millis=timeout_millis)

    def __enter__(self) -> "JobLogsEmitter":
        return self

    def __exit__(
        self, _exc_type: type[BaseException] | None, _exc: BaseException | None, _tb: TracebackType | None
    ) -> None:
        self.flush()
        self._provider.shutdown()
