from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.helpers import (
    HubspotRetryableError,
    _get_property_names,
    _is_retryable_status,
    fetch_data,
)


def _make_response(status: int, payload: dict[str, Any] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload or {}
    response.raise_for_status.side_effect = (
        None if 200 <= status < 300 else HTTPError(f"{status} Client Error", response=response)
    )
    return response


def _patch_session(responses: list[MagicMock]) -> tuple[Any, list[str]]:
    iter_resp = iter(responses)
    captured: list[str] = []

    def _get(url: str, headers: Any = None, params: Any = None, timeout: Any = None) -> MagicMock:  # noqa: ARG001
        captured.append(url)
        return next(iter_resp)

    session = type("_S", (), {"get": staticmethod(_get)})()
    return (
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.helpers.make_tracked_session",
            new=lambda *_a, **_k: session,
        ),
        captured,
    )


@pytest.fixture(autouse=True)
def _no_backoff_sleep() -> Any:
    # fetch_data backs off on transient errors; skip the real waits in tests.
    with patch("time.sleep"):
        yield


@pytest.mark.parametrize(
    "status,expected",
    [
        (200, False),
        (400, False),
        (401, False),
        (403, False),
        (404, False),
        (409, False),
        (422, False),
        (451, False),
        (429, True),
        (477, True),  # non-standard 4xx HubSpot's edge returns during transient incidents
        (499, True),
        (500, True),
        (502, True),
        (503, True),
    ],
)
def test_is_retryable_status(status: int, expected: bool) -> None:
    assert _is_retryable_status(status) is expected


def test_fetch_data_retries_non_standard_477_then_succeeds() -> None:
    # Regression: HubSpot's property endpoint briefly returned a non-standard 477; the discovery
    # path must back off and retry rather than crashing the whole import on an unknown code.
    good = _make_response(200, {"results": [{"id": "1", "properties": {"name": "deal_stage"}}]})
    ctx, captured = _patch_session([_make_response(477), _make_response(477), good])
    with ctx:
        pages = list(fetch_data("/crm/v3/properties/deals", "key", "refresh"))

    assert len(captured) == 3
    assert pages == [[{"name": "deal_stage", "id": "1"}]]


def test_fetch_data_reraises_retryable_after_exhausting_retries() -> None:
    ctx, captured = _patch_session([_make_response(477) for _ in range(5)])
    with ctx:
        with pytest.raises(HubspotRetryableError, match="status=477"):
            list(fetch_data("/crm/v3/properties/deals", "key", "refresh"))

    assert len(captured) == 5


def test_fetch_data_permanent_client_error_is_not_retried() -> None:
    # A genuine permanent client error (404) must surface immediately, not be retried.
    ctx, captured = _patch_session([_make_response(404)])
    with ctx:
        with pytest.raises(HTTPError):
            list(fetch_data("/crm/v3/properties/deals", "key", "refresh"))

    assert len(captured) == 1


def test_fetch_data_refreshes_token_on_401_then_succeeds() -> None:
    good = _make_response(200, {"results": [{"id": "1", "properties": {"name": "deal_stage"}}]})
    ctx, captured = _patch_session([_make_response(401), good])
    with (
        ctx,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.helpers.hubspot_refresh_access_token",
            return_value="new-token",
        ) as refresh,
    ):
        pages = list(fetch_data("/crm/v3/properties/deals", "key", "refresh"))

    refresh.assert_called_once()
    assert len(captured) == 2
    assert pages == [[{"name": "deal_stage", "id": "1"}]]


def test_get_property_names_recovers_from_transient_477() -> None:
    good = _make_response(200, {"results": [{"name": "deal_stage"}, {"name": "amount"}]})
    ctx, captured = _patch_session([_make_response(477), good])
    with ctx:
        names = _get_property_names("key", "refresh", "deal")

    assert names == ["deal_stage", "amount"]
    assert len(captured) == 2
