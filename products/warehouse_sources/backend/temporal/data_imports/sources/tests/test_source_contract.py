"""The source contract: an extraction never holds a worker for long, and it gives control back often.

A worker that shuts down hands its imports to another worker. That works only when each source
(1) puts a deadline on each call and a limit on its retries and waits, and (2) gives control back
to the pipeline after each request, with a yield or a safe point. These tests run each source in the
registry against a fake HTTP server that stalls, rate-limits, or returns empty pages.

`source_contract_baseline.txt` lists each source that fails a condition or that the fake cannot
drive. A source that is not in the file must pass. An entry that no longer matches must change, so
the list of failures only gets shorter.
"""

import os
import sys
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

import requests
from urllib3.util.retry import Retry

import products.warehouse_sources.backend.temporal.data_imports.sources._load_all  # noqa: F401
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import rest_api_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import RESTAPIConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.tests.contract_harness import (
    RATE_LIMIT_BUDGET,
    SAFE_POINT,
    STALL_BUDGET,
    TIMEOUT,
    SourceStatus,
    StartExtraction,
    check_extraction,
    check_source,
    is_stub,
)

BASELINE_PATH = Path(__file__).parent / "source_contract_baseline.txt"
WRITE_BASELINE_VARIABLE = "SOURCE_CONTRACT_WRITE_BASELINE"
TEST_PATH = "products/warehouse_sources/backend/temporal/data_imports/sources/tests/test_source_contract.py"
REGENERATE = f"{WRITE_BASELINE_VARIABLE}=1 pytest {TEST_PATH} -p no:xdist"

BASE_URL = "https://contract.example.com"
PAGES_URL = f"{BASE_URL}/rows"
NO_ADAPTER_RETRY = Retry(total=0)

# A stub is a source directory with a `source.py` and no extraction code: its class still has the
# base `source_for_pipeline`. The contract does not apply to it until the extraction code ships.
IMPLEMENTED_SOURCES = {
    str(source_type.value): source
    for source_type, source in SourceRegistry.get_all_sources().items()
    if not is_stub(source)
}


def _response(items: Any) -> SourceResponse:
    return SourceResponse(name="rows", items=lambda: items, primary_keys=None)


def _manager(inputs: SourceInputs) -> ResumableSourceManager[Any]:
    return ResumableSourceManager(inputs, dict)


def _framework_config(request_timeout: tuple[float, float] | None = None) -> RESTAPIConfig:
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "paginator": JSONResponseCursorPaginator(cursor_path="next_cursor", cursor_param="cursor"),
        },
        "resources": [{"name": "rows", "endpoint": {"path": "/rows", "data_selector": "data"}}],
    }
    if request_timeout is not None:
        config["client"]["request_timeout"] = request_timeout
    return config


def _framework_resource(inputs: SourceInputs) -> tuple[SourceResponse, ResumableSourceManager[Any] | None]:
    manager = _manager(inputs)
    resource = rest_api_resource(_framework_config(), inputs.team_id, inputs.job_id, None)
    return _response(resource), manager


def _framework_resource_with_timeout(
    inputs: SourceInputs,
) -> tuple[SourceResponse, ResumableSourceManager[Any] | None]:
    manager = _manager(inputs)
    resource = rest_api_resource(_framework_config((10, 60)), inputs.team_id, inputs.job_id, None)
    return _response(resource), manager


def _wrapped_framework_resource(inputs: SourceInputs) -> tuple[SourceResponse, ResumableSourceManager[Any] | None]:
    manager = _manager(inputs)
    resource = rest_api_resource(_framework_config(), inputs.team_id, inputs.job_id, None)

    def rows() -> Iterator[Any]:
        yield from resource

    return _response(rows()), manager


def _rest_client_paginate(inputs: SourceInputs) -> tuple[SourceResponse, ResumableSourceManager[Any] | None]:
    manager = _manager(inputs)
    client = RESTClient(base_url=BASE_URL)

    def rows() -> Iterator[Any]:
        paginator = JSONResponseCursorPaginator(cursor_path="next_cursor", cursor_param="cursor")
        for page in client.paginate("/rows", paginator=paginator, data_selector="data"):
            if page:
                yield page

    return _response(rows()), manager


