"""Harness for the source contract tests: a fake network, a fake clock, and one extraction run.

The fake network sits below `requests` and urllib3, at the socket of each HTTP connection. The
retry layers of the adapter, the REST client and the source all run as they do in production. Their
waits add to a fake clock and take no real time.
"""

import gc
import io
import ast
import sys
import json
import time
import socket
import asyncio
import inspect
import functools
import ipaddress
import contextlib
import dataclasses
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Literal

from unittest import mock

from django.db.backends.base.base import BaseDatabaseWrapper

import tenacity
import structlog
from urllib3.connection import HTTPConnection, HTTPSConnection

from posthog.dataclasses import frozen
from posthog.security import url_validation

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ResumableSource,
    SimpleSource,
    _BaseSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.config import is_config
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import activate_safe_point
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse

# The longest time one request, with all of its retries and waits, may hold a worker.
REQUEST_BUDGET_SECONDS = 300.0
# The longest run of requests that a source may make with no yield and no safe point between them.
MAX_REQUESTS_WITHOUT_SAFE_POINT = 3
# A hostile `Retry-After` value. A source that sleeps for it holds a worker for a day.
HOSTILE_RETRY_AFTER_SECONDS = 86400

TIMEOUT = "timeout"
STALL_BUDGET = "stall-budget"
RATE_LIMIT_BUDGET = "rate-limit-budget"
SAFE_POINT = "safe-point"

# A run stops at one of these limits, because the source would not stop by itself.
_CLOCK_LIMIT_SECONDS = 4 * 3600.0
_REQUEST_LIMIT = 40
_EMPTY_PAGE_COUNT = 8

# Modules that open connections outside Python sockets, or from background threads. The fake network
# cannot see or stop those connections, so a source that imports one of them is never run.
NATIVE_DRIVER_MODULES = (
    "confluent_kafka",
    "databricks",
    "duckdb",
    "google.ads",
    "google.cloud",
    "grpc",
    "grpclib",
    "modal",
    "psycopg",
    "pymongo",
    "pymssql",
    "snowflake",
    "temporalio.client",
    "temporalio.service",
)

_SOURCES_ROOT = Path(__file__).parents[1]
_SOURCES_PACKAGE = "products.warehouse_sources.backend.temporal.data_imports.sources"
_UNSET = object()
_PUBLIC_ADDRESS = "93.184.216.34"
_REAL_SLEEP = time.sleep
_REAL_MONOTONIC = time.monotonic
_REAL_TIME = time.time
_REAL_ASYNC_SLEEP = asyncio.sleep

Mode = Literal["stall", "rate_limit", "empty_pages"]
# Starts one extraction. The manager is None for a source that the pipeline treats as not resumable.
StartExtraction = Callable[[SourceInputs], tuple[SourceResponse, ResumableSourceManager[Any] | None]]


@frozen
class Scenario:
    mode: Mode
    # Requests that get a normal answer before the mode applies. With one, a source whose first
    # request is an auth exchange reaches its first extraction request.
    answered_first: int = 0
    # Answer each GET with a JSON list and not an object. Some endpoints return a bare list.
    list_bodies: bool = False


BOUNDED_CALL_SCENARIOS = (
    Scenario(mode="stall"),
    Scenario(mode="stall", answered_first=1),
    Scenario(mode="rate_limit"),
    Scenario(mode="rate_limit", answered_first=1),
)
SAFE_POINT_SCENARIOS = (Scenario(mode="empty_pages"), Scenario(mode="empty_pages", list_bodies=True))


class RunStopped(BaseException):
    """Ends a run that passed a harness limit. A `BaseException`, so that `except Exception` in a source cannot hide it."""


class NetworkBlockedError(OSError):
    """The source opened a connection that does not go through `requests`, so the fake cannot answer it."""


class DatabaseBlockedError(RuntimeError):
    """The source read the application database, which the contract tests do not have."""


