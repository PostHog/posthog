import io
import sys
import json
import time
import types
import socket
import asyncio
import inspect
import functools
import ipaddress
import contextlib
import urllib.parse
from collections.abc import Callable, Iterator, Mapping
from typing import Any, Protocol

from unittest import mock

from django.db.backends.base.base import BaseDatabaseWrapper

import tenacity
from urllib3.connection import HTTPConnection, HTTPSConnection

from posthog.dataclasses import frozen
from posthog.security import url_validation

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# A run stops at one of these limits, because the source would not stop by itself.
_CLOCK_LIMIT_SECONDS = 4 * 3600.0
_REQUEST_LIMIT = 40

_SOURCES_PACKAGE = "products.warehouse_sources.backend.temporal.data_imports.sources"
_UNSET = object()
_PUBLIC_ADDRESS = "93.184.216.34"
_REAL_SLEEP = time.sleep
_REAL_MONOTONIC = time.monotonic
_REAL_TIME = time.time
_REAL_ASYNC_SLEEP = asyncio.sleep


class RunStopped(BaseException):
    """Ends a run that passed a harness limit. A `BaseException`, so that `except Exception` in a source cannot hide it."""


class NetworkBlockedError(OSError):
    """The source opened a connection that does not go through `requests`, so the fake cannot answer it."""


class DatabaseBlockedError(RuntimeError):
    """The source read the application database, which the contract tests do not have."""


@frozen
class RecordedRequest:
    method: str
    origin: str
    # The path without the query string.
    path: str
    # The origin and the request target, with the query string.
    url: str
    query: Mapping[str, tuple[str, ...]]
    # The names are lowercase.
    headers: Mapping[str, str]
    body: bytes | None
    read_timeout: float | None

    def param(self, name: str) -> str | None:
        """The single value of a query parameter, or None when the request carries none."""
        values = self.query.get(name)
        return values[0] if values else None

    def json(self) -> Any:
        """The request body, parsed as JSON."""
        return json.loads(self.body or b"null")


class Responder(Protocol):
    def respond(self, request: RecordedRequest, network: "FakeNetwork") -> bytes: ...


def _parse_request(origin: str, sent: bytes, read_timeout: Any) -> RecordedRequest:
    head, _, body = sent.partition(b"\r\n\r\n")
    request_line, *header_lines = head.split(b"\r\n")
    method, _, target = request_line.partition(b" ")
    target_text = target.rsplit(b" ", 1)[0].decode("latin-1") or "/"
    path, _, query_text = target_text.partition("?")
    headers: dict[str, str] = {}
    for line in header_lines:
        name, _, value = line.decode("latin-1").partition(":")
        headers[name.strip().lower()] = value.strip()
    return RecordedRequest(
        method=method.decode("latin-1"),
        origin=origin,
        path=path,
        url=f"{origin}{target_text}",
        query={key: tuple(values) for key, values in urllib.parse.parse_qs(query_text).items()},
        headers=headers,
        body=body or None,
        read_timeout=None if read_timeout is None or read_timeout is _UNSET else float(read_timeout),
    )


class FakeNetwork:
    """Answers every HTTP request through its responder, and records what the source did."""

    def __init__(self, responder: Responder) -> None:
        self.responder = responder
        self.requests_log: list[RecordedRequest] = []
        self.elapsed = 0.0
        self.requests = 0
        self.unbounded_requests = 0
        self.blocked_connections = 0
        self.blocked_database_reads = 0
        self.longest_request_seconds = 0.0
        self.longest_run_without_progress = 0
        self.error: BaseException | None = None
        self._request_key: bytes | None = None
        self._request_started = 0.0
        self._run_without_progress = 0

    def advance(self, seconds: float | None) -> None:
        if seconds is not None and seconds > 0:
            self.elapsed += seconds
        self.longest_request_seconds = max(self.longest_request_seconds, self.elapsed - self._request_started)
        if self.elapsed > _CLOCK_LIMIT_SECONDS:
            raise RunStopped("clock limit")

    def note_progress(self) -> None:
        """The source yielded an item or reached a safe point, so the pipeline could act."""
        self._run_without_progress = 0

    def respond(self, origin: str, sent: bytes, read_timeout: Any) -> io.BytesIO:
        request_line = sent.split(b"\r\n", 1)[0]

        # Attempts for the same method and URL, one after the other, are one request with its retries.
        if request_line != self._request_key:
            self._request_key = request_line
            self._request_started = self.elapsed
        self.requests += 1
        self._run_without_progress += 1
        self.longest_run_without_progress = max(self.longest_run_without_progress, self._run_without_progress)
        if self.requests > _REQUEST_LIMIT:
            raise RunStopped("request limit")

        request = _parse_request(origin, sent, read_timeout)
        self.requests_log.append(request)
        return io.BytesIO(self.responder.respond(request, self))


