from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.coda.coda import coda_source, validate_credentials
from products.warehouse_sources.backend.temporal.data_imports.sources.coda.settings import CODA_ENDPOINTS, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.coda.source import CodaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coda import CodaSourceConfig


def _driver() -> SourceDriver:
    return SourceDriver(CodaSource(), CodaSourceConfig(api_token="token"))


def _response(items: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"items": items})


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("token") is expected

        assert network.requests_log[0].path == "/apis/v1/whoami"
        assert network.requests_log[0].headers["authorization"] == "Bearer token"


class TestGetRows:
    def test_rows_fan_out_docs_tables_rows(self) -> None:
        result = _driver().run(
            "rows",
            [
                _response([{"id": "doc1"}]),  # docs
                _response([{"id": "grid-1"}]),  # tables for doc1
                _response([{"id": "i-1", "values": {"Name": "x"}}]),  # rows for grid-1
            ],
        )

        assert result.raised is None
        assert [(r["id"], r["_doc_id"], r["_table_id"]) for r in result.rows] == [("i-1", "doc1", "grid-1")]
        assert result.paths[2] == "/apis/v1/docs/doc1/tables/grid-1/rows"
        assert result.requests[2].param("useColumnNames") == "true"

    def test_columns_fan_out_docs_tables_columns(self) -> None:
        result = _driver().run(
            "columns",
            [
                _response([{"id": "doc1"}]),  # docs
                _response([{"id": "grid-1"}]),  # tables for doc1
                _response([{"id": "c-1", "name": "Name"}]),  # columns for grid-1
            ],
        )

        assert result.raised is None
        assert [(c["id"], c["_doc_id"], c["_table_id"]) for c in result.rows] == [("c-1", "doc1", "grid-1")]
        assert result.paths[2] == "/apis/v1/docs/doc1/tables/grid-1/columns"

    def test_doc_analytics_lifts_nested_doc_id(self) -> None:
        result = _driver().run(
            "doc_analytics",
            [_response([{"doc": {"id": "doc1", "title": "Roadmap"}, "metrics": [{"date": "2026-01-01", "views": 5}]}])],
        )

        assert result.raised is None
        # The doc id is nested under `doc`; it must surface as a top-level `doc_id` to key the merge.
        assert result.rows[0]["doc_id"] == "doc1"
        assert result.rows[0]["metrics"][0]["views"] == 5
        assert result.paths[0] == "/apis/v1/analytics/docs"

    def test_page_analytics_fan_out_and_lifts_page_id(self) -> None:
        result = _driver().run(
            "page_analytics",
            [
                _response([{"id": "doc1"}]),  # docs
                _response([{"page": {"id": "page-1", "name": "Launch"}, "metrics": [{"views": 3}]}]),  # pages for doc1
            ],
        )

        assert result.raised is None
        assert [(p["page_id"], p["_doc_id"]) for p in result.rows] == [("page-1", "doc1")]
        assert result.paths[1] == "/apis/v1/analytics/docs/doc1/pages"

    def test_pages_fan_out_over_docs(self) -> None:
        result = _driver().run(
            "pages",
            [
                _response([{"id": "doc1"}]),  # docs
                _response([{"id": "canvas-1", "name": "Launch", "parent": {"id": "canvas-0"}}]),  # pages for doc1
            ],
        )

        assert result.raised is None
        assert [(p["id"], p["_doc_id"]) for p in result.rows] == [("canvas-1", "doc1")]
        assert result.paths[1] == "/apis/v1/docs/doc1/pages"

    @pytest.mark.parametrize(
        "endpoint, parents, denied_status, expected_paths, child_row, key",
        [
            (
                "permissions",
                [{"id": "doc1"}, {"id": "doc2"}],
                403,
                ["/apis/v1/docs", "/apis/v1/docs/doc1/acl/permissions", "/apis/v1/docs/doc2/acl/permissions"],
                {"id": "perm-1", "access": "readonly", "principal": {"type": "email", "email": "a@example.com"}},
                ("_doc_id", "doc2"),
            ),
            (
                "workspace_users",
                [
                    {"id": "doc1", "workspaceId": "ws-1"},
                    {"id": "doc2", "workspaceId": "ws-1"},
                    {"id": "doc3", "workspaceId": "ws-2"},
                ],
                403,
                ["/apis/v1/docs", "/apis/v1/workspaces/ws-1/users", "/apis/v1/workspaces/ws-2/users"],
                {"email": "a@example.com", "name": "A", "role": "Admin", "registeredAt": "2026-01-01T00:00:00Z"},
                ("_workspace_id", "ws-2"),
            ),
            (
                "workspace_role_activity",
                [
                    {"id": "doc1", "workspaceId": "ws-1"},
                    {"id": "doc2", "workspaceId": "ws-1"},
                    {"id": "doc3", "workspaceId": "ws-2"},
                ],
                404,
                ["/apis/v1/docs", "/apis/v1/workspaces/ws-1/roles", "/apis/v1/workspaces/ws-2/roles"],
                {"month": "2026-01-15", "activeAdminCount": 1, "activeEditorCount": 4},
                ("_workspace_id", "ws-2"),
            ),
        ],
    )
    def test_fan_out_skips_inaccessible_parent(
        self,
        endpoint: str,
        parents: list[dict[str, Any]],
        denied_status: int,
        expected_paths: list[str],
        child_row: dict[str, Any],
        key: tuple[str, str],
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _response(parents),
                ScriptedResponse(status=denied_status, json={"statusCode": denied_status}),
                _response([child_row]),
            ],
        )

        assert result.raised is None
        # Workspace endpoints call each workspace once, even when several docs share it.
        assert result.paths == expected_paths
        key_column, parent_id = key
        assert [row[key_column] for row in result.rows] == [parent_id]

    def test_table_without_id_fails_fast_in_rows(self) -> None:
        result = _driver().run("rows", [_response([{"id": "doc1"}]), _response([{"name": "broken"}])])

        # A table row missing its primary key can't be bound into the rows path — fail loud
        # rather than silently dropping the table.
        assert isinstance(result.raised, ValueError)
        assert "expects a field 'id'" in str(result.raised)


class TestCodaSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = CODA_ENDPOINTS[endpoint]
        response = coda_source("token", endpoint, team_id=1, job_id="j")

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
