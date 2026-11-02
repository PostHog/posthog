from datetime import UTC, date, datetime
from typing import Any

import time_machine

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deno_deploy.deno_deploy import (
    DENO_DEPLOY_ENDPOINTS,
    DenoDeployResumeConfig,
    _as_utc_datetime,
    _format_rfc3339,
    _time_window_params,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.deno_deploy.source import DenoDeploySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.denodeploy import (
    DenoDeploySourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(DenoDeploySource(), DenoDeploySourceConfig(access_token="ddo_test"))


class TestPureHelpers:
    @parameterized.expand(
        [
            ("utc", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_treated_as_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_rfc3339(self, _name: str, value: datetime, expected: str) -> None:
        result = _format_rfc3339(value)
        assert result == expected
        assert "+00:00" not in result

    @time_machine.travel("2026-06-01T12:00:00Z", tick=False)
    def test_time_window_future_watermark_clamped(self) -> None:
        start, end = _time_window_params(DENO_DEPLOY_ENDPOINTS["analytics"], True, datetime(2027, 1, 1, tzinfo=UTC))
        assert start == "2026-06-01T11:30:00Z"  # min(future, now) - 30min lookback
        assert end == "2026-06-01T12:00:00Z"

    @parameterized.expand([("date", date(2026, 1, 1), True), ("string", "cursor", False)])
    def test_as_utc_datetime(self, _name: str, value: Any, coerces: bool) -> None:
        result = _as_utc_datetime(value)
        if coerces:
            assert result is not None and result.tzinfo is UTC
        else:
            assert result is None


class TestListEndpoint:
    def test_apps_follows_link_header_and_checkpoints(self) -> None:
        result = _driver().run(
            "apps",
            [
                ScriptedResponse(
                    json=[{"id": "a1", "slug": "one"}],
                    headers={"Link": '<https://api.deno.com/v2/apps?cursor=p2&limit=100>; rel="next"'},
                ),
                ScriptedResponse(json=[{"id": "a2", "slug": "two"}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a1", "a2"]  # rows used as-is, both pages
        assert result.params("cursor") == [None, "p2"]
        # Checkpoint saved after the first page points at the not-yet-fetched next URL.
        assert result.saved_states == [
            DenoDeployResumeConfig(next_url="https://api.deno.com/v2/apps?cursor=p2&limit=100")
        ]

    def test_apps_resumes_from_saved_url(self) -> None:
        result = _driver().run(
            "apps",
            [ScriptedResponse(json=[{"id": "a2", "slug": "two"}])],
            resume_state=DenoDeployResumeConfig(next_url="https://api.deno.com/v2/apps?cursor=p2"),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["a2"]
        assert result.queries == [{"cursor": ("p2",)}]  # resumed URL has no default first-page limit


class TestFanOut:
    def test_revisions_inject_parent_app_context(self) -> None:
        result = _driver().run(
            "revisions",
            [
                ScriptedResponse(json=[{"id": "a1", "slug": "one"}, {"id": "a2", "slug": "two"}]),  # /v2/apps
                ScriptedResponse(json=[{"id": "r1", "status": "success"}]),  # a1 revisions
                ScriptedResponse(json=[{"id": "r2", "status": "failed"}]),  # a2 revisions
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "r1", "status": "success", "app_id": "a1", "app_slug": "one"},
            {"id": "r2", "status": "failed", "app_id": "a2", "app_slug": "two"},
        ]
        assert result.params("limit")[1:] == ["100", "100"]  # child list uses the default page size

    @time_machine.travel("2026-06-01T12:00:00Z", tick=False)
    def test_logs_paginate_via_next_cursor(self) -> None:
        result = _driver().run(
            "logs",
            [
                ScriptedResponse(json=[{"id": "a1", "slug": "one"}]),  # /v2/apps
                ScriptedResponse(
                    json={"logs": [{"timestamp": "2026-06-01T10:00:00Z", "message": "m1"}], "next_cursor": "c2"}
                ),
                ScriptedResponse(
                    json={"logs": [{"timestamp": "2026-06-01T11:00:00Z", "message": "m2"}], "next_cursor": None}
                ),
            ],
            should_use_incremental_field=True,
        )

        assert result.raised is None
        assert [row["message"] for row in result.rows] == ["m1", "m2"]
        assert all(len(row["id"]) == 64 and row["app_id"] == "a1" and row["app_slug"] == "one" for row in result.rows)
        # First logs page carries the bounded window; the second follows the body cursor.
        assert result.requests[1].param("start")
        assert result.requests[1].param("end")
        assert result.requests[1].param("limit") == "1000"
        assert result.requests[1].param("cursor") is None
        assert result.requests[2].param("cursor") == "c2"
        # Checkpoint persists the fan-out resume snapshot carrying the cursor.
        assert any(
            state.fanout_state and state.fanout_state.get("child_state") == {"cursor": "c2"}
            for state in result.saved_states
        )

    @time_machine.travel("2026-06-01T12:00:00Z", tick=False)
    def test_analytics_columnar_explode_with_window(self) -> None:
        result = _driver().run(
            "analytics",
            [
                ScriptedResponse(json=[{"id": "a1", "slug": "one"}]),  # /v2/apps
                ScriptedResponse(
                    json={
                        "fields": [{"name": "time"}, {"name": "request_count"}],
                        "values": [["2026-06-01T00:00:00Z", 5], ["2026-06-01T00:15:00Z", 9]],
                    }
                ),
            ],
            should_use_incremental_field=True,
        )

        assert result.raised is None
        assert result.rows == [
            {"time": "2026-06-01T00:00:00Z", "request_count": 5, "app_id": "a1", "app_slug": "one"},
            {"time": "2026-06-01T00:15:00Z", "request_count": 9, "app_id": "a1", "app_slug": "one"},
        ]
        # Server-side time filters are present.
        assert result.requests[1].param("since") and result.requests[1].param("until")

    def test_fanout_resumes_and_skips_completed_app(self) -> None:
        result = _driver().run(
            "revisions",
            [
                ScriptedResponse(json=[{"id": "a1", "slug": "one"}, {"id": "a2", "slug": "two"}]),  # /v2/apps
                ScriptedResponse(json=[{"id": "r2", "status": "success"}]),  # a2 revisions only
            ],
            resume_state=DenoDeployResumeConfig(
                fanout_state={"completed": ["/v2/apps/a1/revisions"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["r2"]  # a1 skipped, resumed at a2
        assert result.rows[0]["app_id"] == "a2"
        assert result.paths == ["/v2/apps", "/v2/apps/a2/revisions"]  # apps list + a2 only


class TestSsrfGuards:
    def test_off_host_link_is_rejected(self) -> None:
        result = _driver().run(
            "apps",
            [
                ScriptedResponse(
                    json=[{"id": "a1", "slug": "one"}],
                    headers={"Link": '<https://evil.example.com/v2/apps?cursor=p2>; rel="next"'},
                ),
                ScriptedResponse(json=[{"id": "a2", "slug": "two"}]),
            ],
        )
        assert isinstance(result.raised, ValueError)
        assert "disallowed host" in str(result.raised)
        assert result.paths == ["/v2/apps"]

    def test_redirect_is_rejected(self) -> None:
        result = _driver().run(
            "apps", [ScriptedResponse(status=302, json={}, headers={"Location": "https://evil.example.com"})]
        )
        assert isinstance(result.raised, ValueError)
        assert "redirect" in str(result.raised).lower()
        assert result.paths == ["/v2/apps"]


class TestSourceResponse:
    @parameterized.expand(
        [
            ("apps", ["id"], "created_at", False),
            ("revisions", ["app_id", "id"], "created_at", False),
            ("domains", ["id"], "created_at", False),
            ("analytics", ["app_id", "time"], "time", True),
            ("logs", ["id"], "timestamp", True),
        ]
    )
    def test_response_shape(self, endpoint: str, pk: list[str], partition: str, incremental: bool) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])], should_use_incremental_field=incremental)
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == pk
        assert response.partition_keys == [partition]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "week"
        assert response.sort_mode == "asc"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_ok: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            ok, error = validate_credentials("ddo_test")
        assert ok is expected_ok
        assert (error is None) is expected_ok
        assert network.requests_log[0].path == "/v2/apps"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer ddo_test"

    def test_network_error_is_swallowed(self) -> None:
        with scripted_network([ConnectionResetError("reset")]) as network:
            ok, error = validate_credentials("ddo_test")
        assert ok is False
        assert error is not None
        assert network.requests_log[0].path == "/v2/apps"
