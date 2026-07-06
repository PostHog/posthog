from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.fleetio import fleetio
from products.warehouse_sources.backend.temporal.data_imports.sources.fleetio.fleetio import (
    FLEETIO_API_VERSION,
    FleetioRateLimitError,
    FleetioResumeConfig,
    _build_base_params,
    _build_url,
    _format_incremental_value,
    _get_headers,
    _parse_retry_after,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fleetio.settings import FLEETIO_ENDPOINTS


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "some-cursor", "some-cursor"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestHeaders:
    def test_includes_both_auth_headers_and_pinned_version(self) -> None:
        headers = _get_headers("key123", "acct456")
        assert headers["Authorization"] == "Token key123"
        assert headers["Account-Token"] == "acct456"
        # The version pin is what guarantees the cursor-pagination + filter/sort contract.
        assert headers["X-Api-Version"] == FLEETIO_API_VERSION


class TestBuildUrl:
    def test_no_params_returns_base(self) -> None:
        assert _build_url("https://x/api", {}) == "https://x/api"

    def test_brackets_and_timestamp_are_encoded(self) -> None:
        url = _build_url(
            "https://x/api/vehicles",
            {"filter[updated_at][gt]": "2026-03-04T02:58:14+00:00", "per_page": 100},
        )
        # urlencode percent-encodes the brackets and the `+`/`:` in the timestamp; Rack decodes
        # them back server-side, so the encoded form is equivalent to the literal documented form.
        assert "filter%5Bupdated_at%5D%5Bgt%5D=2026-03-04T02%3A58%3A14%2B00%3A00" in url
        assert "per_page=100" in url


class TestBuildBaseParams:
    def test_full_refresh_sorts_by_partition_key_and_has_no_filter(self) -> None:
        params = _build_base_params(
            FLEETIO_ENDPOINTS["vehicles"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params == {"per_page": 100, "sort[created_at]": "asc"}

    def test_incremental_sorts_and_filters_on_chosen_field(self) -> None:
        params = _build_base_params(
            FLEETIO_ENDPOINTS["vehicles"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert params["sort[updated_at]"] == "asc"
        assert params["filter[updated_at][gt]"] == "2026-03-04T02:58:14+00:00"

    def test_incremental_first_sync_has_no_filter_value(self) -> None:
        # First incremental sync has no last value yet — sort, but don't filter (pull everything).
        params = _build_base_params(
            FLEETIO_ENDPOINTS["vehicles"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="updated_at",
        )
        assert params == {"per_page": 100, "sort[updated_at]": "asc"}

    def test_incremental_on_created_at_filters_created_at(self) -> None:
        params = _build_base_params(
            FLEETIO_ENDPOINTS["fuel_entries"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert params["sort[created_at]"] == "asc"
        assert params["filter[created_at][gt]"] == "2026-01-01T00:00:00+00:00"


class TestParseRetryAfter:
    @parameterized.expand(
        [("seconds", "30", 30.0), ("float", "1.5", 1.5), ("blank", None, None), ("garbage", "soon", None)]
    )
    def test_parse(self, _name: str, value: str | None, expected: float | None) -> None:
        assert _parse_retry_after(value) == expected


class _FakeResumableManager:
    def __init__(self, state: FleetioResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[FleetioResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> FleetioResumeConfig | None:
        return self._state

    def save_state(self, data: FleetioResumeConfig) -> None:
        self.saved.append(data)


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[str, Any],
        **kwargs: Any,
    ) -> tuple[list[dict], list[str]]:
        fetched: list[str] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            fetched.append(url)
            result = pages[url]
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(fleetio, "_fetch_page", fake_fetch)

        rows: list[dict] = []
        for table in get_rows(
            api_key="k",
            account_token="a",
            endpoint="vehicles",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **kwargs,
        ):
            rows.extend(table.to_pylist())
        return rows, fetched

    def test_paginates_until_next_cursor_is_null(self, monkeypatch: Any) -> None:
        base = "https://secure.fleetio.com/api/v1/vehicles?per_page=100&sort%5Bcreated_at%5D=asc"
        page2 = base + "&start_cursor=CUR2"
        pages = {
            base: {"records": [{"id": 1}, {"id": 2}], "next_cursor": "CUR2"},
            page2: {"records": [{"id": 3}], "next_cursor": None},
        }
        rows, fetched = self._collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert fetched == [base, page2]

    def test_resume_starts_from_saved_cursor(self, monkeypatch: Any) -> None:
        resumed = "https://secure.fleetio.com/api/v1/vehicles?per_page=100&sort%5Bcreated_at%5D=asc&start_cursor=SAVED"
        pages = {resumed: {"records": [{"id": 9}], "next_cursor": None}}
        manager = _FakeResumableManager(FleetioResumeConfig(start_cursor="SAVED"))
        rows, fetched = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": 9}]
        assert fetched == [resumed]

    def test_saves_state_after_yielding_a_batch_with_more_pages(self, monkeypatch: Any) -> None:
        # Force a yield after every row by capping the batch at one row.
        real_batcher = fleetio.Batcher
        monkeypatch.setattr(
            fleetio,
            "Batcher",
            lambda **kwargs: real_batcher(
                logger=kwargs["logger"], chunk_size=1, chunk_size_bytes=kwargs["chunk_size_bytes"]
            ),
        )
        base = "https://secure.fleetio.com/api/v1/vehicles?per_page=100&sort%5Bcreated_at%5D=asc"
        page2 = base + "&start_cursor=CUR2"
        pages = {
            base: {"records": [{"id": 1}], "next_cursor": "CUR2"},
            page2: {"records": [{"id": 2}], "next_cursor": None},
        }
        manager = _FakeResumableManager()
        self._collect(manager, monkeypatch, pages)
        # State saved with the NEXT page's cursor (so a crash re-yields, never skips), and only while
        # more pages remain — the final page (next_cursor=None) saves nothing.
        assert manager.saved == [FleetioResumeConfig(start_cursor="CUR2")]

    def test_saves_state_once_per_page_even_when_yielding_mid_page(self, monkeypatch: Any) -> None:
        # Multiple yields within a single page (chunk_size=1, two records) must save the cursor only
        # once, AFTER the whole page is batched — saving on the first mid-page yield would advance the
        # cursor past the page's remaining records and skip them on resume.
        real_batcher = fleetio.Batcher
        monkeypatch.setattr(
            fleetio,
            "Batcher",
            lambda **kwargs: real_batcher(
                logger=kwargs["logger"], chunk_size=1, chunk_size_bytes=kwargs["chunk_size_bytes"]
            ),
        )
        base = "https://secure.fleetio.com/api/v1/vehicles?per_page=100&sort%5Bcreated_at%5D=asc"
        page2 = base + "&start_cursor=CUR2"
        pages = {
            base: {"records": [{"id": 1}, {"id": 2}], "next_cursor": "CUR2"},
            page2: {"records": [{"id": 3}], "next_cursor": None},
        }
        manager = _FakeResumableManager()
        rows, _ = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert manager.saved == [FleetioResumeConfig(start_cursor="CUR2")]


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code,expected", [(200, True), (401, False), (403, False)])
    def test_status_maps_to_bool(self, status_code: int, expected: bool, monkeypatch: Any) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        monkeypatch.setattr(fleetio, "make_tracked_session", lambda *a, **k: session)
        assert validate_credentials("k", "a") is expected

    def test_network_error_is_not_valid(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        monkeypatch.setattr(fleetio, "make_tracked_session", lambda *a, **k: session)
        assert validate_credentials("k", "a") is False


class TestFetchPage:
    def _session_returning(self, status_code: int, headers: dict[str, str] | None = None, json_body: Any = None):
        response = MagicMock()
        response.status_code = status_code
        response.headers = headers or {}
        response.ok = status_code < 400
        response.json.return_value = json_body if json_body is not None else {"records": [], "next_cursor": None}
        session = MagicMock()
        session.get.return_value = response
        return session

    def test_429_raises_rate_limit_with_retry_after(self) -> None:
        # Call the undecorated body (bypassing tenacity) to assert the error carries Retry-After.
        session = self._session_returning(429, headers={"Retry-After": "12"})
        with pytest.raises(FleetioRateLimitError) as exc:
            fleetio._fetch_page.__wrapped__(session, "https://x", {}, MagicMock())  # type: ignore[attr-defined]
        assert exc.value.retry_after == 12.0

    def test_non_dict_response_is_treated_as_retryable(self) -> None:
        # A bare list means the version pin was ignored (legacy response) — fail loudly, don't truncate.
        session = self._session_returning(200, json_body=[{"id": 1}])
        with pytest.raises(fleetio.FleetioRetryableError):
            fleetio._fetch_page.__wrapped__(session, "https://x", {}, MagicMock())  # type: ignore[attr-defined]