def http_response(status: bytes, body: bytes, headers: list[bytes]) -> bytes:
    lines = [
        b"HTTP/1.1 " + status,
        b"Content-Type: application/json",
        b"Content-Length: " + str(len(body)).encode(),
        b"Connection: close",
        *headers,
    ]
    return b"\r\n".join(lines) + b"\r\n\r\n" + body


class _FailingStream(io.RawIOBase):
    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self._error = error

    def readable(self) -> bool:
        return True

    def readline(self, size: int | None = -1) -> bytes:
        raise self._error

    def readinto(self, buffer: Any) -> int:
        raise self._error


class _FakeSocket:
    def __init__(self, network: FakeNetwork, origin: str) -> None:
        self._network = network
        self._origin = origin
        self._sent = b""
        self._read_timeout: Any = _UNSET

    def settimeout(self, value: Any) -> None:
        self._read_timeout = value

    def gettimeout(self) -> Any:
        return None if self._read_timeout is _UNSET else self._read_timeout

    def sendall(self, data: Any, *args: Any) -> None:
        self._sent += bytes(data)

    def send(self, data: Any, *args: Any) -> int:
        self._sent += bytes(data)
        return len(data)

    def makefile(self, *args: Any, **kwargs: Any) -> io.IOBase:
        sent, self._sent = self._sent, b""
        try:
            return self._network.respond(self._origin, sent, self._read_timeout)
        except (TimeoutError, RunStopped) as error:
            # A real socket fails at the first read, and not when `http.client` wraps it.
            return _FailingStream(error)

    def setsockopt(self, *args: Any) -> None:
        pass

    def shutdown(self, *args: Any) -> None:
        pass

    def close(self) -> None:
        pass


class _MemoryRedis:
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def ping(self) -> bool:
        return True

    def set(self, key: str, value: Any, **kwargs: Any) -> None:
        self._data[key] = value

    def get(self, key: str) -> Any:
        return self._data.get(key)

    def exists(self, key: str) -> int:
        return int(key in self._data)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)


@functools.cache
def _sleep_aliases() -> list[tuple[Any, str]]:
    """Each `from time import sleep` binding in a loaded source module. A patch of `time.sleep` does not reach them."""
    aliases: list[tuple[Any, str]] = []
    for module_name, module in list(sys.modules.items()):
        # Vendors live in this package and in the top-level `sources` package.
        if not module_name.startswith((_SOURCES_PACKAGE, "sources.")):
            continue
        aliases.extend((module, name) for name, value in list(vars(module).items()) if value is _REAL_SLEEP)
    return aliases


def _controller_of(value: Any) -> tenacity.Retrying | None:
    if isinstance(value, staticmethod | classmethod):
        value = value.__func__
    if not isinstance(value, types.FunctionType):
        return None
    controller = value.__dict__.get("retry")
    return controller if isinstance(controller, tenacity.Retrying) else None


