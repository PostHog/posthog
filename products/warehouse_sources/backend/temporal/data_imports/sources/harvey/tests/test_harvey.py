from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.harvey import HarveySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.harvey.harvey import (
    HarveyResumeConfig,
    HarveyRetryableError,
    _parse_datetime,
    _to_epoch,
    check_endpoint_access,
    get_base_url,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.harvey.settings import MAX_LOOKBACK_DAYS
from products.warehouse_sources.backend.temporal.data_imports.sources.harvey.source import HarveySource

NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
NOW_EPOCH = int(NOW.timestamp())

HARVEY_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.harvey.harvey"


class _FakeManager:
    def __init__(self, resume: HarveyResumeConfig | None = None) -> None:
        self._resume = resume
        self.saved: list[HarveyResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume is not None

    def load_state(self) -> HarveyResumeConfig | None:
        return self._resume

    def save_state(self, data: HarveyResumeConfig) -> None:
        self.saved.append(data)

    def safe_point(self) -> None:
        pass


def _driver() -> SourceDriver:
    return SourceDriver(HarveySource(), HarveySourceConfig(api_key="token", region="us"))


def _vault_page(project_ids: list[str], page: int = 1, total_pages: int = 1) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "response": {
                "content": {
                    "projects": [{"id": project_id, "name": project_id} for project_id in project_ids],
                    "pagination": {"page": page, "per_page": 100, "total": 0, "total_pages": total_pages},
                }
            }
        }
    )


def _audit_log(log_id: str, timestamp: str = "2026-06-01T10:00:00+00:00") -> dict[str, Any]:
    return {
        "id": log_id,
        "timestamp": timestamp,
        "type": "auth:login",
        "user": "user@example.com",
        "ip": "203.0.113.10",
        "user_agent": "curl/8.0",
        "data": {},
    }


def _history_event(usage_id: str, utc_time: str = "2026-07-01 10:30:00") -> dict[str, Any]:
    return {
        "unique_usage_id": usage_id,
        "utc_time": utc_time,
        "user": "user@example.com",
        "product_surface_area": "ASSISTANT",
        "metadata": {},
    }


class TestHelpers:
    @parameterized.expand(
        [
            ("us", "us", "https://api.harvey.ai"),
            ("eu", "eu", "https://eu.api.harvey.ai"),
            ("au", "au", "https://au.api.harvey.ai"),
            ("uppercase", "US", "https://api.harvey.ai"),
            ("none", None, "https://api.harvey.ai"),
            ("unknown", "unknown", "https://api.harvey.ai"),
        ]
    )
    def test_get_base_url(self, _name: str, region: str | None, expected: str) -> None:
        assert get_base_url(region) == expected

    @parameterized.expand(
        [
            ("iso_offset", "2026-06-01T10:00:00+00:00", datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)),
            ("iso_z", "2026-06-01T10:00:00Z", datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)),
            ("space_separated", "2026-02-22 14:01:23", datetime(2026, 2, 22, 14, 1, 23, tzinfo=UTC)),
            ("naive_datetime", datetime(2026, 6, 1, 10, 0, 0), datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)),
            ("unparseable_string", "not a timestamp", None),
            ("none", None, None),
            ("int", 12345, None),
        ]
    )
    def test_parse_datetime(self, _name: str, value: Any, expected: datetime | None) -> None:
        assert _parse_datetime(value) == expected

    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC), NOW_EPOCH),
            ("naive_datetime", datetime(2026, 7, 1, 12, 0, 0), NOW_EPOCH),
            ("date", date(2026, 7, 1), NOW_EPOCH - 12 * 60 * 60),
            ("int", NOW_EPOCH, NOW_EPOCH),
            ("float", float(NOW_EPOCH), NOW_EPOCH),
            ("iso_string", "2026-07-01T12:00:00+00:00", NOW_EPOCH),
        ]
    )
    def test_to_epoch(self, _name: str, value: Any, expected: int) -> None:
        assert _to_epoch(value) == expected

    def test_to_epoch_rejects_unparseable_values(self) -> None:
        with pytest.raises(ValueError):
            _to_epoch("not a timestamp")

    @parameterized.expand([("throttle", 429), ("server_error", 500), ("unavailable", 503)])
    def test_fetch_json_raises_retryable_on_throttle_and_server_errors(self, _name: str, status_code: int) -> None:
        result = _driver().run("client_matters", always(ScriptedResponse(status=status_code, json={})))

        assert isinstance(result.raised, HarveyRetryableError)
        assert set(result.paths) == {"/api/v1/client_matters"}

    def test_fetch_json_raises_http_error_on_client_errors(self) -> None:
        result = _driver().run("client_matters", [ScriptedResponse(status=401, json={"error": "Unauthorized"})])

        assert isinstance(result.raised, HTTPError)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ],
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            assert validate_credentials("token", "us") is expected

        assert {request.url for request in network.requests_log} == {"https://api.harvey.ai/api/whoami"}


