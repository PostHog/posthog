from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shippo import ShippoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.shippo import shippo
from products.warehouse_sources.backend.temporal.data_imports.sources.shippo.settings import ENDPOINTS, SHIPPO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.shippo.shippo import (
    PAGE_SIZE,
    SHIPPO_BASE_URL,
    ShippoResumeConfig,
    ShippoRetryableError,
    ShippoUntrustedURLError,
    _validate_pagination_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shippo.source import ShippoSource

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = shippo._fetch_page.__wrapped__  # type: ignore[attr-defined]


def _driver() -> SourceDriver:
    return SourceDriver(ShippoSource(), ShippoSourceConfig(api_key="shippo_test_key"))


def _page(results: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"next": next_url, "results": results})


class TestGetRows:
    @time_machine.travel("2026-07-08T12:00:00Z", tick=False)
    def test_incremental_walks_creation_windows_under_90_days(self) -> None:
        # Watermark ~188 days before the frozen clock: needs 3 windows to reach "now".
        result = _driver().run(
            "shipments",
            always(_page([{"object_id": "s"}])),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        assert result.raised is None
        assert len(result.rows) == 3
        windows = list(zip(result.params("object_created_gt"), result.params("object_created_lte")))
        assert windows == [
            ("2026-01-01T00:00:00Z", "2026-03-31T00:00:00Z"),
            ("2026-03-31T00:00:00Z", "2026-06-28T00:00:00Z"),
            ("2026-06-28T00:00:00Z", "2026-07-08T12:00:00Z"),
        ]
        # Windows are contiguous (gt of window N+1 == lte of window N): no gaps, no overlap.
        assert all(windows[i][1] == windows[i + 1][0] for i in range(len(windows) - 1))
        # Window completion is persisted so a crash between windows resumes from the boundary.
        completed = [s for s in result.saved_states if s.next_url is None]
        assert [s.window_start for s in completed] == [
            "2026-03-31T00:00:00Z",
            "2026-06-28T00:00:00Z",
            "2026-07-08T12:00:00Z",
        ]

    @time_machine.travel("2026-07-08T12:00:00Z", tick=False)
    def test_incremental_resumes_mid_window_then_advances(self) -> None:
        page_2 = f"{SHIPPO_BASE_URL}/shipments/?page=2&object_created_gt=2026-06-01T00:00:00Z"

        def script(request: RecordedRequest) -> ScriptedResponse:
            return _page([{"object_id": "resumed"}] if request.url == page_2 else [])

        result = _driver().run(
            "shipments",
            script,
            resume_state=ShippoResumeConfig(next_url=page_2, window_start="2026-06-01T00:00:00Z"),
            should_use_incremental_field=True,
            # Stale watermark must be superseded by the resumed window position.
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        assert result.raised is None
        assert result.rows == [{"object_id": "resumed"}]
        # First request is the saved page URL, not a rebuilt window from the watermark.
        assert result.urls[0] == page_2
        # The rest of the run continues from the resumed window's end, not from January.
        assert all("2026-01-01" not in url for url in result.urls[1:])

    def test_incremental_without_watermark_falls_back_to_full_pagination(self) -> None:
        result = _driver().run(
            "shipments",
            [_page([{"object_id": "s"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert result.raised is None
        assert result.rows == [{"object_id": "s"}]
        assert result.urls == [f"{SHIPPO_BASE_URL}/shipments/?results={PAGE_SIZE}"]
        assert result.params("object_created_gt") == [None]

    def test_pagination_cap_404_ends_the_table_without_failing(self) -> None:
        # Shippo advertises a `next` link past its deepest addressable page and 404s that page.
        # Following it must finish the table, not fail the whole sync.
        capped_page = f"{SHIPPO_BASE_URL}/addresses/?page=1001&results={PAGE_SIZE}"

        result = _driver().run(
            "addresses",
            [_page([{"object_id": "a"}], capped_page), ScriptedResponse(status=404)],
        )

        assert result.raised is None
        assert result.rows == [{"object_id": "a"}]
        assert result.urls[-1] == capped_page

    @parameterized.expand([("unpaged_first_page", ""), ("explicit_first_page", "page=1&")])
    def test_404_outside_the_pagination_cap_still_fails(self, _name: str, page_param: str) -> None:
        # A 404 that is not a deep-page refusal means the endpoint itself is gone; swallowing it
        # would silently sync an empty table.
        url = f"{SHIPPO_BASE_URL}/addresses/?{page_param}results={PAGE_SIZE}"

        result = _driver().run(
            "addresses",
            [ScriptedResponse(status=404)],
            resume_state=ShippoResumeConfig(next_url=url) if page_param else None,
        )

        assert isinstance(result.raised, requests.HTTPError)
        assert result.urls == [url]


class TestValidatePaginationURL:
    def test_on_origin_url_passes_through(self) -> None:
        url = f"{SHIPPO_BASE_URL}/shipments/?page=2&results={PAGE_SIZE}"
        assert _validate_pagination_url(url) == url

    @parameterized.expand(
        [
            ("off_origin_host", "https://evil.example.com/shipments/?results=100"),
            ("look_alike_host", "https://api.goshippo.com.evil.com/shipments/"),
            ("plain_http", "http://api.goshippo.com/shipments/"),
            ("credential_in_host", "https://api.goshippo.com@evil.example.com/shipments/"),
        ]
    )
    def test_off_origin_cursor_rejected(self, _name: str, url: str) -> None:
        # A tampered `next` cursor must never redirect the token-bearing request off-origin.
        with pytest.raises(ShippoUntrustedURLError):
            _validate_pagination_url(url)


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"next": None, "results": []}
        response.text = ""
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} error", response=response) if status_code >= 400 else None
        )
        session = MagicMock()
        session.get.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(ShippoRetryableError):
            _fetch_page_unwrapped(session, f"{SHIPPO_BASE_URL}/shipments/", MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("bad_request", 400)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, f"{SHIPPO_BASE_URL}/shipments/", MagicMock())

    @parameterized.expand(
        [
            ("non_dict_body", [{"object_id": "a"}]),
            ("missing_results_key", {"next": None}),
        ]
    )
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(ShippoRetryableError):
            _fetch_page_unwrapped(session, f"{SHIPPO_BASE_URL}/shipments/", MagicMock())

    def test_success_returns_payload(self) -> None:
        body = {"next": "url", "results": [{"object_id": "a"}]}
        session = self._session_returning(200, body)
        assert _fetch_page_unwrapped(session, f"{SHIPPO_BASE_URL}/shipments/", MagicMock()) == body


class TestShippoSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, always(_page([])))
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["object_id"]
        # Shippo doesn't document list ordering, so the watermark must only commit at run end.
        assert response.sort_mode == "desc"

        partition_key = SHIPPO_ENDPOINTS[endpoint].partition_key
        if partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
        else:
            assert response.partition_mode is None

    def test_partition_keys_are_stable_creation_fields(self) -> None:
        # updated_at-style partition keys rewrite partitions on every sync.
        assert all(
            config.partition_key in (None, "object_created", "placed_at") for config in SHIPPO_ENDPOINTS.values()
        )
        # Carrier accounts carry no object_created field, so partitioning them would break the sync.
        assert SHIPPO_ENDPOINTS["carrier_accounts"].partition_key is None

    def test_only_shipments_supports_created_filter(self) -> None:
        # Shippo only honors object_created_* filters on /shipments; declaring them elsewhere
        # would make "incremental" syncs silently unfiltered.
        assert [name for name, config in SHIPPO_ENDPOINTS.items() if config.supports_created_filter] == ["shipments"]
