from typing import Any

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.sources.coda._config import CodaSourceConfig
from products.warehouse_sources.sources.coda.coda import CodaResumeConfig, coda_source, validate_credentials
from products.warehouse_sources.sources.coda.settings import CODA_ENDPOINTS, ENDPOINTS
from products.warehouse_sources.sources.coda.source import CodaSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network


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

    @pytest.mark.parametrize(
        "endpoint, item, key, expected_id, expected_path",
        [
            (
                "doc_analytics",
                {"doc": {"id": "doc1", "title": "Roadmap"}, "metrics": [{"date": "2026-01-01", "views": 5}]},
                "doc_id",
                "doc1",
                "/apis/v1/analytics/docs",
            ),
            (
                "pack_analytics",
                {
                    "pack": {"id": 1003, "name": "Geometry helpers", "createdAt": "2026-01-01T00:00:00Z"},
                    "metrics": [{"date": "2026-01-01", "docInstalls": 4, "revenueUsd": "12.50"}],
                },
                "pack_id",
                1003,
                "/apis/v1/analytics/packs",
            ),
        ],
    )
    def test_analytics_lifts_nested_subject_id(
        self, endpoint: str, item: dict[str, Any], key: str, expected_id: Any, expected_path: str
    ) -> None:
        result = _driver().run(endpoint, [_response([item])])

        assert result.raised is None
        # The subject id is nested under `doc` / `pack`; it must surface top-level to key the merge.
        assert result.rows[0][key] == expected_id
        assert result.rows[0]["metrics"] == item["metrics"]
        assert result.paths == [expected_path]

    @pytest.mark.parametrize(
        "item",
        [
            {"metrics": []},
            {"pack": None, "metrics": []},
            {"pack": {"name": "No id"}, "metrics": []},
        ],
    )
    def test_pack_analytics_without_nested_id_gets_no_key(self, item: dict[str, Any]) -> None:
        result = _driver().run("pack_analytics", [_response([item])])

        assert result.raised is None
        assert "pack_id" not in result.rows[0]

    def test_pack_analytics_walks_pages_until_no_token(self) -> None:
        result = _driver().run(
            "pack_analytics",
            [
                ScriptedResponse(json={"items": [{"pack": {"id": 1}, "metrics": []}], "nextPageToken": "t-2"}),
                ScriptedResponse(json={"items": [], "nextPageToken": "t-3"}),
                _response([{"pack": {"id": 2}, "metrics": []}]),
            ],
        )

        assert result.raised is None
        assert result.params("pageToken") == [None, "t-2", "t-3"]
        assert result.params("limit") == ["100", "100", "100"]
        assert [row["pack_id"] for row in result.rows] == [1, 2]

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

    @pytest.mark.parametrize(
        "endpoint, child_rows",
        [
            ("pages", [{"id": "canvas-1", "name": "Launch", "parent": {"id": "canvas-0"}}]),
            ("controls", [{"id": "ctrl-1", "type": "control", "name": "Cost", "parent": {"id": "canvas-1"}}]),
            ("formulas", [{"id": "f-1", "type": "formula", "name": "Sum of expenses", "parent": {"id": "canvas-1"}}]),
        ],
    )
    def test_doc_objects_fan_out_over_docs(self, endpoint: str, child_rows: list[dict[str, Any]]) -> None:
        result = _driver().run(
            endpoint,
            [
                _response([{"id": "doc1"}, {"id": "doc2"}]),  # docs
                _response(child_rows),  # children of doc1
                _response([]),  # doc2 has none
            ],
        )

        assert result.raised is None
        assert result.paths == ["/apis/v1/docs", f"/apis/v1/docs/doc1/{endpoint}", f"/apis/v1/docs/doc2/{endpoint}"]
        assert [(row["id"], row["_doc_id"]) for row in result.rows] == [(child_rows[0]["id"], "doc1")]
        assert all("_docs_id" not in row for row in result.rows)

    @pytest.mark.parametrize("endpoint", ["controls", "formulas"])
    def test_doc_objects_page_within_a_doc(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [
                _response([{"id": "doc1"}]),  # docs
                ScriptedResponse(json={"items": [{"id": "a"}], "nextPageToken": "t-2"}),
                _response([{"id": "b"}]),
            ],
        )

        assert result.raised is None
        assert result.paths[1:] == [f"/apis/v1/docs/doc1/{endpoint}"] * 2
        assert result.params("pageToken") == [None, None, "t-2"]
        assert [(row["id"], row["_doc_id"]) for row in result.rows] == [("a", "doc1"), ("b", "doc1")]

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

    @pytest.mark.parametrize(
        "endpoint, saved, responses, expected_paths, expected_tokens, expected_ids",
        [
            (
                "docs",
                {"cursor": "token-2"},
                [_response([{"id": "doc2"}])],
                ["/apis/v1/docs"],
                ["token-2"],
                ["doc2"],
            ),
            (
                "pages",
                {"completed": ["/docs/doc1/pages"], "current": None, "child_state": None},
                [_response([{"id": "doc1"}, {"id": "doc2"}]), _response([{"id": "canvas-2"}])],
                ["/apis/v1/docs", "/apis/v1/docs/doc2/pages"],
                [None, None],
                ["canvas-2"],
            ),
        ],
    )
    def test_resumes_from_saved_state(
        self,
        endpoint: str,
        saved: dict[str, Any],
        responses: list[ScriptedResponse],
        expected_paths: list[str],
        expected_tokens: list[str | None],
        expected_ids: list[str],
    ) -> None:
        result = _driver().run(endpoint, responses, resume_state=CodaResumeConfig(paginator_state=saved))

        assert result.raised is None
        assert result.paths == expected_paths
        assert result.params("pageToken") == expected_tokens
        assert [row["id"] for row in result.rows] == expected_ids

    def test_list_endpoint_marks_completion_before_its_last_page(self) -> None:
        result = _driver().run("docs", [_response([{"id": "doc1"}])])

        assert result.raised is None
        assert result.saved_states[-1] == CodaResumeConfig(completed=True)

        resumed = _driver().run("docs", [], resume_state=CodaResumeConfig(completed=True))

        assert resumed.raised is None
        assert resumed.paths == []
        assert resumed.rows == []

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
        manager = MagicMock()
        manager.can_resume.return_value = False
        response = coda_source("token", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
