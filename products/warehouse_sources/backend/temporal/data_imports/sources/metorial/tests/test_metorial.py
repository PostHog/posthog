from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.metorial import metorial
from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.metorial import (
    MetorialResumeConfig,
    _build_params,
    _format_incremental_value,
    get_rows,
    metorial_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.settings import METORIAL_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: MetorialResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[MetorialResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> MetorialResumeConfig | None:
        return self._state

    def save_state(self, data: MetorialResumeConfig) -> None:
        self.saved.append(data)


def _collect(manager: _FakeResumableManager, monkeypatch: Any, endpoint: str, pages: list[dict], **incremental: Any):
    calls: list[dict] = []

    def fake_fetch(session: Any, path: str, params: dict, headers: dict, logger: Any) -> dict:
        calls.append(dict(params))
        return pages[len(calls) - 1]

    monkeypatch.setattr(metorial, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for batch in get_rows(
        api_key="metorial_sk_x",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **incremental,
    ):
        rows.extend(batch)
    return rows, calls


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "ses_cursor", "ses_cursor"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        # The server filter rejects a +00:00 offset; the watermark must serialize with a Z suffix.
        result = _format_incremental_value(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildParams:
    def test_incremental_endpoint_builds_gt_filter_for_chosen_field(self) -> None:
        # Dropping or misnaming this filter turns every "incremental" sync into a full refresh.
        params = _build_params(
            METORIAL_ENDPOINTS["sessions"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert params["updated_at[gt]"] == "2026-03-04T02:58:14.000Z"
        assert params["order"] == "asc"

    def test_honors_user_incremental_field_over_default(self) -> None:
        # sessions default is updated_at; the user picking created_at must be respected.
        params = _build_params(
            METORIAL_ENDPOINTS["sessions"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert "created_at[gt]" in params
        assert "updated_at[gt]" not in params

    def test_first_sync_has_no_filter(self) -> None:
        # No watermark yet: sending an empty gt filter would 400 (or silently sync nothing).
        params = _build_params(
            METORIAL_ENDPOINTS["sessions"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="updated_at",
        )
        assert not any(k.endswith("[gt]") for k in params)

    def test_full_refresh_endpoint_never_filters(self) -> None:
        # providers exposes no server-side timestamp filter; it must not fabricate one.
        params = _build_params(
            METORIAL_ENDPOINTS["providers"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert not any(k.endswith("[gt]") for k in params)


class TestPagination:
    def test_follows_cursor_until_has_more_after_false(self, monkeypatch: Any) -> None:
        pages = [
            {"items": [{"id": "tcl_1"}, {"id": "tcl_2"}], "pagination": {"has_more_after": True}},
            {"items": [{"id": "tcl_3"}], "pagination": {"has_more_after": False}},
        ]
        rows, calls = _collect(_FakeResumableManager(), monkeypatch, "tool_calls", pages)
        assert [r["id"] for r in rows] == ["tcl_1", "tcl_2", "tcl_3"]
        # Page one carries no cursor; page two pages from the last id of page one.
        assert "after" not in calls[0]
        assert calls[1]["after"] == "tcl_2"

    def test_stops_on_empty_first_page(self, monkeypatch: Any) -> None:
        pages = [{"items": [], "pagination": {"has_more_after": False}}]
        rows, calls = _collect(_FakeResumableManager(), monkeypatch, "tool_calls", pages)
        assert rows == []
        assert len(calls) == 1

    def test_drops_sensitive_fields_on_sessions(self, monkeypatch: Any) -> None:
        # A live client_secret must never be persisted to the warehouse.
        pages = [
            {"items": [{"id": "ses_1", "client_secret": "metorial_fk_x"}], "pagination": {"has_more_after": False}}
        ]
        rows, _ = _collect(_FakeResumableManager(), monkeypatch, "sessions", pages)
        assert rows == [{"id": "ses_1"}]


class TestResume:
    def test_saves_next_cursor_after_each_page(self, monkeypatch: Any) -> None:
        # Saving after (not before) yielding means a crash re-fetches the page rather than skipping it.
        pages = [
            {"items": [{"id": "prn_1"}], "pagination": {"has_more_after": True}},
            {"items": [{"id": "prn_2"}], "pagination": {"has_more_after": False}},
        ]
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, "provider_runs", pages)
        # Only the page that had a successor persists a cursor; the terminal page does not.
        assert [s.after for s in manager.saved] == ["prn_1"]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        # A resumed run must continue from the persisted cursor, not restart the whole stream.
        pages = [{"items": [{"id": "prn_9"}], "pagination": {"has_more_after": False}}]
        manager = _FakeResumableManager(MetorialResumeConfig(after="prn_8"))
        rows, calls = _collect(manager, monkeypatch, "provider_runs", pages)
        assert calls[0]["after"] == "prn_8"
        assert [r["id"] for r in rows] == ["prn_9"]


class TestSourceResponse:
    @parameterized.expand(
        [
            # Pagination is by record id (order=asc). `updated_at` is not monotonic in id order, so
            # those syncs must run "desc" (the pipeline then commits the watermark only after a full
            # run). An "asc" claim here lets an interrupted sync advance the watermark past rows it
            # hasn't fetched, silently losing them from the warehouse.
            ("sessions_default_updated_at", "sessions", None, "desc"),
            ("provider_runs_default_updated_at", "provider_runs", None, "desc"),
            ("provider_deployments_default_updated_at", "provider_deployments", None, "desc"),
            # A user overriding sessions onto created_at makes per-batch checkpointing safe again.
            ("sessions_user_picks_created_at", "sessions", "created_at", "asc"),
            # created_at tracks id order, so append-only streams checkpoint safely per batch.
            ("session_messages_created_at", "session_messages", None, "asc"),
            ("tool_calls_created_at", "tool_calls", None, "asc"),
            # Full-refresh-only endpoint has no incremental field.
            ("providers_full_refresh", "providers", None, "asc"),
        ]
    )
    def test_sort_mode_matches_incremental_field(
        self, _name: str, endpoint: str, incremental_field: str | None, expected_sort_mode: str
    ) -> None:
        response = metorial_source(
            api_key="metorial_sk_x",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
            incremental_field=incremental_field,
        )
        assert response.sort_mode == expected_sort_mode
        assert response.primary_keys == ["id"]
        # Partition key must be the stable created_at, never updated_at (partitions would rewrite each sync).
        assert response.partition_keys == ["created_at"]


class TestFetchPageRetries:
    @parameterized.expand(
        [
            ("rate_limited", 429),
            ("server_error", 503),
        ]
    )
    def test_retryable_status_codes_retry(self, _name: str, status: int) -> None:
        # 429/5xx are transient: back off and retry rather than failing the sync.
        bad = MagicMock(status_code=status, ok=False)
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"items": []}
        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(metorial._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = metorial._fetch_page(session, "/sessions", {}, {}, MagicMock())

        assert result == {"items": []}
        assert session.get.call_count == 2

    def test_client_error_is_not_retried(self) -> None:
        # A 401 can never be fixed by retrying; it must surface immediately as an HTTPError.
        resp = requests.Response()
        resp.status_code = 401
        resp.url = "https://api.metorial.com/sessions"
        session = MagicMock()
        session.get.return_value = resp

        with pytest.raises(requests.HTTPError):
            metorial._fetch_page(session, "/sessions", {}, {}, MagicMock())
        assert session.get.call_count == 1

    def test_client_error_scrubs_query_string_and_keeps_non_retryable_prefix(self) -> None:
        # The incremental watermark/cursor ride in the query string and the body can echo synced
        # session content; neither may reach the rebuilt HTTPError (surfaced as the schema's
        # latest_error outside warehouse ACLs). The status + host prefix stays stable so
        # get_non_retryable_errors() still matches.
        resp = requests.Response()
        resp.status_code = 401
        resp.reason = "Unauthorized"
        resp.url = "https://api.metorial.com/sessions?updated_at%5Bgt%5D=2026-03-04T00%3A00%3A00.000Z&after=ses_secret"
        resp._content = b'{"error":"leaked session content and secrets"}'
        session = MagicMock()
        session.get.return_value = resp

        with pytest.raises(requests.HTTPError) as exc:
            metorial._fetch_page(session, "/sessions", {}, {}, MagicMock())
        assert str(exc.value) == "401 Client Error: Unauthorized for url: https://api.metorial.com/sessions"
