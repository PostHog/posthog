import time
from collections.abc import Callable, Sequence
from typing import Any, Literal, cast

import pytest

from django.test import override_settings

import requests
import tenacity
from parameterized import parameterized
from tenacity import RetryCallState, retry_if_exception_type, stop_after_attempt, wait_fixed
from urllib3.util.timeout import Timeout

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    NO_REQUEST_TIMEOUT,
    make_tracked_session,
    request_deadline,
    request_deadline_allows_wait,
    retry_with_deadline,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import _deadline_timeout
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.fake_network import (
    FakeNetwork,
    RecordedRequest,
    fake_environment,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.responders import ScriptedResponse

BASE_URL = "https://api.example.com"
BUDGET = 100.0
READ_TIMEOUT = 40.0
# The fake clock adds real time too, a few milliseconds in a test.
SLACK = 0.5

STALL: Literal["stall"] = "stall"
Answer = ScriptedResponse | Literal["stall"]


def _status(status: int, retry_after: float | None = None) -> ScriptedResponse:
    headers = {} if retry_after is None else {"Retry-After": str(int(retry_after))}
    return ScriptedResponse(status=status, json={}, headers=headers)


OK = ScriptedResponse(json=[])


@frozen
class _Try:
    started_at: float
    read_timeout: float | None


class _StallingVendor:
    """Answers each try from a script. A stall uses the whole read timeout of the try and then fails it."""

    def __init__(self, script: Sequence[Answer]) -> None:
        self._script = list(script)
        self.tries: list[_Try] = []

    def respond(self, request: RecordedRequest, network: FakeNetwork) -> bytes:
        self.tries.append(_Try(started_at=network.elapsed, read_timeout=request.read_timeout))
        answer = self._script.pop(0) if self._script else STALL
        if answer == STALL:
            network.advance(request.read_timeout)
            raise TimeoutError("timed out")
        assert isinstance(answer, ScriptedResponse)
        return answer.to_bytes()


def _through_rest_client() -> None:
    list(RESTClient(base_url=BASE_URL).paginate("/items", paginator=SinglePagePaginator()))


def _through_tracked_session() -> None:
    make_tracked_session().get(f"{BASE_URL}/items").raise_for_status()


Send = Callable[[], None]


@frozen
class _Run:
    vendor: _StallingVendor
    elapsed: float
    error: BaseException | None


def _run(send: Send, script: Sequence[Answer], budget: float = BUDGET) -> _Run:
    vendor = _StallingVendor(script)
    error: BaseException | None = None
    with (
        override_settings(
            DATA_WAREHOUSE_SOURCE_RETRY_BUDGET_SECONDS=budget,
            DATA_WAREHOUSE_SOURCE_READ_TIMEOUT_SECONDS=READ_TIMEOUT,
        ),
        fake_environment(vendor) as network,
    ):
        try:
            send()
        except Exception as raised:
            error = raised
    return _Run(vendor=vendor, elapsed=network.elapsed, error=error)


# The client tries 5 times and waits 1, 2, 4 and 8 seconds. The adapter tries 4 times and waits 0, 1 and 2 seconds.
CASES: list[tuple[str, Send, Sequence[Answer], list[float], float]] = [
    ("client_stall_on_the_first_try", _through_rest_client, [], [0, 41, 83], BUDGET),
    ("adapter_stall_on_the_first_try", _through_tracked_session, [], [0, 40, 81], BUDGET),
    # Fast failures leave most of the budget, and the stalls after them get only what is left.
    (
        "client_stall_after_fast_failures",
        _through_rest_client,
        [_status(503), _status(503)],
        [0, 1, 3, 47, 95],
        BUDGET,
    ),
    (
        "adapter_stall_after_a_fast_failure",
        _through_tracked_session,
        [_status(503)],
        [0, 0, 41, 83],
        BUDGET,
    ),
    # A wait of 70 s after the stall would end after the deadline, so the request fails at once.
    ("client_retry_after_longer_than_the_time_left", _through_rest_client, [STALL, _status(429, 70)], [0, 41], 41),
    ("adapter_retry_after_longer_than_the_time_left", _through_tracked_session, [STALL, _status(429, 70)], [0, 40], 40),
    # A wait that ends exactly at the deadline leaves no time for a try, so it does not start.
    ("client_wait_to_the_exact_deadline", _through_rest_client, [_status(429, 50)] * 3, [0, 50], 50),
    ("adapter_wait_to_the_exact_deadline", _through_tracked_session, [_status(429, 50)] * 3, [0, 50], 50),
]


class TestRequestDeadline:
    @parameterized.expand(CASES)
    def test_all_tries_of_one_request_end_by_the_budget(
        self, _name: str, send: Send, script: Sequence[Answer], starts: list[float], elapsed: float
    ) -> None:
        run = _run(send, script)

        assert isinstance(run.error, RESTClientRetryableError | requests.RequestException)
        assert [t.started_at for t in run.vendor.tries] == pytest.approx(starts, abs=SLACK)
        assert run.elapsed == pytest.approx(elapsed, abs=SLACK)
        assert run.elapsed <= BUDGET
        for attempt in run.vendor.tries:
            assert attempt.read_timeout is not None
            assert attempt.read_timeout <= min(READ_TIMEOUT, BUDGET - attempt.started_at)

    @parameterized.expand([("client", _through_rest_client), ("adapter", _through_tracked_session)])
    def test_each_request_gets_its_own_budget(self, _name: str, send: Send) -> None:
        def two_requests() -> None:
            # The first request stalls for more than 80 s of its budget and then succeeds on its third try.
            send()
            send()

        run = _run(two_requests, [STALL, STALL, OK, STALL])

        assert run.vendor.tries[3].read_timeout == pytest.approx(READ_TIMEOUT, abs=SLACK)

    def test_a_retry_after_past_the_deadline_gets_no_capped_wait(self) -> None:
        # The budget leaves room for the 120 s cap on a wait, but not for the day that the server asks for.
        run = _run(_through_tracked_session, [_status(429, 86400)] * 3, budget=300)

        assert isinstance(run.error, requests.HTTPError)
        assert len(run.vendor.tries) == 1
        assert run.elapsed == pytest.approx(0, abs=SLACK)

    def test_a_caller_deadline_bounds_the_adapter_retries(self) -> None:
        def send() -> None:
            with request_deadline(time.monotonic() + 50):
                _through_tracked_session()

        run = _run(send, [])

        assert [t.started_at for t in run.vendor.tries] == pytest.approx([0, 40], abs=SLACK)
        assert run.elapsed == pytest.approx(50, abs=SLACK)

    def test_a_caller_deadline_bounds_the_client_retries(self) -> None:
        def send() -> None:
            with request_deadline(time.monotonic() + 50):
                _through_rest_client()

        run = _run(send, [])

        assert [t.started_at for t in run.vendor.tries] == pytest.approx([0, 41], abs=SLACK)
        assert run.elapsed == pytest.approx(50, abs=SLACK)

    @parameterized.expand(
        [
            ("tuple", (5.0, 30.0), True),
            ("number", 30.0, True),
            ("urllib3_timeout", Timeout(connect=5.0, read=30.0), True),
            ("no_timeout", NO_REQUEST_TIMEOUT, False),
            ("no_read_timeout", (5.0, None), False),
        ]
    )
    def test_a_try_has_a_total_unless_the_source_opts_out(self, _name: str, timeout: Any, has_total: bool) -> None:
        try_timeout = _deadline_timeout(timeout, time.monotonic() + 50).clone()

        assert (try_timeout.total is not None) == has_total
        if has_total:
            assert cast(float, try_timeout.total) <= 50

    @parameterized.expand(
        [
            ("tuple", (5.0, 30.0), 30.0),
            ("number", 30.0, 30.0),
            ("urllib3_timeout", Timeout(connect=5.0, read=30.0, total=60.0), 30.0),
            ("no_read_timeout", (5.0, None), None),
        ]
    )
    def test_a_source_timeout_keeps_its_shape_and_its_value(
        self, _name: str, timeout: Any, read_timeout: float | None
    ) -> None:
        def send() -> None:
            make_tracked_session().get(f"{BASE_URL}/items", timeout=timeout)

        run = _run(send, [OK])

        assert run.error is None
        assert run.vendor.tries[0].read_timeout == (
            None if read_timeout is None else pytest.approx(read_timeout, abs=SLACK)
        )


SourceRetry = Callable[..., Callable[[Callable[[], None]], Callable[[], None]]]


def _server_delay(state: RetryCallState) -> float | None:
    error = state.outcome.exception() if state.outcome is not None else None
    response = getattr(error, "response", None)
    return None if response is None else float(response.headers.get("Retry-After", 0))


def _source_loop(decorator: SourceRetry, wait: float, **options: Any) -> tuple[Send, list[float]]:
    tries: list[float] = []

    @decorator(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(5),
        wait=wait_fixed(wait),
        reraise=True,
        **options,
    )
    def fetch() -> None:
        tries.append(time.monotonic())
        _through_tracked_session()

    return fetch, tries


def _hand_written_loop(wait: float) -> tuple[Send, list[float]]:
    tries: list[float] = []

    def fetch() -> None:
        with request_deadline():
            for attempt in range(5):
                tries.append(time.monotonic())
                try:
                    _through_tracked_session()
                    return
                except requests.RequestException:
                    if attempt == 4 or not request_deadline_allows_wait(wait):
                        raise
                    time.sleep(wait)

    return fetch, tries


TOO_MANY_REQUESTS = [_status(429, 86400)] * 5
# Each source try below sends one GET. The adapter retries a stall 4 times, so a try of a plain loop
# takes the whole adapter budget of 100 s.
SOURCE_LOOP_CASES: list[tuple[str, tuple[Send, list[float]], Sequence[Answer], int, float]] = [
    ("plain_tenacity_loop_restarts_the_deadline_on_each_try", _source_loop(tenacity.retry, 0), [], 5, 500),
    ("deadline_loop_shares_one_deadline_across_tries", _source_loop(retry_with_deadline, 0), [], 1, 100),
    ("hand_written_loop_shares_one_deadline_across_tries", _hand_written_loop(0), [], 1, 100),
    # A 429 with a day of Retry-After comes back from the adapter at once. The source caps its wait to 30 s.
    ("plain_tenacity_loop_waits_out_its_capped_waits", _source_loop(tenacity.retry, 30), TOO_MANY_REQUESTS, 5, 120),
    (
        "deadline_loop_stops_before_a_wait_past_the_deadline",
        _source_loop(retry_with_deadline, 30),
        TOO_MANY_REQUESTS,
        4,
        90,
    ),
    ("hand_written_loop_stops_before_a_wait_past_the_deadline", _hand_written_loop(30), TOO_MANY_REQUESTS, 4, 90),
    (
        "deadline_loop_stops_at_once_when_the_server_delay_passes_the_deadline",
        _source_loop(retry_with_deadline, 30, requested_wait=_server_delay),
        TOO_MANY_REQUESTS,
        1,
        0,
    ),
]


class TestSourceRetryLoop:
    @parameterized.expand(SOURCE_LOOP_CASES)
    def test_source_tries_share_one_deadline_only_when_the_source_opts_in(
        self, _name: str, loop: tuple[Send, list[float]], script: Sequence[Answer], source_tries: int, elapsed: float
    ) -> None:
        send, tries = loop
        tries.clear()

        run = _run(send, script)

        assert isinstance(run.error, requests.RequestException)
        assert len(tries) == source_tries
        assert run.elapsed == pytest.approx(elapsed, abs=SLACK * source_tries)

    def test_the_deadline_starts_again_on_each_call(self) -> None:
        send, _ = _source_loop(retry_with_deadline, 0)

        def two_calls() -> None:
            with pytest.raises(requests.RequestException):
                send()
            send()

        # The first call uses its whole budget. The second call still gets a full read timeout on its first try.
        run = _run(two_calls, [STALL, STALL, STALL, OK])

        assert run.error is None
        assert run.vendor.tries[3].read_timeout == pytest.approx(READ_TIMEOUT, abs=SLACK)

    def test_tests_still_reach_the_undecorated_function_and_the_controller(self) -> None:
        calls: list[int] = []

        @retry_with_deadline(stop=stop_after_attempt(3), reraise=True)
        def fetch() -> None:
            calls.append(1)
            raise ValueError("try failed")

        with pytest.raises(ValueError):
            cast(Any, fetch).__wrapped__()

        assert len(calls) == 1
        assert isinstance(cast(Any, fetch).retry, tenacity.Retrying)

    def test_a_stop_given_to_retry_with_keeps_the_deadline(self) -> None:
        send, tries = _source_loop(retry_with_deadline, 30)
        tries.clear()

        run = _run(cast(Any, send).retry_with(stop=stop_after_attempt(10)), TOO_MANY_REQUESTS * 2)

        assert isinstance(run.error, requests.RequestException)
        assert len(tries) == 4
        assert run.elapsed == pytest.approx(90, abs=SLACK * 4)
