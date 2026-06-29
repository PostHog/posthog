from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.pylon import pylon
from products.warehouse_sources.backend.temporal.data_imports.sources.pylon.pylon import (
    PylonResumeConfig,
    _build_url,
    _format_rfc3339,
    _parse_rfc3339,
    _to_datetime,
    get_rows,
    pylon_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pylon.settings import PYLON_ENDPOINTS


def _page(items: list[dict[str, Any]], cursor: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"data": items, "request_id": "req"}
    if cursor is not None:
        body["pagination"] = {"cursor": cursor, "has_next_page": True}
    else:
        body["pagination"] = {"cursor": "", "has_next_page": False}
    return body


def _no_resume_manager() -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = False
    manager.load_state.return_value = None
    return manager


class TestFormatRfc3339:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: datetime, expected: str) -> None:
        assert _format_rfc3339(value) == expected

    def test_no_plus_offset(self) -> None:
        assert "+00:00" not in _format_rfc3339(datetime(2026, 3, 4, tzinfo=UTC))

    def test_roundtrip(self) -> None:
        dt = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)
        assert _parse_rfc3339(_format_rfc3339(dt)) == dt


class TestToDatetime:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)),
            ("naive_datetime", datetime(2026, 1, 2, 3, 4, 5), datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)),
            ("date", date(2026, 1, 2), datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC)),
            ("rfc3339_string", "2026-01-02T03:04:05Z", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)),
        ]
    )
    def test_to_datetime(self, _name: str, value: Any, expected: datetime) -> None:
        assert _to_datetime(value) == expected


class TestBuildUrl:
    def test_no_params(self) -> None:
        assert _build_url("https://api.usepylon.com/teams", {}) == "https://api.usepylon.com/teams"

    def test_encodes_params(self) -> None:
        url = _build_url("https://api.usepylon.com/issues", {"limit": 100, "cursor": "a b"})
        query = parse_qs(urlparse(url).query)
        assert query["limit"] == ["100"]
        assert query["cursor"] == ["a b"]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_validate_credentials(self, _name: str, status_code: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status_code)
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: session)
            assert pylon.validate_credentials("token") is expected

    def test_validate_credentials_handles_exception(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: session)
            assert pylon.validate_credentials("token") is False

    def test_validate_credentials_hits_me_endpoint(self) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=200)
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: session)
            pylon.validate_credentials("token")
        called_url = session.get.call_args.args[0]
        assert called_url == "https://api.usepylon.com/me"


class TestSimpleEndpointPagination:
    def test_follows_cursor_until_exhausted(self) -> None:
        pages = [_page([{"id": "1"}], cursor="c1"), _page([{"id": "2"}], cursor="c2"), _page([{"id": "3"}])]
        manager = _no_resume_manager()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: MagicMock())
            mp.setattr(pylon, "_fetch_page", MagicMock(side_effect=pages))
            batches = list(
                get_rows(api_token="t", endpoint="teams", logger=MagicMock(), resumable_source_manager=manager)
            )

        assert [row["id"] for batch in batches for row in batch] == ["1", "2", "3"]

    def test_saves_state_after_each_page_with_next_cursor(self) -> None:
        pages = [_page([{"id": "1"}], cursor="c1"), _page([{"id": "2"}])]
        manager = _no_resume_manager()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: MagicMock())
            mp.setattr(pylon, "_fetch_page", MagicMock(side_effect=pages))
            list(get_rows(api_token="t", endpoint="teams", logger=MagicMock(), resumable_source_manager=manager))

        # Only the page that has a next cursor saves state (the last page must not).
        assert manager.save_state.call_count == 1
        assert manager.save_state.call_args.args[0] == PylonResumeConfig(cursor="c1")

    def test_resumes_from_saved_cursor(self) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = PylonResumeConfig(cursor="resume-cursor")
        fetch = MagicMock(side_effect=[_page([{"id": "9"}])])

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: MagicMock())
            mp.setattr(pylon, "_fetch_page", fetch)
            list(get_rows(api_token="t", endpoint="teams", logger=MagicMock(), resumable_source_manager=manager))

        first_url = fetch.call_args_list[0].args[1]
        assert parse_qs(urlparse(first_url).query)["cursor"] == ["resume-cursor"]

    def test_stops_when_cursor_does_not_advance(self) -> None:
        # An endpoint that keeps returning the same cursor with has_next_page=true must not loop forever.
        stuck = _page([{"id": "1"}], cursor="same")
        manager = _no_resume_manager()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: MagicMock())
            mp.setattr(pylon, "_fetch_page", MagicMock(return_value=stuck))
            batches = list(
                get_rows(api_token="t", endpoint="teams", logger=MagicMock(), resumable_source_manager=manager)
            )

        # First page yielded, second fetch returns the same cursor -> stop. So at most two pages.
        assert len(batches) <= 2

    def test_accounts_sends_required_limit(self) -> None:
        manager = _no_resume_manager()
        fetch = MagicMock(side_effect=[_page([{"id": "1"}])])

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: MagicMock())
            mp.setattr(pylon, "_fetch_page", fetch)
            list(get_rows(api_token="t", endpoint="accounts", logger=MagicMock(), resumable_source_manager=manager))

        url = fetch.call_args_list[0].args[1]
        assert parse_qs(urlparse(url).query)["limit"] == ["999"]


