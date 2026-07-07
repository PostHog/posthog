from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import patch

import grpc

from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc import transport
from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.transport import (
    TrackedUnaryStreamClientInterceptor,
    TrackedUnaryUnaryClientInterceptor,
    make_tracked_channel,
    tracked_interceptors,
)

HOST = "googleads.googleapis.com"
METHOD = "/google.ads.googleads.v23.services.GoogleAdsService/Search"


class _FakeMessage:
    def __init__(self, byte_size: int):
        self._byte_size = byte_size

    def ByteSize(self) -> int:
        return self._byte_size


class _FakeUnaryOutcome:
    """Mimics grpc's `_UnaryOutcome`: resolved future with code/result/exception."""

    def __init__(self, response: Any, code: grpc.StatusCode = grpc.StatusCode.OK):
        self._response = response
        self._code = code

    def code(self) -> grpc.StatusCode:
        return self._code

    def exception(self) -> BaseException | None:
        return None

    def result(self) -> Any:
        return self._response


class _FakeRpcError(grpc.RpcError):
    def __init__(self, code: grpc.StatusCode):
        self._code = code

    def code(self) -> grpc.StatusCode:
        return self._code


def _call_details(method: str = METHOD) -> SimpleNamespace:
    return SimpleNamespace(method=method)


# ---------------------------------------------------------------------------
# Unary-unary
# ---------------------------------------------------------------------------


def test_unary_success_records_and_returns_outcome_unchanged():
    request = _FakeMessage(11)
    response = _FakeMessage(22)
    outcome = _FakeUnaryOutcome(response, grpc.StatusCode.OK)

    interceptor = TrackedUnaryUnaryClientInterceptor(HOST)
    with patch.object(transport, "record_unary") as record:
        result = interceptor.intercept_unary_unary(lambda d, r: outcome, _call_details(), request)

    assert result is outcome
    kwargs = record.call_args.kwargs
    assert kwargs["method"] == METHOD
    assert kwargs["host"] == HOST
    assert kwargs["request"] is request
    assert kwargs["response"] is response
    assert kwargs["code"] == grpc.StatusCode.OK
    assert kwargs["exception"] is None


def test_unary_error_records_error_and_returns_outcome_unchanged():
    request = _FakeMessage(11)
    error = _FakeRpcError(grpc.StatusCode.UNAVAILABLE)

    interceptor = TrackedUnaryUnaryClientInterceptor(HOST)
    with patch.object(transport, "record_unary") as record:
        result = interceptor.intercept_unary_unary(lambda d, r: error, _call_details(), request)

    # The raw RpcError is returned so the SDK's `.result()` still raises.
    assert result is error
    kwargs = record.call_args.kwargs
    assert kwargs["code"] == grpc.StatusCode.UNAVAILABLE
    assert kwargs["response"] is None
    assert kwargs["exception"] is error


def test_unary_observer_failure_does_not_mask_outcome():
    outcome = _FakeUnaryOutcome(_FakeMessage(1))
    interceptor = TrackedUnaryUnaryClientInterceptor(HOST)
    with patch.object(transport, "record_unary", side_effect=RuntimeError("telemetry boom")):
        result = interceptor.intercept_unary_unary(lambda d, r: outcome, _call_details(), _FakeMessage(1))
    assert result is outcome


# ---------------------------------------------------------------------------
# Unary-stream
# ---------------------------------------------------------------------------


def test_stream_success_sizes_counts_and_records_once():
    messages = [_FakeMessage(10), _FakeMessage(20), _FakeMessage(30)]
    interceptor = TrackedUnaryStreamClientInterceptor(HOST)

    with (
        patch.object(transport, "record_stream") as record,
        patch.object(transport, "is_capture_armed", return_value=False),
    ):
        wrapper = interceptor.intercept_unary_stream(lambda d, r: iter(messages), _call_details(), _FakeMessage(5))
        collected = list(wrapper)

    assert collected == messages
    assert record.call_count == 1
    kwargs = record.call_args.kwargs
    assert kwargs["code"] == grpc.StatusCode.OK
    assert kwargs["message_count"] == 3
    assert kwargs["response_bytes"] == 60
    assert kwargs["exception"] is None
    assert kwargs["retained_responses"] == []  # capture disarmed → nothing retained


def test_stream_is_lazy_and_does_not_buffer():
    produced: list[int] = []

    def gen():
        for i in range(3):
            produced.append(i)
            yield _FakeMessage(1)

    interceptor = TrackedUnaryStreamClientInterceptor(HOST)
    with patch.object(transport, "record_stream"), patch.object(transport, "is_capture_armed", return_value=False):
        wrapper = interceptor.intercept_unary_stream(lambda d, r: gen(), _call_details(), _FakeMessage(0))
        it = iter(wrapper)
        next(it)
        # Only the first element should have been produced so far.
        assert produced == [0]
        next(it)
        assert produced == [0, 1]


