from datetime import UTC, datetime

from opentelemetry.sdk._logs.export import InMemoryLogExporter

from products.engineering_analytics.backend.job_logs.emitter import JobLogsEmitter

_ATTRS = {"job_id": 42, "run_id": 7, "branch": "main", "conclusion": "failure"}


def _emit(archive: str, attributes=_ATTRS):
    exporter = InMemoryLogExporter()
    with JobLogsEmitter(exporter=exporter) as emitter:
        emitted = emitter.emit_log_archive(archive, attributes=attributes)
    return emitted, [d.log_record for d in exporter.get_finished_logs()]


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
    assert all(dict(r.attributes) == _ATTRS for r in records)
    expected_ns = int(datetime(2026, 6, 25, 9, 14, 2, 123456, tzinfo=UTC).timestamp() * 1_000_000_000)
    assert records[0].timestamp == expected_ns


def test_skips_blank_lines():
    # Blank/whitespace-only lines must not become empty Logs records (noise in the corpus).
    emitted, records = _emit("2026-06-25T09:14:02.000000Z real line\n\n   \n")
    assert emitted == 1
    assert records[0].body == "real line"


def test_drops_non_scalar_attributes():
    # OTEL attributes accept scalars only; a Mapping-valued attribute must be dropped, not crash
    # or serialize garbage, while scalar attributes survive.
    _, records = _emit("2026-06-25T09:14:02.000000Z x", attributes={"job_id": 1, "nested": {"a": 1}})
    assert dict(records[0].attributes) == {"job_id": 1}


def test_noop_when_unconfigured():
    # With no exporter, endpoint, or token, the emitter must be a safe no-op (return 0, no crash)
    # so the worker is harmless until the Logs lane is wired in.
    assert JobLogsEmitter().emit_log_archive("2026-06-25T09:14:02.000000Z x", attributes=_ATTRS) == 0


def test_noop_when_token_missing():
    # Endpoint set but no token must also no-op — we never emit unauthenticated (it would 401 and
    # the records would be lost), and a half-configured lane shouldn't crash the worker.
    emitter = JobLogsEmitter(endpoint="http://localhost:8010/i/v1/logs", token=None)
    assert emitter.emit_log_archive("2026-06-25T09:14:02.000000Z x", attributes=_ATTRS) == 0
