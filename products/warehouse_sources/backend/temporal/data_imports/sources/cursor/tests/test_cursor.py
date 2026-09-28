import base64
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from tenacity import wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.cursor import cursor
from products.warehouse_sources.backend.temporal.data_imports.sources.cursor.cursor import (
    CursorResumeConfig,
    _build_windows,
    _extract_rows,
    _has_next_page,
    _make_iso_normalizer,
    _normalize_daily_usage,
    _normalize_usage_event,
    _page_item_count,
    _to_iso_date,
    _usage_event_id,
    cursor_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cursor.settings import CURSOR_ENDPOINTS

DAY_MS = 24 * 60 * 60 * 1000
WINDOW_MS = cursor.MAX_WINDOW_DAYS * DAY_MS


@pytest.fixture(autouse=True)
def _instant_retries():
    fetch: Any = cursor._fetch  # the tenacity wrapper's `retry` attribute isn't in the Callable type
    original_wait = fetch.retry.wait
    fetch.retry.wait = wait_none()
    yield
    fetch.retry.wait = original_wait


def _response(status_code: int = 200, json_data: dict | None = None) -> requests.Response:
    response = mock.Mock(spec=requests.Response)
    response.status_code = status_code
    response.ok = status_code < 400
    response.text = ""
    response.json.return_value = json_data or {}
    typed = cast(requests.Response, response)
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} Client Error: Error for url: {cursor.CURSOR_BASE_URL}/x", response=typed
        )
    return typed


def _manager(resume_state: CursorResumeConfig | None = None) -> mock.Mock:
    manager = mock.Mock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _batches(source: SourceResponse) -> Iterator[list[dict[str, Any]]]:
    return iter(cast(Iterable[list[dict[str, Any]]], source.items()))