class TestCheckEndpointAccess:
    @parameterized.expand(
        [
            ("audit_logs", "audit_logs", "/api/v1/logs/audit/latest"),
            ("usage_history", "usage_history", "/api/v2/history/usage"),
            ("query_history", "query_history", "/api/v2/history/query"),
            ("client_matters", "client_matters", "/api/v1/client_matters"),
            ("vault_projects", "vault_projects", "/api/v1/vault/workspace/projects"),
        ]
    )
    def test_probes_the_right_endpoint(self, _name: str, endpoint: str, expected_path: str) -> None:
        with scripted_network([ScriptedResponse(json={})]) as network:
            assert check_endpoint_access("token", "us", endpoint) is None

        assert network.requests_log[0].path == expected_path

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_denial_returns_reason(self, _name: str, status_code: int) -> None:
        with scripted_network([ScriptedResponse(status=status_code, json={})]):
            reason = check_endpoint_access("token", "us", "audit_logs")

        assert reason is not None
        assert "permission" in reason

    @parameterized.expand([("not_found", 404), ("throttle", 429), ("server_error", 500)])
    def test_non_denial_statuses_are_reachable(self, _name: str, status_code: int) -> None:
        with scripted_network([ScriptedResponse(status=status_code, json={})]):
            assert check_endpoint_access("token", "us", "audit_logs") is None

    def test_network_error_is_reachable(self) -> None:
        with scripted_network(always(ConnectionError("boom"))):
            assert check_endpoint_access("token", "us", "audit_logs") is None

    @parameterized.expand(
        [
            ("vault_project_users", "vault_project_users", "/api/v1/vault/projects/proj-1/users"),
            ("vault_project_files", "vault_project_files", "/api/v1/vault/projects/proj-1/files"),
            ("review_tables", "review_tables", "/api/v1/vault/get_metadata/proj-1"),
            ("review_table_rows", "review_table_rows", "/api/v1/vault/get_metadata/proj-1"),
        ]
    )
    def test_fan_out_probes_child_endpoint_of_first_project(
        self, _name: str, endpoint: str, expected_path: str
    ) -> None:
        with scripted_network([_vault_page(["proj-1"]), ScriptedResponse(status=403, json={})]) as network:
            reason = check_endpoint_access("token", "us", endpoint)

        assert reason is not None
        assert network.requests_log[0].path == "/api/v1/vault/workspace/projects"
        assert network.requests_log[1].path == expected_path

    def test_fan_out_probe_without_projects_is_reachable(self) -> None:
        with scripted_network([_vault_page([])]) as network:
            assert check_endpoint_access("token", "us", "vault_project_users") is None

        assert len(network.requests_log) == 1