def test_stream_error_mid_iteration_records_and_reraises():
    error = _FakeRpcError(grpc.StatusCode.RESOURCE_EXHAUSTED)

    def gen():
        yield _FakeMessage(10)
        yield _FakeMessage(20)
        raise error

    interceptor = TrackedUnaryStreamClientInterceptor(HOST)
    with (
        patch.object(transport, "record_stream") as record,
        patch.object(transport, "is_capture_armed", return_value=False),
    ):
        wrapper = interceptor.intercept_unary_stream(lambda d, r: gen(), _call_details(), _FakeMessage(0))
        it = iter(wrapper)
        next(it)
        next(it)
        with pytest.raises(grpc.RpcError):
            next(it)

    assert record.call_count == 1
    kwargs = record.call_args.kwargs
    assert kwargs["code"] == grpc.StatusCode.RESOURCE_EXHAUSTED
    assert kwargs["exception"] is error
    assert kwargs["message_count"] == 2
    assert kwargs["response_bytes"] == 30


def test_stream_retains_head_only_when_capture_armed():
    messages = [_FakeMessage(1) for _ in range(10)]
    interceptor = TrackedUnaryStreamClientInterceptor(HOST)

    with (
        patch.object(transport, "record_stream") as record,
        patch.object(transport, "is_capture_armed", return_value=True),
    ):
        wrapper = interceptor.intercept_unary_stream(lambda d, r: iter(messages), _call_details(), _FakeMessage(0))
        list(wrapper)

    retained = record.call_args.kwargs["retained_responses"]
    # MAX_CAPTURED_RESPONSE_MESSAGES head only, not all 10.
    assert 0 < len(retained) <= 3
    assert record.call_args.kwargs["message_count"] == 10


def test_stream_observer_failure_does_not_break_iteration():
    messages = [_FakeMessage(1)]
    interceptor = TrackedUnaryStreamClientInterceptor(HOST)
    with (
        patch.object(transport, "record_stream", side_effect=RuntimeError("boom")),
        patch.object(transport, "is_capture_armed", return_value=False),
    ):
        wrapper = interceptor.intercept_unary_stream(lambda d, r: iter(messages), _call_details(), _FakeMessage(0))
        assert list(wrapper) == messages


def test_stream_wrapper_delegates_unknown_attributes():
    sentinel = object()

    class _CallLike:
        def __iter__(self):
            return iter([])

        def cancel(self):
            return sentinel

    interceptor = TrackedUnaryStreamClientInterceptor(HOST)
    with patch.object(transport, "is_capture_armed", return_value=False):
        wrapper = interceptor.intercept_unary_stream(lambda d, r: _CallLike(), _call_details(), _FakeMessage(0))
    assert wrapper.cancel() is sentinel


def test_stream_close_records_partial_stream_when_consumer_stops_early():
    messages = [_FakeMessage(10), _FakeMessage(20), _FakeMessage(30)]
    interceptor = TrackedUnaryStreamClientInterceptor(HOST)

    with (
        patch.object(transport, "record_stream") as record,
        patch.object(transport, "is_capture_armed", return_value=False),
    ):
        wrapper = interceptor.intercept_unary_stream(lambda d, r: iter(messages), _call_details(), _FakeMessage(0))
        it = iter(wrapper)
        next(it)  # consume one message, then bail out early
        wrapper.close()

    assert record.call_count == 1
    kwargs = record.call_args.kwargs
    assert kwargs["code"] is None
    assert kwargs["exception"] is None
    assert kwargs["message_count"] == 1
    assert kwargs["response_bytes"] == 10


def test_stream_close_after_completion_does_not_double_record():
    messages = [_FakeMessage(10)]
    interceptor = TrackedUnaryStreamClientInterceptor(HOST)

    with (
        patch.object(transport, "record_stream") as record,
        patch.object(transport, "is_capture_armed", return_value=False),
    ):
        wrapper = interceptor.intercept_unary_stream(lambda d, r: iter(messages), _call_details(), _FakeMessage(0))
        list(wrapper)  # drains to StopIteration → records once
        wrapper.close()  # idempotent: guarded by _recorded

    assert record.call_count == 1
    assert record.call_args.kwargs["code"] == grpc.StatusCode.OK


def test_stream_close_delegates_to_inner_iterator():
    closed = []

    class _ClosableCall:
        def __iter__(self):
            return iter([])

        def close(self):
            closed.append(True)

    interceptor = TrackedUnaryStreamClientInterceptor(HOST)
    with (
        patch.object(transport, "record_stream"),
        patch.object(transport, "is_capture_armed", return_value=False),
    ):
        wrapper = interceptor.intercept_unary_stream(lambda d, r: _ClosableCall(), _call_details(), _FakeMessage(0))
        wrapper.close()

    assert closed == [True]


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def test_tracked_interceptors_returns_both_kinds():
    interceptors = tracked_interceptors(HOST)
    assert len(interceptors) == 2
    assert any(isinstance(i, grpc.UnaryUnaryClientInterceptor) for i in interceptors)
    assert any(isinstance(i, grpc.UnaryStreamClientInterceptor) for i in interceptors)


def test_make_tracked_channel_wraps_with_interceptors():
    base = grpc.insecure_channel("localhost:50051")
    captured: dict[str, Any] = {}

    def fake_intercept(channel, *interceptors):
        captured["channel"] = channel
        captured["interceptors"] = interceptors
        return "intercepted"

    with patch("grpc.intercept_channel", side_effect=fake_intercept):
        result = make_tracked_channel(base, host=HOST)

    assert result == "intercepted"
    assert captured["channel"] is base
    assert len(captured["interceptors"]) == 2
    base.close()
