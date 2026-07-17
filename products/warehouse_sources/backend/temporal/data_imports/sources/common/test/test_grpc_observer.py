import logging

import pytest
from unittest.mock import patch

import grpc

from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc import observer
from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.observer import (
    record_stream,
    record_unary,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_context import scoped_job_context


class _FakeMessage:
    def __init__(self, byte_size: int):
        self._byte_size = byte_size

    def ByteSize(self) -> int:
        return self._byte_size


def _ctx():
    return scoped_job_context(
        team_id=99,
        source_type="google_ads",
        external_data_source_id="src",
        external_data_schema_id="schema",
        external_data_job_id="job",
    )


def test_record_unary_emits_debug_log_on_ok(caplog):
    with _ctx(), patch.object(observer, "_emit_metrics"), patch.object(observer, "maybe_capture"):
        with caplog.at_level(
            logging.DEBUG,
            logger="products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.observer",
        ):
            record_unary(
                method="/svc/M",
                host="h",
                request=_FakeMessage(1),
                response=_FakeMessage(2),
                code=grpc.StatusCode.OK,
                exception=None,
                started_at_monotonic=0.0,
            )
    levels = {r.levelname for r in caplog.records}
    assert "WARNING" not in levels


def test_record_unary_emits_warning_on_error():
    captured: list[tuple] = []

    class FakeLogger:
        def warning(self, *args, **kwargs):
            captured.append(("warning", args, kwargs))

        def debug(self, *args, **kwargs):
            captured.append(("debug", args, kwargs))

    with (
        _ctx(),
        patch.object(observer, "logger", FakeLogger()),
        patch.object(observer, "_emit_metrics"),
        patch.object(observer, "maybe_capture"),
    ):
        record_unary(
            method="/svc/M",
            host="h",
            request=_FakeMessage(1),
            response=None,
            code=grpc.StatusCode.UNAVAILABLE,
            exception=_FakeError(),
            started_at_monotonic=0.0,
        )

    assert captured and captured[0][0] == "warning"


class _FakeError(grpc.RpcError):
    pass


def test_observer_swallows_metric_failures():
    with (
        _ctx(),
        patch.object(observer, "maybe_capture"),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.observer.get_grpc_requests_counter",
            side_effect=RuntimeError("metrics down"),
        ),
    ):
        # Must not raise.
        record_unary(
            method="/svc/M",
            host="h",
            request=_FakeMessage(1),
            response=_FakeMessage(2),
            code=grpc.StatusCode.OK,
            exception=None,
            started_at_monotonic=0.0,
        )


def test_observer_swallows_sampling_failures():
    with (
        _ctx(),
        patch.object(observer, "_emit_metrics"),
        patch.object(observer, "maybe_capture", side_effect=RuntimeError("s3 down")),
    ):
        record_stream(
            method="/svc/M",
            host="h",
            request=_FakeMessage(1),
            retained_responses=[_FakeMessage(2)],
            response_bytes=2,
            message_count=1,
            code=grpc.StatusCode.OK,
            exception=None,
            started_at_monotonic=0.0,
        )


def test_record_unary_calls_sample_capture_with_response_messages():
    with _ctx(), patch.object(observer, "_emit_metrics"), patch.object(observer, "maybe_capture") as capture:
        response = _FakeMessage(2)
        record_unary(
            method="/svc/M",
            host="h",
            request=_FakeMessage(1),
            response=response,
            code=grpc.StatusCode.OK,
            exception=None,
            started_at_monotonic=0.0,
        )
    kwargs = capture.call_args.kwargs
    assert kwargs["response_messages"] == [response]
    assert kwargs["record"].status_class == "ok"
    assert kwargs["record"].status_code_num == 0


def test_no_metrics_or_capture_without_job_context():
    """Outside a bound JobContext, metrics + capture are skipped (no crash)."""
    with patch.object(observer, "_emit_metrics") as metrics, patch.object(observer, "maybe_capture") as capture:
        record_unary(
            method="/svc/M",
            host="h",
            request=_FakeMessage(1),
            response=_FakeMessage(2),
            code=grpc.StatusCode.OK,
            exception=None,
            started_at_monotonic=0.0,
        )
    # _emit_metrics is always invoked but no-ops on None ctx; capture is gated on ctx.
    metrics.assert_called_once()
    capture.assert_not_called()


@pytest.mark.parametrize(
    "code,expected_num",
    [
        (grpc.StatusCode.OK, 0),
        (grpc.StatusCode.UNAVAILABLE, 14),
        (grpc.StatusCode.RESOURCE_EXHAUSTED, 8),
        (None, None),
    ],
)
def test_status_code_num_extraction(code, expected_num):
    with _ctx(), patch.object(observer, "_emit_metrics"), patch.object(observer, "maybe_capture") as capture:
        record_unary(
            method="/svc/M",
            host="h",
            request=_FakeMessage(1),
            response=_FakeMessage(2) if code is not None else None,
            code=code,
            exception=None if code is not None else _FakeError(),
            started_at_monotonic=0.0,
        )
    assert capture.call_args.kwargs["record"].status_code_num == expected_num