def _session_pages(session: requests.Session, **request_kwargs: Any) -> Iterator[list[Any]]:
    url: str | None = PAGES_URL
    while url:
        response = session.get(url, **request_kwargs)
        response.raise_for_status()
        body = response.json()
        yield body["data"]
        url = body.get("next")


def _tracked_session(inputs: SourceInputs) -> tuple[SourceResponse, ResumableSourceManager[Any] | None]:
    manager = _manager(inputs)

    def rows() -> Iterator[Any]:
        for page in _session_pages(make_tracked_session(), timeout=(10, 60)):
            if page:
                yield page
            manager.safe_point()

    return _response(rows()), manager


# The shared paths that most sources are built on. Each one has a baseline entry of its own, so a
# fix in the shared code removes the entry here and the entries of the sources that the fix covers.
SHARED_PATHS: dict[str, StartExtraction] = {
    "shared-path:rest-framework-resource": _framework_resource,
    "shared-path:rest-framework-resource-with-timeout": _framework_resource_with_timeout,
    "shared-path:rest-framework-wrapped-resource": _wrapped_framework_resource,
    "shared-path:rest-client-paginate": _rest_client_paginate,
    "shared-path:tracked-session": _tracked_session,
}


def _bespoke(
    *,
    timeout: Any = (10, 30),
    attempts: int = 1,
    honor_retry_after: bool = False,
    safe_point: bool = False,
    resumable: bool = True,
) -> StartExtraction:
    def start(inputs: SourceInputs) -> tuple[SourceResponse, ResumableSourceManager[Any] | None]:
        manager = _manager(inputs)
        session = make_tracked_session(retry=NO_ADAPTER_RETRY)

        def get(url: str) -> requests.Response:
            for attempt in range(attempts):
                try:
                    response = session.get(url, timeout=timeout)
                except (requests.Timeout, requests.ConnectionError):
                    if attempt == attempts - 1:
                        raise
                    continue
                if response.status_code == 429 and honor_retry_after:
                    # The harness replaces `time.sleep` with its fake clock.
                    time.sleep(float(response.headers["Retry-After"]))
                    continue
                return response
            raise RuntimeError("no attempt is left")

        def rows() -> Iterator[Any]:
            url: str | None = PAGES_URL
            while url:
                response = get(url)
                response.raise_for_status()
                body = response.json()
                if body["data"]:
                    yield body["data"]
                if safe_point:
                    manager.safe_point()
                url = body.get("next")

        return _response(rows()), manager if resumable else None

    return start


DETECTION_CASES = [
    ("bounded_call_with_a_safe_point_per_page_passes", _bespoke(safe_point=True), set()),
    ("request_with_no_timeout", _bespoke(timeout=None, safe_point=True), {TIMEOUT}),
    ("request_with_no_read_timeout", _bespoke(timeout=(10, None), safe_point=True), {TIMEOUT}),
    ("retries_that_pass_the_budget", _bespoke(attempts=20, safe_point=True), {STALL_BUDGET}),
    ("retries_inside_the_budget_pass", _bespoke(attempts=5, safe_point=True), set()),
    ("uncapped_retry_after_wait", _bespoke(honor_retry_after=True, safe_point=True), {RATE_LIMIT_BUDGET}),
    ("empty_pages_with_no_safe_point", _bespoke(), {SAFE_POINT}),
    (
        "safe_points_do_not_count_when_the_pipeline_installs_no_hook",
        _bespoke(safe_point=True, resumable=False),
        {SAFE_POINT},
    ),
]


@pytest.mark.parametrize(
    ("start", "expected"), [case[1:] for case in DETECTION_CASES], ids=[c[0] for c in DETECTION_CASES]
)
def test_harness_detects_each_condition(start: StartExtraction, expected: set[str]) -> None:
    assert check_extraction(start, ["rows"]).failed == expected


