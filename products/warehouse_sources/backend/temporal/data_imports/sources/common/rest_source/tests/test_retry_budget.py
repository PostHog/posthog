from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import requests
from parameterized import parameterized
from requests.adapters import HTTPAdapter

from posthog.dataclasses import frozen
from posthog.temporal.common.shutdown import WorkerShuttingDownError

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.safe_point import (
    PipelineSafePointHandler,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    WAIT_SLICE_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import rest_client
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import activate_safe_point

BASE_URL = "https://api.example.com"
BUDGET = 600.0
MAX_RETRY_AFTER = 300.0


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@contextmanager
def _fake_time() -> Iterator[_Clock]:
    clock = _Clock()
    with (
        override_settings(
            DATA_WAREHOUSE_SOURCE_RETRY_BUDGET_SECONDS=BUDGET,
            DATA_WAREHOUSE_SOURCE_MAX_RETRY_AFTER_SECONDS=MAX_RETRY_AFTER,
        ),
        patch("time.sleep", side_effect=clock.sleep),
        patch.object(rest_client, "_monotonic", clock.monotonic),
    ):
        yield clock


def _response(status: int, headers: dict[str, str] | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = f"{BASE_URL}/items"
    response._content = b"[]"
    response.headers.update(headers or {})
    return response


class _Host:
    """A session whose every answer is the same failure and takes `attempt_seconds` to arrive."""

    def __init__(self, clock: _Clock, status: int, headers: dict[str, str] | None, attempt_seconds: float) -> None:
        self.headers: dict[str, str] = {}
        self.starts: list[float] = []
        self._clock = clock
        self._status = status
        self._headers = headers
        self._attempt_seconds = attempt_seconds

    def prepare_request(self, _request: requests.Request) -> MagicMock:
        return MagicMock(url=f"{BASE_URL}/items")

    def send(self, _request: Any, **_kwargs: Any) -> requests.Response:
        self.starts.append(self._clock.now)
        self._clock.now += self._attempt_seconds
        return _response(self._status, self._headers)


def _paginate(client: RESTClient) -> None:
    list(client.paginate(path="/items", paginator=SinglePagePaginator()))


class _ShutdownMonitor:
    def __init__(self) -> None:
        self.shutting_down = False

    def is_worker_shutdown(self) -> bool:
        return self.shutting_down

    def raise_if_is_worker_shutdown(self) -> None:
        if self.shutting_down:
            raise WorkerShuttingDownError("activity", "import", "queue", 1, None, None)


class TestRetryBudget:
    @parameterized.expand(
        [
            ("server_error_fails_fast", 503, None, 0.0),
            ("server_error_after_a_stalled_read", 503, None, 330.0),
            ("rate_limit_without_a_delay", 429, None, 0.0),
            ("rate_limit_with_a_delay", 429, {"Retry-After": "200"}, 0.0),
            ("rate_limit_with_the_longest_allowed_delay", 429, {"Retry-After": "300"}, 5.0),
        ]
    )
    def test_one_request_starts_no_try_after_its_budget(
        self, _name: str, status: int, headers: dict[str, str] | None, attempt_seconds: float
    ) -> None:
        with _fake_time() as clock:
            host = _Host(clock, status, headers, attempt_seconds)
            # More attempts than the budget allows, so the budget is the limit under test.
            client = RESTClient(base_url=BASE_URL, session=host, max_retry_attempts=100)  # type: ignore[arg-type]
            with pytest.raises(RESTClientRetryableError):
                _paginate(client)

        assert len(host.starts) >= 2
        assert host.starts[-1] <= BUDGET
        assert clock.now <= BUDGET + attempt_seconds

    def test_a_client_budget_replaces_the_setting(self) -> None:
        with _fake_time() as clock:
            host = _Host(clock, 429, {"Retry-After": "200"}, 0.0)
            client = RESTClient(base_url=BASE_URL, session=host, max_retry_attempts=100, retry_budget_seconds=1000.0)  # type: ignore[arg-type]
            with pytest.raises(RESTClientRetryableError):
                _paginate(client)

        assert clock.sleeps == [200.0] * 5

    @parameterized.expand(
        [
            ("retry_after_seconds", {"Retry-After": "301"}),
            ("retry_after_absurd", {"Retry-After": "100000000000"}),
            ("reset_header", {"X-RateLimit-Reset": str(int(datetime.now(UTC).timestamp()) + 10_000)}),
        ]
    )
    def test_a_delay_above_the_limit_fails_the_request_without_a_wait(
        self, _name: str, headers: dict[str, str]
    ) -> None:
        with _fake_time() as clock:
            host = _Host(clock, 429, headers, 0.0)
            with pytest.raises(RESTClientRetryableError, match="asked for a wait"):
                _paginate(RESTClient(base_url=BASE_URL, session=host))  # type: ignore[arg-type]

        assert len(host.starts) == 1
        assert clock.sleeps == []

    def test_a_client_limit_lets_a_long_window_be_waited_out(self) -> None:
        with _fake_time() as clock:
            host = _Host(clock, 429, {"Retry-After": "900"}, 0.0)
            client = RESTClient(
                base_url=BASE_URL,
                session=host,  # type: ignore[arg-type]
                max_retry_attempts=2,
                retry_after_max_seconds=960.0,
                retry_budget_seconds=1000.0,
            )
            with pytest.raises(RESTClientRetryableError):
                _paginate(client)

        assert clock.sleeps == [900.0]


class TestRetryOwnership:
    @parameterized.expand(
        [
            ("client_retries", 5, [0] * 5),
            ("client_does_not_retry", 1, [3]),
        ]
    )
    def test_only_one_layer_retries_a_request(
        self, _name: str, max_retry_attempts: int, expected_adapter_retries: list[int]
    ) -> None:
        adapter_retries: list[int | bool | None] = []

        def send(adapter: HTTPAdapter, _request: requests.PreparedRequest, **_kwargs: Any) -> requests.Response:
            adapter_retries.append(adapter.max_retries.total)
            return _response(503)

        with _fake_time(), patch.object(HTTPAdapter, "send", autospec=True, side_effect=send):
            with pytest.raises(RESTClientRetryableError):
                _paginate(RESTClient(base_url=BASE_URL, max_retry_attempts=max_retry_attempts))

        assert adapter_retries == expected_adapter_retries

    def test_a_bespoke_session_call_keeps_the_adapter_retries(self) -> None:
        adapter_retries: list[int | bool | None] = []

        def send(adapter: HTTPAdapter, _request: requests.PreparedRequest, **_kwargs: Any) -> requests.Response:
            adapter_retries.append(adapter.max_retries.total)
            return _response(200)

        with patch.object(HTTPAdapter, "send", autospec=True, side_effect=send):
            make_tracked_session().get(f"{BASE_URL}/items")

        assert adapter_retries == [3]


@frozen
class _Outcome:
    clock: _Clock
    host: _Host
    error: BaseException


class TestShutdownDuringARetryWait:
    def _run(self, *, covers_framework_checkpoints: bool, with_signal: bool) -> _Outcome:
        monitor = _ShutdownMonitor()
        manager = MagicMock()
        manager.has_staged_state.return_value = False
        handler = PipelineSafePointHandler(
            shutdown_monitor=monitor,  # type: ignore[arg-type]
            resumable_source_manager=manager,
            has_unwritten_rows=lambda: False,
        )

        with _fake_time() as clock:
            host = _Host(clock, 429, {"Retry-After": "200"}, 0.0)

            def sleep(seconds: float) -> None:
                clock.sleep(seconds)
                monitor.shutting_down = True

            with (
                patch("time.sleep", side_effect=sleep),
                activate_safe_point(
                    handler,
                    covers_framework_checkpoints=covers_framework_checkpoints,
                    is_shutting_down=monitor.is_worker_shutdown if with_signal else None,
                ),
                pytest.raises(Exception) as raised,
            ):
                _paginate(RESTClient(base_url=BASE_URL, session=host))  # type: ignore[arg-type]
        return _Outcome(clock=clock, host=host, error=raised.value)

    def test_the_run_hands_off_at_the_safe_point(self) -> None:
        outcome = self._run(covers_framework_checkpoints=True, with_signal=True)

        assert isinstance(outcome.error, WorkerShuttingDownError)
        assert outcome.clock.now == WAIT_SLICE_SECONDS
        assert len(outcome.host.starts) == 1

    def test_a_wrapped_resource_stops_waiting_but_does_not_reach_a_safe_point(self) -> None:
        outcome = self._run(covers_framework_checkpoints=False, with_signal=True)

        assert isinstance(outcome.error, RESTClientRetryableError)
        assert outcome.clock.now == WAIT_SLICE_SECONDS
        assert len(outcome.host.starts) == 5

    def test_a_run_that_cannot_hand_off_waits_the_whole_delay(self) -> None:
        outcome = self._run(covers_framework_checkpoints=False, with_signal=False)

        assert isinstance(outcome.error, RESTClientRetryableError)
        assert outcome.clock.sleeps == [200.0, 200.0, 200.0]
        assert outcome.host.starts[-1] <= BUDGET