class TestFanOutEndpoint:
    def test_fans_out_over_all_object_types_and_stamps_object_type(self) -> None:
        object_types = PYLON_ENDPOINTS["custom_fields"].fan_out_object_types or []
        # One single-page response per object type; the field omits object_type so the stamp must fill it.
        pages = [_page([{"id": f"f-{ot}"}]) for ot in object_types]
        manager = _no_resume_manager()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: MagicMock())
            mp.setattr(pylon, "_fetch_page", MagicMock(side_effect=pages))
            batches = list(
                get_rows(api_token="t", endpoint="custom_fields", logger=MagicMock(), resumable_source_manager=manager)
            )

        rows = [row for batch in batches for row in batch]
        assert {row["object_type"] for row in rows} == set(object_types)
        assert len(rows) == len(object_types)

    def test_resumes_from_saved_object_type(self) -> None:
        object_types = PYLON_ENDPOINTS["custom_fields"].fan_out_object_types or []
        resume_type = object_types[2]
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = PylonResumeConfig(object_type=resume_type)
        # Remaining object types after (and including) the resume position.
        remaining = object_types[object_types.index(resume_type) :]
        fetch = MagicMock(side_effect=[_page([{"id": "x", "object_type": ot}]) for ot in remaining])

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: MagicMock())
            mp.setattr(pylon, "_fetch_page", fetch)
            batches = list(
                get_rows(api_token="t", endpoint="custom_fields", logger=MagicMock(), resumable_source_manager=manager)
            )

        seen = [row["object_type"] for batch in batches for row in batch]
        assert seen == remaining


class TestWindowedIssues:
    @freeze_time("2026-06-23T00:00:00Z")
    def test_first_sync_walks_lookback_in_30_day_windows(self) -> None:
        manager = _no_resume_manager()
        fetch = MagicMock(return_value=_page([{"id": "i", "created_at": "2026-01-01T00:00:00Z"}]))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: MagicMock())
            mp.setattr(pylon, "_fetch_page", fetch)
            list(
                get_rows(
                    api_token="t",
                    endpoint="issues",
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=None,
                )
            )

        windows = [parse_qs(urlparse(c.args[1]).query) for c in fetch.call_args_list]
        # 365-day lookback in <=30-day windows => 13 windows.
        assert len(windows) == 13
        # First window starts a year before frozen now and the last window ends exactly at now.
        assert windows[0]["start_time"] == ["2025-06-23T00:00:00Z"]
        assert windows[-1]["end_time"] == ["2026-06-23T00:00:00Z"]
        # Each window is contiguous: a window's end is the next window's start.
        for earlier, later in zip(windows, windows[1:]):
            assert earlier["end_time"] == later["start_time"]

    @freeze_time("2026-06-23T00:00:00Z")
    def test_incremental_starts_from_watermark(self) -> None:
        manager = _no_resume_manager()
        fetch = MagicMock(return_value=_page([{"id": "i", "created_at": "2026-06-10T00:00:00Z"}]))
        watermark = datetime(2026, 6, 1, tzinfo=UTC)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: MagicMock())
            mp.setattr(pylon, "_fetch_page", fetch)
            list(
                get_rows(
                    api_token="t",
                    endpoint="issues",
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=watermark,
                )
            )

        windows = [parse_qs(urlparse(c.args[1]).query) for c in fetch.call_args_list]
        # Watermark is 22 days before now, so a single <=30-day window covers it.
        assert len(windows) == 1
        assert windows[0]["start_time"] == ["2026-06-01T00:00:00Z"]
        assert windows[0]["end_time"] == ["2026-06-23T00:00:00Z"]

    @freeze_time("2026-06-23T00:00:00Z")
    def test_future_watermark_is_a_no_op(self) -> None:
        manager = _no_resume_manager()
        fetch = MagicMock(return_value=_page([]))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: MagicMock())
            mp.setattr(pylon, "_fetch_page", fetch)
            list(
                get_rows(
                    api_token="t",
                    endpoint="issues",
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2027, 1, 1, tzinfo=UTC),
                )
            )

        assert fetch.call_count == 0

    @freeze_time("2026-06-23T00:00:00Z")
    def test_resumes_from_saved_window(self) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = PylonResumeConfig(cursor="page2", window_start="2026-06-10T00:00:00Z")
        fetch = MagicMock(return_value=_page([{"id": "i", "created_at": "2026-06-11T00:00:00Z"}]))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: MagicMock())
            mp.setattr(pylon, "_fetch_page", fetch)
            list(
                get_rows(
                    api_token="t",
                    endpoint="issues",
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2020, 1, 1, tzinfo=UTC),
                )
            )

        first = parse_qs(urlparse(fetch.call_args_list[0].args[1]).query)
        # Resume picks up at the saved window start and saved cursor, not the stale watermark.
        assert first["start_time"] == ["2026-06-10T00:00:00Z"]
        assert first["cursor"] == ["page2"]


class TestPylonSourceResponse:
    @parameterized.expand(
        [
            ("issues", ["id"], "created_at"),
            ("accounts", ["id"], "created_at"),
            ("contacts", ["id"], None),
            ("custom_fields", ["object_type", "id"], None),
            ("issue_statuses", ["slug"], None),
            ("tasks", ["id"], "created_at"),
        ]
    )
    def test_source_response_shape(self, endpoint: str, primary_keys: list[str], partition_key: str | None) -> None:
        response = pylon_source(
            api_token="t", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=_no_resume_manager()
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "asc"
        if partition_key is None:
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
