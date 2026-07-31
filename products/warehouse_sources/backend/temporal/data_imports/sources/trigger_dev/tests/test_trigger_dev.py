from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.trigger_dev import trigger_dev
from products.warehouse_sources.backend.temporal.data_imports.sources.trigger_dev.trigger_dev import (
    TriggerDevResumeConfig,
    _format_incremental_value,
    _should_stop_desc,
    get_rows,
    resolve_base_url,
    trigger_dev_source,
    validate_base_url,
    validate_credentials,
)

BASE_URL = "https://api.trigger.dev"


class _FakeManager:
    def __init__(self, state: TriggerDevResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[TriggerDevResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> TriggerDevResumeConfig | None:
        return self._state

    def save_state(self, data: TriggerDevResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared = True


def _run_get_rows(
    monkeypatch: Any,
    endpoint: str,
    responses: list[Any],
    manager: _FakeManager | None = None,
    **kwargs: Any,
) -> tuple[list[dict], list[str], _FakeManager]:
    fetched: list[str] = []
    resp_iter = iter(responses)

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        fetched.append(url)
        result = next(resp_iter)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(trigger_dev, "_fetch_page", fake_fetch)
    monkeypatch.setattr(trigger_dev, "make_tracked_session", lambda *a, **k: MagicMock())

    manager = manager or _FakeManager()
    rows: list[dict] = []
    for page in get_rows(
        api_key="tr_prod_x",
        base_url=BASE_URL,
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(page)
    return rows, fetched, manager


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "run_1234", "run_1234"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestResolveBaseUrl:
    @parameterized.expand(
        [
            ("blank", None, "https://api.trigger.dev"),
            ("empty", "", "https://api.trigger.dev"),
            ("trailing_slash", "https://trigger.acme.internal/", "https://trigger.acme.internal"),
            ("custom", "https://trigger.acme.dev", "https://trigger.acme.dev"),
        ]
    )
    def test_resolve(self, _name: str, given: str | None, expected: str) -> None:
        assert resolve_base_url(given) == expected


class TestValidateBaseUrl:
    @parameterized.expand(
        [
            ("default", "https://api.trigger.dev"),
            ("self_hosted_https", "https://trigger.acme.dev"),
        ]
    )
    def test_https_urls_pass(self, _name: str, base_url: str) -> None:
        assert validate_base_url(base_url) is None

    @parameterized.expand(
        [
            # Plaintext would send the secret bearer token in the clear.
            ("http", "http://trigger.acme.dev"),
            # `urlsplit` reads the host as example.com, but requests connects to 169.254.169.254.
            ("backslash_authority_confusion", "https://169.254.169.254\\@example.com"),
        ]
    )
    def test_unsafe_urls_are_rejected(self, _name: str, base_url: str) -> None:
        assert validate_base_url(base_url) is not None


class TestShouldStopDesc:
    def test_no_cutoff_never_stops(self) -> None:
        # First sync has no watermark; stopping early here would truncate the initial backfill.
        items = [{"createdAt": "2020-01-01T00:00:00Z"}]
        assert _should_stop_desc(items, "createdAt", None) is False

    def test_stops_once_a_row_predates_cutoff(self) -> None:
        cutoff = datetime(2026, 1, 7, tzinfo=UTC)
        items = [{"createdAt": "2026-01-12T00:00:00Z"}, {"createdAt": "2026-01-02T00:00:00Z"}]
        assert _should_stop_desc(items, "createdAt", cutoff) is True

    def test_keeps_walking_while_page_is_newer_than_cutoff(self) -> None:
        cutoff = datetime(2026, 1, 7, tzinfo=UTC)
        items = [{"createdAt": "2026-01-12T00:00:00Z"}, {"createdAt": "2026-01-10T00:00:00Z"}]
        assert _should_stop_desc(items, "createdAt", cutoff) is False


class TestRunsCursorPagination:
    def test_first_sync_sends_no_filter_and_walks_until_cursor_exhausted(self, monkeypatch: Any) -> None:
        # No watermark => full backfill: no createdAt filter, follow pagination.next until it's null.
        responses = [
            {"data": [{"id": "r3"}, {"id": "r2"}], "pagination": {"next": "r2"}},
            {"data": [{"id": "r1"}], "pagination": {"next": None}},
        ]
        rows, fetched, _ = _run_get_rows(
            monkeypatch, "runs", responses, should_use_incremental_field=True, db_incremental_field_last_value=None
        )
        assert [r["id"] for r in rows] == ["r3", "r2", "r1"]
        assert len(fetched) == 2
        assert not any("filter" in url for url in fetched)
        assert "page%5Bafter%5D=r2" in fetched[1]

    def test_incremental_filters_first_page_then_stops_at_watermark(self, monkeypatch: Any) -> None:
        # The createdAt filter is only sent on page one; later cursor pages must stop client-side once
        # a page predates the watermark, or every incremental sync re-walks all history.
        responses = [
            {
                "data": [
                    {"id": "r3", "createdAt": "2026-01-12T00:00:00Z"},
                    {"id": "r2", "createdAt": "2026-01-11T00:00:00Z"},
                ],
                "pagination": {"next": "r2"},
            },
            {
                "data": [{"id": "r1", "createdAt": "2026-01-02T00:00:00Z"}],
                "pagination": {"next": "r0"},
            },
            # Never fetched: the walk stops after the page containing r1 (older than the cutoff).
            {"data": [{"id": "should_not_fetch"}], "pagination": {"next": None}},
        ]
        rows, fetched, _ = _run_get_rows(
            monkeypatch,
            "runs",
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 10, tzinfo=UTC),
        )
        assert [r["id"] for r in rows] == ["r3", "r2", "r1"]
        assert len(fetched) == 2
        assert "filter%5BcreatedAt%5D%5Bfrom%5D=" in fetched[0]
        assert "filter" not in fetched[1]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeManager(TriggerDevResumeConfig(after="r5"))
        responses = [{"data": [{"id": "r4"}], "pagination": {"next": None}}]
        rows, fetched, _ = _run_get_rows(monkeypatch, "runs", responses, manager=manager)
        assert [r["id"] for r in rows] == ["r4"]
        assert "page%5Bafter%5D=r5" in fetched[0]

    def test_checkpoints_current_page_cursor_after_yield(self, monkeypatch: Any) -> None:
        # Resume must re-fetch the last yielded page (checkpoint the CURRENT cursor, not the next one)
        # so a crash can't skip rows; merge dedupes the re-pulled page.
        responses = [
            {"data": [{"id": "r3"}], "pagination": {"next": "r2"}},
            {"data": [{"id": "r1"}], "pagination": {"next": None}},
        ]
        _, _, manager = _run_get_rows(monkeypatch, "runs", responses)
        assert [s.after for s in manager.saved] == [None, "r2"]

    def test_clears_checkpoint_when_walk_completes(self, monkeypatch: Any) -> None:
        # A finished walk must drop its checkpoint, or a later attempt resumes from the final page's
        # cursor and skips every run created since (runs arrive newest-first, on page one).
        responses = [{"data": [{"id": "r1"}], "pagination": {"next": None}}]
        _, _, manager = _run_get_rows(monkeypatch, "runs", responses)
        assert manager.cleared is True


class TestClassicPagination:
    def test_walks_pages_until_total_and_never_checkpoints(self, monkeypatch: Any) -> None:
        # schedules/queues are small full-refresh tables: walk page/perPage to the last page and never
        # save resume state (a restart just re-reads from page one).
        responses = [
            {"data": [{"id": "sched_1"}], "pagination": {"currentPage": 1, "totalPages": 2, "count": 2}},
            {"data": [{"id": "sched_2"}], "pagination": {"currentPage": 2, "totalPages": 2, "count": 2}},
        ]
        rows, fetched, manager = _run_get_rows(monkeypatch, "schedules", responses)
        assert [r["id"] for r in rows] == ["sched_1", "sched_2"]
        assert "page=1" in fetched[0] and "page=2" in fetched[1]
        assert manager.saved == []

    def test_stops_on_empty_page(self, monkeypatch: Any) -> None:
        responses = [{"data": [], "pagination": {"currentPage": 1, "totalPages": 5, "count": 0}}]
        rows, fetched, _ = _run_get_rows(monkeypatch, "queues", responses)
        assert rows == []
        assert len(fetched) == 1

    def test_bails_out_of_a_never_ending_pager(self, monkeypatch: Any) -> None:
        # A page endpoint that keeps returning non-empty data with no totalPages must not loop forever.
        responses = [{"data": [{"id": "q"}], "pagination": {}}] * (trigger_dev.MAX_CLASSIC_PAGES + 5)
        _, fetched, _ = _run_get_rows(monkeypatch, "queues", responses)
        assert len(fetched) == trigger_dev.MAX_CLASSIC_PAGES


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_valid: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        with patch.object(trigger_dev, "make_tracked_session", return_value=session):
            valid, error = validate_credentials("tr_prod_x", BASE_URL)
        assert valid is expected_valid
        assert (error is None) is expected_valid

    def test_network_error_is_invalid_not_raised(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(trigger_dev, "make_tracked_session", return_value=session):
            valid, error = validate_credentials("tr_prod_x", BASE_URL)
        assert valid is False
        assert error is not None


class TestFetchPageRetries:
    @parameterized.expand(
        [
            ("rate_limited", 429),
            ("server_error", 503),
        ]
    )
    def test_retryable_status_is_retried(self, _name: str, status_code: int) -> None:
        bad = MagicMock()
        bad.status_code = status_code
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"data": []}
        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(trigger_dev._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = trigger_dev._fetch_page(session, f"{BASE_URL}/api/v1/runs", {}, MagicMock())

        assert result == {"data": []}
        assert session.get.call_count == 2

    def test_unauthorized_raises_and_is_not_retried(self) -> None:
        response = MagicMock()
        response.status_code = 401
        response.ok = False
        response.raise_for_status.side_effect = requests.HTTPError("401 Client Error: Unauthorized", response=response)
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            trigger_dev._fetch_page(session, f"{BASE_URL}/api/v1/runs", {}, MagicMock())
        assert session.get.call_count == 1


class TestSourceResponseSortMode:
    @parameterized.expand([("runs", "desc"), ("schedules", "asc"), ("queues", "asc")])
    def test_sort_mode_matches_arrival_order(self, endpoint: str, expected: str) -> None:
        # Runs arrive newest-first; declaring asc there would corrupt the incremental watermark.
        response = trigger_dev_source(
            api_key="tr_prod_x",
            base_url=BASE_URL,
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.sort_mode == expected

    def test_runs_partitioned_on_created_at(self, _name: str = "") -> None:
        response = trigger_dev_source(
            api_key="tr_prod_x",
            base_url=BASE_URL,
            endpoint="runs",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.partition_keys == ["createdAt"]
        assert response.primary_keys == ["id"]