class TestSessionRedaction:
    # A dropped `redact_values` would copy the bearer token into captured request samples and logged
    # errors, leaking the credential into warehouse job telemetry. Every request-issuing entry point
    # must build its session with the token registered for redaction.
    @parameterized.expand(
        [
            ("validate_credentials", "validate_credentials"),
            ("check_endpoint_access", "check_endpoint_access"),
            ("get_rows", "get_rows"),
        ]
    )
    def test_tracked_session_redacts_api_token(self, _name: str, entrypoint: str) -> None:
        if entrypoint == "get_rows":
            result = _driver().run("client_matters", [ScriptedResponse(json={})])
            assert result.raised is None
            options = result.session_options
        else:
            with scripted_network([ScriptedResponse(json={})]) as network:
                if entrypoint == "validate_credentials":
                    validate_credentials("token", "us")
                else:
                    check_endpoint_access("token", "us", "audit_logs")
            options = network.session_options

        assert options[0]["redact_values"] == ("token",)


class TestHttpSampleCapture:
    # Capture is off by default (Harvey serves confidential legal/business data); only endpoints
    # returning purely structured metrics opt back in. usage_history is the lone opt-in; every other
    # endpoint returns free-text names, descriptions, audit metadata, or prompt/response content that
    # would leak past the scrubbers, so their sessions must be built with capture=False. A regression
    # here (flipping the default back on or dropping the per-endpoint flag) would re-introduce the leak.
    @parameterized.expand(
        [
            # History endpoints resume at `now` so the window loop makes no request - the session is
            # still built up front, which is where the capture flag is decided.
            ("query_history", "query_history", HarveyResumeConfig(window_start=NOW_EPOCH), [], False),
            ("usage_history", "usage_history", HarveyResumeConfig(window_start=NOW_EPOCH), [], True),
            ("client_matters", "client_matters", None, [ScriptedResponse(json=[])], False),
            (
                "audit_logs",
                "audit_logs",
                HarveyResumeConfig(last_audit_log_id="log-1"),
                [ScriptedResponse(json=[])],
                False,
            ),
            (
                "vault_projects",
                "vault_projects",
                HarveyResumeConfig(next_page=1),
                [ScriptedResponse(json={"response": {"content": {"projects": []}}})],
                False,
            ),
            (
                "review_table_rows",
                "review_table_rows",
                HarveyResumeConfig(next_page=1),
                [ScriptedResponse(json={"response": {"content": {"projects": []}}})],
                False,
            ),
        ]
    )
    def test_get_rows_capture_flag(
        self,
        _name: str,
        endpoint: str,
        resume: HarveyResumeConfig | None,
        responses: list[ScriptedResponse],
        expected_capture: bool,
    ) -> None:
        with time_machine.travel(NOW, tick=False):
            result = _driver().run(endpoint, responses, resume_state=resume)

        assert result.raised is None
        assert result.session_options[0]["capture"] is expected_capture

    @parameterized.expand(
        [
            ("usage_history", "usage_history", True),
            ("query_history", "query_history", False),
            ("audit_logs", "audit_logs", False),
        ]
    )
    def test_check_endpoint_access_capture_flag(self, _name: str, endpoint: str, expected_capture: bool) -> None:
        with scripted_network([ScriptedResponse(json={})]) as network:
            check_endpoint_access("token", "us", endpoint)

        assert network.session_options[0]["capture"] is expected_capture


