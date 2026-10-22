from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest import mock

import requests
import responses
from parameterized import parameterized
from tenacity import wait_none

from products.warehouse_sources.backend.temporal.data_imports.external_data_job import Any_Source_Errors
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.cursor import cursor
from products.warehouse_sources.backend.temporal.data_imports.sources.cursor.cursor import (
    CursorResumeConfig,
    _build_windows,
    _extract_rows,
    _has_next_page,
    _normalize_daily_usage,
    _page_item_count,
    cursor_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cursor.settings import CURSOR_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.cursor.source import CursorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cursor import CursorSourceConfig

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


CURSOR_PLAN_REJECTION = {
    "code": "error",
    "message": "You must be a member of an enterprise team to access this resource",
}


def _resolve_friendly_error(error: Exception) -> str | None:
    errors = {**Any_Source_Errors, **CursorSource().get_non_retryable_errors()}
    message = f"{type(error).__name__}: {error}"
    return next((friendly for key, friendly in errors.items() if error_message_matches(message, [key])), None)


def _driver() -> SourceDriver:
    return SourceDriver(CursorSource(), CursorSourceConfig(api_key="key_test"))


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
        ]
    )
    def test_validate_credentials_maps_status(self, status_code, expected):
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("key_test") == expected
        assert [request.path for request in network.requests_log] == ["/teams/members"]
        assert network.requests_log[0].method == "GET"

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

    @parameterized.expand(
        [
            (
                "plan_rejection_on_analytics",
                "dau",
                401,
                CURSOR_PLAN_REJECTION,
                cursor.CursorPlanError,
                cursor.ANALYTICS_PLAN_MESSAGE,
            ),
            (
                "plan_rejection_as_forbidden",
                "ai_code_commits",
                403,
                CURSOR_PLAN_REJECTION,
                cursor.CursorPlanError,
                cursor.ANALYTICS_PLAN_MESSAGE,
            ),
            (
                "rejected_key_on_analytics",
                "dau",
                401,
                {"code": "error", "message": "Invalid API key"},
                requests.HTTPError,
                cursor.KEY_REJECTED_MESSAGE,
            ),
            (
                "rejected_key_with_non_json_body",
                "members",
                401,
                "Unauthorized",
                requests.HTTPError,
                cursor.KEY_REJECTED_MESSAGE,
            ),
            (
                "forbidden_key_on_admin_api",
                "members",
                403,
                {"code": "error", "message": "Forbidden"},
                requests.HTTPError,
                cursor.KEY_FORBIDDEN_MESSAGE,
            ),
        ]
    )
    def test_rejected_request_resolves_to_the_message_for_its_cause(
        self,
        _name: str,
        endpoint: str,
        status: int,
        body: dict[str, str] | str,
        raised: type[requests.HTTPError],
        expected: str,
    ) -> None:
        config = CURSOR_ENDPOINTS[endpoint]
        with responses.RequestsMock() as mocked:
            if isinstance(body, dict):
                mocked.add(config.method, f"{cursor.CURSOR_BASE_URL}{config.path}", status=status, json=body)
            else:
                mocked.add(config.method, f"{cursor.CURSOR_BASE_URL}{config.path}", status=status, body=body)
            with pytest.raises(requests.HTTPError) as excinfo:
                list(_batches(cursor_source("key_test", endpoint, mock.Mock(), _manager())))

        assert type(excinfo.value) is raised
        assert _resolve_friendly_error(excinfo.value) == expected

    def test_unknown_endpoint_raises(self):
        result = _driver().run("not_a_table", [])

        assert isinstance(result.raised, ValueError)
        assert "Unknown Cursor endpoint" in str(result.raised)

    @parameterized.expand(
        [
            ("members", ["id"], None),
            ("daily_usage", ["date", "userId"], ["date"]),
            ("usage_events", ["id"], ["timestamp"]),
            ("spend", ["userId"], None),
        ]
    )
    def test_source_response_shape(self, endpoint, primary_keys, partition_keys):
        result = _driver().run(
            endpoint,
            always(ScriptedResponse(json={})),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.now(UTC),
        )
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == partition_keys
        assert response.sort_mode == "asc"

    def test_members_yields_single_batch_via_get(self):
        result = _driver().run(
            "members", [ScriptedResponse(json={"teamMembers": [{"id": 1, "email": "a@b.com", "role": "owner"}]})]
        )

        assert result.raised is None
        assert result.items == [[{"id": 1, "email": "a@b.com", "role": "owner"}]]
        assert result.requests[0].method == "GET"
        assert result.paths == ["/teams/members"]

    def test_spend_paginates_and_stamps_cycle_start(self):
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
        result = _driver().run("spend", [ScriptedResponse(json=page_one), ScriptedResponse(json=page_two)])

        assert result.raised is None
        assert [len(batch) for batch in result.items] == [100, 1]
        assert all(row["subscriptionCycleStart"] == 1_700_000_000_000 for row in result.rows)
        assert [request.json()["page"] for request in result.requests] == [1, 2]
        # State was saved after the non-final page so a retry resumes at page 2.
        assert result.saved_states == [CursorResumeConfig(page=2)]

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
        pages = [
            ScriptedResponse(json={"data": {"idle@example.com": []}, "pagination": {"hasNextPage": True}}),
            ScriptedResponse(
                json={
                    "data": {"alice@example.com": [{"event_date": "2023-11-14", "total_accepts": 2}]},
                    "pagination": {"hasNextPage": False},
                }
            ),
        ]

        with mock.patch.object(cursor, "_now_ms", return_value=now_ms):
            result = _driver().run(
                "by_user_tabs",
                pages,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime.fromtimestamp((now_ms - DAY_MS) / 1000, tz=UTC),
            )

        assert result.raised is None
        assert len(result.requests) == 2
        assert [row["userEmail"] for row in result.rows] == ["alice@example.com"]

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
            ("bugbot_reviews", {"data": [], "pagination": {"hasNextPage": False}}, True),
            ("conversation_insights", {"data": {}}, False),
        ]
    )
    def test_analytics_endpoints_send_calendar_dates_as_query_params(self, endpoint, payload, paginated):
        now_ms = 1_700_000_000_000  # 2023-11-14T22:13:20Z
        watermark = datetime.fromtimestamp((now_ms - 5 * DAY_MS) / 1000, tz=UTC)
        with mock.patch.object(cursor, "_now_ms", return_value=now_ms):
            result = _driver().run(
                endpoint,
                [ScriptedResponse(json=payload)],
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark,
            )

        assert result.raised is None
        assert result.requests[0].method == "GET"
        assert result.requests[0].body is None
        # The Analytics API resolves dates to the day and documents YYYY-MM-DD as the cacheable form.
        assert result.requests[0].param("startDate") == "2023-11-09"
        assert result.requests[0].param("endDate") == "2023-11-14"
        assert (result.requests[0].param("page") is not None) is paginated

    def test_windowed_first_sync_starts_at_lookback(self):
        now_ms = 1_700_000_000_000
        with mock.patch.object(cursor, "_now_ms", return_value=now_ms):
            result = _driver().run(
                "usage_events",
                always(ScriptedResponse(json={"usageEvents": [], "pagination": {"hasNextPage": False}})),
            )

        assert result.raised is None
        first_body = result.requests[0].json()
        assert first_body["startDate"] == now_ms - cursor.DEFAULT_LOOKBACK_DAYS * DAY_MS
        assert first_body["endDate"] == first_body["startDate"] + WINDOW_MS - 1
        # The whole lookback is covered in <=30-day chunks.
        expected_requests = -(-cursor.DEFAULT_LOOKBACK_DAYS * DAY_MS // WINDOW_MS)
        assert len(result.requests) == expected_requests

    def test_windowed_resumes_from_saved_window_and_page(self):
        now_ms = 1_700_000_000_000
        window_start = now_ms - 10 * DAY_MS
        with mock.patch.object(cursor, "_now_ms", return_value=now_ms):
            result = _driver().run(
                "usage_events",
                [ScriptedResponse(json={"usageEvents": [], "pagination": {"hasNextPage": False}})],
                resume_state=CursorResumeConfig(window_start=window_start, page=4),
            )

        assert result.raised is None
        body = result.requests[0].json()
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

    @parameterized.expand(
        [
            # The Admin API names the audit log range startTime/endTime. Sent as startDate/endDate,
            # the range is ignored and every window returns the default last 7 days.
            (
                "audit_logs",
                {"events": [], "pagination": {"hasNextPage": False}},
                {"startTime": "1699568000000", "endTime": "1700000000000", "pageSize": "500", "startDate": None},
            ),
            # `include` is required, and the slices it names are the ones the rows are built from.
            (
                "conversation_insights",
                {"data": {}},
                {"include": "intents,complexity,categories,guidanceLevels,workTypes", "page": None},
            ),
        ]
    )
    def test_endpoint_specific_query_params(self, endpoint, payload, expected_params):
        now_ms = 1_700_000_000_000
        watermark = datetime.fromtimestamp((now_ms - 5 * DAY_MS) / 1000, tz=UTC)
        with mock.patch.object(cursor, "_now_ms", return_value=now_ms):
            result = _driver().run(
                endpoint,
                [ScriptedResponse(json=payload)],
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark,
            )

        assert result.raised is None
        assert {name: result.requests[0].param(name) for name in expected_params} == expected_params

    def test_audit_logs_walk_every_page_of_a_window(self):
        now_ms = 1_700_000_000_000
        pages = [
            ScriptedResponse(
                json={
                    "events": [{"event_id": "evt-1", "timestamp": "2023-11-13T08:00:00.000Z"}],
                    "pagination": {"hasNextPage": True},
                }
            ),
            ScriptedResponse(
                json={
                    "events": [{"event_id": "evt-2", "timestamp": "2023-11-14T09:30:00.000Z"}],
                    "pagination": {"hasNextPage": False},
                }
            ),
        ]
        with mock.patch.object(cursor, "_now_ms", return_value=now_ms):
            result = _driver().run(
                "audit_logs",
                pages,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime.fromtimestamp((now_ms - DAY_MS) / 1000, tz=UTC),
            )

        assert result.raised is None
        assert result.paths == ["/teams/audit-logs", "/teams/audit-logs"]
        assert result.params("page") == ["1", "2"]
        assert [row["event_id"] for row in result.rows] == ["evt-1", "evt-2"]
        assert result.rows[1]["timestamp"] == datetime(2023, 11, 14, 9, 30, tzinfo=UTC)

    @parameterized.expand(
        [
            (
                "groups_and_unassigned",
                {
                    "groups": [
                        {
                            "id": "group_eng",
                            "name": "Engineering",
                            "spendCents": 1200,
                            "createdAt": "2025-01-02T00:00:00.000Z",
                            "currentMembers": [
                                {"userId": "user_a", "joinedAt": "2025-01-03T00:00:00.000Z", "leftAt": None}
                            ],
                            "formerMembers": [
                                {
                                    "userId": "user_b",
                                    "joinedAt": "2025-01-01T00:00:00.000Z",
                                    "leftAt": "2025-01-05T00:00:00.000Z",
                                }
                            ],
                        }
                    ],
                    "unassignedGroup": {
                        "id": "group_unassigned",
                        "name": "Unassigned",
                        "currentMembers": [{"userId": "user_c", "joinedAt": "2025-01-04T00:00:00.000Z"}],
                    },
                    "billingCycle": {"cycleStart": "2025-01-01T00:00:00.000Z", "cycleEnd": "2025-02-01T00:00:00.000Z"},
                },
                ["group_eng", "group_unassigned"],
                [("group_eng", "user_a", True), ("group_eng", "user_b", False), ("group_unassigned", "user_c", True)],
            ),
            ("unassigned_group_null", {"groups": [], "unassignedGroup": None}, [], []),
            ("empty_body", {}, [], []),
        ]
    )
    def test_billing_group_tables_read_one_listing(self, _name, body, expected_group_ids, expected_members):
        groups_result = _driver().run("billing_groups", [ScriptedResponse(json=body)])
        members_result = _driver().run("billing_group_members", [ScriptedResponse(json=body)])

        assert groups_result.raised is None and members_result.raised is None
        assert groups_result.paths == members_result.paths == ["/teams/groups"]
        assert [row["id"] for row in groups_result.rows] == expected_group_ids
        # Members get their own table, so the unbounded member lists stay out of the group rows.
        assert all("currentMembers" not in row and "formerMembers" not in row for row in groups_result.rows)
        assert [
            (row["groupId"], row["userId"], row["isCurrentMember"]) for row in members_result.rows
        ] == expected_members
        if expected_members:
            cycle_start = datetime(2025, 1, 1, tzinfo=UTC)
            assert all(row["billingCycleStart"] == cycle_start for row in groups_result.rows + members_result.rows)
            assert members_result.rows[1]["leftAt"] == datetime(2025, 1, 5, tzinfo=UTC)

    def test_conversation_insights_rows_come_from_the_daily_series_only(self):
        data = {
            "data": {
                # Range totals change with the window, so they must not become rows.
                "intents": {
                    "distribution": [{"intent": "Ask", "count": 7}],
                    "topValues": [{"intent": "Ask", "count": 7}],
                    "timeSeries": [
                        {"date": "2026-03-01", "intent": "Ask", "count": 2},
                        {"date": "2026-03-02", "intent": "Write Code", "count": 6},
                    ],
                    "subcategories": {"askMode": [{"subcategory": "error_fix", "count": 4}]},
                },
                "workTypes": {"timeSeries": [{"date": "2026-03-01", "workType": "bug", "count": 2}]},
                "complexity": {"distribution": [{"complexity": "high", "count": 1}]},
                "categories": None,
            }
        }

        rows = _extract_rows(CURSOR_ENDPOINTS["conversation_insights"], data)

        assert rows == [
            {"date": "2026-03-01", "slice": "intents", "value": "Ask", "count": 2},
            {"date": "2026-03-02", "slice": "intents", "value": "Write Code", "count": 6},
            {"date": "2026-03-01", "slice": "workTypes", "value": "bug", "count": 2},
        ]
