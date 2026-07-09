from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.shippo import shippo
from products.warehouse_sources.backend.temporal.data_imports.sources.shippo.settings import ENDPOINTS, SHIPPO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.shippo.shippo import (
    PAGE_SIZE,
    SHIPPO_BASE_URL,
    ShippoResumeConfig,
    ShippoRetryableError,
    check_access,
    get_rows,
    shippo_source,
    validate_credentials,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = shippo._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: ShippoResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[ShippoResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> ShippoResumeConfig | None:
        return self._state

    def save_state(self, data: ShippoResumeConfig) -> None:
        self.saved.append(data)


def _query_params(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[str, dict],
        endpoint: str = "shipments",
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[dict], list[str]]:
        requested: list[str] = []

        def fake_fetch(session: Any, url: str, logger: Any) -> dict:
            requested.append(url)
            for prefix, response in pages.items():
                if url.startswith(prefix):
                    return response
            raise AssertionError(f"Unexpected URL fetched: {url}")

        monkeypatch.setattr(shippo, "_fetch_page", fake_fetch)
        monkeypatch.setattr(shippo, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="shippo_test_key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ):
            rows.extend(batch)
        return rows, requested

    def test_full_refresh_follows_next_urls_and_saves_state_after_yield(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        page_2 = f"{SHIPPO_BASE_URL}/addresses/?page=2&results={PAGE_SIZE}"
        pages: dict[str, dict] = {
            page_2: {"next": None, "results": [{"object_id": "b"}]},
            f"{SHIPPO_BASE_URL}/addresses/?results={PAGE_SIZE}": {"next": page_2, "results": [{"object_id": "a"}]},
        }
        rows, requested = self._collect(manager, monkeypatch, pages, endpoint="addresses")

        assert rows == [{"object_id": "a"}, {"object_id": "b"}]
        assert requested[0] == f"{SHIPPO_BASE_URL}/addresses/?results={PAGE_SIZE}"
        # State points at the *next* page so a crash re-fetches only unpersisted data.
        assert [(s.next_url, s.window_start) for s in manager.saved] == [(page_2, None)]

    def test_full_refresh_resumes_from_saved_next_url(self, monkeypatch: Any) -> None:
        page_3 = f"{SHIPPO_BASE_URL}/parcels/?page=3&results={PAGE_SIZE}"
        manager = _FakeResumableManager(ShippoResumeConfig(next_url=page_3, window_start=None))
        rows, requested = self._collect(
            manager, monkeypatch, {page_3: {"next": None, "results": [{"object_id": "z"}]}}, endpoint="parcels"
        )
        assert rows == [{"object_id": "z"}]
        # The first (unfiltered) page must never be re-fetched on resume.
        assert requested == [page_3]

    def test_empty_results_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, _ = self._collect(
            manager,
            monkeypatch,
            {f"{SHIPPO_BASE_URL}/refunds/?results={PAGE_SIZE}": {"next": None, "results": []}},
            endpoint="refunds",
        )
        assert rows == []
        assert manager.saved == []

    @freeze_time("2026-07-08T12:00:00Z")
    def test_incremental_walks_creation_windows_under_90_days(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {f"{SHIPPO_BASE_URL}/shipments/": {"next": None, "results": [{"object_id": "s"}]}}
        # Watermark ~188 days before the frozen clock: needs 3 windows to reach "now".
        rows, requested = self._collect(
            manager,
            monkeypatch,
            pages,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        assert len(rows) == 3
        windows = [
            (_query_params(url)["object_created_gt"], _query_params(url)["object_created_lte"]) for url in requested
        ]
        assert windows == [
            ("2026-01-01T00:00:00Z", "2026-03-31T00:00:00Z"),
            ("2026-03-31T00:00:00Z", "2026-06-28T00:00:00Z"),
            ("2026-06-28T00:00:00Z", "2026-07-08T12:00:00Z"),
        ]
        # Windows are contiguous (gt of window N+1 == lte of window N): no gaps, no overlap.
        assert all(windows[i][1] == windows[i + 1][0] for i in range(len(windows) - 1))
        # Window completion is persisted so a crash between windows resumes from the boundary.
        completed = [s for s in manager.saved if s.next_url is None]
        assert [s.window_start for s in completed] == [
            "2026-03-31T00:00:00Z",
            "2026-06-28T00:00:00Z",
            "2026-07-08T12:00:00Z",
        ]

    @freeze_time("2026-07-08T12:00:00Z")
    def test_incremental_resumes_mid_window_then_advances(self, monkeypatch: Any) -> None:
        page_2 = f"{SHIPPO_BASE_URL}/shipments/?page=2&object_created_gt=2026-06-01T00:00:00Z"
        manager = _FakeResumableManager(ShippoResumeConfig(next_url=page_2, window_start="2026-06-01T00:00:00Z"))
        pages: dict[str, dict] = {
            page_2: {"next": None, "results": [{"object_id": "resumed"}]},
            f"{SHIPPO_BASE_URL}/shipments/?results=": {"next": None, "results": []},
        }
        rows, requested = self._collect(
            manager,
            monkeypatch,
            pages,
            should_use_incremental_field=True,
            # Stale watermark must be superseded by the resumed window position.
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        assert rows == [{"object_id": "resumed"}]
        # First request is the saved page URL, not a rebuilt window from the watermark.
        assert requested[0] == page_2
        # The rest of the run continues from the resumed window's end, not from January.
        assert all("2026-01-01" not in url for url in requested[1:])

    def test_incremental_without_watermark_falls_back_to_full_pagination(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, requested = self._collect(
            manager,
            monkeypatch,
            {f"{SHIPPO_BASE_URL}/shipments/?results={PAGE_SIZE}": {"next": None, "results": [{"object_id": "s"}]}},
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert rows == [{"object_id": "s"}]
        assert "object_created_gt" not in requested[0]

    def test_first_page_url_uses_endpoint_path(self, monkeypatch: Any) -> None:
        # The customs endpoints live under a nested path; a bare name-derived URL would 404.
        manager = _FakeResumableManager()
        _, requested = self._collect(
            manager,
            monkeypatch,
            {f"{SHIPPO_BASE_URL}/customs/items/?results={PAGE_SIZE}": {"next": None, "results": []}},
            endpoint="customs_items",
        )
        assert requested == [f"{SHIPPO_BASE_URL}/customs/items/?results={PAGE_SIZE}"]


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


class TestCheckAccess:
    @staticmethod
    def _session(response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Shippo API token"),
            ("forbidden", 403, False, "Invalid Shippo API token"),
            ("server_error", 500, False, "Shippo returned HTTP 500"),
        ]
    )
    @patch(f"{shippo.__name__}.make_tracked_session")
    def test_validate_credentials_status_mapping(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        mock_session.return_value = self._session(response)
        assert validate_credentials("shippo_test_key") == (expected_valid, expected_message)

    @patch(f"{shippo.__name__}.make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_session: MagicMock) -> None:
        mock_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access("shippo_test_key")
        assert status == 0
        assert message is not None and "boom" in message


class TestShippoSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = shippo_source(
            api_key="shippo_test_key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
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
