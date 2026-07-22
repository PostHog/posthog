from datetime import UTC, datetime

from unittest.mock import patch

from opentelemetry.exporter.otlp.proto.common._internal._log_encoder import encode_logs
from opentelemetry.sdk._logs.export import InMemoryLogExporter
from parameterized import parameterized

from products.engineering_analytics.backend.logic.job_logs.emitter import JobLogsEmitter
from products.engineering_analytics.backend.logic.job_logs.thinning import ThinnedLine

_ATTRS = {"job_id": 42, "run_id": 7, "branch": "main", "conclusion": "failure"}


def _lines(archive: str) -> list[ThinnedLine]:
    # An un-thinned archive: every line kept, numbered 1..N (the small-log passthrough shape).
    return [ThinnedLine(text, index + 1) for index, text in enumerate(archive.splitlines())]


def _emit_lines(lines: list[ThinnedLine], attributes=_ATTRS):
    exporter = InMemoryLogExporter()
    with JobLogsEmitter(exporter=exporter) as emitter:
        emitted = emitter.emit_log_archive(lines, attributes=attributes)
    return emitted, [d.log_record for d in exporter.get_finished_logs()]


def _emit(archive: str, attributes=_ATTRS):
    return _emit_lines(_lines(archive), attributes)


def _encode_one(*, trace_id, span_id):
    exporter = InMemoryLogExporter()
    with JobLogsEmitter(exporter=exporter) as emitter:
        emitter.emit_log_archive(
            [ThinnedLine("2026-06-25T09:14:02.000000Z ##[error]boom", 1)],
            attributes=_ATTRS,
            trace_id=trace_id,
            span_id=span_id,
        )
    encoded = encode_logs(exporter.get_finished_logs())  # must not raise
    return encoded.resource_logs[0].scope_logs[0].log_records[0]


def test_run_and_job_ids_encode_as_trace_and_span():
    # Production ships via the real OTLP HTTP exporter, which protobuf-encodes each batch — the step
    # InMemoryLogExporter skips. The encoder treats trace/span == 0 as "unset" and calls
    # int(trace_flags); leaving them None (the SDK default) or passing a str (run_id is a nullable
    # warehouse column, often numeric string) raises in encode_logs and silently drops the whole
    # batch. This asserts a string run/job id coerces and round-trips into the right-width bytes.
    record = _encode_one(trace_id="7", span_id="42")
    assert record.body.string_value == "##[error]boom"
    assert record.trace_id == (7).to_bytes(16, "big")
    assert record.span_id == (42).to_bytes(8, "big")


@parameterized.expand(
    [
        ("missing", None, None),
        ("non_numeric", "abc", "xyz"),
        ("out_of_range", 1 << 128, 1 << 64),  # too wide for trace (16B) / span (8B)
    ]
)
def test_unmappable_ids_fall_back_to_unset(_name, trace_id, span_id):
    # Bad/oversized ids must encode as unset (empty bytes), never crash the batch — int.to_bytes on
    # an over-width id raises OverflowError, and a non-numeric str has no to_bytes at all.
    record = _encode_one(trace_id=trace_id, span_id=span_id)
    assert record.trace_id == b""
    assert record.span_id == b""


def test_emits_per_line_with_parsed_timestamp_severity_and_attributes():
    # The core contract: one record per line, GitHub timestamp parsed (so build order is kept),
    # severity derived from ##[error]/##[warning], job attributes attached. A regression in the
    # line regex, the ns timestamp parse, or the severity map would surface here.
    archive = (
        "2026-06-25T09:14:02.1234567Z Running tests\n"
        "2026-06-25T09:14:03.0000000Z ##[warning]deprecated API\n"
        "2026-06-25T09:14:04.0000000Z ##[error]Process completed with exit code 1\n"
    )
    emitted, records = _emit(archive)
    assert emitted == 3
    assert [r.body for r in records] == [
        "Running tests",
        "##[warning]deprecated API",
        "##[error]Process completed with exit code 1",
    ]
    assert [r.severity_text for r in records] == ["INFO", "WARN", "ERROR"]
    # Attributes are stringified — the logs pipeline only indexes string-typed values into the
    # queryable map, so an int attribute would be unreadable by `attributes['...']`.
    assert all(all(record.attributes[key] == str(value) for key, value in _ATTRS.items()) for record in records)
    expected_ns = int(datetime(2026, 6, 25, 9, 14, 2, 123456, tzinfo=UTC).timestamp() * 1_000_000_000)
    assert records[0].timestamp == expected_ns


