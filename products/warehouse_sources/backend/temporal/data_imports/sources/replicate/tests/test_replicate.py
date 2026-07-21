from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.replicate import replicate
from products.warehouse_sources.backend.temporal.data_imports.sources.replicate.replicate import (
    ReplicateResumeConfig,
    _build_initial_url,
    _extract_items,
    _format_incremental_value,
    _next_url,
    _page_predates_cutoff,
    _sanitize_next_url,
    get_rows,
    replicate_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.replicate.settings import REPLICATE_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: ReplicateResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[ReplicateResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> ReplicateResumeConfig | None:
        return self._state

    def save_state(self, data: ReplicateResumeConfig) -> None:
        self.saved.append(data)


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T00:00:00Z", "2026-03-04T00:00:00Z"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        # A +00:00 offset instead of the Z suffix would build a created_after value the API may reject.
        result = _format_incremental_value(value)
        assert result == expected
        assert "+00:00" not in result


class TestResponseShapeExtraction:
    @parameterized.expand(
        [
            (
                "paginated_results",
                "predictions",
                {"results": [{"id": "p1"}, {"id": "p2"}], "next": "https://api.replicate.com/v1/predictions?cursor=c"},
                [{"id": "p1"}, {"id": "p2"}],
                "https://api.replicate.com/v1/predictions?cursor=c",
            ),
            ("paginated_last_page", "predictions", {"results": [{"id": "p3"}], "next": None}, [{"id": "p3"}], None),
            (
                "bare_array",
                "hardware",
                [{"name": "Nvidia T4 GPU", "sku": "gpu-t4"}],
                [{"name": "Nvidia T4 GPU", "sku": "gpu-t4"}],
                None,
            ),
            (
                "single_object",
                "account",
                {"username": "acme", "type": "organization"},
                [{"username": "acme", "type": "organization"}],
                None,
            ),
        ]
    )
    def test_extract_items_and_next(
        self, _name: str, endpoint: str, payload: Any, expected_items: list[dict], expected_next: str | None
    ) -> None:
        config = REPLICATE_ENDPOINTS[endpoint]
        assert _extract_items(payload, config) == expected_items
        assert _next_url(payload) == expected_next


class TestBuildInitialUrl:
    def test_predictions_incremental_appends_created_after(self) -> None:
        url = _build_initial_url(
            REPLICATE_ENDPOINTS["predictions"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert url.startswith("https://api.replicate.com/v1/predictions?created_after=")
        assert "2026-03-04T00%3A00%3A00Z" in url

    def test_predictions_first_sync_has_no_filter(self) -> None:
        url = _build_initial_url(
            REPLICATE_ENDPOINTS["predictions"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert url == "https://api.replicate.com/v1/predictions"

    def test_trainings_never_gets_a_time_filter(self) -> None:
        # trainings exposes no server-side timestamp filter, so a created_after must never be added
        # (it would silently do nothing while implying incremental behavior).
        url = _build_initial_url(
            REPLICATE_ENDPOINTS["trainings"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert url == "https://api.replicate.com/v1/trainings"


class TestPagePredatesCutoff:
    @parameterized.expand(
        [
            ("all_older", ["2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"], True),
            ("some_newer", ["2026-01-01T00:00:00Z", "2026-05-01T00:00:00Z"], False),
            ("no_dates", [None, None], False),
        ]
    )
    def test_page_predates_cutoff(self, _name: str, timestamps: list[str | None], expected: bool) -> None:
        cutoff = datetime(2026, 3, 4, tzinfo=UTC)
        items = [{"created_at": ts} for ts in timestamps]
        assert _page_predates_cutoff(items, "created_at", cutoff) is expected


class TestSanitizeNextUrl:
    @parameterized.expand(
        [
            # The API can return an http:// next URL; following it verbatim would leak the bearer
            # token over plaintext, so it must be pinned back to the https origin.
            (
                "http_upgraded_to_https",
                "http://api.replicate.com/v1/predictions?cursor=c",
                "https://api.replicate.com/v1/predictions?cursor=c",
            ),
            (
                "https_preserved",
                "https://api.replicate.com/v1/predictions?cursor=c",
                "https://api.replicate.com/v1/predictions?cursor=c",
            ),
            # A cursor pointing at any other host is dropped rather than followed with the token.
            ("foreign_host_rejected", "https://evil.example.com/v1/predictions?cursor=c", None),
            ("none_passthrough", None, None),
        ]
    )
    def test_sanitize_next_url(self, _name: str, raw: str | None, expected: str | None) -> None:
        assert _sanitize_next_url(raw) == expected


def _collect(
    manager: _FakeResumableManager, monkeypatch: Any, pages: dict[str, Any], endpoint: str, **incremental: Any
) -> tuple[list[dict], list[str]]:
    fetched: list[str] = []

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> Any:
        fetched.append(url)
        return pages[url]

    monkeypatch.setattr(replicate, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for page in get_rows(
        api_key="r8_test",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **incremental,
    ):
        rows.extend(page)
    return rows, fetched


class TestGetRows:
    def test_paginates_following_next_urls(self, monkeypatch: Any) -> None:
        next_url = "https://api.replicate.com/v1/trainings?cursor=c2"
        pages = {
            "https://api.replicate.com/v1/trainings": {"results": [{"id": "t1"}], "next": next_url},
            next_url: {"results": [{"id": "t2"}], "next": None},
        }
        manager = _FakeResumableManager()
        rows, fetched = _collect(manager, monkeypatch, pages, "trainings")

        assert rows == [{"id": "t1"}, {"id": "t2"}]
        assert fetched == ["https://api.replicate.com/v1/trainings", next_url]
        # State is saved after yielding the first page so a crash re-yields it, not skips it.
        assert manager.saved == [ReplicateResumeConfig(next_url=next_url)]

    def test_resumes_from_saved_next_url(self, monkeypatch: Any) -> None:
        resume_url = "https://api.replicate.com/v1/trainings?cursor=resume"
        pages = {resume_url: {"results": [{"id": "t9"}], "next": None}}
        manager = _FakeResumableManager(ReplicateResumeConfig(next_url=resume_url))
        rows, fetched = _collect(manager, monkeypatch, pages, "trainings")

        assert rows == [{"id": "t9"}]
        assert fetched == [resume_url]

    def test_incremental_stops_once_a_page_predates_watermark(self, monkeypatch: Any) -> None:
        # Guards the re-walk-history cost bug: if the server drops created_after on cursor pages, the
        # desc walk must still terminate at the watermark instead of paging through all of history.
        cutoff = datetime(2026, 3, 4, tzinfo=UTC)
        initial = _build_initial_url(REPLICATE_ENDPOINTS["predictions"], True, cutoff)
        page2 = "https://api.replicate.com/v1/predictions?cursor=p2"
        page3 = "https://api.replicate.com/v1/predictions?cursor=p3"
        pages = {
            initial: {"results": [{"id": "a", "created_at": "2026-05-01T00:00:00Z"}], "next": page2},
            page2: {"results": [{"id": "b", "created_at": "2026-01-01T00:00:00Z"}], "next": page3},
            page3: {"results": [{"id": "c", "created_at": "2025-12-01T00:00:00Z"}], "next": None},
        }
        manager = _FakeResumableManager()
        rows, fetched = _collect(
            manager,
            monkeypatch,
            pages,
            "predictions",
            should_use_incremental_field=True,
            db_incremental_field_last_value=cutoff,
            incremental_field="created_at",
        )

        assert [r["id"] for r in rows] == ["a", "b"]
        assert fetched == [initial, page2]  # page3 never fetched

    def test_incremental_ignores_stale_cursor_when_watermark_advanced(self, monkeypatch: Any) -> None:
        # A cursor saved against an older watermark must not be resumed: descending pagination puts
        # predictions created since the prior run on the first page, so we rebuild the initial URL
        # for the current watermark instead of paging deeper and skipping them.
        watermark = datetime(2026, 3, 4, tzinfo=UTC)
        initial = _build_initial_url(REPLICATE_ENDPOINTS["predictions"], True, watermark)
        stale_cursor = "https://api.replicate.com/v1/predictions?cursor=stale"
        pages = {initial: {"results": [{"id": "new", "created_at": "2026-05-01T00:00:00Z"}], "next": None}}
        manager = _FakeResumableManager(
            ReplicateResumeConfig(next_url=stale_cursor, created_after="2026-01-01T00:00:00Z")
        )
        rows, fetched = _collect(
            manager,
            monkeypatch,
            pages,
            "predictions",
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
            incremental_field="created_at",
        )

        assert [r["id"] for r in rows] == ["new"]
        assert fetched == [initial]  # stale cursor never fetched

    def test_incremental_resumes_when_watermark_matches(self, monkeypatch: Any) -> None:
        # Same-watermark cursor (a crash mid-run) is safe to resume: no newer rows exist above it.
        watermark = datetime(2026, 3, 4, tzinfo=UTC)
        resume_url = "https://api.replicate.com/v1/predictions?cursor=resume"
        pages = {resume_url: {"results": [{"id": "r", "created_at": "2026-05-01T00:00:00Z"}], "next": None}}
        manager = _FakeResumableManager(
            ReplicateResumeConfig(next_url=resume_url, created_after=_format_incremental_value(watermark))
        )
        rows, fetched = _collect(
            manager,
            monkeypatch,
            pages,
            "predictions",
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
            incremental_field="created_at",
        )

        assert [r["id"] for r in rows] == ["r"]
        assert fetched == [resume_url]

    def test_single_request_endpoints_do_not_paginate(self, monkeypatch: Any) -> None:
        cases = [
            ("hardware", [{"name": "Nvidia T4 GPU", "sku": "gpu-t4"}], [{"name": "Nvidia T4 GPU", "sku": "gpu-t4"}]),
            ("account", {"username": "acme", "type": "organization"}, [{"username": "acme", "type": "organization"}]),
        ]
        for endpoint, payload, expected in cases:
            base = f"https://api.replicate.com/v1{REPLICATE_ENDPOINTS[endpoint].path}"
            manager = _FakeResumableManager()
            rows, fetched = _collect(manager, monkeypatch, {base: payload}, endpoint)

            assert rows == expected
            assert fetched == [base]
            assert manager.saved == []


class TestFetchPageRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_codes_retry_then_succeed(self, _name: str, status: int) -> None:
        bad = MagicMock(status_code=status, ok=False)
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"results": []}

        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(replicate._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = replicate._fetch_page(session, "https://api.replicate.com/v1/predictions", {}, MagicMock())

        assert result == {"results": []}
        assert session.get.call_count == 2

    def test_client_error_raises_immediately(self) -> None:
        # A 401/403 must surface (so get_non_retryable_errors can disable the source), not retry.
        response = requests.Response()
        response.status_code = 401
        response.url = "https://api.replicate.com/v1/predictions"

        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            replicate._fetch_page(session, "https://api.replicate.com/v1/predictions", {}, MagicMock())
        assert session.get.call_count == 1


class TestSourceResponse:
    @parameterized.expand(
        [
            ("predictions", ["id"], "created_at", "desc"),
            ("trainings", ["id"], "created_at", "desc"),
            ("deployments", ["owner", "name"], None, "desc"),
            ("models", ["owner", "name"], None, "desc"),
            ("hardware", ["sku"], None, "desc"),
            ("account", ["username"], None, "desc"),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, expected_pk: list[str], partition_key: str | None, sort_mode: str
    ) -> None:
        response = replicate_source(
            api_key="r8_test",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        assert response.sort_mode == sort_mode
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None
