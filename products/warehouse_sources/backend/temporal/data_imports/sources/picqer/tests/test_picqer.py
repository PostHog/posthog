from datetime import date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.picqer import picqer
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.picqer import (
    PicqerResumeConfig,
    _base_url,
    _build_params,
    get_rows,
    normalize_account,
    to_picqer_datetime,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.settings import PAGE_SIZE, PICQER_ENDPOINTS


class TestNormalizeAccount:
    @parameterized.expand(
        [
            ("bare", "acme", "acme"),
            ("full_host", "acme.picqer.com", "acme"),
            ("https_url", "https://acme.picqer.com", "acme"),
            ("trailing_slash", "acme.picqer.com/", "acme"),
            ("with_hyphen", "acme-corp", "acme-corp"),
            ("whitespace", "  acme  ", "acme"),
        ]
    )
    def test_valid_accounts(self, _name: str, value: str, expected: str) -> None:
        assert normalize_account(value) == expected

    @parameterized.expand(
        [
            ("path_injection", "acme/../evil"),
            ("host_injection", "acme.evil.com"),
            ("userinfo_injection", "acme@evil.com"),
            ("empty", ""),
            ("space_inside", "ac me"),
            ("trailing_hyphen", "acme-"),
        ]
    )
    def test_invalid_accounts_raise(self, _name: str, value: str) -> None:
        # The account is the host the stored API key is sent to; a loosened regex would let an org
        # member retarget the credential at a server they control.
        with pytest.raises(ValueError):
            normalize_account(value)

    def test_base_url(self) -> None:
        assert _base_url("acme") == "https://acme.picqer.com/api/v1"


class TestToPicqerDatetime:
    @parameterized.expand(
        [
            ("naive_datetime", datetime(2020, 1, 2, 3, 4, 5), "2020-01-02 03:04:05"),
            ("date_value", date(2020, 1, 2), "2020-01-02 00:00:00"),
            ("iso_string", "2020-01-02T03:04:05", "2020-01-02 03:04:05"),
            ("already_spaced_string", "2020-01-02 03:04:05", "2020-01-02 03:04:05"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        # Picqer's `updated_after` filter expects `YYYY-MM-DD HH:MM:SS`; a broken format silently
        # returns wrong/empty incremental pages.
        assert to_picqer_datetime(value) == expected


class TestBuildParams:
    def test_incremental_endpoint_adds_filter(self) -> None:
        params = _build_params(
            PICQER_ENDPOINTS["purchaseorders"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2020, 1, 2, 3, 4, 5),
        )
        assert params == {"updated_after": "2020-01-02 03:04:05"}

    def test_incremental_endpoint_without_cursor_omits_filter(self) -> None:
        params = _build_params(
            PICQER_ENDPOINTS["purchaseorders"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert params == {}

    def test_full_refresh_endpoint_never_filters(self) -> None:
        # orders exposes only a creation-date filter (`sincedate`), so it syncs full refresh; a
        # cursor must never leak into the request and silently drop updated rows.
        params = _build_params(
            PICQER_ENDPOINTS["orders"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2020, 1, 2, 3, 4, 5),
        )
        assert params == {}


class _FakeResumableManager:
    def __init__(self, state: PicqerResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[PicqerResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> PicqerResumeConfig | None:
        return self._state

    def save_state(self, data: PicqerResumeConfig) -> None:
        self.saved.append(data)


def _patch_fetch(monkeypatch: Any, responses: list[Any]) -> list[dict[str, Any]]:
    """Return pages in order, recording the params (offset + any filter) of each request."""
    calls: list[dict[str, Any]] = []
    pages = iter(responses)

    def fake_fetch(session: Any, url: str, params: dict[str, Any]) -> Any:
        calls.append(params)
        return next(pages)

    monkeypatch.setattr(picqer, "_fetch_page", fake_fetch)
    monkeypatch.setattr(picqer, "_make_session", lambda api_key: MagicMock())
    return calls


def _collect(monkeypatch: Any, manager: _FakeResumableManager, **kwargs: Any) -> list[dict]:
    rows: list[dict] = []
    for batch in get_rows(
        account="acme",
        api_key="key",
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(batch)
    return rows


def _page(n: int) -> list[dict]:
    return [{"idorder": i} for i in range(n)]


class TestGetRows:
    def test_paginates_by_offset_until_short_page(self, monkeypatch: Any) -> None:
        calls = _patch_fetch(monkeypatch, [_page(PAGE_SIZE), _page(3)])
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="orders")

        assert len(rows) == PAGE_SIZE + 3
        assert [c["offset"] for c in calls] == [0, PAGE_SIZE]

    def test_stops_on_empty_first_page(self, monkeypatch: Any) -> None:
        calls = _patch_fetch(monkeypatch, [[]])
        rows = _collect(monkeypatch, _FakeResumableManager(), endpoint="orders")

        assert rows == []
        assert [c["offset"] for c in calls] == [0]

    def test_saves_next_offset_only_while_more_pages_remain(self, monkeypatch: Any) -> None:
        _patch_fetch(monkeypatch, [_page(PAGE_SIZE), _page(1)])
        manager = _FakeResumableManager()
        _collect(monkeypatch, manager, endpoint="orders")

        # State is saved after the full first page (advance to PAGE_SIZE), never after the short last page.
        assert manager.saved == [PicqerResumeConfig(offset=PAGE_SIZE)]

    def test_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        calls = _patch_fetch(monkeypatch, [_page(2)])
        rows = _collect(monkeypatch, _FakeResumableManager(PicqerResumeConfig(offset=PAGE_SIZE)), endpoint="orders")

        assert len(rows) == 2
        assert [c["offset"] for c in calls] == [PAGE_SIZE]

    def test_incremental_filter_present_on_every_page(self, monkeypatch: Any) -> None:
        calls = _patch_fetch(monkeypatch, [_page(PAGE_SIZE), _page(1)])
        _collect(
            monkeypatch,
            _FakeResumableManager(),
            endpoint="purchaseorders",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2020, 1, 2, 3, 4, 5),
        )
        # The filter must stay on the paginated request so pagination walks only the filtered set.
        assert all(c.get("updated_after") == "2020-01-02 03:04:05" for c in calls)
        assert [c["offset"] for c in calls] == [0, PAGE_SIZE]

    def test_full_refresh_endpoint_sends_no_filter(self, monkeypatch: Any) -> None:
        calls = _patch_fetch(monkeypatch, [_page(1)])
        _collect(
            monkeypatch,
            _FakeResumableManager(),
            endpoint="orders",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2020, 1, 2, 3, 4, 5),
        )
        assert "updated_after" not in calls[0]