def empty_page_body(next_url: str | None, page: int) -> dict[str, Any]:
    """A page with no rows, in the shapes that most paginators and token exchanges read.

    With `next_url` the page points at a next page in each common way, so a paginator continues.
    """
    row_keys = ("data", "results", "items", "records", "result", "values", "value", "list", "rows", "entries")
    body: dict[str, Any] = dict.fromkeys(row_keys, [])
    body.update({"access_token": "contract-token", "token": "contract-token", "token_type": "Bearer"})
    body["expires_in"] = 3600
    if next_url is not None:
        cursor = f"contract-cursor-{page}"
        body.update(
            {
                "next": next_url,
                "next_page": next_url,
                "next_url": next_url,
                "next_cursor": cursor,
                "nextCursor": cursor,
                "cursor": cursor,
                "next_page_token": cursor,
                "nextPageToken": cursor,
                "has_more": True,
                "hasMore": True,
                "has_next": True,
                "links": {"next": next_url},
                "paging": {"next": {"after": cursor, "link": next_url}, "cursors": {"after": cursor}},
                "pagination": {"next": next_url, "next_cursor": cursor, "has_more": True, "next_page": page + 1},
                "meta": {"next_cursor": cursor, "has_more": True, "next": next_url, "next_page": page + 1},
                "response_metadata": {"next_cursor": cursor},
            }
        )
    return body


class FakeNetwork:
    """Answers every HTTP request as the scenario says, and records what the source did."""

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
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
        method, _, target = request_line.partition(b" ")
        path = target.rsplit(b" ", 1)[0].decode("latin-1") or "/"

        # Attempts for the same method and URL, one after the other, are one request with its retries.
        if request_line != self._request_key:
            self._request_key = request_line
            self._request_started = self.elapsed
        self.requests += 1
        self._run_without_progress += 1
        self.longest_run_without_progress = max(self.longest_run_without_progress, self._run_without_progress)
        if self.requests > _REQUEST_LIMIT:
            raise RunStopped("request limit")

        mode = self.scenario.mode
        answered = self.requests <= self.scenario.answered_first
        if mode == "stall" and not answered:
            if read_timeout is None or read_timeout is _UNSET:
                self.unbounded_requests += 1
                raise RunStopped("request with no read timeout")
            self.advance(float(read_timeout))
            raise TimeoutError("timed out")

        if mode == "rate_limit" and not answered:
            return _http_response(
                b"429 Too Many Requests", b"{}", [b"Retry-After: " + str(HOSTILE_RETRY_AFTER_SECONDS).encode()]
            )

        last = mode == "empty_pages" and self.requests >= _EMPTY_PAGE_COUNT
        next_url = None if last else f"{origin}{path.split('?', 1)[0]}?contract_page={self.requests + 1}"
        headers = [] if next_url is None else [b"Link: <" + next_url.encode() + b'>; rel="next"']
        if self.scenario.list_bodies and method == b"GET":
            return _http_response(b"200 OK", b"[]", headers)
        return _http_response(b"200 OK", json.dumps(empty_page_body(next_url, self.requests)).encode(), headers)


def _http_response(status: bytes, body: bytes, headers: list[bytes]) -> io.BytesIO:
    lines = [
        b"HTTP/1.1 " + status,
        b"Content-Type: application/json",
        b"Content-Length: " + str(len(body)).encode(),
        b"Connection: close",
        *headers,
    ]
    return io.BytesIO(b"\r\n".join(lines) + b"\r\n\r\n" + body)


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
        if not module_name.startswith(_SOURCES_PACKAGE):
            continue
        aliases.extend((module, name) for name, value in list(vars(module).items()) if value is _REAL_SLEEP)
    return aliases


@functools.cache
def _retry_controllers() -> list[tenacity.Retrying]:
    """Each synchronous tenacity controller that a `@retry` decorator created.

    A test can replace the `sleep` of one for the rest of the process, for example
    `RESTClient._send_request.retry.sleep = lambda *_: None`. That wait then never reaches the fake
    clock, and the verdict of every later source depends on which tests ran before.
    """
    return [controller for controller in gc.get_objects() if isinstance(controller, tenacity.Retrying)]


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
def fake_environment(scenario: Scenario) -> Iterator[FakeNetwork]:
    """Route HTTP to a `FakeNetwork`, block every other connection, and make each wait advance a fake clock."""
    network = FakeNetwork(scenario)
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


def is_stub(source: _BaseSource[Any]) -> bool:
    """Whether the source has no extraction code: its class still has the base `source_for_pipeline` stub."""
    extraction = getattr(type(source), "source_for_pipeline", None)
    return extraction in (SimpleSource.source_for_pipeline, ResumableSource.source_for_pipeline)