class TestAuditLogRows:
    def test_full_sync_no_logs(self) -> None:
        result = _driver().run("audit_logs", [ScriptedResponse(status=404, json={"error": "Not found"})])

        assert result.raised is None
        assert result.items == []
        assert result.saved_states == []

    @time_machine.travel(NOW, tick=False)
    def test_incremental_seeds_from_search(self) -> None:
        last_value = datetime(2026, 6, 30, 9, 0, 0, tzinfo=UTC)
        result = _driver().run(
            "audit_logs",
            [
                ScriptedResponse(json={"log": _audit_log("log-a")}),
                ScriptedResponse(json=[_audit_log("log-b")]),
            ],
            incremental_field="timestamp",
            db_incremental_field_last_value=last_value,
        )

        assert result.paths[0] == "/api/v1/logs/audit/search"
        assert result.queries[0] == {"time": (str(int(last_value.timestamp())),)}
        assert [[log["id"] for log in batch] for batch in result.items] == [["log-a"], ["log-b"]]
        assert result.raised is None

    @time_machine.travel(NOW, tick=False)
    def test_incremental_caught_up(self) -> None:
        # No log at or after the watermark - the search endpoint 404s.
        result = _driver().run(
            "audit_logs",
            [ScriptedResponse(status=404, json={"error": "Not found"})],
            incremental_field="timestamp",
            db_incremental_field_last_value=NOW,
        )

        assert result.items == []
        assert result.raised is None

    @time_machine.travel(NOW, tick=False)
    def test_incremental_watermark_older_than_search_limit_falls_back_to_earliest(self) -> None:
        stale_watermark = datetime(2024, 1, 1, tzinfo=UTC)
        result = _driver().run(
            "audit_logs",
            [
                ScriptedResponse(json={"log": _audit_log("log-a")}),
                ScriptedResponse(json=[]),
            ],
            incremental_field="timestamp",
            db_incremental_field_last_value=stale_watermark,
        )

        assert result.urls[0] == "https://api.harvey.ai/api/v1/logs/audit/earliest"
        assert result.raised is None


class TestHistoryRows:
    @parameterized.expand(
        [
            ("usage_history", "usage_history", "/api/v2/history/usage"),
            ("query_history", "query_history", "/api/v2/history/query"),
        ]
    )
    @time_machine.travel(NOW, tick=False)
    def test_incremental_fetches_windows_up_to_now(self, _name: str, endpoint: str, expected_path: str) -> None:
        last_value = datetime(2026, 7, 1, 10, 0, 0, tzinfo=UTC)
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={"events": [_history_event("usage-1")]})],
            incremental_field="utc_time",
            db_incremental_field_last_value=last_value,
        )

        assert result.paths == [expected_path]
        assert result.queries[0] == {
            "start_time": (str(int(last_value.timestamp())),),
            "end_time": (str(NOW_EPOCH),),
        }
        assert [[event["unique_usage_id"] for event in batch] for batch in result.items] == [["usage-1"]]
        # utc_time is parsed so the incremental watermark and partitioning see a datetime.
        assert result.rows[0]["utc_time"] == datetime(2026, 7, 1, 10, 30, 0, tzinfo=UTC)
        assert [state.window_start for state in result.saved_states] == [NOW_EPOCH]
        assert result.raised is None

    @time_machine.travel(NOW, tick=False)
    def test_full_sync_starts_at_lookback_floor(self) -> None:
        # Widen the window so the full backfill is a single request.
        with mock.patch(f"{HARVEY_MODULE}.HISTORY_WINDOW_SECONDS", 400 * 24 * 60 * 60):
            result = _driver().run("usage_history", [ScriptedResponse(json={"events": []})])

        assert result.requests[0].param("start_time") == str(NOW_EPOCH - MAX_LOOKBACK_DAYS * 24 * 60 * 60)
        assert result.requests[0].param("end_time") == str(NOW_EPOCH)
        assert result.raised is None


class TestClientMatterRows:
    def test_single_unpaginated_fetch(self) -> None:
        matters = [
            {"id": "cm-1", "name": "1234-5678", "user_count": 3},
            {"id": "cm-2", "name": "8765-4321", "user_count": 1},
        ]
        result = _driver().run("client_matters", [ScriptedResponse(json=matters)])

        assert result.items == [matters]
        assert result.urls == ["https://api.harvey.ai/api/v1/client_matters"]
        assert result.raised is None


