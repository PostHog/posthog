from typing import Any

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign import boldsign
from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.boldsign import (
    BOLDSIGN_HOSTS,
    PAGE_SIZE,
    BoldSignResumeConfig,
    _base_url,
    _get_headers,
    boldsign_source,
    get_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.settings import BOLDSIGN_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: BoldSignResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[BoldSignResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> BoldSignResumeConfig | None:
        return self._state

    def save_state(self, data: BoldSignResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    manager: _FakeResumableManager, monkeypatch: Any, endpoint: str, responses: list[dict]
) -> tuple[list[dict], list[dict[str, Any]]]:
    """Run get_rows against a queue of canned API responses and flatten the yielded pages."""
    calls: list[dict[str, Any]] = []
    queue = list(responses)

    def fake_fetch(session: Any, url: str, headers: dict[str, str], params: dict[str, Any], logger: Any) -> dict:
        calls.append({"url": url, "params": dict(params)})
        return queue.pop(0)

    monkeypatch.setattr(boldsign, "_fetch_page", fake_fetch)
    monkeypatch.setattr(boldsign, "make_tracked_session", lambda *a, **k: MagicMock())

    rows: list[dict] = []
    for page in get_rows(
        region="us",
        api_key="key",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(page)
    return rows, calls


class TestBaseUrlAndHeaders:
    @pytest.mark.parametrize(
        "region, expected",
        [
            ("us", "https://api.boldsign.com"),
            ("eu", "https://api-eu.boldsign.com"),
        ],
    )
    def test_base_url_per_region(self, region: str, expected: str) -> None:
        assert _base_url(region) == expected
        assert BOLDSIGN_HOSTS[region] == expected

    def test_base_url_rejects_unknown_region(self) -> None:
        with pytest.raises(ValueError):
            _base_url("apac")

    def test_headers_use_api_key_header(self) -> None:
        headers = _get_headers("secret")
        assert headers["X-API-KEY"] == "secret"
        assert headers["Accept"] == "application/json"


class TestPagination:
    def test_non_paginated_endpoint_makes_single_request(self, monkeypatch: Any) -> None:
        responses = [{"result": [{"brandId": "B1"}, {"brandId": "B2"}]}]
        rows, calls = _collect(_FakeResumableManager(), monkeypatch, "brands", responses)
        assert rows == [{"brandId": "B1"}, {"brandId": "B2"}]
        assert len(calls) == 1
        assert "Page" not in calls[0]["params"]

    def test_short_page_terminates_pagination(self, monkeypatch: Any) -> None:
        # A page shorter than PAGE_SIZE is the last page.
        responses = [{"result": [{"documentId": "D1"}]}]
        rows, calls = _collect(_FakeResumableManager(), monkeypatch, "documents", responses)
        assert rows == [{"documentId": "D1"}]
        assert len(calls) == 1
        assert calls[0]["params"]["Page"] == 1
        assert calls[0]["params"]["PageSize"] == PAGE_SIZE

    def test_full_page_advances_to_next_page(self, monkeypatch: Any) -> None:
        full = [{"documentId": f"D{i}"} for i in range(PAGE_SIZE)]
        responses = [{"result": full}, {"result": [{"documentId": "last"}]}]
        rows, calls = _collect(_FakeResumableManager(), monkeypatch, "documents", responses)
        assert len(rows) == PAGE_SIZE + 1
        assert [c["params"]["Page"] for c in calls] == [1, 2]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        rows, calls = _collect(_FakeResumableManager(), monkeypatch, "documents", [{"result": []}])
        assert rows == []
        assert len(calls) == 1

    def test_teams_uses_results_data_key(self, monkeypatch: Any) -> None:
        responses = [{"results": [{"teamId": "T1"}]}]
        rows, _ = _collect(_FakeResumableManager(), monkeypatch, "teams", responses)
        assert rows == [{"teamId": "T1"}]

    def test_templates_send_template_type_param(self, monkeypatch: Any) -> None:
        responses = [{"result": [{"documentId": "T1"}]}]
        _, calls = _collect(_FakeResumableManager(), monkeypatch, "templates", responses)
        assert calls[0]["params"]["TemplateType"] == "all"


class TestResume:
    def test_saves_next_page_after_yielding_each_full_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        full = [{"documentId": f"D{i}"} for i in range(PAGE_SIZE)]
        responses = [{"result": full}, {"result": [{"documentId": "tail"}]}]
        _collect(manager, monkeypatch, "documents", responses)
        # Only the page that had a full page of results (page 1) saves state, pointing at page 2.
        assert [s.page for s in manager.saved] == [2]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(BoldSignResumeConfig(page=5, next_cursor=None, records_fetched=400))
        responses = [{"result": [{"documentId": "D5"}]}]
        _, calls = _collect(manager, monkeypatch, "documents", responses)
        assert calls[0]["params"]["Page"] == 5


class TestCursorPagination:
    def test_documents_switch_to_cursor_past_record_threshold(self, monkeypatch: Any) -> None:
        # Fill exactly the 10k page-cap with full pages, then expect a NextCursor request.
        boldsign_threshold_pages = boldsign.RECORD_CURSOR_THRESHOLD // PAGE_SIZE
        full_pages = [
            {"result": [{"documentId": f"D{p}-{i}", "cursor": p * PAGE_SIZE + i} for i in range(PAGE_SIZE)]}
            for p in range(boldsign_threshold_pages)
        ]
        # One more page reached via cursor, then a short page to stop.
        cursor_page = {"result": [{"documentId": "after-cursor", "cursor": 999999}]}
        responses = [*full_pages, cursor_page]

        _, calls = _collect(_FakeResumableManager(), monkeypatch, "documents", responses)

        last_call = calls[-1]
        assert "NextCursor" in last_call["params"]
        # The cursor passed is the last record's cursor from the final full page.
        expected_cursor = full_pages[-1]["result"][-1]["cursor"]
        assert last_call["params"]["NextCursor"] == expected_cursor

    def test_non_cursor_endpoint_stops_at_record_threshold(self, monkeypatch: Any) -> None:
        # users/list has no cursor support, so it must stop at the 10k page cap rather than loop.
        threshold_pages = boldsign.RECORD_CURSOR_THRESHOLD // PAGE_SIZE
        full_pages = [{"result": [{"userId": f"U{p}-{i}"} for i in range(PAGE_SIZE)]} for p in range(threshold_pages)]
        # Provide an extra page that should never be requested.
        responses = [*full_pages, {"result": [{"userId": "should-not-fetch"}]}]

        rows, calls = _collect(_FakeResumableManager(), monkeypatch, "users", responses)

        assert len(calls) == threshold_pages
        assert len(rows) == boldsign.RECORD_CURSOR_THRESHOLD


class TestSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, expected_pk",
        [
            ("documents", ["documentId"]),
            ("templates", ["documentId"]),
            ("users", ["userId"]),
            ("teams", ["teamId"]),
            ("contacts", ["id"]),
            ("sender_identities", ["id"]),
            ("brands", ["brandId"]),
        ],
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_pk: list[str]) -> None:
        response = boldsign_source(
            region="us",
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        # Full refresh: BoldSign timestamps are epoch ints, so no datetime partitioning.
        assert response.partition_mode is None
        assert response.primary_keys == BOLDSIGN_ENDPOINTS[endpoint].primary_keys
