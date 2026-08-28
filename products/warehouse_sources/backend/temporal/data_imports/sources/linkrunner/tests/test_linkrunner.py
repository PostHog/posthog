from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.linkrunner import linkrunner
from products.warehouse_sources.backend.temporal.data_imports.sources.linkrunner.linkrunner import (
    LinkrunnerRateLimitError,
    LinkrunnerResumeConfig,
    LinkrunnerRetryableError,
    _flatten_attributed_user,
    _format_timestamp,
    _has_next_page,
    _parse_retry_after,
    get_rows,
    validate_credentials,
)


class TestFormatTimestamp:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_timestamp(self, _name: str, value: Any, expected: str) -> None:
        # A wrong timestamp shape silently breaks the server-side start_timestamp filter, so lock the ISO-8601 Z form.
        assert _format_timestamp(value) == expected

    def test_no_plus_zero_offset(self) -> None:
        assert "+00:00" not in _format_timestamp(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))


class TestHasNextPage:
    @parameterized.expand(
        [
            # (page, total_pages, num_items, limit, expected)
            ("more_pages_by_count", 1, 4, 100, 100, True),
            ("last_page_by_count", 4, 4, 100, 50, False),
            ("empty_page_always_stops", 2, 9, 0, 100, False),
            ("full_page_no_pagination_block", 1, None, 100, 100, True),
            ("partial_page_no_pagination_block", 1, None, 30, 100, False),
        ]
    )
    def test_has_next_page(
        self, _name: str, page: int, total_pages: Any, num_items: int, limit: int, expected: bool
    ) -> None:
        assert _has_next_page(page, total_pages, num_items, limit) is expected


class TestFlattenAttributedUser:
    def test_promotes_user_id_to_top_level(self) -> None:
        # user_id is part of the primary key, so it must exist as a top-level column, not stay nested.
        row = _flatten_attributed_user(
            {
                "campaign_display_id": "C1",
                "attributed_at": "2026-01-01T00:00:00Z",
                "user_data": {"id": "U1", "name": "Ada", "email": "a@b.c", "phone": "1", "device_data": {"brand": "x"}},
            }
        )
        assert row["user_id"] == "U1"
        assert row["user_name"] == "Ada"
        assert row["user_email"] == "a@b.c"
        assert row["user_phone"] == "1"
        assert row["device_data"] == {"brand": "x"}
        assert "user_data" not in row

    def test_missing_user_data_leaves_row_intact(self) -> None:
        row = _flatten_attributed_user({"campaign_display_id": "C1", "attributed_at": "t"})
        assert row == {"campaign_display_id": "C1", "attributed_at": "t"}


class TestParseRetryAfter:
    @parameterized.expand(
        [
            ("valid_seconds", {"Retry-After": "45"}, 45),
            ("missing_header_defaults_to_60", {}, 60),
            ("non_numeric_defaults_to_60", {"Retry-After": "soon"}, 60),
        ]
    )
    def test_parse_retry_after(self, _name: str, headers: dict[str, str], expected: int) -> None:
        response = requests.Response()
        response.headers.update(headers)
        assert _parse_retry_after(response) == expected


