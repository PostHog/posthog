from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.auth import (
    MAX_RETRY_AFTER_SECONDS,
    HubspotRetryableError,
    _parse_retry_after,
    _wait_strategy,
    hubspot_refresh_access_token,
)


def _make_response(
    status: int, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None
) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload or {}
    response.headers = headers or {}
    return response


def _patch_post(response: MagicMock) -> Any:
    session = MagicMock()
    session.post.return_value = response
    return patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.auth.make_tracked_session",
        return_value=session,
    )


@pytest.fixture(autouse=True)
def _no_backoff_sleep() -> Any:
    # hubspot_refresh_access_token backs off on transient errors; skip the real waits in tests.
    with patch("time.sleep"):
        yield


@pytest.mark.parametrize(
    "status,message",
    [
        (429, "You have reached your rate limit."),
        (500, "Internal server error"),
        (502, "Bad gateway"),
        (503, "Service unavailable"),
    ],
)
def test_transient_status_raises_retryable_error(status: int, message: str) -> None:
    with _patch_post(_make_response(status, {"message": message})):
        with pytest.raises(HubspotRetryableError, match=message):
            hubspot_refresh_access_token("refresh-token")


@pytest.mark.parametrize(
    "status,message",
    [
        (400, "missing or invalid refresh token"),
        (401, "unauthorized"),
        (403, "forbidden"),
    ],
)
def test_non_transient_status_raises_plain_exception(status: int, message: str) -> None:
    with _patch_post(_make_response(status, {"message": message})):
        with pytest.raises(Exception) as exc_info:
            hubspot_refresh_access_token("refresh-token")
        assert not isinstance(exc_info.value, HubspotRetryableError)
        assert message in str(exc_info.value)


@pytest.mark.parametrize("status", [400, 403, 423])
def test_portal_migration_in_progress_is_retryable(status: int) -> None:
    # A portal mid-migration is a transient HubSpot state on a non-5xx status; it must back off
    # and retry instead of failing the sync and disabling the schema.
    message = "Migration in progress and the portal is not available for access."
    session = MagicMock()
    session.post.side_effect = [
        _make_response(status, {"message": message}),
        _make_response(status, {"message": message}),
        _make_response(200, {"access_token": "new-token"}),
    ]
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.auth.make_tracked_session",
        return_value=session,
    ):
        assert hubspot_refresh_access_token("refresh-token") == "new-token"
    assert session.post.call_count == 3


def test_transient_status_with_non_json_body_still_retryable() -> None:
    response = MagicMock()
    response.status_code = 429
    response.json.side_effect = ValueError("not json")
    response.text = "<html>rate limited</html>"
    response.headers = {}
    with _patch_post(response):
        with pytest.raises(HubspotRetryableError, match="rate limited"):
            hubspot_refresh_access_token("refresh-token")


def test_transient_status_with_message_less_body_still_retryable() -> None:
    response = MagicMock()
    response.status_code = 503
    response.json.return_value = {"error": "unavailable"}
    response.text = "service unavailable"
    with _patch_post(response):
        with pytest.raises(HubspotRetryableError, match="service unavailable"):
            hubspot_refresh_access_token("refresh-token")


def test_success_returns_access_token() -> None:
    with _patch_post(_make_response(200, {"access_token": "new-token"})):
        assert hubspot_refresh_access_token("refresh-token") == "new-token"


def test_transient_status_is_retried_then_succeeds() -> None:
    # A momentary rate limit on the token endpoint should back off and retry rather than
    # fail the whole sync; once HubSpot stops returning 429 the refresh succeeds.
    session = MagicMock()
    session.post.side_effect = [
        _make_response(429, {"message": "You have reached your rate limit."}),
        _make_response(429, {"message": "You have reached your rate limit."}),
        _make_response(200, {"access_token": "new-token"}),
    ]
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.auth.make_tracked_session",
        return_value=session,
    ):
        assert hubspot_refresh_access_token("refresh-token") == "new-token"
    assert session.post.call_count == 3


def test_transient_status_reraises_after_exhausting_retries() -> None:
    session = MagicMock()
    session.post.return_value = _make_response(429, {"message": "You have reached your rate limit."})
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.auth.make_tracked_session",
        return_value=session,
    ):
        with pytest.raises(HubspotRetryableError, match="You have reached your rate limit."):
            hubspot_refresh_access_token("refresh-token")
    assert session.post.call_count == 5


def test_non_transient_status_is_not_retried() -> None:
    # A non-transient status (e.g. invalid_grant) must surface immediately, not be retried.
    session = MagicMock()
    session.post.return_value = _make_response(400, {"message": "missing or invalid refresh token"})
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.auth.make_tracked_session",
        return_value=session,
    ):
        with pytest.raises(Exception) as exc_info:
            hubspot_refresh_access_token("refresh-token")
        assert not isinstance(exc_info.value, HubspotRetryableError)
    assert session.post.call_count == 1


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({"Retry-After": "7"}, 7.0),
        ({"Retry-After": "0"}, 0.0),
        ({"Retry-After": "-3"}, 0.0),
        ({}, None),
        ({"Retry-After": "not-a-number"}, None),
        ({"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}, None),
    ],
)
def test_parse_retry_after(headers: dict[str, str], expected: float | None) -> None:
    assert _parse_retry_after(_make_response(429, headers=headers)) == expected


def test_429_retry_after_carried_on_exception_and_capped_by_wait_strategy() -> None:
    session = MagicMock()
    session.post.return_value = _make_response(
        429,
        {"message": "You have reached your rate limit."},
        headers={"Retry-After": str(MAX_RETRY_AFTER_SECONDS + 30)},
    )
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.auth.make_tracked_session",
        return_value=session,
    ):
        with pytest.raises(HubspotRetryableError) as exc_info:
            hubspot_refresh_access_token("refresh-token")

    assert exc_info.value.retry_after == MAX_RETRY_AFTER_SECONDS + 30
    # An oversized Retry-After is clamped so a single header can't pin the activity open.
    state = MagicMock()
    state.outcome.exception.return_value = exc_info.value
    assert _wait_strategy(state) == MAX_RETRY_AFTER_SECONDS


def test_wait_strategy_falls_back_to_backoff_without_retry_after() -> None:
    state = MagicMock()
    state.outcome.exception.return_value = HubspotRetryableError("rate limited", retry_after=None)
    state.attempt_number = 1
    assert _wait_strategy(state) >= 0