def test_stamps_seq_and_orig_line_so_thinned_lines_stay_anchored_and_ordered():
    # The thinned log drops most lines, so each kept line carries its original 1-based position
    # (orig_line) — the only durable anchor once the full log expires — and every record carries seq
    # (emit order) so the reader can order them. Omission markers (no original line) carry seq but no
    # orig_line. Values are stringified so they land in the queryable string attribute map (a numeric
    # attribute is dropped from it). Without this the failure region is contiguous and unlocatable.
    _, records = _emit_lines(
        [
            ThinnedLine("2026-06-25T09:14:02.000000Z first", 1),
            ThinnedLine("... 4810 lines omitted ...", None),
            ThinnedLine("2026-06-25T09:14:50.000000Z ##[error]boom", 4812),
        ]
    )
    assert [r.body for r in records] == ["first", "... 4810 lines omitted ...", "##[error]boom"]
    assert [r.attributes["seq"] for r in records] == ["0", "1", "2"]
    assert records[0].attributes["orig_line"] == "1"
    assert "orig_line" not in records[1].attributes  # a marker has no original line
    assert records[2].attributes["orig_line"] == "4812"


def test_skips_blank_lines():
    # Blank/whitespace-only lines must not become empty Logs records (noise in the corpus).
    emitted, records = _emit("2026-06-25T09:14:02.000000Z real line\n\n   \n")
    assert emitted == 1
    assert records[0].body == "real line"


def test_drops_non_scalar_attributes():
    # OTEL attributes accept scalars only; a Mapping-valued attribute must be dropped, not crash
    # or serialize garbage, while scalar attributes survive.
    _, records = _emit("2026-06-25T09:14:02.000000Z x", attributes={"job_id": 1, "nested": {"a": 1}})
    assert records[0].attributes["job_id"] == "1"
    assert "nested" not in records[0].attributes


def test_noop_when_unconfigured():
    # With no exporter, endpoint, or token, the emitter must be a safe no-op (return 0, no crash)
    # so the worker is harmless until the Logs lane is wired in.
    assert JobLogsEmitter().emit_log_archive(_lines("2026-06-25T09:14:02.000000Z x"), attributes=_ATTRS) == 0


def test_production_exporter_bypasses_egress_proxy():
    # The endpoint+token path builds the real OTLP exporter, and its requests.Session must have
    # trust_env=False: capture-logs is an in-cluster private ClusterIP, and the worker's
    # HTTP_PROXY/HTTPS_PROXY Smokescreen egress proxy denies private-range hosts (407) — so a
    # proxy-routed export silently drops every batch. No other test hits this branch (they all inject
    # an in-memory exporter), which is exactly how the 407 shipped unnoticed.
    otlp = "products.engineering_analytics.backend.logic.job_logs.emitter.OTLPLogExporter"
    with patch(otlp) as mock_otlp:
        with JobLogsEmitter(endpoint="http://capture-logs.posthog.svc.cluster.local:4318/i/v1/logs", token="phc_x"):
            pass
    assert mock_otlp.call_args.kwargs["session"].trust_env is False


def test_noop_when_token_missing():
    # Endpoint set but no token must also no-op — we never emit unauthenticated (it would 401 and
    # the records would be lost), and a half-configured lane shouldn't crash the worker.
    emitter = JobLogsEmitter(endpoint="http://localhost:8010/i/v1/logs", token=None)
    assert emitter.emit_log_archive(_lines("2026-06-25T09:14:02.000000Z x"), attributes=_ATTRS) == 0


def test_records_carry_ci_logs_service_name_despite_pod_otel_env():
    # The worker pod sets OTEL_SERVICE_NAME to its own workload name, and a hand-built LogRecord
    # defaults its resource from that env — Logger.emit(record) never attaches the provider's
    # resource. Without pinning the resource on each record, every line lands under the pod's
    # service.name and the failure-logs read filter (service.name = github-ci-logs) matches nothing.
    env = {"OTEL_SERVICE_NAME": "temporal-worker-general-purpose", "OTEL_RESOURCE_ATTRIBUTES": ""}
    with patch.dict("os.environ", env):
        _, records = _emit("2026-06-25T09:14:02.000000Z hello")
    assert [r.resource.attributes["service.name"] for r in records] == ["github-ci-logs"]