@functools.cache
def _imports_of_source_directory(directory: str) -> tuple[frozenset[str], frozenset[str]]:
    """The modules that a source directory imports, and the other source directories it imports from."""
    modules: set[str] = set()
    for path in (_SOURCES_ROOT / directory).rglob("*.py"):
        if path.name.startswith("test_") or "tests" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules.add(node.module)
    prefix = f"{_SOURCES_PACKAGE}."
    siblings = {module[len(prefix) :].split(".")[0] for module in modules if module.startswith(prefix)}
    return frozenset(modules), frozenset(siblings - {directory, "common", "generated_configs"})


def native_driver(source: _BaseSource[Any]) -> str | None:
    """The first module of `NATIVE_DRIVER_MODULES` that the source imports, also through another source."""
    pending = [type(source).__module__[len(_SOURCES_PACKAGE) + 1 :].split(".")[0]]
    seen: set[str] = set()
    while pending:
        directory = pending.pop()
        if directory in seen or not (_SOURCES_ROOT / directory).is_dir():
            continue
        seen.add(directory)
        modules, siblings = _imports_of_source_directory(directory)
        for driver in NATIVE_DRIVER_MODULES:
            if any(module == driver or module.startswith(f"{driver}.") for module in modules):
                return driver
        pending.extend(siblings)
    return None


_PLACEHOLDERS_BY_NAME = (
    ("url", "https://contract.example.com"),
    ("host", "contract.example.com"),
    ("domain", "contract.example.com"),
    ("region", "us-east-1"),
    ("date", "2024-01-01"),
)
_UUID = "00000000-0000-4000-8000-000000000000"


def _placeholder_config(config_class: type, text: str | None, fill_optional: bool) -> Any:
    kwargs: dict[str, Any] = {}
    annotations = inspect.get_annotations(config_class)
    for field in dataclasses.fields(config_class):
        if not field.init:
            continue
        annotation = annotations.get(field.name, field.type)
        required = field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING
        if not required and not (fill_optional and field.default is None and "str" in str(annotation)):
            continue
        if isinstance(annotation, type) and is_config(annotation):
            kwargs[field.name] = _placeholder_config(annotation, text, fill_optional)
        elif annotation in (int, "int"):
            kwargs[field.name] = 1
        elif annotation in (bool, "bool"):
            kwargs[field.name] = False
        elif text is not None:
            kwargs[field.name] = text
        else:
            kwargs[field.name] = next(
                (value for fragment, value in _PLACEHOLDERS_BY_NAME if fragment in field.name), "contract"
            )
    return config_class(**kwargs)


def placeholder_configs(config_class: type) -> Iterator[Any]:
    """Configs with a plausible value in each field. They hold no credential and reach no real host.

    A source validates its fields before the first request, and the valid shapes differ. The
    variants cover the common ones: a host or a URL, a bare subdomain, a number, a UUID, and a
    source that needs one of its optional credential fields.
    """
    for text, fill_optional in ((None, False), ("contract", False), (None, True), ("1", False), (_UUID, False)):
        try:
            yield _placeholder_config(config_class, text, fill_optional)
        except Exception:
            continue


def source_inputs(schema_name: str) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="00000000-0000-4000-8000-000000000001",
        source_id="00000000-0000-4000-8000-000000000002",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="00000000-0000-4000-8000-000000000003",
        logger=structlog.get_logger("source_contract"),
        reset_pipeline=False,
    )


def start_source(source: _BaseSource[Any], config: Any) -> StartExtraction:
    def start(inputs: SourceInputs) -> tuple[SourceResponse, ResumableSourceManager[Any] | None]:
        if isinstance(source, ResumableSource):
            manager = source.get_resumable_source_manager(inputs)
            return source.source_for_pipeline(config, manager, inputs), manager
        assert isinstance(source, SimpleSource)
        return source.source_for_pipeline(config, inputs), None

    return start


async def _drain_async(items: Any, on_item: Callable[[], None]) -> None:
    async for _ in items:
        on_item()


def run_extraction(start: StartExtraction, schema_name: str, scenario: Scenario) -> FakeNetwork:
    """Run one extraction to its end, or to its first error, and return what the fake network recorded."""
    with fake_environment(scenario) as network:
        try:
            response, manager = start(source_inputs(schema_name))
            items = response.items()
            with contextlib.ExitStack() as stack:
                # The pipeline installs the safe-point hook only for a resumable source, and the
                # framework safe points count only when the pipeline reads the framework `Resource`.
                if manager is not None:
                    stack.enter_context(
                        activate_safe_point(
                            network.note_progress, covers_framework_checkpoints=isinstance(items, Resource)
                        )
                    )
                if hasattr(items, "__aiter__"):
                    asyncio.run(_drain_async(items, network.note_progress))
                else:
                    for _ in items:
                        network.note_progress()
        except (Exception, RunStopped) as error:
            # Most scenarios end in an error. The verdict comes from what the network recorded.
            network.error = error
        return network


