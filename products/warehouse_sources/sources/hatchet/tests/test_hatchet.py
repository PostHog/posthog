import json
import base64
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hatchet import (
    HatchetSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet import (
    HatchetHostNotAllowedError,
    HatchetResumeConfig,
    HatchetTokenError,
    _build_initial_params,
    _fetch_page,
    _resolve_since,
    resolve_connection,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.settings import HATCHET_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.source import HatchetSource

logger = structlog.get_logger()


def _make_token(claims: dict[str, Any]) -> str:
    """Build a JWT-shaped token whose (unverified) payload carries the given claims."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.signature"


class TestResolveConnection:
    @pytest.mark.parametrize("token", ["not-a-jwt", "only.two", ""])
    def test_malformed_token_raises_token_error(self, token):
        with pytest.raises(HatchetTokenError):
            resolve_connection(token)

    def test_missing_tenant_raises_token_error(self):
        token = _make_token({"server_url": "https://cloud.example"})

        with pytest.raises(HatchetTokenError):
            resolve_connection(token)


class TestResolveSince:
    def test_full_refresh_without_required_since_sends_nothing(self):
        config = HATCHET_ENDPOINTS["event_keys"]

        since = _resolve_since(config, should_use_incremental_field=False, db_incremental_field_last_value=None)

        assert since is None


class TestBuildInitialParams:
    def test_workflow_runs_carries_required_static_params(self):
        params = _build_initial_params(
            HATCHET_ENDPOINTS["workflow_runs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
        )

        # only_tasks and include_payloads are required/expected by the endpoint and must always be sent.
        assert params["only_tasks"] == "false"
        assert params["include_payloads"] == "true"
        assert params["limit"] == 100
        assert "since" in params


def _collect(tables: Iterable[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in tables:
        rows.extend(table.to_pylist())
    return rows


def _row(row_id: str) -> dict[str, Any]:
    return {"metadata": {"id": row_id, "createdAt": "2026-06-01T00:00:00Z", "updatedAt": "2026-06-01T00:00:00Z"}}


def _log(created_at: str, message: str) -> dict[str, Any]:
    return {
        "createdAt": created_at,
        "message": message,
        "metadata": {"source": "worker"},
        "taskExternalId": "11111111-1111-1111-1111-111111111111",
        "retryCount": 0,
        "attempt": 1,
        "level": "INFO",
    }


_LOG_BOUNDARY = "2026-06-01T00:00:01.000000Z"
_LOG_LATER = "2026-06-01T00:00:02.000000Z"

# 998 lines at distinct timestamps, then two identical lines at the boundary timestamp. The next
# window re-reads the boundary timestamp, which now also holds a third line.
_SPLIT_GROUP_SCRIPT = [
    ScriptedResponse(
        json={
            "rows": [_log(f"2026-06-01T00:00:00.{i:06d}Z", f"line {i}") for i in range(998)]
            + [_log(_LOG_BOUNDARY, "dup"), _log(_LOG_BOUNDARY, "dup")],
            "pagination": {},
        }
    ),
    ScriptedResponse(
        json={
            "rows": [
                _log(_LOG_BOUNDARY, "dup"),
                _log(_LOG_BOUNDARY, "new"),
                _log(_LOG_BOUNDARY, "dup"),
                _log(_LOG_LATER, "last"),
            ],
            "pagination": {},
        }
    ),
]

# A full page that holds one timestamp only, so its group is read on its own with a larger limit.
_SINGLE_TIMESTAMP_SCRIPT = [
    ScriptedResponse(json={"rows": [_log(_LOG_BOUNDARY, f"line {i}") for i in range(1000)], "pagination": {}}),
    ScriptedResponse(json={"rows": [_log(_LOG_BOUNDARY, f"line {i}") for i in range(1001)], "pagination": {}}),
    ScriptedResponse(json={"rows": [_log(_LOG_LATER, "last")], "pagination": {}}),
]


class TestGetRows:
    @staticmethod
    def _driver(host: str = "https://cloud.example") -> SourceDriver:
        token = _make_token({"sub": "tenant-1", "server_url": host})
        return SourceDriver(HatchetSource(), HatchetSourceConfig(api_token=token, host=None, tenant_id=None))

    def test_pagination_walks_offsets_until_num_pages_reached(self):
        full_page = [_row(f"p1-{i}") for i in range(100)]
        second_page = [_row(f"p2-{i}") for i in range(100)]
        result = self._driver().run(
            "workflow_runs",
            [
                ScriptedResponse(json={"rows": full_page, "pagination": {"current_page": 1, "num_pages": 2}}),
                ScriptedResponse(json={"rows": second_page, "pagination": {"current_page": 2, "num_pages": 2}}),
            ],
        )

        assert result.raised is None
        assert len(_collect(result.items)) == 200
        # Second request advances the offset by the page size.
        assert result.params("offset") == ["0", "100"]

    def test_resume_starts_from_saved_offset_and_pins_since(self):
        result = self._driver().run(
            "workflow_runs",
            [ScriptedResponse(json={"rows": [_row("x")], "pagination": {"current_page": 2, "num_pages": 2}})],
            resume_state=HatchetResumeConfig(offset=100, since="2026-01-01T00:00:00.000000Z"),
            should_use_incremental_field=True,
        )

        assert result.raised is None
        assert result.params("offset") == ["100"]
        # The window the interrupted run started on is replayed, not recomputed from a new watermark.
        assert result.params("since") == ["2026-01-01T00:00:00.000000Z"]

    def test_syncs_bare_top_level_array_response(self):
        # event_keys returns a top-level JSON array, not a `{"rows": [...]}` envelope; it must still
        # sync instead of silently loading zero rows.
        result = self._driver().run("event_keys", [ScriptedResponse(json=["user:signed_up", "billing:charged"])])

        assert result.raised is None
        assert _collect(result.items) == [{"key": "user:signed_up"}, {"key": "billing:charged"}]

    def test_unsafe_host_raises_before_any_fetch(self):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet._is_host_safe",
            return_value=(False, "Hosts with internal IP addresses are not allowed"),
        ):
            result = self._driver().run("workflow_runs", [], team_id=99)

        assert isinstance(result.raised, HatchetHostNotAllowedError)
        assert result.requests == []

    def test_plaintext_http_host_raises_on_cloud(self):
        # On cloud the bearer token must never go over plaintext http, even when the host passes the
        # SSRF check.
        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet._is_host_safe",
                return_value=(True, None),
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet.is_cloud",
                return_value=True,
            ),
        ):
            result = self._driver("http://cloud.example").run("workflow_runs", [])

        assert isinstance(result.raised, HatchetHostNotAllowedError)
        assert result.requests == []

    def test_session_disables_redirects_and_redacts_token(self):
        # The bearer token is sent to a user-controlled host, so the session must never follow a
        # redirect off it and must redact the token from captured samples/logs. Response bodies
        # carry opaque workflow payloads, so they must also be excluded from HTTP sample capture.
        page = {"rows": [_row("a")], "pagination": {"current_page": 1, "num_pages": 1}}
        driver = self._driver()
        result = driver.run("workflow_runs", [ScriptedResponse(json=page)])

        assert result.raised is None
        assert result.session_options[0]["allow_redirects"] is False
        assert result.session_options[0]["redact_values"] == (
            _make_token({"sub": "tenant-1", "server_url": "https://cloud.example"}),
        )
        assert result.session_options[0]["capture"] is False

    def test_fan_out_tags_child_rows_with_parent_run_and_skips_purged_runs(self):
        parent_page = {
            "rows": [
                {"metadata": {"id": "run-1", "createdAt": "2026-06-01T00:00:00Z", "updatedAt": "2026-06-01T00:00:00Z"}},
                {
                    "metadata": {
                        "id": "run-gone",
                        "createdAt": "2026-06-02T00:00:00Z",
                        "updatedAt": "2026-06-02T00:00:00Z",
                    }
                },
            ],
            "pagination": {"current_page": 1, "num_pages": 1},
        }
        result = self._driver().run(
            "task_events",
            [
                ScriptedResponse(json=parent_page),
                ScriptedResponse(
                    json={
                        "rows": [
                            {"id": 1, "taskId": "task-a", "eventType": "STARTED", "timestamp": "2026-06-01T00:00:01Z"},
                            {"id": 2, "taskId": "task-a", "eventType": "FINISHED", "timestamp": "2026-06-01T00:00:02Z"},
                        ],
                        "pagination": {},
                    }
                ),
                ScriptedResponse(status=404),
            ],
            should_use_incremental_field=True,
        )

        assert result.raised is None
        assert result.paths == [
            "/api/v1/stable/tenants/tenant-1/workflow-runs",
            "/api/v1/stable/workflow-runs/run-1/task-events",
            "/api/v1/stable/workflow-runs/run-gone/task-events",
        ]
        assert result.requests[0].param("include_payloads") == "false"
        rows = _collect(result.items)
        assert [(r["id"], r["workflow_run_id"], r["workflow_run_created_at"]) for r in rows] == [
            (1, "run-1", "2026-06-01T00:00:00Z"),
            (2, "run-1", "2026-06-01T00:00:00Z"),
        ]

    @pytest.mark.parametrize(
        "script,expected_rows,expected_since,expected_until,expected_limit",
        [
            (
                _SPLIT_GROUP_SCRIPT,
                1002,
                [None, "2026-06-01T00:00:00.999999Z"],
                [None, None],
                ["1000", "1000"],
            ),
            (
                _SINGLE_TIMESTAMP_SCRIPT,
                1002,
                [None, "2026-06-01T00:00:00.999999Z", "2026-06-01T00:00:01.000000Z"],
                [None, "2026-06-01T00:00:01.000001Z", None],
                ["1000", "10000", "1000"],
            ),
        ],
        ids=["group_split_across_pages", "page_of_one_timestamp"],
    )
    def test_logs_advance_since_window_without_losing_or_repeating_lines(
        self, script, expected_rows, expected_since, expected_until, expected_limit
    ):
        result = self._driver().run("logs", script)

        assert result.raised is None
        assert result.params("since") == expected_since
        assert result.params("until") == expected_until
        assert result.params("limit") == expected_limit
        assert result.params("order_by_direction") == ["ASC"] * len(script)
        rows = _collect(result.items)
        assert len(rows) == expected_rows
        assert len({row["id"] for row in rows}) == expected_rows
        # The log's own metadata stays a column; it is not the resource envelope other endpoints lift.
        assert json.loads(rows[0]["metadata"]) == {"source": "worker"}

    def test_logs_resume_from_saved_since(self):
        result = self._driver().run(
            "logs",
            [ScriptedResponse(json={"rows": [_log(_LOG_LATER, "last")], "pagination": {}})],
            resume_state=HatchetResumeConfig(offset=0, since="2026-06-01T00:00:00.999999Z"),
            should_use_incremental_field=True,
        )

        assert result.raised is None
        assert result.params("since") == ["2026-06-01T00:00:00.999999Z"]
        assert result.params("offset") == [None]

    def test_tenant_members_read_in_one_request(self):
        # The members endpoint has no pagination, so a full page must not trigger an offset request
        # that would read every member again.
        members = [
            {
                "metadata": {
                    "id": f"member-{i}",
                    "createdAt": "2026-06-01T00:00:00Z",
                    "updatedAt": "2026-06-01T00:00:00Z",
                },
                "user": {"email": f"user{i}@example.com"},
                "role": "MEMBER",
            }
            for i in range(150)
        ]
        result = self._driver().run("tenant_members", [ScriptedResponse(json={"rows": members})])

        assert result.raised is None
        assert result.paths == ["/api/v1/tenants/tenant-1/members"]
        assert result.params("offset") == [None]
        rows = _collect(result.items)
        assert len(rows) == 150
        assert rows[0]["id"] == "member-0"


class TestFetchPage:
    @pytest.mark.parametrize("allow_not_found", [True, False])
    def test_not_found_is_skipped_only_when_allowed(self, allow_not_found):
        response = requests.Response()
        response.status_code = 404
        session = mock.MagicMock()
        session.get.return_value = response

        if allow_not_found:
            assert _fetch_page(session, "https://cloud.example/x", {}, logger, allow_not_found=True) is None
        else:
            with pytest.raises(requests.HTTPError):
                _fetch_page(session, "https://cloud.example/x", {}, logger)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_valid",
        [(200, True), (401, False), (403, False), (404, False), (500, False)],
    )
    def test_status_mapping(self, status_code, expected_valid):
        token = _make_token({"sub": "tenant-1", "server_url": "https://cloud.example"})
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            valid, message = validate_credentials(token, None, None)

        assert valid is expected_valid
        if not expected_valid:
            assert message
        assert network.requests_log[0].path == "/api/v1/stable/tenants/tenant-1/events/keys"
        assert network.requests_log[0].headers["authorization"] == f"Bearer {token}"

    def test_undecodable_token_fails_without_network_call(self):
        with scripted_network([]) as network:
            valid, message = validate_credentials("garbage", None, None)

        assert valid is False
        assert message
        assert network.requests_log == []
        assert network.session_options == []

    def test_unsafe_host_fails_before_network_call(self):
        # A host resolving to an internal address must be rejected before the token is ever sent.
        token = _make_token({"sub": "tenant-1", "server_url": "https://internal.example"})

        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet._is_host_safe",
                return_value=(False, "Hosts with internal IP addresses are not allowed"),
            ),
            scripted_network([]) as network,
        ):
            valid, message = validate_credentials(token, None, None, team_id=99)

        assert valid is False
        assert message
        assert network.requests_log == []
        assert network.session_options == []

    def test_plaintext_http_host_fails_on_cloud(self):
        # On cloud, a plaintext http host must be rejected before the token is sent — even when the
        # host itself passes the SSRF check.
        token = _make_token({"sub": "tenant-1", "server_url": "http://cloud.example"})

        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet._is_host_safe",
                return_value=(True, None),
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hatchet.hatchet.is_cloud",
                return_value=True,
            ),
            scripted_network([]) as network,
        ):
            valid, message = validate_credentials(token, None, None, team_id=99)

        assert valid is False
        assert message
        assert network.requests_log == []
        assert network.session_options == []
