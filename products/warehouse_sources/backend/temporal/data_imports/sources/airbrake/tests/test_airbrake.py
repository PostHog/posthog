from datetime import UTC, date, datetime
from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.airbrake import airbrake
from products.warehouse_sources.backend.temporal.data_imports.sources.airbrake.airbrake import (
    NOTICES_MAX_PAGES_PER_GROUP,
    AirbrakeResumeConfig,
    AirbrakeRetryableError,
    _build_groups_params,
    _format_start_time,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.airbrake.source import AirbrakeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.airbrake import (
    AirbrakeSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(AirbrakeSource(), AirbrakeSourceConfig(api_key="user-key"))


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


class TestFetchPageRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500)])
    def test_retryable_statuses_are_retried(self, _name: str, status_code: int) -> None:
        result = _driver().run("projects", [ScriptedResponse(status=status_code), _page("projects", [])])
        assert result.raised is None
        assert result.rows == []
        assert result.paths == ["/api/v4/projects", "/api/v4/projects"]

    @parameterized.expand([("rate_limited", 429), ("server_error", 500)])
    def test_persistent_retryable_status_raises_a_retryable_error(self, _name: str, status_code: int) -> None:
        # The adapter absorbs one failed try, so only a status that persists reaches the source's own check.
        result = _driver().run("projects", always(ScriptedResponse(status=status_code)))
        assert isinstance(result.raised, AirbrakeRetryableError)

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
