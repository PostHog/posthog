from datetime import UTC, datetime

from unittest.mock import patch

from opentelemetry.exporter.otlp.proto.common._internal._log_encoder import encode_logs
from opentelemetry.sdk._logs.export import InMemoryLogExporter
from parameterized import parameterized

from products.engineering_analytics.backend.logic.job_logs.emitter import JobLogsEmitter
from products.engineering_analytics.backend.logic.job_logs.thinning import ThinnedLine

_ATTRS = {"job_id": 42, "run_id": 7, "branch": "main", "conclusion": "failure"}


def _lines(archive: str) -> list[ThinnedLine]:
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
    # The OTLP exporter protobuf-encodes each batch, a step InMemoryLogExporter skips. A None or
    # str trace or span id raises in the encoder and drops the whole batch.
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
    record = _encode_one(trace_id=trace_id, span_id=span_id)
    assert record.trace_id == b""
    assert record.span_id == b""


def test_emits_per_line_with_parsed_timestamp_severity_and_attributes():
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
    # The logs pipeline indexes only string attributes into the queryable map.
    assert all(all(record.attributes[key] == str(value) for key, value in _ATTRS.items()) for record in records)
    expected_ns = int(datetime(2026, 6, 25, 9, 14, 2, 123456, tzinfo=UTC).timestamp() * 1_000_000_000)
    assert records[0].timestamp == expected_ns


def test_stamps_seq_and_orig_line_so_thinned_lines_stay_anchored_and_ordered():
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
    emitted, records = _emit("2026-06-25T09:14:02.000000Z real line\n\n   \n")
    assert emitted == 1
    assert records[0].body == "real line"


def test_drops_non_scalar_attributes():
    _, records = _emit("2026-06-25T09:14:02.000000Z x", attributes={"job_id": 1, "nested": {"a": 1}})
    assert records[0].attributes["job_id"] == "1"
    assert "nested" not in records[0].attributes


def test_noop_when_unconfigured():
    assert JobLogsEmitter().emit_log_archive(_lines("2026-06-25T09:14:02.000000Z x"), attributes=_ATTRS) == 0


def test_production_exporter_bypasses_egress_proxy():
    # Every other test injects an in-memory exporter, so only this test builds the OTLP exporter.
    otlp = "products.engineering_analytics.backend.logic.job_logs.emitter.OTLPLogExporter"
    with patch(otlp) as mock_otlp:
        with JobLogsEmitter(endpoint="http://capture-logs.posthog.svc.cluster.local:4318/i/v1/logs", token="phc_x"):
            pass
    assert mock_otlp.call_args.kwargs["session"].trust_env is False


def test_noop_when_token_missing():
    emitter = JobLogsEmitter(endpoint="http://localhost:8010/i/v1/logs", token=None)
    assert emitter.emit_log_archive(_lines("2026-06-25T09:14:02.000000Z x"), attributes=_ATTRS) == 0


def test_records_carry_ci_logs_service_name_despite_pod_otel_env():
    # The worker pod sets OTEL_SERVICE_NAME, and a hand-built LogRecord takes its resource from it.
    env = {"OTEL_SERVICE_NAME": "temporal-worker-general-purpose", "OTEL_RESOURCE_ATTRIBUTES": ""}
    with patch.dict("os.environ", env):
        _, records = _emit("2026-06-25T09:14:02.000000Z hello")
    assert [r.resource.attributes["service.name"] for r in records] == ["github-ci-logs"]