def _rest_client_without_adapter_retry(
    inputs: SourceInputs,
) -> tuple[SourceResponse, ResumableSourceManager[Any] | None]:
    manager = _manager(inputs)
    client = RESTClient(
        base_url=BASE_URL, session=make_tracked_session(retry=NO_ADAPTER_RETRY), request_timeout=(10, 60)
    )

    def rows() -> Iterator[Any]:
        paginator = JSONResponseCursorPaginator(cursor_path="next_cursor", cursor_param="cursor")
        for page in client.paginate("/rows", paginator=paginator, data_selector="data"):
            if page:
                yield page

    return _response(rows()), manager


def test_waits_of_a_retry_controller_that_an_earlier_test_replaced_still_count(monkeypatch: pytest.MonkeyPatch) -> None:
    # Some source tests replace `RESTClient._send_request.retry.sleep` and never put it back. The
    # verdict of a source must not depend on whether such a test ran earlier in the same process.
    monkeypatch.setattr(cast(Any, RESTClient._send_request).retry, "sleep", lambda *_: None)
    failed = check_extraction(_rest_client_without_adapter_retry, ["rows"]).failed
    assert {STALL_BUDGET, RATE_LIMIT_BUDGET} <= failed


def read_baseline() -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in BASELINE_PATH.read_text().splitlines():
        if line.strip():
            name, status = line.split(" ", 1)
            entries[name] = status
    return entries


def _status_of(name: str) -> SourceStatus:
    if name in SHARED_PATHS:
        verdict = check_extraction(SHARED_PATHS[name], ["rows"])
        status = f"fail:{','.join(sorted(verdict.failed))}" if verdict.failed else "pass"
        return SourceStatus(status=status, safe_point_exercised=verdict.safe_point_exercised)
    return check_source(IMPLEMENTED_SOURCES[name])


# A source that sets its timeouts still runs the retry code of these shared paths. While a path
# fails a budget, no source on it can pass that budget, so a new source may fail it too.
PATHS_THAT_SET_A_TIMEOUT = ("shared-path:rest-framework-resource-with-timeout", "shared-path:tracked-session")
INHERITABLE_CONDITIONS = {STALL_BUDGET, RATE_LIMIT_BUDGET}


def _conditions(status: str) -> set[str]:
    return set(status[len("fail:") :].split(",")) if status.startswith("fail:") else set()


def matches_baseline(name: str, status: str, baseline: dict[str, str]) -> bool:
    if name in baseline:
        return status == baseline[name]
    shared_failures = set[str]().union(*(_conditions(baseline.get(path, "pass")) for path in PATHS_THAT_SET_A_TIMEOUT))
    inherited = INHERITABLE_CONDITIONS & shared_failures
    return status == "pass" or (status.startswith("fail:") and _conditions(status) <= inherited)


SHARED_CODE_FAILS_BUDGETS = dict.fromkeys(PATHS_THAT_SET_A_TIMEOUT, "fail:rate-limit-budget,stall-budget")
RATCHET_CASES = [
    ("recorded_failure_that_is_unchanged", "Old", "fail:timeout", {"Old": "fail:timeout"}, True),
    ("recorded_failure_that_now_passes_must_leave_the_file", "Old", "pass", {"Old": "fail:timeout"}, False),
    ("recorded_failure_that_got_shorter_must_change", "Old", "fail:timeout", {"Old": "fail:safe-point,timeout"}, False),
    ("recorded_failure_that_got_longer", "Old", "fail:safe-point,timeout", {"Old": "fail:timeout"}, False),
    ("new_source_that_passes", "New", "pass", {}, True),
    ("new_source_with_no_timeout", "New", "fail:timeout", SHARED_CODE_FAILS_BUDGETS, False),
    ("new_source_that_is_not_checkable_needs_an_entry", "New", "not-checkable:schemas", {}, False),
    (
        "new_source_that_fails_a_budget_the_shared_code_fails",
        "New",
        "fail:stall-budget",
        SHARED_CODE_FAILS_BUDGETS,
        True,
    ),
    ("new_source_that_fails_a_budget_the_shared_code_meets", "New", "fail:stall-budget", {}, False),
    (
        "new_source_with_no_safe_point",
        "New",
        "fail:rate-limit-budget,safe-point",
        SHARED_CODE_FAILS_BUDGETS,
        False,
    ),
]


