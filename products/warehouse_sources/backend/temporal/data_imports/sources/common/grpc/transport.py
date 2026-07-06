"""Tracked gRPC client interceptors.

`tracked_interceptors(host)` returns the interceptor list to hand to SDKs that
accept an `interceptors=` argument (e.g. google-ads' `GoogleAdsClient.get_service`).
`make_tracked_channel(channel, host=...)` wraps an already-built, credential-bearing
channel for SDKs that accept a `channel=` / `transport=` argument (e.g. BigQuery
Storage).

Both interceptors feed the observer once per call — unary-unary on return,
unary-stream on stream completion or error. Telemetry is wrapped in try/except
so it can never raise into the call path; a broken observer must not turn into
a sync failure. Streaming responses are sized-and-released (never buffered);
only a small head of messages is retained, and only when sample capture is armed.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import grpc

from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.observer import (
    record_stream,
    record_unary,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.proto_utils import message_byte_size
from products.warehouse_sources.backend.temporal.data_imports.sources.common.grpc.sampling import (
    MAX_CAPTURED_RESPONSE_MESSAGES,
    is_capture_armed,
)


def _safe_code(obj: Any) -> grpc.StatusCode | None:
    code_fn = getattr(obj, "code", None)
    if code_fn is None:
        return None
    try:
        return code_fn()
    except Exception:
        return None


def _resolve_unary_outcome(outcome: Any) -> tuple[grpc.StatusCode | None, Any, BaseException | None]:
    """Extract (status_code, response, exception) from a unary continuation result.

    In this grpc version the unary continuation performs the RPC synchronously,
    so reading `.code()` / `.exception()` / `.result()` neither blocks nor
    re-issues the call.
    """
    if isinstance(outcome, grpc.RpcError):
        return _safe_code(outcome), None, outcome

    # An interceptor continuation returns a call/future (resolved synchronously
    # in this grpc version). But be defensive: some stubs/continuations hand back
    # the response message directly. Anything without the call surface
    # (`.exception()` / `.result()` / `.code()`) is treated as an already-resolved
    # successful response, so we still size it correctly rather than recording a
    # spurious error.
    if not (hasattr(outcome, "exception") and hasattr(outcome, "result")):
        return grpc.StatusCode.OK, outcome, None

    try:
        exc = outcome.exception()
    except Exception:
        exc = None
    if exc is not None:
        return _safe_code(outcome), None, exc

    try:
        response = outcome.result()
    except grpc.RpcError as rpc_error:
        return _safe_code(rpc_error), None, rpc_error
    except Exception as error:
        return _safe_code(outcome), None, error

    return _safe_code(outcome) or grpc.StatusCode.OK, response, None


class TrackedUnaryUnaryClientInterceptor(grpc.UnaryUnaryClientInterceptor):
    def __init__(self, host: str) -> None:
        self._host = host

    def intercept_unary_unary(self, continuation: Any, client_call_details: Any, request: Any) -> Any:
        started = time.monotonic()
        outcome = continuation(client_call_details, request)
        try:
            code, response, exception = _resolve_unary_outcome(outcome)
            record_unary(
                method=getattr(client_call_details, "method", "") or "",
                host=self._host,
                request=request,
                response=response,
                code=code,
                exception=exception,
                started_at_monotonic=started,
            )
        except Exception:
            # Telemetry must never mask the real call outcome.
            pass
        return outcome


class TrackedUnaryStreamClientInterceptor(grpc.UnaryStreamClientInterceptor):
    def __init__(self, host: str) -> None:
        self._host = host

    def intercept_unary_stream(self, continuation: Any, client_call_details: Any, request: Any) -> Any:
        started = time.monotonic()
        response_iter = continuation(client_call_details, request)
        return _TrackedStreamWrapper(
            response_iter,
            host=self._host,
            method=getattr(client_call_details, "method", "") or "",
            request=request,
            started_at_monotonic=started,
        )


class _TrackedStreamWrapper(Iterator[Any]):
    """Wrap a unary-stream response iterator to time, size and (optionally) sample it.

    Messages are sized and released as they pass through — never buffered. Only
    the first `MAX_CAPTURED_RESPONSE_MESSAGES` are retained, and only when sample
    capture is armed. Recording happens exactly once, on stream completion or the
    first error.
    """

    def __init__(
        self, response_iter: Any, *, host: str, method: str, request: Any, started_at_monotonic: float
    ) -> None:
        self._iter = response_iter
        self._host = host
        self._method = method
        self._request = request
        self._started = started_at_monotonic
        self._response_bytes = 0
        self._message_count = 0
        self._retained: list[Any] = []
        self._armed = self._safe_is_armed()
        self._recorded = False

    @staticmethod
    def _safe_is_armed() -> bool:
        try:
            return is_capture_armed()
        except Exception:
            return False

    def __iter__(self) -> _TrackedStreamWrapper:
        return self

    def __next__(self) -> Any:
        try:
            message = next(self._iter)
        except StopIteration:
            self._record(code=grpc.StatusCode.OK, exception=None)
            raise
        except grpc.RpcError as rpc_error:
            self._record(code=_safe_code(rpc_error), exception=rpc_error)
            raise
        except Exception as error:
            self._record(code=None, exception=error)
            raise

        self._message_count += 1
        self._response_bytes += message_byte_size(message)
        if self._armed and len(self._retained) < MAX_CAPTURED_RESPONSE_MESSAGES:
            self._retained.append(message)
        return message

    def _record(self, *, code: grpc.StatusCode | None, exception: BaseException | None) -> None:
        if self._recorded:
            return
        self._recorded = True
        try:
            record_stream(
                method=self._method,
                host=self._host,
                request=self._request,
                retained_responses=self._retained,
                response_bytes=self._response_bytes,
                message_count=self._message_count,
                code=code,
                exception=exception,
                started_at_monotonic=self._started,
            )
        except Exception:
            pass

    def close(self) -> None:
        # A consumer that stops early (explicit close, cancellation, generator
        # teardown) never drives __next__ to its terminal StopIteration/error,
        # so record the partial stream here before tearing the iterator down.
        # The _recorded guard keeps this idempotent if __next__ already fired.
        self._record(code=None, exception=None)
        inner_close = getattr(self._iter, "close", None)
        if inner_close is not None:
            inner_close()

    def __getattr__(self, name: str) -> Any:
        # Delegate Call-surface methods (cancel, trailing_metadata, …) the SDK
        # may reach for on the response object to the wrapped iterator.
        return getattr(self._iter, name)


def tracked_interceptors(host: str) -> list[grpc.UnaryUnaryClientInterceptor | grpc.UnaryStreamClientInterceptor]:
    return [TrackedUnaryUnaryClientInterceptor(host), TrackedUnaryStreamClientInterceptor(host)]


def make_tracked_channel(channel: grpc.Channel, *, host: str) -> grpc.Channel:
    """Wrap a credential-bearing channel so every RPC rides the tracked interceptors."""
    return grpc.intercept_channel(channel, *tracked_interceptors(host))
