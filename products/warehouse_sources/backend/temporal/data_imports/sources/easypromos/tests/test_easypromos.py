from typing import Any

from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.easypromos import easypromos
from products.warehouse_sources.backend.temporal.data_imports.sources.easypromos.easypromos import (
    EASYPROMOS_BASE_URL,
    EasypromosResumeConfig,
    _next_cursor,
    easypromos_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.easypromos.settings import EASYPROMOS_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: EasypromosResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[EasypromosResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> EasypromosResumeConfig | None:
        return self._state

    def save_state(self, data: EasypromosResumeConfig) -> None:
        self.saved.append(data)


def _page(items: list[dict], next_cursor: int | None) -> dict:
    return {"items": items, "paging": {"next_cursor": next_cursor, "items_page": 100}}


def _install_fake_fetch(monkeypatch: Any, pages: dict[tuple[str, int | None], dict]) -> list[tuple[str, int | None]]:
    """Patch `_fetch_page` to serve canned pages keyed by (url, next_cursor request param)."""
    fetched: list[tuple[str, int | None]] = []

    def fake_fetch(session: Any, url: str, params: dict[str, Any], headers: dict[str, str], logger: Any) -> dict:
        key = (url, params.get("next_cursor"))
        fetched.append(key)
        return pages[key]

    monkeypatch.setattr(easypromos, "_fetch_page", fake_fetch)
    return fetched


def _collect(endpoint: str, manager: _FakeResumableManager, monkeypatch: Any) -> list[dict]:
    rows: list[dict] = []
    for table in get_rows(
        access_token="tok",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(table.to_pylist())
    return rows


class TestNextCursor:
    @parameterized.expand(
        [
            ("has_next", {"items": [], "paging": {"next_cursor": 42, "items_page": 100}}, 42),
            ("null_next", {"items": [], "paging": {"next_cursor": None, "items_page": 100}}, None),
            ("no_paging", {"items": []}, None),
            ("paging_not_dict", {"items": [], "paging": None}, None),
        ]
    )
    def test_next_cursor(self, _name: str, data: dict, expected: int | None) -> None:
        assert _next_cursor(data) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden_plan", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.return_value = response
        with patch.object(easypromos, "make_tracked_session", return_value=session):
            ok, error = validate_credentials("tok")
        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_request_exception_is_invalid(self) -> None:
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(easypromos, "make_tracked_session", return_value=session):
            ok, error = validate_credentials("tok")
        assert ok is False
        assert error is not None


class TestTopLevelPagination:
    def test_follows_cursor_until_null(self, monkeypatch: Any) -> None:
        url = f"{EASYPROMOS_BASE_URL}/promotions"
        pages = {
            (url, None): _page([{"id": 1}, {"id": 2}], 100),
            (url, 100): _page([{"id": 3}], None),
        }
        _install_fake_fetch(monkeypatch, pages)
        rows = _collect("promotions", _FakeResumableManager(), monkeypatch)
        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]

    def test_does_not_inject_promotion_id_for_top_level(self, monkeypatch: Any) -> None:
        url = f"{EASYPROMOS_BASE_URL}/organizing_brands"
        pages: dict[tuple[str, int | None], dict] = {(url, None): _page([{"id": 7, "name": "Acme"}], None)}
        _install_fake_fetch(monkeypatch, pages)
        rows = _collect("organizing_brands", _FakeResumableManager(), monkeypatch)
        assert rows == [{"id": 7, "name": "Acme"}]
        assert "promotion_id" not in rows[0]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        url = f"{EASYPROMOS_BASE_URL}/promotions"
        # Only the resumed page is served; if the loop started at the first page this would KeyError.
        pages: dict[tuple[str, int | None], dict] = {(url, 100): _page([{"id": 3}], None)}
        fetched = _install_fake_fetch(monkeypatch, pages)
        rows = _collect("promotions", _FakeResumableManager(EasypromosResumeConfig(cursor=100)), monkeypatch)
        assert rows == [{"id": 3}]
        assert fetched == [(url, 100)]

    def test_saves_current_page_cursor_after_yield(self, monkeypatch: Any) -> None:
        # Force a yield per row so we can observe the checkpoint cursor.
        monkeypatch.setattr(
            easypromos,
            "Batcher",
            lambda **kw: Batcher(logger=kw["logger"], chunk_size=1, chunk_size_bytes=kw["chunk_size_bytes"]),
        )
        url = f"{EASYPROMOS_BASE_URL}/promotions"
        pages = {
            (url, None): _page([{"id": 1}], 100),
            (url, 100): _page([{"id": 2}], None),
        }
        _install_fake_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()
        _collect("promotions", manager, monkeypatch)
        # Checkpoints record the cursor that fetched the page being processed (None then 100).
        assert [s.cursor for s in manager.saved] == [None, 100]


class TestFanOut:
    def _promotions_url(self) -> str:
        return f"{EASYPROMOS_BASE_URL}/promotions"

    def test_fans_out_over_promotions_and_injects_promotion_id(self, monkeypatch: Any) -> None:
        promos_url = self._promotions_url()
        pages: dict[tuple[str, int | None], dict] = {
            (promos_url, None): _page([{"id": 10}, {"id": 20}], None),
            (f"{EASYPROMOS_BASE_URL}/users/10", None): _page([{"id": 1}, {"id": 2}], None),
            (f"{EASYPROMOS_BASE_URL}/users/20", None): _page([{"id": 1}], None),
        }
        _install_fake_fetch(monkeypatch, pages)
        rows = _collect("users", _FakeResumableManager(), monkeypatch)
        assert rows == [
            {"id": 1, "promotion_id": 10},
            {"id": 2, "promotion_id": 10},
            {"id": 1, "promotion_id": 20},
        ]

    def test_follows_child_pagination(self, monkeypatch: Any) -> None:
        promos_url = self._promotions_url()
        pages = {
            (promos_url, None): _page([{"id": 10}], None),
            (f"{EASYPROMOS_BASE_URL}/participations/10", None): _page([{"id": 1}], 5),
            (f"{EASYPROMOS_BASE_URL}/participations/10", 5): _page([{"id": 2}], None),
        }
        _install_fake_fetch(monkeypatch, pages)
        rows = _collect("participations", _FakeResumableManager(), monkeypatch)
        assert rows == [{"id": 1, "promotion_id": 10}, {"id": 2, "promotion_id": 10}]

    def test_resume_skips_completed_promotions_and_uses_child_cursor(self, monkeypatch: Any) -> None:
        promos_url = self._promotions_url()
        # Saved state: mid-way through promotion 20, child cursor 5. Promotion 10 must be skipped and
        # promotion 20's children must resume at cursor 5 (the un-served cursor None pages would KeyError).
        pages = {
            (promos_url, None): _page([{"id": 10}, {"id": 20}, {"id": 30}], None),
            (f"{EASYPROMOS_BASE_URL}/users/20", 5): _page([{"id": 9}], None),
            (f"{EASYPROMOS_BASE_URL}/users/30", None): _page([{"id": 1}], None),
        }
        _install_fake_fetch(monkeypatch, pages)
        manager = _FakeResumableManager(EasypromosResumeConfig(cursor=None, promotion_id=20, child_cursor=5))
        rows = _collect("users", manager, monkeypatch)
        assert rows == [{"id": 9, "promotion_id": 20}, {"id": 1, "promotion_id": 30}]

    def test_checkpoint_records_promotion_and_child_cursor(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            easypromos,
            "Batcher",
            lambda **kw: Batcher(logger=kw["logger"], chunk_size=1, chunk_size_bytes=kw["chunk_size_bytes"]),
        )
        promos_url = self._promotions_url()
        pages: dict[tuple[str, int | None], dict] = {
            (promos_url, None): _page([{"id": 10}], None),
            (f"{EASYPROMOS_BASE_URL}/prizes/10", None): _page([{"id": 1}], None),
        }
        _install_fake_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()
        _collect("prizes", manager, monkeypatch)
        assert manager.saved == [EasypromosResumeConfig(cursor=None, promotion_id=10, child_cursor=None)]


class TestSourceResponse:
    @parameterized.expand(list(EASYPROMOS_ENDPOINTS.keys()))
    def test_primary_keys_and_partitioning_match_settings(self, endpoint: str) -> None:
        config = EASYPROMOS_ENDPOINTS[endpoint]
        response = easypromos_source(
            access_token="tok",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_fan_out_children_carry_promotion_id_in_primary_key(self) -> None:
        for endpoint, config in EASYPROMOS_ENDPOINTS.items():
            if config.fan_out_over_promotions:
                assert "promotion_id" in config.primary_keys, endpoint
