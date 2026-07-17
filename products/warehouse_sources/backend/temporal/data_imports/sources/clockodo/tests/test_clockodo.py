from datetime import UTC, datetime
from typing import Any

from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo import clockodo
from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.clockodo import (
    EXTERNAL_APPLICATION_NAME,
    ClockodoResumeConfig,
    _build_headers,
    _endpoint_params,
    _format_z,
    clockodo_source,
    get_rows,
    validate_credentials,
)


def _row_count(tables: list[pa.Table]) -> int:
    return sum(t.num_rows for t in tables)


def _ids(tables: list[pa.Table]) -> list[Any]:
    ids: list[Any] = []
    for t in tables:
        ids.extend(t.column("id").to_pylist())
    return ids


class TestHeaders:
    def test_includes_mandatory_external_application_header(self) -> None:
        headers = _build_headers("me@example.com", "key123")
        assert headers["X-ClockodoApiUser"] == "me@example.com"
        assert headers["X-ClockodoApiKey"] == "key123"
        # The API rejects every request without this identification header.
        assert headers["X-Clockodo-External-Application"] == f"{EXTERNAL_APPLICATION_NAME};me@example.com"


class TestFormatZ:
    @parameterized.expand(
        [
            ("utc", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("with_micros_truncated", datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45Z"),
        ]
    )
    def test_format_z(self, _name: str, value: datetime, expected: str) -> None:
        assert _format_z(value) == expected


class TestEndpointParams:
    @freeze_time("2026-06-29T12:00:00Z")
    def test_entries_requires_time_window(self) -> None:
        params = _endpoint_params("entries")
        # Listing entries without a time range is rejected by the API.
        assert params["time_since"] == "2000-01-01T00:00:00Z"
        # time_until is pushed a year past now to also capture planned (future) entries.
        assert params["time_until"] == "2027-06-29T12:00:00Z"

    @parameterized.expand([("customers",), ("projects",), ("services",), ("users",)])
    def test_non_entries_have_no_time_window(self, endpoint: str) -> None:
        params = _endpoint_params(endpoint)
        assert "time_since" not in params
        assert "time_until" not in params


# Force a 1-row chunk so every row yields a table — exercises the resume save path.
def _patch_small_batcher() -> Any:
    def _factory(*_args: Any, logger: Any = None, **_kwargs: Any) -> Batcher:
        return Batcher(logger=logger or MagicMock(), chunk_size=1, chunk_size_bytes=10**12)

    return patch.object(clockodo, "Batcher", side_effect=_factory)


class TestGetRows:
    def test_paginated_walks_all_pages_and_saves_state(self) -> None:
        pages = {
            1: {"paging": {"count_pages": 2}, "customers": [{"id": 1}, {"id": 2}]},
            2: {"paging": {"count_pages": 2}, "customers": [{"id": 3}]},
        }
        seen_pages: list[int] = []

        def fake_fetch(_session: Any, _url: str, _headers: Any, params: dict, _logger: Any) -> dict:
            seen_pages.append(params["page"])
            return pages[params["page"]]

        manager = MagicMock()
        manager.can_resume.return_value = False

        with (
            patch.object(clockodo, "make_tracked_session", return_value=MagicMock()),
            patch.object(clockodo, "_fetch_page", side_effect=fake_fetch),
            _patch_small_batcher(),
        ):
            tables = list(get_rows("u", "k", "customers", MagicMock(), manager))

        assert seen_pages == [1, 2]
        assert _ids(tables) == [1, 2, 3]
        # State is saved once per page, pointing at the oldest unflushed page (the page being
        # processed here, since every row yields), so a crash re-fetches it rather than skipping its tail.
        saved = [c.args[0].next_page for c in manager.save_state.call_args_list]
        assert saved == [1, 2]

    def test_paginated_saves_state_per_page_even_without_a_yield(self) -> None:
        # Realistic batcher: pages are far under the chunk threshold, so nothing yields mid-walk.
        # State must still be saved once per page (pointing at page 1, the oldest unflushed page)
        # so a crash resumes near where it stopped rather than always from page 1.
        pages = {
            1: {"paging": {"count_pages": 2}, "customers": [{"id": 1}, {"id": 2}]},
            2: {"paging": {"count_pages": 2}, "customers": [{"id": 3}]},
        }

        def fake_fetch(_session: Any, _url: str, _headers: Any, params: dict, _logger: Any) -> dict:
            return pages[params["page"]]

        manager = MagicMock()
        manager.can_resume.return_value = False

        with (
            patch.object(clockodo, "make_tracked_session", return_value=MagicMock()),
            patch.object(clockodo, "_fetch_page", side_effect=fake_fetch),
        ):
            tables = list(get_rows("u", "k", "customers", MagicMock(), manager))

        assert _ids(tables) == [1, 2, 3]
        saved = [c.args[0].next_page for c in manager.save_state.call_args_list]
        assert saved == [1, 1]

    def test_resumes_from_saved_page(self) -> None:
        pages = {2: {"paging": {"count_pages": 2}, "customers": [{"id": 3}]}}
        seen_pages: list[int] = []

        def fake_fetch(_session: Any, _url: str, _headers: Any, params: dict, _logger: Any) -> dict:
            seen_pages.append(params["page"])
            return pages[params["page"]]

        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = ClockodoResumeConfig(next_page=2)

        with (
            patch.object(clockodo, "make_tracked_session", return_value=MagicMock()),
            patch.object(clockodo, "_fetch_page", side_effect=fake_fetch),
            _patch_small_batcher(),
        ):
            tables = list(get_rows("u", "k", "customers", MagicMock(), manager))

        # Picks up at the saved page rather than restarting at page 1.
        assert seen_pages == [2]
        assert _ids(tables) == [3]

    def test_non_paginated_single_fetch(self) -> None:
        seen_params: list[dict] = []

        def fake_fetch(_session: Any, _url: str, _headers: Any, params: dict, _logger: Any) -> dict:
            seen_params.append(dict(params))
            return {"services": [{"id": 1}, {"id": 2}]}

        manager = MagicMock()
        manager.can_resume.return_value = False

        with (
            patch.object(clockodo, "make_tracked_session", return_value=MagicMock()),
            patch.object(clockodo, "_fetch_page", side_effect=fake_fetch),
            _patch_small_batcher(),
        ):
            tables = list(get_rows("u", "k", "services", MagicMock(), manager))

        assert len(seen_params) == 1
        # Non-paginated endpoints never send a page param.
        assert "page" not in seen_params[0]
        assert _ids(tables) == [1, 2]
        manager.save_state.assert_not_called()

    def test_empty_response_yields_nothing(self) -> None:
        def fake_fetch(_session: Any, _url: str, _headers: Any, params: dict, _logger: Any) -> dict:
            return {"paging": {"count_pages": 1}, "customers": []}

        manager = MagicMock()
        manager.can_resume.return_value = False

        with (
            patch.object(clockodo, "make_tracked_session", return_value=MagicMock()),
            patch.object(clockodo, "_fetch_page", side_effect=fake_fetch),
            _patch_small_batcher(),
        ):
            tables = list(get_rows("u", "k", "customers", MagicMock(), manager))

        assert _row_count(tables) == 0


class TestClockodoSourceResponse:
    @parameterized.expand([("customers",), ("entries",), ("users",)])
    def test_primary_keys_default_to_id(self, endpoint: str) -> None:
        response = clockodo_source("u", "k", endpoint, MagicMock(), MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_validate_credentials_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status)
        with patch.object(clockodo, "make_tracked_session", return_value=session):
            assert validate_credentials("u", "k") is expected

    def test_validate_credentials_swallows_transport_errors(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with patch.object(clockodo, "make_tracked_session", return_value=session):
            assert validate_credentials("u", "k") is False