class TestCursorTransport:
    @parameterized.expand(
        [
            (10, 1),  # under one window
            (30, 1),  # exactly one window
            (31, 2),
            (90, 3),
        ]
    )
    def test_build_windows_chunks_to_max_window(self, start_offset_days, expected_windows):
        end_ms = 1_700_000_000_000
        start_ms = end_ms - start_offset_days * DAY_MS + 1

        windows = list(_build_windows(start_ms, end_ms))

        assert len(windows) == expected_windows
        assert windows[0].start_ms == start_ms
        assert windows[-1].end_ms == end_ms
        for previous, following in zip(windows, windows[1:]):
            assert following.start_ms == previous.end_ms + 1  # inclusive bounds — no gap, no overlap
        assert all(window.end_ms - window.start_ms < WINDOW_MS for window in windows)

    def test_usage_event_id_is_deterministic_and_distinct(self):
        event = {"timestamp": "1700000000000", "userEmail": "a@b.com", "model": "gpt-5"}

        assert _usage_event_id(dict(event)) == _usage_event_id({k: event[k] for k in reversed(list(event))})
        assert _usage_event_id(event) != _usage_event_id({**event, "model": "other"})

    def test_normalize_usage_event_adds_id_and_parses_timestamp(self):
        item = _normalize_usage_event({"timestamp": "1700000000000", "userEmail": "a@b.com"})

        assert item["timestamp"] == datetime.fromtimestamp(1_700_000_000, tz=UTC)
        assert isinstance(item["id"], str) and len(item["id"]) == 64

    def test_normalize_daily_usage_parses_date(self):
        item = _normalize_daily_usage({"date": 1_700_000_000_000, "userId": 1})

        assert item["date"] == datetime.fromtimestamp(1_700_000_000, tz=UTC)

    @parameterized.expand(
        [
            ({"pagination": {"hasNextPage": True}}, 1, 100, True),
            ({"pagination": {"hasNextPage": False}}, 1, 100, False),
            ({"pagination": {"numPages": 3}}, 2, 100, True),
            ({"pagination": {"numPages": 3}}, 3, 100, False),
            ({"pagination": {"totalPages": 2}}, 1, 100, True),
            ({"totalPages": 2}, 1, 100, True),  # /teams/spend keeps totalPages at the top level
            ({"totalPages": 2}, 2, 100, False),
            ({"totalCount": 250}, 1, 100, True),  # /analytics/ai-code/commits reports a row total
            ({"totalCount": 250}, 3, 100, False),
            ({}, 1, 100, True),  # no pagination info — full page implies more
            ({}, 1, 50, False),  # partial page implies done
        ]
    )
    def test_has_next_page_across_response_shapes(self, data, page, items_count, expected):
        assert _has_next_page(data, page, items_count, 100) is expected

    @parameterized.expand(
        [
            (200, (True, None)),
            (401, (False, cursor.KEY_REJECTED_MESSAGE)),
            (403, (False, cursor.KEY_FORBIDDEN_MESSAGE)),
            # A Cursor-side failure leaves the key unjudged, so it must not be blamed on the key.
            (500, (False, cursor.PROBE_FAILED_MESSAGE)),
        ]
    )
    def test_validate_credentials_maps_status(self, status_code, expected):
        session = mock.Mock()
        session.get.return_value = _response(status_code)

        with mock.patch.object(cursor, "make_tracked_session", return_value=session):
            assert validate_credentials("key_test") == expected

    def test_validate_credentials_does_not_blame_the_key_when_cursor_is_unreachable(self):
        session = mock.Mock()
        session.get.side_effect = requests.ConnectionError("boom")

        with mock.patch.object(cursor, "make_tracked_session", return_value=session):
            assert validate_credentials("key_test") == (False, cursor.PROBE_FAILED_MESSAGE)

    def test_session_masks_credentials_and_sends_basic_auth(self):
        # The tracked transport logs and samples requests; without redaction the raw key and the
        # derived Basic token would leak into HTTP telemetry.
        expected_token = base64.b64encode(b"key_test:").decode("ascii")

        with mock.patch.object(cursor, "make_tracked_session") as make_session:
            cursor._make_session("key_test")

        kwargs = make_session.call_args.kwargs
        assert kwargs["headers"]["Authorization"] == f"Basic {expected_token}"
        assert "key_test" in kwargs["redact_values"]
        assert expected_token in kwargs["redact_values"]
        assert kwargs["allow_redirects"] is False

    @parameterized.expand([(429,), (500,), (503,)])
    def test_fetch_retries_transient_errors(self, status_code):
        session = mock.Mock()
        session.request.side_effect = [_response(status_code), _response(200, {"ok": True})]

        result = cursor._fetch(session, "POST", "https://api.cursor.com/teams/spend", mock.Mock())

        assert result == {"ok": True}
        assert session.request.call_count == 2

    def test_fetch_raises_on_client_error_without_retry(self):
        session = mock.Mock()
        session.request.return_value = _response(401)

        with pytest.raises(requests.HTTPError):
            cursor._fetch(session, "GET", "https://api.cursor.com/teams/members", mock.Mock())

        assert session.request.call_count == 1

    def test_unknown_endpoint_raises(self):
        with pytest.raises(ValueError, match="Unknown Cursor endpoint"):
            cursor_source("key_test", "audit_logs", mock.Mock(), _manager())

    @parameterized.expand(
        [
            ("members", ["id"], None),
            ("daily_usage", ["date", "userId"], ["date"]),
            ("usage_events", ["id"], ["timestamp"]),
            ("spend", ["userId"], None),
        ]
    )
    def test_source_response_shape(self, endpoint, primary_keys, partition_keys):
        response = cursor_source("key_test", endpoint, mock.Mock(), _manager())

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == partition_keys
        assert response.sort_mode == "asc"

    def test_members_yields_single_batch_via_get(self):
        session = mock.Mock()
        session.request.return_value = _response(200, {"teamMembers": [{"id": 1, "email": "a@b.com", "role": "owner"}]})

        with mock.patch.object(cursor, "make_tracked_session", return_value=session):
            batches = list(_batches(cursor_source("key_test", "members", mock.Mock(), _manager())))

        assert batches == [[{"id": 1, "email": "a@b.com", "role": "owner"}]]
        assert session.request.call_args.args[0] == "GET"
        assert session.request.call_args.args[1].endswith("/teams/members")

    def test_spend_paginates_and_stamps_cycle_start(self):
        manager = _manager()
        page_one = {
            "teamMemberSpend": [{"userId": i} for i in range(100)],
            "subscriptionCycleStart": 1_700_000_000_000,
            "totalPages": 2,
        }
        page_two = {
            "teamMemberSpend": [{"userId": 100}],
            "subscriptionCycleStart": 1_700_000_000_000,
            "totalPages": 2,
        }
        session = mock.Mock()
        session.request.side_effect = [_response(200, page_one), _response(200, page_two)]

        with mock.patch.object(cursor, "make_tracked_session", return_value=session):
            batches = list(_batches(cursor_source("key_test", "spend", mock.Mock(), manager)))

        assert [len(batch) for batch in batches] == [100, 1]
        assert all(row["subscriptionCycleStart"] == 1_700_000_000_000 for batch in batches for row in batch)
        assert session.request.call_args_list[0].kwargs["json"]["page"] == 1
        assert session.request.call_args_list[1].kwargs["json"]["page"] == 2
        # State was saved after the non-final page so a retry resumes at page 2.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].page == 2

    def test_spend_resumes_from_saved_page(self):
        manager = _manager(CursorResumeConfig(page=3))
        session = mock.Mock()
        session.request.return_value = _response(200, {"teamMemberSpend": [{"userId": 7}], "totalPages": 3})

        with mock.patch.object(cursor, "make_tracked_session", return_value=session):
            batches = list(_batches(cursor_source("key_test", "spend", mock.Mock(), manager)))

        assert len(batches) == 1
        assert session.request.call_args.kwargs["json"]["page"] == 3

    def test_iso_normalizer_parses_dates_and_timestamps(self):
        normalize = _make_iso_normalizer("commitTs", "createdAt", "event_date")

        item = normalize({"commitTs": "2025-07-30T14:12:03.000Z", "createdAt": None, "event_date": "2025-01-15"})

        assert item["commitTs"] == datetime(2025, 7, 30, 14, 12, 3, tzinfo=UTC)
        assert item["createdAt"] is None
        assert item["event_date"] == datetime(2025, 1, 15, tzinfo=UTC)

    def test_by_user_rows_carry_the_user_identity(self):
        data = {
            "data": {
                "alice@example.com": [{"event_date": "2025-01-15", "total_accepts": 3}],
                "bob@example.com": [{"event_date": "2025-01-15", "total_accepts": 1}],
            },
            "params": {"userMappings": [{"id": "user_abc", "email": "alice@example.com"}]},
        }

        rows = _extract_rows(CURSOR_ENDPOINTS["by_user_tabs"], data)

        assert rows == [
            {
                "event_date": "2025-01-15",
                "total_accepts": 3,
                "userEmail": "alice@example.com",
                "userId": "user_abc",
            },
            # A user missing from the mappings still keeps the email the primary key is built on.
            {"event_date": "2025-01-15", "total_accepts": 1, "userEmail": "bob@example.com", "userId": None},
        ]

    def test_by_user_models_expands_the_per_model_map_into_rows(self):
        # Left nested, the map's keys are model names, so the column set would change whenever the
        # team starts using a model it has not used before.
        data = {
            "data": {
                "alice@example.com": [
                    {"date": "2025-01-15", "model_breakdown": {"claude-sonnet-4.5": {"messages": 85, "users": 1}}}
                ]
            }
        }

        rows = _extract_rows(CURSOR_ENDPOINTS["by_user_models"], data)

        assert rows == [
            {
                "date": "2025-01-15",
                "userEmail": "alice@example.com",
                "userId": None,
                "model": "claude-sonnet-4.5",
                "messages": 85,
                "users": 1,
            }
        ]

    def test_team_models_expands_the_per_model_map_into_rows(self):
        # The team endpoint returns the same per-model map, but arrives as a plain list rather
        # than the per-user object, so it takes the other branch of the row extractor.
        data = {"data": [{"date": "2025-01-15", "model_breakdown": {"gpt-4o": {"messages": 450, "users": 15}}}]}

        rows = _extract_rows(CURSOR_ENDPOINTS["models"], data)

        assert rows == [{"date": "2025-01-15", "model": "gpt-4o", "messages": 450, "users": 15}]

    def test_every_windowed_endpoint_has_a_normalizer(self):
        # A windowed endpoint with no normalizer raises only once a sync reaches it, so an
        # endpoint added without one ships broken.
        missing = [
            name
            for name, config in CURSOR_ENDPOINTS.items()
            if config.windowed and name not in cursor._WINDOWED_NORMALIZERS
        ]

        assert missing == []

    def test_by_user_pagination_walks_past_a_page_where_nobody_was_active(self):
        # Pages are sized in users, so a page of users who did nothing in the window yields no
        # rows. Treating that as the end of the data would drop every later user.
        now_ms = 1_700_000_000_000
        session = mock.Mock()
        session.request.side_effect = [
            _response(200, {"data": {"idle@example.com": []}, "pagination": {"hasNextPage": True}}),
            _response(
                200,
                {
                    "data": {"alice@example.com": [{"event_date": "2023-11-14", "total_accepts": 2}]},
                    "pagination": {"hasNextPage": False},
                },
            ),
        ]

        with (
            mock.patch.object(cursor, "_now_ms", return_value=now_ms),
            mock.patch.object(cursor, "make_tracked_session", return_value=session),
        ):
            batches = list(
                _batches(
                    cursor_source(
                        "key_test",
                        "by_user_tabs",
                        mock.Mock(),
                        _manager(),
                        should_use_incremental_field=True,
                        db_incremental_field_last_value=datetime.fromtimestamp((now_ms - DAY_MS) / 1000, tz=UTC),
                    )
                )
            )

        assert session.request.call_count == 2
        assert [row["userEmail"] for batch in batches for row in batch] == ["alice@example.com"]

    @parameterized.expand(
        [
            # A by-user page holds `pageSize` users, so 200 rows spread over 100 users is 100 items.
            ("by_user_tabs", {"data": {f"u{i}@example.com": [{}, {}] for i in range(100)}}, 200, 100),
            ("ai_code_commits", {"items": [{}] * 7}, 7, 7),
        ]
    )
    def test_page_item_count_uses_the_unit_the_page_is_sized_in(self, endpoint, data, row_count, expected):
        assert _page_item_count(CURSOR_ENDPOINTS[endpoint], data, [{}] * row_count) == expected

    @parameterized.expand(
        [
            ("agent_edits", {"data": []}, False),
            ("dau", {"data": []}, False),
            ("by_user_agent_edits", {"data": {}, "pagination": {"hasNextPage": False}}, True),
            ("ai_code_commits", {"items": [], "totalCount": 0}, True),
            ("ai_code_changes", {"items": [], "totalCount": 0}, True),
        ]
    )
    def test_analytics_endpoints_send_calendar_dates_as_query_params(self, endpoint, payload, paginated):
        now_ms = 1_700_000_000_000  # 2023-11-14T22:13:20Z
        watermark = datetime.fromtimestamp((now_ms - 5 * DAY_MS) / 1000, tz=UTC)
        session = mock.Mock()
        session.request.return_value = _response(200, payload)

        with (
            mock.patch.object(cursor, "_now_ms", return_value=now_ms),
            mock.patch.object(cursor, "make_tracked_session", return_value=session),
        ):
            list(
                _batches(
                    cursor_source(
                        "key_test",
                        endpoint,
                        mock.Mock(),
                        _manager(),
                        should_use_incremental_field=True,
                        db_incremental_field_last_value=watermark,
                    )
                )
            )

        call = session.request.call_args
        assert call.args[0] == "GET"
        assert call.kwargs["json"] is None
        # The Analytics API resolves dates to the day and documents YYYY-MM-DD as the cacheable form.
        assert call.kwargs["params"]["startDate"] == "2023-11-09"
        assert call.kwargs["params"]["endDate"] == "2023-11-14"
        assert ("page" in call.kwargs["params"]) is paginated

    def test_analytics_windows_stay_within_the_calendar_day_cap(self):
        # The Analytics API rejects a range wider than 30 inclusive calendar days, and windows are
        # millisecond ranges that are not midnight-aligned, so a 30-day window would straddle 31.
        end_ms = 1_700_000_000_000
        window_days = CURSOR_ENDPOINTS["agent_edits"].window_days

        windows = _build_windows(end_ms - cursor.DEFAULT_LOOKBACK_DAYS * DAY_MS, end_ms, window_days)

        for window in windows:
            start_date = date.fromisoformat(_to_iso_date(window.start_ms))
            end_date = date.fromisoformat(_to_iso_date(window.end_ms))
            assert (end_date - start_date).days + 1 <= 30

    def test_windowed_first_sync_starts_at_lookback(self):
        now_ms = 1_700_000_000_000
        session = mock.Mock()
        session.request.return_value = _response(200, {"usageEvents": [], "pagination": {"hasNextPage": False}})

        with (
            mock.patch.object(cursor, "_now_ms", return_value=now_ms),
            mock.patch.object(cursor, "make_tracked_session", return_value=session),
        ):
            list(_batches(cursor_source("key_test", "usage_events", mock.Mock(), _manager())))

        first_body = session.request.call_args_list[0].kwargs["json"]
        assert first_body["startDate"] == now_ms - cursor.DEFAULT_LOOKBACK_DAYS * DAY_MS
        assert first_body["endDate"] == first_body["startDate"] + WINDOW_MS - 1
        # The whole lookback is covered in <=30-day chunks.
        expected_requests = -(-cursor.DEFAULT_LOOKBACK_DAYS * DAY_MS // WINDOW_MS)
        assert session.request.call_count == expected_requests

    def test_windowed_incremental_starts_at_watermark(self):
        now_ms = 1_700_000_000_000
        watermark = datetime.fromtimestamp((now_ms - 5 * DAY_MS) / 1000, tz=UTC)
        session = mock.Mock()
        session.request.return_value = _response(200, {"usageEvents": [], "pagination": {"hasNextPage": False}})

        with (
            mock.patch.object(cursor, "_now_ms", return_value=now_ms),
            mock.patch.object(cursor, "make_tracked_session", return_value=session),
        ):
            list(
                _batches(
                    cursor_source(
                        "key_test",
                        "usage_events",
                        mock.Mock(),
                        _manager(),
                        should_use_incremental_field=True,
                        db_incremental_field_last_value=watermark,
                    )
                )
            )

        assert session.request.call_count == 1
        body = session.request.call_args.kwargs["json"]
        assert body["startDate"] == now_ms - 5 * DAY_MS
        assert body["endDate"] == now_ms

    def test_windowed_resumes_from_saved_window_and_page(self):
        now_ms = 1_700_000_000_000
        window_start = now_ms - 10 * DAY_MS
        manager = _manager(CursorResumeConfig(window_start=window_start, page=4))
        session = mock.Mock()
        session.request.return_value = _response(200, {"usageEvents": [], "pagination": {"hasNextPage": False}})

        with (
            mock.patch.object(cursor, "_now_ms", return_value=now_ms),
            mock.patch.object(cursor, "make_tracked_session", return_value=session),
        ):
            list(_batches(cursor_source("key_test", "usage_events", mock.Mock(), manager)))

        body = session.request.call_args.kwargs["json"]
        assert body["startDate"] == window_start
        assert body["page"] == 4

    def test_windowed_saves_state_after_each_batch(self):
        now_ms = 1_700_000_000_000
        manager = _manager()
        pages = [
            _response(
                200,
                {
                    "usageEvents": [{"timestamp": str(now_ms - 1), "userEmail": "a@b.com"}],
                    "pagination": {"hasNextPage": True},
                },
            ),
            _response(
                200,
                {
                    "usageEvents": [{"timestamp": str(now_ms), "userEmail": "a@b.com"}],
                    "pagination": {"hasNextPage": False},
                },
            ),
        ]
        session = mock.Mock()
        session.request.side_effect = pages

        with (
            mock.patch.object(cursor, "_now_ms", return_value=now_ms),
            mock.patch.object(cursor, "make_tracked_session", return_value=session),
        ):
            # A recent watermark keeps the sync to a single window so both mocked pages belong to it.
            source = cursor_source(
                "key_test",
                "usage_events",
                mock.Mock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime.fromtimestamp((now_ms - 10 * DAY_MS) / 1000, tz=UTC),
            )
            iterator = _batches(source)

            first_batch = next(iterator)
            assert first_batch[0]["id"]  # synthetic primary key was added
            # The generator is suspended at the yield — nothing saved until the consumer has
            # taken the batch and pulls the next one, so a crash mid-batch re-fetches it.
            assert manager.save_state.call_count == 0

            next(iterator)
            # Resuming past the first yield saved a bookmark at page 2 of the same window.
            saved = manager.save_state.call_args.args[0]
            assert saved.page == 2
            assert saved.window_start is not None

            list(iterator)

        assert session.request.call_count == 2
        assert session.request.call_args_list[1].kwargs["json"]["page"] == 2
