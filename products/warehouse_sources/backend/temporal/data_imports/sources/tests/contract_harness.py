"""Harness for the source contract tests: a fake network, a fake clock, and one extraction run.

The fake network sits below `requests` and urllib3, at the socket of each HTTP connection. The
retry layers of the adapter, the REST client and the source all run as they do in production. Their
waits add to a fake clock and take no real time.
"""

import ast
import json
import asyncio
import inspect
import functools
import contextlib
import dataclasses
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources import TOP_LEVEL_SOURCES_PACKAGE
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ResumableSource,
    SimpleSource,
    _BaseSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.config import is_config
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import activate_safe_point
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.fake_network import (
    _SOURCES_PACKAGE,
    FakeNetwork,
    RecordedRequest,
    RunStopped,
    fake_environment,
    http_response,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.inputs import source_inputs
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
# Vendors live in this package and in the top-level `sources` package.
_ROOT_BY_PACKAGE = {
    _SOURCES_PACKAGE: _SOURCES_ROOT,
    TOP_LEVEL_SOURCES_PACKAGE: Path(__file__).parents[7] / TOP_LEVEL_SOURCES_PACKAGE,
}
_SHARED_DIRECTORIES = {
    (_SOURCES_PACKAGE, "common"),
    (_SOURCES_PACKAGE, "generated_configs"),
    (TOP_LEVEL_SOURCES_PACKAGE, "sdk"),
}
_EMPTY_PAGE_COUNT = 8

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


class ScenarioResponder:
    """Answers every HTTP request as the scenario says."""

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario

    def respond(self, request: RecordedRequest, network: FakeNetwork) -> bytes:
        mode = self.scenario.mode
        answered = network.requests <= self.scenario.answered_first
        if mode == "stall" and not answered:
            read_timeout = request.read_timeout
            if read_timeout is None:
                network.unbounded_requests += 1
                raise RunStopped("request with no read timeout")
            network.advance(float(read_timeout))
            raise TimeoutError("timed out")

        if mode == "rate_limit" and not answered:
            return http_response(
                b"429 Too Many Requests", b"{}", [b"Retry-After: " + str(HOSTILE_RETRY_AFTER_SECONDS).encode()]
            )

        last = mode == "empty_pages" and network.requests >= _EMPTY_PAGE_COUNT
        next_url = None if last else f"{request.origin}{request.path}?contract_page={network.requests + 1}"
        headers = [] if next_url is None else [b"Link: <" + next_url.encode() + b'>; rel="next"']
        if self.scenario.list_bodies and request.method == "GET":
            return http_response(b"200 OK", b"[]", headers)
        return http_response(b"200 OK", json.dumps(empty_page_body(next_url, network.requests)).encode(), headers)


def is_stub(source: _BaseSource[Any]) -> bool:
    """Whether the source has no extraction code: its class still has the base `source_for_pipeline` stub."""
    extraction = getattr(type(source), "source_for_pipeline", None)
    return extraction in (SimpleSource.source_for_pipeline, ResumableSource.source_for_pipeline)


def _source_directory(module: str) -> tuple[str, str] | None:
    """The source package and the vendor directory of a module, or None when it is not a source module."""
    for package in _ROOT_BY_PACKAGE:
        if module.startswith(f"{package}."):
            return package, module[len(package) + 1 :].split(".")[0]
    return None


@functools.cache
def _imports_of_source_directory(package: str, directory: str) -> tuple[frozenset[str], frozenset[tuple[str, str]]]:
    """The modules that a source directory imports, and the other source directories it imports from."""
    modules: set[str] = set()
    for path in (_ROOT_BY_PACKAGE[package] / directory).rglob("*.py"):
        if path.name.startswith("test_") or "tests" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules.add(node.module)
    siblings = {found for module in modules if (found := _source_directory(module)) is not None}
    return frozenset(modules), frozenset(siblings - _SHARED_DIRECTORIES - {(package, directory)})


def native_driver(source: _BaseSource[Any]) -> str | None:
    """The first module of `NATIVE_DRIVER_MODULES` that the source imports, also through another source."""
    start = _source_directory(type(source).__module__)
    pending = [] if start is None else [start]
    seen: set[tuple[str, str]] = set()
    while pending:
        package, directory = pending.pop()
        if (package, directory) in seen or not (_ROOT_BY_PACKAGE[package] / directory).is_dir():
            continue
        seen.add((package, directory))
        modules, siblings = _imports_of_source_directory(package, directory)
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
    with fake_environment(ScenarioResponder(scenario)) as network:
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
    with fake_environment(ScenarioResponder(Scenario(mode="empty_pages"))) as discovery:
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
