from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.airbrake import airbrake
from products.warehouse_sources.sources.airbrake._config import AirbrakeSourceConfig
from products.warehouse_sources.sources.airbrake.airbrake import (
    NOTICES_MAX_PAGES_PER_GROUP,
    AirbrakeResumeConfig,
    _build_groups_params,
    _format_start_time,
    _stats_rows_from_response,
    _stats_windows,
    validate_credentials,
)
from products.warehouse_sources.sources.airbrake.settings import AIRBRAKE_ENDPOINTS
from products.warehouse_sources.sources.airbrake.source import AirbrakeSource
from products.warehouse_sources.sources.sdk import RetryableHTTPError
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network


def _driver() -> SourceDriver:
    return SourceDriver(AirbrakeSource(), AirbrakeSourceConfig(api_key="user-key"))


NOW = datetime(2026, 3, 10, 12, 30, tzinfo=UTC)


def _epoch(year: int, month: int, day: int, hour: int = 0) -> int:
    return int(datetime(year, month, day, hour, tzinfo=UTC).timestamp())


def _stats(times: list[str], **series: list[Any]) -> ScriptedResponse:
    return ScriptedResponse(json={"time": times, **series})


def _page(collection: str, rows: list[dict[str, Any]], count: int | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"count": len(rows) if count is None else count, collection: rows})


class TestFormatStartTime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "2026-03-04T00:00:00Z", "2026-03-04T00:00:00Z"),
        ]
    )
    def test_format_start_time(self, _name: str, value: Any, expected: str) -> None:
        # Airbrake expects RFC 3339; a +00:00 offset or bare isoformat drifts from the documented shape.
        assert _format_start_time(value) == expected


class TestBuildGroupsParams:
    def test_incremental_run_sets_server_side_start_time(self) -> None:
        params = _build_groups_params(True, datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))
        assert params == {"order": "created", "start_time": "2026-03-04T02:58:14.000Z"}

    @parameterized.expand(
        [
            ("first_sync_no_watermark", True, None),
            ("full_refresh", False, datetime(2026, 3, 4, tzinfo=UTC)),
        ]
    )
    def test_no_start_time_without_incremental_watermark(
        self, _name: str, should_use_incremental_field: bool, last_value: Any
    ) -> None:
        # start_time=None (or a stale watermark on full refresh) must not leak into the query string.
        params = _build_groups_params(should_use_incremental_field, last_value)
        assert params == {"order": "created"}


