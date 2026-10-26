import json
from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zero import ZeroSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zero.source import ZeroSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zero.zero import ZeroResumeConfig

WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"
OTHER_WORKSPACE_ID = "22222222-2222-2222-2222-222222222222"


def _page(rows: list[dict[str, Any]], total: int) -> ScriptedResponse:
    return ScriptedResponse(json={"data": rows, "total": total})


def _drive(
    endpoint: str,
    responses: list[ScriptedResponse],
    workspace_id: str | None = WORKSPACE_ID,
    resume_state: ZeroResumeConfig | None = None,
    **inputs: Any,
) -> DriveResult:
    driver = SourceDriver(ZeroSource(), ZeroSourceConfig(api_key="test-key", workspace_id=workspace_id))
    return driver.run(endpoint, responses, resume_state=resume_state, **inputs)


class TestZeroPagination:
    def test_walks_offset_pages_and_saves_the_next_offset(self) -> None:
        responses = [
            _page([{"id": f"c{i}"} for i in range(100)], total=250),
            _page([{"id": f"c{i}"} for i in range(100, 200)], total=250),
            _page([{"id": f"c{i}"} for i in range(200, 250)], total=250),
        ]
        result = _drive("Companies", responses)

        assert result.raised is None
        assert result.paths == ["/api/companies"] * 3
        assert result.params("offset") == ["0", "100", "200"]
        assert [request.headers["authorization"] for request in result.requests] == ["Bearer test-key"] * 3
        assert [row["id"] for row in result.rows] == [f"c{i}" for i in range(250)]
        assert result.saved_states == [ZeroResumeConfig(offset=100), ZeroResumeConfig(offset=200)]

    def test_resume_starts_from_the_saved_offset(self) -> None:
        result = _drive("Companies", [_page([{"id": "c200"}], total=201)], resume_state=ZeroResumeConfig(offset=200))

        assert result.raised is None
        assert result.params("offset") == ["200"]


class TestZeroRequestShaping:
    @pytest.mark.parametrize(
        ("endpoint", "workspace_id", "inputs", "expected_where"),
        [
            pytest.param("Companies", WORKSPACE_ID, {}, {"workspaceId": WORKSPACE_ID}, id="full_refresh_scoped"),
            pytest.param("Companies", None, {}, None, id="full_refresh_all_workspaces"),
            pytest.param("Workspaces", WORKSPACE_ID, {}, {"id": WORKSPACE_ID}, id="workspace_row_scoped_by_id"),
            pytest.param(
                "Users",
                WORKSPACE_ID,
                {
                    "should_use_incremental_field": True,
                    "incremental_field": "updatedAt",
                    "db_incremental_field_last_value": datetime(2026, 1, 1, 12, tzinfo=UTC),
                },
                {"updatedAt": {"$gt": "2026-01-01T12:00:00+00:00"}},
                id="users_have_no_workspace_scope",
            ),
            pytest.param(
                "MeetingTranscripts",
                WORKSPACE_ID,
                {
                    "should_use_incremental_field": True,
                    "incremental_field": "createdAt",
                    "db_incremental_field_last_value": date(2026, 1, 1),
                },
                {"workspaceId": WORKSPACE_ID, "createdAt": {"$gt": "2026-01-01T00:00:00+00:00"}},
                id="date_cursor_is_midnight_utc",
            ),
            pytest.param(
                "Companies",
                WORKSPACE_ID,
                {
                    "should_use_incremental_field": True,
                    "incremental_field": "not_a_real_field",
                    "db_incremental_field_last_value": "2026-01-01T00:00:00Z",
                },
                {"workspaceId": WORKSPACE_ID, "updatedAt": {"$gt": "2026-01-01T00:00:00Z"}},
                id="unknown_cursor_falls_back_to_updated_at",
            ),
            pytest.param(
                "Companies",
                WORKSPACE_ID,
                {
                    "should_use_incremental_field": True,
                    "incremental_field": "updatedAt",
                    "db_incremental_field_last_value": None,
                },
                {"workspaceId": WORKSPACE_ID},
                id="first_incremental_sync_reads_everything",
            ),
            pytest.param(
                "Companies",
                WORKSPACE_ID,
                {
                    "should_use_incremental_field": False,
                    "incremental_field": None,
                    "db_incremental_field_last_value": "2026-01-01T00:00:00Z",
                },
                {"workspaceId": WORKSPACE_ID},
                id="full_refresh_ignores_a_stale_watermark",
            ),
        ],
    )
    def test_where_scopes_the_workspace_and_cursor_and_order_stays_on_created_at(
        self, endpoint: str, workspace_id: str | None, inputs: dict[str, Any], expected_where: dict[str, Any] | None
    ) -> None:
        result = _drive(endpoint, [_page([], total=0)], workspace_id=workspace_id, **inputs)

        assert result.raised is None
        where = result.requests[0].param("where")
        assert (json.loads(where) if where is not None else None) == expected_where
        # An updatedAt order lets a row updated mid-sync shift the offset pages and skip a row.
        assert json.loads(result.requests[0].param("orderBy") or "{}") == {"createdAt": "asc"}


class TestZeroValidateCredentials:
    @pytest.mark.parametrize(
        ("status", "workspace_id", "expected_valid", "expected_fragment"),
        [
            pytest.param(200, None, True, None, id="valid_key"),
            pytest.param(200, f" {WORKSPACE_ID} ", True, None, id="reachable_workspace"),
            pytest.param(200, "33333333-3333-3333-3333-333333333333", False, "can't access that workspace", id="other"),
            pytest.param(401, None, False, "rejected the API key", id="bad_key"),
            pytest.param(500, None, False, "Could not reach", id="server_error"),
        ],
    )
    def test_maps_the_workspace_probe_to_a_message(
        self, status: int, workspace_id: str | None, expected_valid: bool, expected_fragment: str | None
    ) -> None:
        body = {"data": [{"id": WORKSPACE_ID}, {"id": OTHER_WORKSPACE_ID}], "total": 2}
        config = ZeroSourceConfig(api_key="test-key", workspace_id=workspace_id)
        with scripted_network(always(ScriptedResponse(status=status, json=body))) as network:
            is_valid, message = ZeroSource().validate_credentials(config, team_id=1)

        assert is_valid is expected_valid
        assert (message is None) if expected_fragment is None else (expected_fragment in (message or ""))
        assert {request.path for request in network.requests_log} == {"/api/workspaces"}