@pytest.mark.parametrize(
    ("name", "status", "baseline", "expected"), [case[1:] for case in RATCHET_CASES], ids=[c[0] for c in RATCHET_CASES]
)
def test_ratchet_rule(name: str, status: str, baseline: dict[str, str], expected: bool) -> None:
    assert matches_baseline(name, status, baseline) is expected


_observed: dict[str, SourceStatus] = {}


@pytest.fixture(scope="module", autouse=True)
def _write_baseline_when_asked() -> Iterator[None]:
    yield
    if not os.environ.get(WRITE_BASELINE_VARIABLE):
        return
    lines = [f"{name} {result.status}" for name, result in sorted(_observed.items()) if result.status != "pass"]
    BASELINE_PATH.write_text("\n".join(lines) + "\n")

    sources = {name: result for name, result in _observed.items() if name in IMPLEMENTED_SOURCES}
    checked = {name: result for name, result in sources.items() if not result.status.startswith("not-checkable")}
    counts = Counter(
        part
        for result in sources.values()
        for part in (
            [f"fail:{condition}" for condition in result.status[5:].split(",")]
            if result.status.startswith("fail:")
            else [result.status]
        )
    )
    exercised = sum(result.safe_point_exercised for result in checked.values())
    summary = [
        f"{BASELINE_PATH.name} written: {len(lines)} entries for {len(sources)} sources with extraction code",
        f"  checked: {len(checked)}, of which {exercised} made enough requests to exercise the safe-point condition",
        *(f"  {count:4d} {status}" for status, count in sorted(counts.items())),
    ]
    sys.stdout.write("\n".join(summary) + "\n")


@pytest.mark.parametrize("name", [*SHARED_PATHS, *sorted(IMPLEMENTED_SOURCES)])
def test_source_meets_the_contract_or_matches_the_baseline(name: str) -> None:
    result = _status_of(name)
    _observed[name] = result
    if os.environ.get(WRITE_BASELINE_VARIABLE):
        return

    baseline = read_baseline()
    recorded = baseline.get(name, "pass")
    detail = f" The attempt ended with: {result.detail}" if result.detail else ""
    assert matches_baseline(name, result.status, baseline), (
        f"{name}: the contract check gives `{result.status}`, and {BASELINE_PATH.name} records `{recorded}`.\n"
        "`fail:timeout`: a request has no read timeout, so a stalled server holds the worker without limit. "
        "Set `request_timeout` in the REST client config, or pass `timeout=` to each session call.\n"
        "`fail:stall-budget`: one request and its retries can wait more than "
        "5 minutes for a server that never answers. Lower the timeout or the retry count.\n"
        "`fail:rate-limit-budget`: one request can wait more than 5 minutes after a 429 with a large "
        "`Retry-After`. Cap the wait, and fail the attempt when the cap is not enough.\n"
        "`fail:safe-point`: more than 3 requests in a row gave no yield and no safe point, so the pipeline "
        "cannot stop the run on empty pages. Return the framework resource itself as `SourceResponse.items`, "
        "or call `ResumableSourceManager.safe_point()` after each request. The pipeline gives safe points only "
        "to a `ResumableSource`, so a source that pages through an endpoint must be one.\n"
        "`not-checkable:*`: the fake HTTP server could not drive this source. A new source that uses a "
        "driver or an SDK needs a reviewed entry in the baseline, with the deadlines stated in the pull request."
        f"{detail}\n"
        "A new source must pass. Do not add a `fail` entry for it. One exception: while the baseline "
        f"lists a budget failure for {' or '.join(PATHS_THAT_SET_A_TIMEOUT)}, a new source may fail that "
        "budget, because the shared retry code decides it.\n"
        f"When a source improved, the file must record that too. Run: {REGENERATE}"
    )


def test_baseline_lists_only_known_names() -> None:
    unknown = sorted(set(read_baseline()) - set(IMPLEMENTED_SOURCES) - set(SHARED_PATHS))
    assert not unknown, f"{BASELINE_PATH.name} lists names that are not implemented sources. Run: {REGENERATE}"