class TestVaultProjectRows:
    def test_multiple_pages_save_state_between_pages(self) -> None:
        result = _driver().run(
            "vault_projects",
            [
                _vault_page(["proj-1"], page=1, total_pages=2),
                _vault_page(["proj-2"], page=2, total_pages=2),
            ],
        )

        assert len(result.items) == 2
        assert result.requests[1].param("page") == "2"
        assert [state.next_page for state in result.saved_states] == [2]
        assert result.raised is None


class TestProjectFanOutRows:
    def _users(self, project_id: str, user_ids: list[str]) -> ScriptedResponse:
        return ScriptedResponse(
            json={
                "status": "COMPLETED",
                "data": {
                    "project_id": project_id,
                    "users": [{"user_id": user_id, "access_level": "READ"} for user_id in user_ids],
                },
            }
        )

    def test_forbidden_project_users_raise(self) -> None:
        result = _driver().run("vault_project_users", [_vault_page(["proj-1"]), ScriptedResponse(status=403, json={})])

        assert isinstance(result.raised, HTTPError)

    def test_fan_out_saves_projects_page_after_its_children(self) -> None:
        result = _driver().run(
            "vault_project_users",
            [
                _vault_page(["proj-1"], page=1, total_pages=2),
                self._users("proj-1", ["user-1"]),
                _vault_page(["proj-2"], page=2, total_pages=2),
                self._users("proj-2", ["user-2"]),
            ],
        )

        assert len(result.items) == 2
        assert result.requests[2].param("page") == "2"
        assert [state.next_page for state in result.saved_states] == [2]
        assert result.raised is None

    def _files_page(self, file_ids: list[str], next_cursor: str | None) -> ScriptedResponse:
        return ScriptedResponse(
            json={
                "response": {
                    "content": {
                        "files": [
                            {"id": file_id, "name": f"{file_id}.pdf", "size": 10, "uploaded_at": 1767225600}
                            for file_id in file_ids
                        ],
                        "pagination": {
                            "page_size": len(file_ids),
                            "has_more": next_cursor is not None,
                            "next_cursor": next_cursor,
                            "total_count": 3,
                        },
                    }
                }
            }
        )

    def test_project_files_follow_cursor_until_has_more_is_false(self) -> None:
        result = _driver().run(
            "vault_project_files",
            [
                _vault_page(["proj-1"]),
                self._files_page(["file-1", "file-2"], next_cursor="cursor-abc"),
                self._files_page(["file-3"], next_cursor=None),
            ],
        )

        rows = result.rows
        assert [(row["project_id"], row["id"]) for row in rows] == [
            ("proj-1", "file-1"),
            ("proj-1", "file-2"),
            ("proj-1", "file-3"),
        ]
        assert rows[0]["uploaded_at"] == datetime(2026, 1, 1, tzinfo=UTC)

        first, second = result.requests[1:]
        assert first.param("cursor") is None
        assert second.param("cursor") == "cursor-abc"
        assert first.param("sort_by") == "uploaded_at"
        assert first.param("sort_order") == "asc"
        assert result.raised is None

    @parameterized.expand(
        [
            ("consecutive_repeat", ["cursor-a", "cursor-a"]),
            ("cycle", ["cursor-a", "cursor-b", "cursor-a"]),
        ]
    )
    def test_project_files_reject_cursor_cycles(self, _name: str, cursors: list[str]) -> None:
        result = _driver().run(
            "vault_project_files",
            [
                _vault_page(["proj-1"]),
                *(self._files_page([f"file-{index}"], next_cursor=cursor) for index, cursor in enumerate(cursors)),
            ],
        )

        assert isinstance(result.raised, HarveyRetryableError)
        assert "repeated Vault project files cursor" in str(result.raised)

    @parameterized.expand(
        [
            # The spec documents an object but its example wraps the metadata in a list.
            ("list_content", [{"project_id": "proj-1", "review_table_ids": [11, 12]}]),
            ("object_content", {"project_id": "proj-1", "review_table_ids": [11, 12]}),
        ]
    )
    def test_review_tables_are_enumerated_from_project_metadata(self, _name: str, metadata_content: Any) -> None:
        result = _driver().run(
            "review_tables",
            [
                _vault_page(["proj-1"]),
                ScriptedResponse(status=201, json={"response": {"content": metadata_content}}),
                ScriptedResponse(
                    json={"response": {"content": {"review_table_id": 11, "title": "Leases", "file_ids": ["f-1"]}}}
                ),
                ScriptedResponse(status=404, json={}),
            ],
        )

        assert result.items == [
            [{"review_table_id": 11, "title": "Leases", "file_ids": ["f-1"], "project_id": "proj-1"}]
        ]
        assert result.paths[2] == "/api/v1/vault/review_table/11"
        assert result.raised is None

    def test_review_table_rows_fetch_one_row_per_file(self) -> None:
        cells = {"cells": [{"column_name": "Start date", "summary": "February 7, 2011"}]}
        result = _driver().run(
            "review_table_rows",
            [
                _vault_page(["proj-1"]),
                ScriptedResponse(status=201, json={"response": {"content": [{"review_table_ids": [11]}]}}),
                ScriptedResponse(json={"response": {"content": {"review_table_id": 11, "file_ids": ["f-1", "f-2"]}}}),
                ScriptedResponse(
                    json={
                        "event_id": 11,
                        "file_id": "f-1",
                        "updated_at": "Wed, 10 Dec 2025 00:38:49 GMT",
                        "response": cells,
                    },
                ),
                # A file without a row of its own or a file group row.
                ScriptedResponse(status=404, json={}),
            ],
        )

        assert result.items == [
            [
                {
                    "event_id": 11,
                    "file_id": "f-1",
                    "updated_at": datetime(2025, 12, 10, 0, 38, 49, tzinfo=UTC),
                    "response": cells,
                    "review_table_id": 11,
                    "project_id": "proj-1",
                }
            ]
        ]
        assert result.paths[3:] == [
            "/api/v1/vault/get_row/11/f-1",
            "/api/v1/vault/get_row/11/f-2",
        ]
        assert result.raised is None


