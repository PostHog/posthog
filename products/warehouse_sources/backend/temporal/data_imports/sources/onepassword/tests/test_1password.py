from datetime import UTC, date, datetime
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword import onepassword
from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword.onepassword import (
    OnePasswordResumeConfig,
    _initial_start_time,
    get_base_url,
    get_rows,
    introspect,
    onepassword_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword.settings import ONEPASSWORD_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: OnePasswordResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[OnePasswordResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> OnePasswordResumeConfig | None:
        return self._state

    def save_state(self, data: OnePasswordResumeConfig) -> None:
        self.saved.append(data)


def _run_get_rows(
    pages: list[dict[str, Any]],
    manager: _FakeResumableManager,
    **kwargs: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run get_rows against canned pages, returning (rows, request bodies sent)."""
    bodies: list[dict[str, Any]] = []

    def fake_fetch(session: Any, url: str, headers: dict, body: dict, logger: Any) -> dict[str, Any]:
        bodies.append(body)
        return pages[len(bodies) - 1]

    rows: list[dict[str, Any]] = []
    with patch.object(onepassword, "_fetch_page", fake_fetch):
        for batch in get_rows(
            region="us",
            api_token="token",
            endpoint="audit_events",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **kwargs,
        ):
            rows.extend(batch)
    return rows, bodies


class TestOnePasswordTransport:
    @parameterized.expand(
        [
            ("us", "https://events.1password.com"),
            ("ca", "https://events.1password.ca"),
            ("eu", "https://events.1password.eu"),
            ("enterprise", "https://events.ent.1password.com"),
        ]
    )
    def test_region_maps_to_host(self, region: str, expected: str) -> None:
        assert get_base_url(region) == expected

    def test_unknown_region_raises(self) -> None:
        # The bearer token must only ever be sent to a 1Password-owned host; an unmapped region
        # value must fail instead of building a URL from it.
        with pytest.raises(ValueError):
            get_base_url("attacker.example.com")

    @parameterized.expand(
        [
            # ResetCursor's start_time defaults to one hour ago server-side, so a first sync that
            # omitted it (or sent nothing on full refresh) would silently drop all history.
            ("first_sync_uses_default_lookback", False, None, "2025-07-15T12:00:00+00:00"),
            ("full_refresh_ignores_watermark", False, "2026-07-01T00:00:00Z", "2025-07-15T12:00:00+00:00"),
            (
                "incremental_uses_datetime_watermark",
                True,
                datetime(2026, 7, 1, tzinfo=UTC),
                "2026-07-01T00:00:00+00:00",
            ),
            ("incremental_uses_date_watermark", True, date(2026, 7, 1), "2026-07-01T00:00:00+00:00"),
            ("incremental_passes_string_watermark", True, "2026-07-01T00:00:00Z", "2026-07-01T00:00:00Z"),
        ]
    )
    def test_initial_start_time(self, _name: str, use_incremental: bool, watermark: Any, expected: str) -> None:
        with freeze_time("2026-07-15T12:00:00Z"):
            assert _initial_start_time(use_incremental, watermark) == expected

    def test_pagination_follows_cursor_until_has_more_is_false(self) -> None:
        pages = [
            {"cursor": "c1", "has_more": True, "items": [{"uuid": "a"}, {"uuid": "b"}]},
            {"cursor": "c2", "has_more": False, "items": [{"uuid": "c"}]},
        ]
        rows, bodies = _run_get_rows(pages, _FakeResumableManager())

        assert [r["uuid"] for r in rows] == ["a", "b", "c"]
        # First request is a ResetCursor; every subsequent request must carry only the cursor —
        # resending the ResetCursor would restart the stream from start_time on every page.
        assert bodies[0] == {"limit": onepassword.PAGE_LIMIT, "start_time": bodies[0]["start_time"]}
        assert bodies[1] == {"cursor": "c1"}

    def test_incremental_reset_cursor_starts_from_watermark(self) -> None:
        pages = [{"cursor": "c1", "has_more": False, "items": [{"uuid": "a"}]}]
        _, bodies = _run_get_rows(
            pages,
            _FakeResumableManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-07-01T00:00:00Z",
        )
        assert bodies[0] == {"limit": onepassword.PAGE_LIMIT, "start_time": "2026-07-01T00:00:00Z"}

    def test_state_is_saved_after_each_yielded_page(self) -> None:
        pages = [
            {"cursor": "c1", "has_more": True, "items": [{"uuid": "a"}]},
            {"cursor": "c2", "has_more": False, "items": [{"uuid": "b"}]},
        ]
        manager = _FakeResumableManager()

        def fake_fetch(session: Any, url: str, headers: dict, body: dict, logger: Any) -> dict[str, Any]:
            return pages[0] if not manager.saved else pages[1]

        with patch.object(onepassword, "_fetch_page", fake_fetch):
            batches = get_rows(
                region="us",
                api_token="token",
                endpoint="audit_events",
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
            )
            first = next(batches)
            # A crash while the pipeline holds this batch must re-enter BEFORE it (merge dedupes
            # the re-pulled rows on uuid) — saving before the yield would skip the batch entirely.
            assert first == [{"uuid": "a"}]
            assert manager.saved == []
            assert [b["uuid"] for b in next(batches)] == ["b"]
            assert next(batches, None) is None
        assert [s.cursor for s in manager.saved] == ["c1", "c2"]

    def test_resume_posts_saved_cursor_instead_of_reset_cursor(self) -> None:
        pages = [{"cursor": "c9", "has_more": False, "items": [{"uuid": "z"}]}]
        manager = _FakeResumableManager(OnePasswordResumeConfig(cursor="c8"))
        rows, bodies = _run_get_rows(pages, manager)
        # Sending a ResetCursor on resume would re-walk the stream from start_time, re-paying the
        # whole backfill after every heartbeat timeout.
        assert bodies == [{"cursor": "c8"}]
        assert [r["uuid"] for r in rows] == ["z"]

    def test_empty_page_with_stale_cursor_terminates(self) -> None:
        # Defensive guard: has_more=true with no items and a cursor that never advances would
        # otherwise loop forever against the API.
        pages = [
            {"cursor": "c1", "has_more": True, "items": [{"uuid": "a"}]},
            {"cursor": "c1", "has_more": True, "items": []},
        ]
        rows, bodies = _run_get_rows(pages, _FakeResumableManager())
        assert [r["uuid"] for r in rows] == ["a"]
        assert len(bodies) == 2

    def test_empty_page_with_advancing_cursor_continues(self) -> None:
        # An empty page whose cursor advanced is progress (the API can skip ahead); only a stale
        # cursor means stuck.
        pages = [
            {"cursor": "c1", "has_more": True, "items": []},
            {"cursor": "c2", "has_more": False, "items": [{"uuid": "a"}]},
        ]
        rows, bodies = _run_get_rows(pages, _FakeResumableManager())
        assert [r["uuid"] for r in rows] == ["a"]
        assert bodies[1] == {"cursor": "c1"}


class TestFetchRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_codes_are_retried(self, _name: str, status: int) -> None:
        bad = MagicMock(status_code=status)
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"has_more": False, "items": []}
        session = MagicMock()
        session.post.side_effect = [bad, good]

        with patch.object(onepassword._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = onepassword._fetch_page(
                session, "https://events.1password.com/api/v2/auditevents", {}, {}, MagicMock()
            )

        assert result == {"has_more": False, "items": []}
        assert session.post.call_count == 2

    def test_unauthorized_raises_without_retry(self) -> None:
        # Retrying a 401 can never succeed; it must surface immediately so the job fails with the
        # non-retryable credential message instead of burning five attempts.
        bad = requests.Response()
        bad.status_code = 401
        bad.url = "https://events.1password.com/api/v2/auditevents"
        session = MagicMock()
        session.post.return_value = bad

        with pytest.raises(requests.HTTPError):
            onepassword._fetch_page(session, "https://events.1password.com/api/v2/auditevents", {}, {}, MagicMock())
        assert session.post.call_count == 1


class TestIntrospect:
    @parameterized.expand(
        [
            ("valid", 200, {"features": ["auditevents"]}, {"features": ["auditevents"]}),
            ("unauthorized", 401, {"Error": {"Message": "Unauthorized"}}, None),
            ("server_error", 500, {}, None),
        ]
    )
    def test_status_maps_to_result(self, _name: str, status: int, payload: dict, expected: dict | None) -> None:
        response = MagicMock(status_code=status)
        response.json.return_value = payload
        session = MagicMock()
        session.get.return_value = response
        with patch.object(onepassword, "make_tracked_session", return_value=session):
            assert introspect("us", "token") == expected

    def test_network_error_returns_none(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with patch.object(onepassword, "make_tracked_session", return_value=session):
            assert introspect("us", "token") is None


class TestSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ONEPASSWORD_ENDPOINTS])
    def test_response_shape(self, endpoint: str) -> None:
        # Ordering of the cursor stream is not documented, so "desc" is required: it defers the
        # watermark to successful job end, which is safe for any arrival order. Flipping to "asc"
        # per-batch checkpointing could advance the watermark past unseen older events.
        response = onepassword_source(
            region="us",
            api_token="token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.sort_mode == "desc"
        assert response.primary_keys == ["uuid"]
        assert response.partition_keys == ["timestamp"]
        assert response.partition_mode == "datetime"
