from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import time_machine
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.render import RenderSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.render import render
from products.warehouse_sources.backend.temporal.data_imports.sources.render.render import (
    RenderResumeConfig,
    RenderRetryableError,
    _build_params,
    _format_incremental_value,
    _unwrap_item,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.render.settings import (
    RENDER_ENDPOINTS,
    RenderEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.render.source import RenderSource


def _driver(owner_id: str | None = "tea-123") -> SourceDriver:
    return SourceDriver(RenderSource(), RenderSourceConfig(api_key="rnd_test", owner_id=owner_id))


def _run(endpoint: str, script: Script, owner_id: str | None = "tea-123", **inputs: Any) -> DriveResult:
    return _driver(owner_id).run(endpoint, script, **inputs)


def _pages(*payloads: Any) -> list[ScriptedResponse]:
    return [ScriptedResponse(json=payload) for payload in payloads]


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            (
                # Watermarks come back from the pipeline in whatever offset the API row carried;
                # sending a non-UTC offset to Render's ISO filters is undocumented territory.
                "non_utc_offset_converted",
                datetime(2026, 3, 4, 4, 58, 14, tzinfo=timezone(timedelta(hours=2))),
                "2026-03-04T02:58:14Z",
            ),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestUnwrapItem:
    @parameterized.expand(
        [
            (
                "wrapped_with_sibling_cursor",
                {"service": {"id": "srv-1"}, "cursor": "c1"},
                "service",
                ({"id": "srv-1"}, "c1"),
            ),
            (
                "unwrapped_env_group_shape",
                {"id": "evg-1", "name": "group"},
                "envGroup",
                ({"id": "evg-1", "name": "group"}, None),
            ),
        ]
    )
    def test_unwrap_item(self, _name: str, item: dict, wrapper_key: str, expected: tuple) -> None:
        assert _unwrap_item(item, wrapper_key) == expected


class TestBuildParams:
    WATERMARK = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)

    @parameterized.expand(
        [
            ("services_updated_at", "services", "updatedAt", {"updatedAfter": "2026-03-04T02:58:14Z"}),
            ("deploys_finished_at", "deploys", "finishedAt", {"finishedAfter": "2026-03-04T02:58:14Z"}),
            ("deploys_default_field", "deploys", None, {"finishedAfter": "2026-03-04T02:58:14Z"}),
            ("events_timestamp_maps_to_start_time", "events", "timestamp", {"startTime": "2026-03-04T02:58:14Z"}),
        ]
    )
    def test_incremental_field_maps_to_server_side_filter(
        self, _name: str, endpoint: str, incremental_field: str | None, expected_params: dict
    ) -> None:
        params = _build_params(
            RENDER_ENDPOINTS[endpoint],
            owner_id=None,
            should_use_incremental_field=True,
            db_incremental_field_last_value=self.WATERMARK,
            incremental_field=incremental_field,
            logger=MagicMock(),
        )
        for key, value in expected_params.items():
            assert params[key] == value

    @parameterized.expand(
        [
            ("owner_filter_on_supporting_endpoint", "services", True),
            ("no_owner_filter_on_fan_out_child", "deploys", False),
        ]
    )
    def test_owner_filter(self, _name: str, endpoint: str, expects_owner: bool) -> None:
        params = _build_params(
            RENDER_ENDPOINTS[endpoint],
            owner_id="tea-123",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
            logger=MagicMock(),
        )
        assert ("ownerId" in params) == expects_owner

    @parameterized.expand(
        [
            ("full_refresh_starts_at_window_floor", False, None, "2026-03-04T00:00:00Z"),
            ("stale_watermark_is_clamped_to_window", True, datetime(2025, 1, 1, tzinfo=UTC), "2026-03-04T00:00:00Z"),
            ("recent_watermark_is_kept", True, datetime(2026, 5, 20, 10, 0, tzinfo=UTC), "2026-05-20T10:00:00Z"),
            ("recent_string_watermark_is_kept", True, "2026-05-20T10:00:00Z", "2026-05-20T10:00:00Z"),
            ("stale_string_watermark_is_clamped", True, "2025-01-01T00:00:00Z", "2026-03-04T00:00:00Z"),
        ]
    )
    def test_audit_logs_start_time_stays_inside_lookback_window(
        self, _name: str, should_use_incremental_field: bool, watermark: Any, expected_start: str
    ) -> None:
        # Render caps an audit log query at a 90-day span: a start older than that is rejected,
        # and with no start at all the server picks its own default window.
        with time_machine.travel(datetime(2026, 6, 1, tzinfo=UTC), tick=False):
            params = _build_params(
                RENDER_ENDPOINTS["audit_logs"],
                owner_id=None,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=watermark,
                incremental_field="timestamp",
                logger=MagicMock(),
            )

        assert params == {"limit": 1000, "startTime": expected_start}

    def test_incremental_field_without_server_filter_is_skipped(self) -> None:
        config = RenderEndpointConfig(name="x", path="/x", wrapper_key="x", default_incremental_field="updatedAt")
        logger = MagicMock()
        params = _build_params(
            config,
            owner_id=None,
            should_use_incremental_field=True,
            db_incremental_field_last_value=self.WATERMARK,
            incremental_field="updatedAt",
            logger=logger,
        )
        assert params == {"limit": 100}
        logger.warning.assert_called_once()


class TestPagination:
    def test_resume_starts_from_saved_cursor(self) -> None:
        result = _run(
            "services",
            _pages([{"service": {"id": "srv-9"}, "cursor": "c9"}], []),
            resume_state=RenderResumeConfig(cursor="c-resume"),
        )

        assert result.requests[0].param("cursor") == "c-resume"
        assert result.items == [[{"id": "srv-9"}]]

    def test_full_page_without_cursor_stops_instead_of_looping(self) -> None:
        # Unwrapped responses (env groups) carry no cursor: a full page must terminate with a
        # truncation warning, not refetch the same page forever.
        page = [{"id": f"evg-{i}"} for i in range(100)]
        result = _run("env_groups", _pages(page))

        assert len(result.items) == 1
        assert len(result.requests) == 1


class TestFanOut:
    SERVICES_PAGE = [
        {"service": {"id": "srv-1", "createdAt": "2024-01-01T00:00:00Z"}},
        {"service": {"id": "srv-2", "createdAt": "2024-02-01T00:00:00Z"}},
    ]

    def test_deploys_fetched_per_service_with_injected_service_id(self) -> None:
        result = _run(
            "deploys",
            _pages(
                self.SERVICES_PAGE,
                [{"deploy": {"id": "dep-1", "status": "live"}}],
                [{"deploy": {"id": "dep-2", "status": "live"}}],
            ),
        )

        assert result.paths[1] == "/v1/services/srv-1/deploys"
        assert result.paths[2] == "/v1/services/srv-2/deploys"
        # Deploy payloads omit the service id; rows must carry it for the composite primary key.
        assert result.items == [
            [{"serviceId": "srv-1", "id": "dep-1", "status": "live"}],
            [{"serviceId": "srv-2", "id": "dep-2", "status": "live"}],
        ]
        # The bookmark advances to the next parent so a crash between parents resumes correctly.
        assert RenderResumeConfig(cursor=None, parent_id="srv-2") in result.saved_states

    def test_deleted_parent_404_is_skipped(self) -> None:
        result = _run(
            "deploys",
            [
                *_pages(self.SERVICES_PAGE),
                ScriptedResponse(status=404, json={"message": "Not Found"}),
                *_pages([{"deploy": {"id": "dep-2"}}]),
            ],
        )

        assert result.items == [[{"serviceId": "srv-2", "id": "dep-2"}]]

    OWNERS_PAGE = [{"owner": {"id": "tea-1", "type": "team"}}, {"owner": {"id": "tea-2", "type": "team"}}]

    @parameterized.expand(
        [
            # Render 400s /custom-domains for service types that can't have them (cron jobs, etc.).
            ("custom_domains_unsupported_service", "custom_domains", "customDomain", 400, "serviceId", "srv-2"),
            # Audit logs need a Pro workspace and an admin key: one ineligible workspace must not
            # fail the table for a key that spans several workspaces.
            ("audit_logs_bad_request", "audit_logs", "auditLog", 400, "ownerId", "tea-2"),
            ("audit_logs_forbidden", "audit_logs", "auditLog", 403, "ownerId", "tea-2"),
        ]
    )
    def test_ineligible_parent_is_skipped(
        self, _name: str, endpoint: str, wrapper_key: str, status: int, parent_key: str, second_parent: str
    ) -> None:
        parents_page = self.OWNERS_PAGE if parent_key == "ownerId" else self.SERVICES_PAGE
        result = _run(
            endpoint,
            [
                *_pages(parents_page),
                ScriptedResponse(status=status, json={"message": "rejected"}),
                *_pages([{wrapper_key: {"id": "row-2"}, "cursor": "c2"}], []),
            ],
            owner_id=None,
        )

        assert result.raised is None
        assert result.rows == [{parent_key: second_parent, "id": "row-2"}]

    @parameterized.expand([("bad_request", 400), ("forbidden", 403)])
    def test_rejected_parent_still_fails_for_endpoints_without_skip_flag(self, _name: str, status: int) -> None:
        result = _run(
            "deploys",
            [
                *_pages(self.SERVICES_PAGE),
                ScriptedResponse(status=status, json={"message": "rejected"}),
            ],
        )

        assert isinstance(result.raised, requests.HTTPError)

    @parameterized.expand(
        [
            ("instances", "services", "/v1/services/srv-1/instances", "serviceId", "srv-1"),
            ("members", "owners", "/v1/owners/tea-123/members", "ownerId", "tea-123"),
        ]
    )
    def test_unpaginated_child_is_fetched_once_per_parent(
        self, endpoint: str, parent: str, expected_path: str, parent_key: str, parent_id: str
    ) -> None:
        # These endpoints return the whole list in one response with no cursor. A long list must
        # not read as a truncated page, and the request must not carry pagination params.
        parent_wrapper = "service" if parent == "services" else "owner"
        children = [{"id": f"row-{i}", "createdAt": "2026-01-01T00:00:00Z"} for i in range(150)]
        result = _run(endpoint, _pages([{parent_wrapper: {"id": parent_id}}], children))

        child_requests = [request for request in result.requests if request.path == expected_path]
        assert len(child_requests) == 1
        assert child_requests[0].param("limit") is None
        assert len(result.rows) == 150
        assert result.rows[0] == {parent_key: parent_id, "id": "row-0", "createdAt": "2026-01-01T00:00:00Z"}

    def test_owner_scoped_source_only_fans_out_over_its_workspace(self) -> None:
        # /owners takes no ownerId filter, so a source scoped to one workspace must drop the
        # other workspaces itself before it reads their members or audit logs.
        result = _run(
            "members",
            _pages(
                [{"owner": {"id": "tea-999"}}, {"owner": {"id": "tea-123"}}],
                [{"userId": "usr-1", "name": "Ada", "role": "ADMIN"}],
            ),
        )

        assert result.paths == ["/v1/owners", "/v1/owners/tea-123/members"]
        assert result.rows == [{"ownerId": "tea-123", "userId": "usr-1", "name": "Ada", "role": "ADMIN"}]

    def test_audit_logs_walk_cursor_pages_per_workspace(self) -> None:
        with time_machine.travel(datetime(2026, 6, 1, tzinfo=UTC), tick=False):
            result = _run(
                "audit_logs",
                _pages(
                    [{"owner": {"id": "tea-123"}}],
                    [{"auditLog": {"id": "aud-1", "event": "CreateServerEvent"}, "cursor": "c1"}],
                    [{"auditLog": {"id": "aud-2", "event": "LoginEvent"}, "cursor": "c2"}],
                    [],
                ),
            )

        audit_requests = result.requests[1:]
        assert [request.path for request in audit_requests] == ["/v1/owners/tea-123/audit-logs"] * 3
        assert [request.param("cursor") for request in audit_requests] == [None, "c1", "c2"]
        assert {request.param("startTime") for request in audit_requests} == {"2026-03-04T00:00:00Z"}
        assert result.rows == [
            {"ownerId": "tea-123", "id": "aud-1", "event": "CreateServerEvent"},
            {"ownerId": "tea-123", "id": "aud-2", "event": "LoginEvent"},
        ]

    def test_resume_skips_parents_before_bookmark_and_seeds_cursor(self) -> None:
        result = _run(
            "deploys",
            _pages(self.SERVICES_PAGE, [{"deploy": {"id": "dep-5"}}]),
            resume_state=RenderResumeConfig(cursor="c-mid", parent_id="srv-2"),
        )

        deploy_requests = [request for request in result.requests if "/deploys" in request.path]
        assert len(deploy_requests) == 1
        assert deploy_requests[0].path == "/v1/services/srv-2/deploys"
        assert deploy_requests[0].param("cursor") == "c-mid"

    def test_environments_pass_project_id_as_query_param(self) -> None:
        result = _run(
            "environments",
            _pages(
                [{"project": {"id": "prj-1"}}],
                [{"environment": {"id": "env-1", "projectId": "prj-1"}}],
            ),
        )

        assert result.requests[1].path == "/v1/environments"
        assert result.requests[1].param("projectId") == "prj-1"

    def test_events_full_refresh_uses_service_created_at_as_window_start(self) -> None:
        # The events endpoint defaults to the last hour server-side; omitting startTime on a
        # full refresh would silently drop everything older.
        result = _run(
            "events",
            _pages(
                [{"service": {"id": "srv-1", "createdAt": "2024-01-01T00:00:00Z"}}],
                [{"event": {"id": "evt-1", "serviceId": "srv-1"}}],
            ),
        )

        assert result.requests[1].param("startTime") == "2024-01-01T00:00:00Z"


class TestSensitiveEndpointHandling:
    def test_env_group_secret_values_are_redacted_from_rows(self) -> None:
        # Env var values and secret-file contents are credentials the key is only meant to use
        # for sync; leaking them into a queryable table exposes database URLs and API tokens.
        result = _run(
            "env_groups",
            _pages(
                [
                    {
                        "id": "evg-1",
                        "name": "prod",
                        "envVars": [{"key": "DATABASE_URL", "value": "postgres://user:pw@host/db"}],
                        "secretFiles": [{"name": "config.yaml", "contents": "token: super-secret"}],
                    }
                ],
            ),
        )

        row = result.items[0][0]
        # Metadata survives so the table stays useful.
        assert row["id"] == "evg-1"
        assert row["name"] == "prod"
        assert row["envVars"][0]["key"] == "DATABASE_URL"
        assert row["secretFiles"][0]["name"] == "config.yaml"
        # The actual secrets do not.
        assert row["envVars"][0]["value"] == render.REDACTED_VALUE
        assert row["secretFiles"][0]["contents"] == render.REDACTED_VALUE

    @parameterized.expand(
        [
            # Sensitive endpoints skip sample capture — capture snapshots the raw response before
            # row-level redaction, so it would otherwise persist secrets to the sample store.
            ("env_groups", [{"id": "evg-1"}], False),
            ("owners", [{"owner": {"id": "own-1"}}], True),
        ]
    )
    def test_sample_capture_disabled_for_sensitive_endpoints(
        self, endpoint: str, page: list[dict], expected_capture: bool
    ) -> None:
        result = _run(endpoint, _pages(page))

        assert result.session_options == [{"capture": expected_capture}]


class TestFetchPage:
    def test_retryable_status_is_retried_until_success(self) -> None:
        result = _run(
            "owners",
            [ScriptedResponse(status=429, json={"message": "rate limited"}), *_pages([{"owner": {"id": "own-1"}}])],
        )

        assert result.rows == [{"id": "own-1"}]
        assert len(result.requests) == 2

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_persistent_retryable_status_raises_retryable_error(self, _name: str, status_code: int) -> None:
        result = _run("owners", always(ScriptedResponse(status=status_code, json={"message": "unavailable"})))

        assert isinstance(result.raised, RenderRetryableError)

    def test_auth_error_raises_without_retry(self) -> None:
        result = _run("owners", [ScriptedResponse(status=401, json={"message": "Unauthorized"})])

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestRenderSourceResponse:
    @parameterized.expand(
        [
            ("services", ["id"], ["createdAt"]),
            # Fan-out children key on (parent, id): a non-unique key multi-matches on every
            # delta merge and degrades each sync until the pod OOMs.
            ("deploys", ["serviceId", "id"], ["createdAt"]),
            ("events", ["serviceId", "id"], ["timestamp"]),
            ("owners", ["id"], None),
        ]
    )
    def test_source_response_keys_and_partitioning(
        self, endpoint: str, expected_primary_keys: list[str], expected_partition_keys: list[str] | None
    ) -> None:
        result = _run(endpoint, _pages([]))

        assert result.response is not None
        assert result.response.primary_keys == expected_primary_keys
        assert result.response.partition_keys == expected_partition_keys
        # Render documents no list ordering, so the watermark must only persist at job end.
        assert result.response.sort_mode == "desc"
