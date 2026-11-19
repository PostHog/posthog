import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import patch

from django.test import override_settings

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.retry_policy import (
    RetryableHTTPError,
    parse_retry_after,
    raise_for_retryable_status,
    raise_for_status_redacted,
    vendor_retry,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import (
    activate_safe_point,
    reach_safe_point,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.responders import (
    ScriptedResponse,
    always,
    scripted_network,
)

URL = "https://api.example.com/items?api_key=secret-key"


def _make_response(json_body: Any, status_code: int = 200) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    resp._content = json.dumps(json_body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _status(status: int, retry_after: int | None = None) -> ScriptedResponse:
    headers = {} if retry_after is None else {"Retry-After": str(retry_after)}
    return ScriptedResponse(status=status, json={}, headers=headers)


OK = ScriptedResponse(json={"ok": True})


@vendor_retry(max_retry_after=60)
def _fetch() -> Any:
    response = make_tracked_session().get(URL)
    raise_for_retryable_status(response, vendor="Example")
    raise_for_status_redacted(response)
    return response.json()


class TestVendorRetry:
    @parameterized.expand(
        [
            # Each scripted failure costs one try only, because the adapter does not retry inside the loop.
            ("one_try_per_5xx", [_status(503), _status(502), OK], 3, None),
            ("408_is_retried", [_status(408), OK], 2, None),
            ("waits_the_retry_after", [_status(429, retry_after=7), OK], 2, 7.0),
            ("connection_error", [requests.ConnectionError("reset"), OK], 2, None),
        ]
    )
    def test_retries_until_the_vendor_answers(
        self, _name: str, script: list[Any], requests_sent: int, elapsed: float | None
    ) -> None:
        with scripted_network(script) as network:
            assert _fetch() == {"ok": True}

        assert network.requests == requests_sent
        if elapsed is not None:
            assert network.elapsed == pytest.approx(elapsed, abs=0.5)

    def test_gives_up_after_the_attempts_with_a_redacted_message(self) -> None:
        with scripted_network(always(_status(503))) as network, pytest.raises(RetryableHTTPError) as raised:
            _fetch()

        assert network.requests == 5
        assert raised.value.status == 503
        assert str(raised.value) == "Example API error (retryable): HTTP 503 for https://api.example.com/items"

    def test_a_retry_after_over_the_limit_fails_at_once(self) -> None:
        with scripted_network(always(_status(429, retry_after=120))) as network, pytest.raises(RetryableHTTPError):
            _fetch()

        assert network.requests == 1
        assert network.elapsed == pytest.approx(0, abs=0.5)

    @parameterized.expand([("client_error", 404, "Client"), ("unauthorized", 401, "Client")])
    def test_a_non_retryable_status_raises_the_stock_message_without_the_query(
        self, _name: str, status: int, kind: str
    ) -> None:
        with scripted_network([_status(status)]) as network, pytest.raises(requests.HTTPError) as raised:
            _fetch()

        assert network.requests == 1
        reason = raised.value.response.reason
        assert str(raised.value) == f"{status} {kind} Error: {reason} for url: https://api.example.com/items"

    @parameterized.expand([("with_safe_point", reach_safe_point, 1), ("without_safe_point", None, 0)])
    def test_reaches_the_safe_point_before_a_retry_wait(
        self, _name: str, safe_point: Callable[[], None] | None, reached: int
    ) -> None:
        @vendor_retry(safe_point=safe_point)
        def fetch() -> Any:
            response = make_tracked_session().get(URL)
            raise_for_retryable_status(response, vendor="Example")
            return response.json()

        hooks: list[str] = []
        with (
            scripted_network([_status(503), OK]),
            activate_safe_point(lambda: hooks.append("reached"), covers_framework_checkpoints=False),
        ):
            assert fetch() == {"ok": True}

        assert len(hooks) == reached

    def test_refuses_a_generator_function(self) -> None:
        with pytest.raises(TypeError):

            @vendor_retry()
            def pages() -> Any:
                yield 1


class TestParseRetryAfter:
    @parameterized.expand(
        [
            ("rfc3339_utc", "2026-03-06T12:00:45Z", 45.0),
            ("rfc3339_offset", "2026-03-06T12:01:00+00:00", 60.0),
            # The header says when the bucket is full again, which can be an hour away while the
            # next request is already allowed, so a far reset waits the longest honored delay.
            ("far_future", "2026-03-06T13:00:00Z", 300.0),
            # A window that has already cleared, or a value we can't read, tells us nothing — the
            # caller falls back to exponential backoff rather than retrying with no delay at all.
            ("already_elapsed", "2026-03-06T11:59:55Z", None),
            ("unparseable", "in a bit", None),
        ]
    )
    @override_settings(DATA_WAREHOUSE_SOURCE_MAX_RETRY_AFTER_SECONDS=300.0)
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.common.http.retry_policy.datetime")
    def test_parse_retry_after_honors_anthropic_rate_limit_reset(
        self, _name: str, header_value: str, expected: float | None, mock_datetime
    ) -> None:
        # Anthropic rate limits its Admin API per organization but answers 429 without a
        # ``Retry-After``; this RFC 3339 reset instant is the only delay it advertises, and without
        # it a rate-limited report sync spends its whole attempt budget inside a few seconds.
        mock_datetime.now.return_value = datetime(2026, 3, 6, 12, 0, 0, tzinfo=UTC)
        mock_datetime.fromisoformat = datetime.fromisoformat

        response = _make_response({"error": "rate limited"}, status_code=429)
        response.headers["anthropic-ratelimit-requests-reset"] = header_value

        assert parse_retry_after(response) == expected

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.common.http.retry_policy.datetime")
    def test_parse_retry_after_honors_x_rate_limit_reset(self, mock_datetime) -> None:
        # X answers 429 with a UNIX epoch reset and no ``Retry-After``. Its windows run 15 minutes,
        # so without this the exponential fallback burns the attempt budget inside one window.
        now = datetime(2026, 3, 6, 12, 0, 0, tzinfo=UTC)
        mock_datetime.now.return_value = now

        response = _make_response({"title": "Too Many Requests"}, status_code=429)
        response.headers["x-rate-limit-reset"] = str(int(now.timestamp()) + 120)

        assert parse_retry_after(response) == 120

    @parameterized.expand(
        [
            ("epoch_milliseconds", 1_772_798_430_000, 30.0),
            ("epoch_seconds", 1_772_798_430, 30.0),
            ("elapsed_epoch_milliseconds", 1_772_798_390_000, None),
            ("plain_delay", 45, 45.0),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.common.http.retry_policy.datetime")
    def test_parse_retry_after_reads_a_reset_instant_in_retry_after(
        self, _name: str, header_value: int, expected: float | None, mock_datetime
    ) -> None:
        mock_datetime.now.return_value = datetime(2026, 3, 6, 12, 0, 0, tzinfo=UTC)

        response = _make_response({"error": "rate limited"}, status_code=429)
        response.headers["Retry-After"] = str(header_value)

        assert parse_retry_after(response) == expected

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.common.http.retry_policy.datetime")
    def test_parse_retry_after_ignores_already_elapsed_sentry_reset(self, mock_datetime) -> None:
        now = datetime(2026, 3, 6, 12, 0, 0, tzinfo=UTC)
        mock_datetime.now.return_value = now

        response = _make_response({"error": "rate limited"}, status_code=429)
        response.headers["X-Sentry-Rate-Limit-Reset"] = str(int(now.timestamp()) - 5)

        assert parse_retry_after(response) is None