class _FakeResumableManager:
    def __init__(self, state: LinkrunnerResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[LinkrunnerResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> LinkrunnerResumeConfig | None:
        return self._state

    def save_state(self, data: LinkrunnerResumeConfig) -> None:
        self.saved.append(data)


def _body(data_key: str, items: list[dict], pages: int) -> dict:
    return {"data": {data_key: items, "pagination": {"total": len(items), "pages": pages, "page": 1, "limit": 1000}}}


def _make_fake_fetch(responses: dict, calls: list | None = None):
    def fake_fetch(session: Any, path: str, headers: dict, params: dict, logger: Any) -> Any:
        if calls is not None:
            calls.append((path, dict(params)))
        key = (path, params.get("page", 1), params.get("display_id"))
        result = responses.get(key)
        if isinstance(result, Exception):
            raise result
        return result

    return fake_fetch


def _collect(
    manager: _FakeResumableManager, endpoint: str, monkeypatch: Any, responses: dict, **kwargs: Any
) -> list[dict]:
    monkeypatch.setattr(linkrunner, "_fetch_page", _make_fake_fetch(responses))
    rows: list[dict] = []
    for table in get_rows(
        api_key="k",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(table.to_pylist())
    return rows


class TestCampaignsPagination:
    def test_follows_pages_until_last(self, monkeypatch: Any) -> None:
        responses = {
            ("/campaigns", 1, None): _body("campaigns", [{"display_id": "C1"}], pages=2),
            ("/campaigns", 2, None): _body("campaigns", [{"display_id": "C2"}], pages=2),
        }
        rows = _collect(_FakeResumableManager(), "campaigns", monkeypatch, responses)
        assert [r["display_id"] for r in rows] == ["C1", "C2"]

    def test_resume_starts_from_saved_page(self, monkeypatch: Any) -> None:
        # A resumed list sync must continue at the saved page, not restart at page 1.
        calls: list = []
        responses = {("/campaigns", 3, None): _body("campaigns", [{"display_id": "C3"}], pages=3)}
        monkeypatch.setattr(linkrunner, "_fetch_page", _make_fake_fetch(responses, calls))
        rows: list[dict] = []
        for table in get_rows(
            api_key="k",
            endpoint="campaigns",
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(LinkrunnerResumeConfig(page=3)),  # type: ignore[arg-type]
        ):
            rows.extend(table.to_pylist())
        assert [r["display_id"] for r in rows] == ["C3"]
        assert calls[0][1]["page"] == 3

    def test_204_yields_no_rows(self, monkeypatch: Any) -> None:
        responses = {("/campaigns", 1, None): None}
        rows = _collect(_FakeResumableManager(), "campaigns", monkeypatch, responses)
        assert rows == []


class TestAttributedUsersFanOut:
    def _responses_two_campaigns(self) -> dict:
        return {
            ("/campaigns", 1, None): _body("campaigns", [{"display_id": "C1"}, {"display_id": "C2"}], pages=1),
            ("/attributed-users", 1, "C1"): _body(
                "users",
                [{"campaign_display_id": "C1", "attributed_at": "t1", "user_data": {"id": "U1"}}],
                pages=1,
            ),
            ("/attributed-users", 1, "C2"): _body(
                "users",
                [{"campaign_display_id": "C2", "attributed_at": "t2", "user_data": {"id": "U2"}}],
                pages=1,
            ),
        }

    def test_fans_out_over_campaigns_and_flattens_keys(self, monkeypatch: Any) -> None:
        rows = _collect(_FakeResumableManager(), "attributed_users", monkeypatch, self._responses_two_campaigns())
        # Every row carries the parent campaign id and a top-level user_id (the composite primary key).
        assert {(r["campaign_display_id"], r["user_id"]) for r in rows} == {("C1", "U1"), ("C2", "U2")}

    def test_advances_bookmark_between_campaigns(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        _collect(manager, "attributed_users", monkeypatch, self._responses_two_campaigns())
        # After finishing C1 the bookmark must point at C2 so a crash resumes at the next campaign, not the first.
        assert LinkrunnerResumeConfig(page=1, campaign_display_id="C2") in manager.saved

    def test_resume_from_bookmark_skips_completed_campaigns(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(LinkrunnerResumeConfig(page=1, campaign_display_id="C2"))
        rows = _collect(manager, "attributed_users", monkeypatch, self._responses_two_campaigns())
        assert [r["user_id"] for r in rows] == ["U2"]

    def test_incremental_passes_start_timestamp(self, monkeypatch: Any) -> None:
        calls: list = []
        responses = {
            ("/campaigns", 1, None): _body("campaigns", [{"display_id": "C1"}], pages=1),
            ("/attributed-users", 1, "C1"): _body(
                "users", [{"campaign_display_id": "C1", "attributed_at": "t1", "user_data": {"id": "U1"}}], pages=1
            ),
        }
        monkeypatch.setattr(linkrunner, "_fetch_page", _make_fake_fetch(responses, calls))
        list(
            get_rows(
                api_key="k",
                endpoint="attributed_users",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )
        attributed_calls = [params for path, params in calls if path == "/attributed-users"]
        assert attributed_calls[0]["start_timestamp"] == "2026-03-04T02:58:14Z"


class TestFetchPage:
    def _response(self, status: int, headers: dict | None = None, body: dict | None = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status
        response.ok = 200 <= status < 300
        response.headers = headers or {}
        response.json.return_value = body or {}
        return response

    def test_204_returns_none(self) -> None:
        session = MagicMock()
        session.get.return_value = self._response(204)
        assert linkrunner._fetch_page(session, "/campaigns", {}, {}, MagicMock()) is None

    def test_429_raises_rate_limit_error_with_retry_after(self) -> None:
        session = MagicMock()
        session.get.return_value = self._response(429, headers={"Retry-After": "60"})
        with patch.object(linkrunner._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(LinkrunnerRateLimitError) as exc:
                linkrunner._fetch_page(session, "/reporting/campaigns", {}, {}, MagicMock())
        assert exc.value.retry_after == 60

    def test_retries_5xx_then_succeeds(self) -> None:
        session = MagicMock()
        session.get.side_effect = [self._response(503), self._response(200, body={"data": {}})]
        with patch.object(linkrunner._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = linkrunner._fetch_page(session, "/campaigns", {}, {}, MagicMock())
        assert result == {"data": {}}
        assert session.get.call_count == 2

    @parameterized.expand(
        [
            ("rate_limit", LinkrunnerRateLimitError(1)),
            ("retryable", LinkrunnerRetryableError("boom")),
            ("read_timeout", requests.ReadTimeout("timeout")),
        ]
    )
    def test_retryable_error_types(self, _name: str, exc: Exception) -> None:
        # These are the error types the retry decorator must keep retrying rather than fail the sync on.
        retry_types = linkrunner._fetch_page.retry.retry.exception_types  # type: ignore[attr-defined]
        assert isinstance(exc, retry_types)


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("no_content", 204, True), ("unauthorized", 401, False)])
    def test_status_maps_to_validity(self, _name: str, status: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response
        with patch.object(linkrunner, "make_tracked_session", return_value=session):
            assert validate_credentials("key") is expected

    def test_network_failure_is_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("down")
        with patch.object(linkrunner, "make_tracked_session", return_value=session):
            assert validate_credentials("key") is False