@functools.cache
def _retry_controllers() -> list[tenacity.Retrying]:
    """Each synchronous tenacity controller that a `@retry` decorator put on a function or a method.

    A test can replace the `sleep` of one for the rest of the process, for example
    `RESTClient._send_request.retry.sleep = lambda *_: None`. That wait then never reaches the fake
    clock, and the verdict of every later source depends on which tests ran before.
    """
    controllers: dict[int, tenacity.Retrying] = {}
    for module in list(sys.modules.values()):
        for value in list(getattr(module, "__dict__", {}).values()):
            candidates = list(vars(value).values()) if inspect.isclass(value) else []
            for candidate in [value, *candidates]:
                if (controller := _controller_of(candidate)) is not None:
                    controllers[id(controller)] = controller
    return list(controllers.values())


@contextlib.contextmanager
def _waits_on_the_fake_clock(sleep: Callable[[float], None]) -> Iterator[None]:
    """Give each retry controller the fake `sleep`, and put back what each one had. This is cheaper than `mock.patch`."""
    controllers = _retry_controllers()
    originals = [controller.sleep for controller in controllers]
    for controller in controllers:
        controller.sleep = sleep
    try:
        yield
    finally:
        for controller, original in zip(controllers, originals):
            controller.sleep = original


@contextlib.contextmanager
def fake_environment(responder: Responder) -> Iterator[FakeNetwork]:
    """Route HTTP to a `FakeNetwork`, block every other connection, and make each wait advance a fake clock."""
    network = FakeNetwork(responder)
    redis = _MemoryRedis()

    def connect(connection: Any) -> None:
        scheme = "https" if isinstance(connection, HTTPSConnection) else "http"
        default_port = 443 if scheme == "https" else 80
        port = "" if connection.port in (None, default_port) else f":{connection.port}"
        connection.sock = _FakeSocket(network, f"{scheme}://{connection.host}{port}")
        connection.is_verified = True

    def blocked_connection(*args: Any, **kwargs: Any) -> Any:
        network.blocked_connections += 1
        raise NetworkBlockedError("the contract tests allow no real connection")

    def blocked_database(*args: Any, **kwargs: Any) -> Any:
        network.blocked_database_reads += 1
        raise DatabaseBlockedError("the contract tests have no database")

    # A source that checks its host before it connects gets a public address. Nothing connects to it.
    def resolve(host: Any, port: Any, *args: Any, **kwargs: Any) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_PUBLIC_ADDRESS, int(port or 0)))]

    def resolve_host_ips(host: str) -> set[Any]:
        return {ipaddress.ip_address(_PUBLIC_ADDRESS)}

    def sleep(seconds: float) -> None:
        network.advance(seconds)

    async def async_sleep(seconds: float, result: Any = None) -> Any:
        network.advance(seconds)
        return await _REAL_ASYNC_SLEEP(0, result)

    @contextlib.contextmanager
    def memory_redis(_manager: Any) -> Iterator[_MemoryRedis]:
        yield redis

    patches: list[Any] = [
        mock.patch.object(HTTPConnection, "connect", connect),
        mock.patch.object(HTTPSConnection, "connect", connect),
        mock.patch.object(socket.socket, "connect", blocked_connection),
        mock.patch.object(socket.socket, "connect_ex", blocked_connection),
        mock.patch.object(socket.socket, "sendto", blocked_connection),
        mock.patch.object(socket, "create_connection", blocked_connection),
        mock.patch.object(socket, "getaddrinfo", resolve),
        mock.patch.object(url_validation, "resolve_host_ips", resolve_host_ips),
        mock.patch.object(BaseDatabaseWrapper, "ensure_connection", blocked_database),
        mock.patch.object(time, "sleep", sleep),
        mock.patch.object(time, "monotonic", lambda: _REAL_MONOTONIC() + network.elapsed),
        mock.patch.object(time, "time", lambda: _REAL_TIME() + network.elapsed),
        mock.patch.object(asyncio, "sleep", async_sleep),
        mock.patch.object(ResumableSourceManager, "_get_redis", memory_redis),
        *(mock.patch.object(module, name, sleep) for module, name in _sleep_aliases()),
        _waits_on_the_fake_clock(sleep),
    ]
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        yield network