class TestIterPages:
    def test_max_pages_cap_truncates_collection(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(airbrake, "NOTICES_MAX_PAGES_PER_GROUP", 3)
        result = _driver().run(
            "notices",
            [
                _page("projects", [{"id": 1}]),
                _page("groups", [{"id": "g1"}]),
                *[_page("notices", [{"id": page}], count=999) for page in range(1, 4)],
            ],
        )
        assert result.raised is None
        assert result.rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert [request.param("page") for request in result.requests if request.path.endswith("/notices")] == [
            "1",
            "2",
            "3",
        ]


class TestStatsWindows:
    @parameterized.expand(
        [
            # 90 days of daily buckets fit in one request, floored to the start of the day.
            ("project_full_refresh", "project_stats", None, [(_epoch(2025, 12, 10), None)]),
            # 7 days of hourly buckets need two requests, and only the first one is bounded.
            (
                "group_full_refresh",
                "group_stats",
                None,
                [(_epoch(2026, 3, 3, 12), _epoch(2026, 3, 7, 16)), (_epoch(2026, 3, 7, 16), None)],
            ),
            (
                "project_watermark_rereads_last_bucket",
                "project_stats",
                NOW.replace(hour=0, minute=0),
                [(_epoch(2026, 3, 10), None)],
            ),
            (
                "group_watermark_floored_to_hour",
                "group_stats",
                datetime(2026, 3, 10, 9, 15, tzinfo=UTC),
                [(_epoch(2026, 3, 10, 9), None)],
            ),
            ("group_watermark_as_iso_string", "group_stats", "2026-03-10T09:00:00Z", [(_epoch(2026, 3, 10, 9), None)]),
            # A watermark older than the lookback must not turn one sync into an unbounded backfill.
            (
                "group_stale_watermark_clamped_to_lookback",
                "group_stats",
                datetime(2025, 1, 1, tzinfo=UTC),
                [(_epoch(2026, 3, 3, 12), _epoch(2026, 3, 7, 16)), (_epoch(2026, 3, 7, 16), None)],
            ),
        ]
    )
    def test_windows(self, _name: str, endpoint: str, last_value: Any, expected: list[tuple[int, int | None]]) -> None:
        stats = AIRBRAKE_ENDPOINTS[endpoint].stats
        assert stats is not None
        windows = _stats_windows(stats, NOW, last_value)
        assert windows == expected
        # No window may hold more buckets than one request returns, or buckets are cut off.
        for start, end in windows:
            assert ((end or int(NOW.timestamp())) - start) // stats.period_seconds <= 100


class TestStatsRowsFromResponse:
    @parameterized.expand(
        [
            (
                "parallel_arrays",
                {"projectId": 9, "time": ["t1", "t2"], "accepted": [1, 2], "limited": [3, 4]},
                [
                    {"projectId": 1, "time": "t1", "accepted": 1, "limited": 3},
                    {"projectId": 1, "time": "t2", "accepted": 2, "limited": 4},
                ],
            ),
            (
                "short_series_padded_with_none",
                {"time": ["t1", "t2"], "accepted": [1]},
                [{"projectId": 1, "time": "t1", "accepted": 1}, {"projectId": 1, "time": "t2", "accepted": None}],
            ),
            (
                "null_bucket_skipped",
                {"time": [None, "t2"], "accepted": [1, 2]},
                [{"projectId": 1, "time": "t2", "accepted": 2}],
            ),
            ("missing_time", {"accepted": [1]}, []),
            ("null_time", {"time": None, "accepted": [1]}, []),
        ]
    )
    def test_rows(self, _name: str, data: dict[str, Any], expected: list[dict[str, Any]]) -> None:
        assert _stats_rows_from_response(data, {"projectId": 1}) == expected


class TestStatsFanOut:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self) -> Iterator[None]:
        with time_machine.travel(NOW, tick=False):
            yield

    def test_project_stats_requests_and_rows(self) -> None:
        result = _driver().run(
            "project_stats",
            [
                _page("projects", [{"id": 1}, {"id": 2}]),
                _stats(["2026-03-09T00:00:00Z"], accepted=[5], limited=[0], overQuota=[1]),
                ScriptedResponse(status=404),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 9, tzinfo=UTC),
        )
        assert result.raised is None
        assert result.rows == [
            {"projectId": 1, "time": "2026-03-09T00:00:00Z", "accepted": 5, "limited": 0, "overQuota": 1}
        ]
        assert result.paths == ["/api/v4/projects", "/api/v4/projects/1/stats", "/api/v4/projects/2/stats"]
        assert result.params("period")[1:] == ["24h", "24h"]
        assert result.params("time__gte")[1:] == [str(_epoch(2026, 3, 9))] * 2
        assert result.params("time__lt")[1:] == [None, None]
        assert result.saved_states == [AirbrakeResumeConfig(project_id=2)]

    def test_group_stats_reads_every_window_of_every_group(self) -> None:
        result = _driver().run(
            "group_stats",
            [
                _page("projects", [{"id": 1}]),
                _page("groups", [{"id": "g1"}, {"id": "g2"}]),
                _stats(["2026-03-03T12:00:00Z"], accepted=[1], limited=[0]),
                _stats([]),
                _stats([]),
                _stats(["2026-03-10T12:00:00Z"], accepted=[7], limited=[2]),
            ],
        )
        assert result.raised is None
        assert result.rows == [
            {"projectId": 1, "groupId": "g1", "time": "2026-03-03T12:00:00Z", "accepted": 1, "limited": 0},
            {"projectId": 1, "groupId": "g2", "time": "2026-03-10T12:00:00Z", "accepted": 7, "limited": 2},
        ]
        assert (
            result.paths[2:] == ["/api/v4/projects/1/groups/g1/stats"] * 2 + ["/api/v4/projects/1/groups/g2/stats"] * 2
        )
        assert result.params("period")[2:] == ["hour"] * 4
        assert result.params("time__lt")[2:] == [str(_epoch(2026, 3, 7, 16)), None] * 2
        # The bookmark moves to the next group only after the last window of the current one.
        assert result.saved_states == [
            AirbrakeResumeConfig(project_id=1, group_id="g1"),
            AirbrakeResumeConfig(project_id=1, group_id="g2"),
            AirbrakeResumeConfig(project_id=1, group_id="g2"),
        ]

    @parameterized.expand(
        [
            (
                "project_stats",
                AirbrakeResumeConfig(project_id=2),
                [_page("projects", [{"id": 1}, {"id": 2}])],
                "/api/v4/projects/2/stats",
            ),
            (
                "group_stats",
                AirbrakeResumeConfig(project_id=1, group_id="g2"),
                [_page("projects", [{"id": 1}]), _page("groups", [{"id": "g1"}, {"id": "g2"}])],
                "/api/v4/projects/1/groups/g2/stats",
            ),
        ]
    )
    def test_resume_skips_parents_before_bookmark(
        self, endpoint: str, resume_state: AirbrakeResumeConfig, listing: list[ScriptedResponse], expected_path: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [*listing, *[_stats(["2026-03-10T00:00:00Z"], accepted=[1])] * 2],
            resume_state=resume_state,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 10, tzinfo=UTC),
        )
        assert result.raised is None
        assert result.paths[len(listing) :] == [expected_path]

    def test_group_budget_caps_total_fan_out(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(airbrake, "GROUP_STATS_MAX_GROUPS_PER_SYNC", 1)
        result = _driver().run(
            "group_stats",
            [
                _page("projects", [{"id": 1}]),
                _page("groups", [{"id": "g1"}, {"id": "g2"}]),
                _stats([]),
                _stats(["2026-03-10T12:00:00Z"], accepted=[1]),
            ],
        )
        assert result.raised is None
        assert result.paths[2:] == ["/api/v4/projects/1/groups/g1/stats"] * 2

    def test_non_404_http_error_propagates(self) -> None:
        result = _driver().run("project_stats", [_page("projects", [{"id": 1}]), ScriptedResponse(status=403)])
        assert isinstance(result.raised, requests.HTTPError)


class TestFetchPageRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500)])
    def test_retryable_statuses_are_retried(self, _name: str, status_code: int) -> None:
        result = _driver().run("projects", [ScriptedResponse(status=status_code), _page("projects", [])])
        assert result.raised is None
        assert result.rows == []
        assert result.paths == ["/api/v4/projects", "/api/v4/projects"]

    @parameterized.expand([("rate_limited", 429), ("server_error", 500)])
    def test_persistent_retryable_status_raises_a_retryable_error(self, _name: str, status_code: int) -> None:
        result = _driver().run("projects", always(ScriptedResponse(status=status_code)))
        assert isinstance(result.raised, RetryableHTTPError)

    def test_auth_error_raises_immediately_without_leaking_key(self) -> None:
        # 401 must surface as HTTPError on the first attempt so get_non_retryable_errors can stop
        # the sync — and its message must not carry the ?key= credential, since it is persisted
        # into job errors and logs.
        result = _driver().run("projects", [ScriptedResponse(status=401, json={"code": 401, "type": "Unauthorized"})])
        assert len(result.requests) == 1
        assert isinstance(result.raised, requests.HTTPError)
        assert "401 Client Error: Unauthorized for url: https://api.airbrake.io/api/v4/projects" in str(result.raised)
        assert "user-key" not in str(result.raised)
        # `response` must ride along so fan-out callers can distinguish 404s.
        assert result.raised.response is not None
        assert result.raised.response.status_code == 401