class TestHarveySourceResponse:
    @parameterized.expand(
        [
            ("audit_logs", "audit_logs", ["id"], ["timestamp"]),
            ("usage_history", "usage_history", ["unique_usage_id"], ["utc_time"]),
            ("query_history", "query_history", ["unique_usage_id"], ["utc_time"]),
            ("client_matters", "client_matters", ["id"], None),
            ("vault_projects", "vault_projects", ["id"], None),
        ]
    )
    def test_source_response_shape(
        self, _name: str, endpoint: str, primary_keys: list[str], partition_keys: list[str] | None
    ) -> None:
        if endpoint in ("usage_history", "query_history"):
            script: list[ScriptedResponse] = []
            resume = HarveyResumeConfig(window_start=NOW_EPOCH)
        elif endpoint == "audit_logs":
            script = [ScriptedResponse(status=404, json={})]
            resume = None
        elif endpoint == "client_matters":
            script = [ScriptedResponse(json=[])]
            resume = None
        else:
            script = [_vault_page([])]
            resume = None

        with time_machine.travel(NOW, tick=False):
            result = _driver().run(endpoint, script, resume_state=resume)

        response = result.response
        assert response is not None
        assert result.raised is None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == partition_keys
        assert response.partition_mode == ("datetime" if partition_keys else None)
        assert response.sort_mode is None

    def test_unknown_endpoint_raises(self) -> None:
        with mock.patch(f"{HARVEY_MODULE}.make_tracked_session", return_value=mock.MagicMock()):
            with pytest.raises(ValueError):
                list(
                    get_rows(
                        api_key="token",
                        region="us",
                        endpoint="nonexistent",
                        logger=mock.MagicMock(),
                        resumable_source_manager=_FakeManager(),  # type: ignore[arg-type]
                    )
                )