@frozen
class Verdict:
    failed: frozenset[str]
    requests: int
    blocked_connections: int
    blocked_database_reads: int
    # Whether an empty-page run made enough requests for the safe-point condition to mean something.
    safe_point_exercised: bool
    first_error: BaseException | None


def check_extraction(start: StartExtraction, schema_names: list[str]) -> Verdict:
    """Run the scenarios against the first schema and the last one.

    The bounded-call scenarios run one time, against the first of the two schemas that sends a request.
    A source uses one HTTP client for all of its schemas, and a webhook-fed schema sends no request.
    """
    failed: set[str] = set()
    runs: list[FakeNetwork] = []
    safe_point_exercised = False
    bounded_calls_checked = False
    for schema_name in dict.fromkeys([schema_names[0], schema_names[-1]]):
        scenarios = (*SAFE_POINT_SCENARIOS, *(() if bounded_calls_checked else BOUNDED_CALL_SCENARIOS))
        for scenario in scenarios:
            network = run_extraction(start, schema_name, scenario)
            runs.append(network)
            over_budget = network.longest_request_seconds > REQUEST_BUDGET_SECONDS
            if scenario.mode == "stall":
                if network.unbounded_requests:
                    failed.add(TIMEOUT)
                elif over_budget:
                    failed.add(STALL_BUDGET)
            elif scenario.mode == "rate_limit":
                if over_budget:
                    failed.add(RATE_LIMIT_BUDGET)
            else:
                bounded_calls_checked |= network.requests > 0
                safe_point_exercised |= network.requests > MAX_REQUESTS_WITHOUT_SAFE_POINT
                if network.longest_run_without_progress > MAX_REQUESTS_WITHOUT_SAFE_POINT:
                    failed.add(SAFE_POINT)
    return Verdict(
        failed=frozenset(failed),
        requests=sum(network.requests for network in runs),
        blocked_connections=sum(network.blocked_connections for network in runs),
        blocked_database_reads=sum(network.blocked_database_reads for network in runs),
        safe_point_exercised=safe_point_exercised,
        first_error=next((network.error for network in runs if network.error is not None), None),
    )


@frozen
class SourceStatus:
    """`pass`, `fail:<condition>,...` or `not-checkable:<reason>`."""

    status: str
    safe_point_exercised: bool = False
    # For a source that is not checkable: the error that ended the attempt.
    detail: str = ""


def check_source(source: _BaseSource[Any]) -> SourceStatus:
    driver = native_driver(source)
    if driver is not None:
        return SourceStatus(status=f"not-checkable:driver:{driver}")

    result = SourceStatus(status="not-checkable:config")
    for config in placeholder_configs(source._config_class):
        result = _check_source_with_config(source, config)
        # The other reasons do not depend on the placeholder values.
        if result.status not in ("not-checkable:schemas", "not-checkable:no-request"):
            break
    return result


def _check_source_with_config(source: _BaseSource[Any], config: Any) -> SourceStatus:
    with fake_environment(Scenario(mode="empty_pages")) as discovery:
        try:
            schema_names = [schema.name for schema in source.get_schemas(config, team_id=1)]
        except (Exception, RunStopped) as error:
            discovery.error = error
            schema_names = []
    if not schema_names:
        reason = _not_checkable(discovery.blocked_database_reads, discovery.blocked_connections, "schemas")
        return SourceStatus(status=reason, detail=repr(discovery.error))

    verdict = check_extraction(start_source(source, config), schema_names)
    if verdict.failed:
        return SourceStatus(
            status=f"fail:{','.join(sorted(verdict.failed))}", safe_point_exercised=verdict.safe_point_exercised
        )
    if verdict.requests == 0:
        reason = _not_checkable(verdict.blocked_database_reads, verdict.blocked_connections, "no-request")
        return SourceStatus(status=reason, detail=repr(verdict.first_error))
    return SourceStatus(status="pass", safe_point_exercised=verdict.safe_point_exercised)


def _not_checkable(blocked_database_reads: int, blocked_connections: int, otherwise: str) -> str:
    if blocked_database_reads:
        return "not-checkable:database"
    if blocked_connections:
        return "not-checkable:transport"
    return f"not-checkable:{otherwise}"