class TestGroupsFanOut:
    def test_incremental_run_passes_start_time_to_every_project(self) -> None:
        result = _driver().run(
            "groups",
            [
                _page("projects", [{"id": 1}, {"id": 2}]),
                _page("groups", [{"id": "g1"}]),
                _page("groups", [{"id": "g2"}]),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert result.raised is None
        groups_requests = [request for request in result.requests if request.path.endswith("/groups")]
        assert len(groups_requests) == 2
        for request in groups_requests:
            assert request.param("start_time") == "2026-03-04T02:58:14.000Z"
            assert request.param("order") == "created"

    def test_resume_skips_projects_before_bookmark_and_reuses_saved_page(self) -> None:
        result = _driver().run(
            "groups",
            [
                _page("projects", [{"id": 1}, {"id": 2}, {"id": 3}]),
                # Project 1 must not be re-fetched; project 2 resumes at page 3.
                _page("groups", [{"id": "g2-p3"}], count=999),
                _page("groups", []),
                _page("groups", [{"id": "g3"}]),
            ],
            resume_state=AirbrakeResumeConfig(page=3, project_id=2),
        )
        assert result.raised is None
        assert result.rows == [{"id": "g2-p3"}, {"id": "g3"}]
        assert result.paths == [
            "/api/v4/projects",
            "/api/v4/projects/2/groups",
            "/api/v4/projects/2/groups",
            "/api/v4/projects/3/groups",
        ]
        assert result.params("page") == ["1", "3", "4", "1"]

    def test_resume_from_deleted_project_restarts_from_first(self) -> None:
        result = _driver().run(
            "groups",
            [_page("projects", [{"id": 1}]), _page("groups", [{"id": "g1"}])],
            resume_state=AirbrakeResumeConfig(page=5, project_id=999),
        )
        assert result.raised is None
        assert result.rows == [{"id": "g1"}]
        assert result.paths == ["/api/v4/projects", "/api/v4/projects/1/groups"]
        assert result.params("page") == ["1", "1"]

    def test_state_saved_after_each_page_and_bookmark_advanced_between_projects(self) -> None:
        result = _driver().run(
            "groups",
            [
                _page("projects", [{"id": 1}, {"id": 2}]),
                _page("groups", [{"id": "g1"}]),
                _page("groups", [{"id": "g2"}]),
            ],
        )
        assert result.raised is None
        assert result.saved_states == [
            AirbrakeResumeConfig(page=2, project_id=1),
            AirbrakeResumeConfig(page=1, project_id=2),
            AirbrakeResumeConfig(page=2, project_id=2),
        ]

    def test_project_deleted_mid_fan_out_is_skipped(self) -> None:
        result = _driver().run(
            "groups",
            [
                _page("projects", [{"id": 1}, {"id": 2}]),
                ScriptedResponse(status=404),
                _page("groups", [{"id": "g2"}]),
            ],
        )
        assert result.raised is None
        assert result.rows == [{"id": "g2"}]
        assert result.paths[-1] == "/api/v4/projects/2/groups"

    def test_non_404_http_error_propagates(self) -> None:
        result = _driver().run("groups", [_page("projects", [{"id": 1}]), ScriptedResponse(status=403)])
        assert isinstance(result.raised, requests.HTTPError)
        assert result.raised.response is not None
        assert result.raised.response.status_code == 403


class TestActivitiesFanOut:
    def test_activities_are_read_per_project(self) -> None:
        result = _driver().run(
            "activities",
            [
                _page("projects", [{"id": 1}, {"id": 2}]),
                _page("activities", [{"projectId": 1, "activity": "group.resolved", "trackableId": 5}]),
                _page("activities", []),
            ],
        )
        assert result.raised is None
        assert result.rows == [{"projectId": 1, "activity": "group.resolved", "trackableId": 5}]
        assert result.paths == ["/api/v4/projects", "/api/v4/projects/1/activities", "/api/v4/projects/2/activities"]


class TestDeploysFanOut:
    def test_project_id_is_injected_into_deploy_rows(self) -> None:
        # The Airbrake deploy payload carries no project reference; without injection the table
        # can't be joined back to projects.
        result = _driver().run(
            "deploys",
            [
                _page("projects", [{"id": 7}]),
                _page("deploys", [{"environment": "production", "revision": "abc123"}]),
            ],
        )
        assert result.raised is None
        assert result.rows == [{"environment": "production", "revision": "abc123", "projectId": 7}]


class TestNoticesFanOut:
    def test_resume_skips_groups_before_bookmark(self) -> None:
        result = _driver().run(
            "notices",
            [
                _page("projects", [{"id": 1}]),
                _page("groups", [{"id": "g1"}, {"id": "g2"}]),
                _page("notices", [{"id": "n2-p2"}], count=999),
                _page("notices", []),
            ],
            resume_state=AirbrakeResumeConfig(page=2, project_id=1, group_id="g2"),
        )
        assert result.raised is None
        assert result.rows == [{"id": "n2-p2"}]
        assert result.paths[2:] == [
            "/api/v4/projects/1/groups/g2/notices",
            "/api/v4/projects/1/groups/g2/notices",
        ]
        assert result.params("page")[2:] == ["2", "3"]

    def test_group_deleted_mid_fan_out_is_skipped(self) -> None:
        result = _driver().run(
            "notices",
            [
                _page("projects", [{"id": 1}]),
                _page("groups", [{"id": "gone"}, {"id": "g2"}]),
                ScriptedResponse(status=404),
                _page("notices", [{"id": "n2"}]),
            ],
        )
        assert result.raised is None
        assert result.rows == [{"id": "n2"}]
        assert result.paths[-1] == "/api/v4/projects/1/groups/g2/notices"

    def test_per_group_history_is_capped(self) -> None:
        # One noisy group with unbounded history must not dominate the sync.
        result = _driver().run(
            "notices",
            [
                _page("projects", [{"id": 1}]),
                _page("groups", [{"id": "g1"}]),
                *[
                    _page("notices", [{"id": f"n{page}"}], count=99999)
                    for page in range(1, NOTICES_MAX_PAGES_PER_GROUP + 1)
                ],
            ],
        )
        assert result.raised is None
        assert len(result.rows) == NOTICES_MAX_PAGES_PER_GROUP
        assert result.params("page")[2:] == [str(page) for page in range(1, NOTICES_MAX_PAGES_PER_GROUP + 1)]

    def test_group_budget_caps_total_fan_out(self, monkeypatch: Any) -> None:
        # The per-group page cap bounds each group, but only this budget bounds the two-level
        # fan-out as a whole; an account with many groups must stop once it is exhausted.
        monkeypatch.setattr(airbrake, "NOTICES_MAX_GROUPS_PER_SYNC", 2)
        result = _driver().run(
            "notices",
            [
                _page("projects", [{"id": 1}]),
                _page("groups", [{"id": "g1"}, {"id": "g2"}, {"id": "g3"}, {"id": "g4"}]),
                _page("notices", [{"id": "n-g1"}]),
                _page("notices", [{"id": "n-g2"}]),
            ],
        )
        assert result.raised is None
        assert result.rows == [{"id": "n-g1"}, {"id": "n-g2"}]
        assert result.paths[2:] == [
            "/api/v4/projects/1/groups/g1/notices",
            "/api/v4/projects/1/groups/g2/notices",
        ]


class TestSourceResponse:
    @parameterized.expand(
        [
            ("projects", ["id"], None),
            ("groups", ["id"], ["createdAt"]),
            ("deploys", None, None),
            ("notices", ["groupId", "id"], ["createdAt"]),
            ("activities", None, None),
            ("project_stats", ["projectId", "time"], ["time"]),
            ("group_stats", ["groupId", "time"], ["time"]),
        ]
    )
    def test_primary_and_partition_keys(
        self, endpoint: str, expected_pks: list[str] | None, expected_partition_keys: list[str] | None
    ) -> None:
        # Dropping groupId from the notices key multi-matches merges if notice ids repeat across
        # groups; partitioning on a mutable field rewrites partitions every sync.
        result = _driver().run(endpoint, [_page("projects", [])])
        assert result.raised is None
        assert result.response is not None
        assert result.response.primary_keys == expected_pks
        assert result.response.partition_keys == expected_partition_keys
        # Watermark persistence must stay deferred to job end: fan-out batches arrive per project,
        # so per-batch asc checkpointing could advance the cursor past projects a crashed run never reached.
        assert result.response.sort_mode == "desc"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, True),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("user-key") is expected
        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/api/v4/projects"
        assert network.requests_log[0].param("key") == "user-key"
        assert network.requests_log[0].param("limit") == "1"

    def test_network_error_maps_to_invalid(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            assert validate_credentials("user-key") is False
        # The real stack retries a dropped connection.
        assert {request.path for request in network.requests_log} == {"/api/v4/projects"}
