from typing import Any

from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hex import HexSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hex import hex as hex_module
from products.warehouse_sources.backend.temporal.data_imports.sources.hex.hex import (
    HexResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hex.source import HexSource


def _driver(workspace_url: str | None = None) -> SourceDriver:
    return SourceDriver(HexSource(), HexSourceConfig(api_key="tok", workspace_url=workspace_url))


def _projects_page(ids: list[str], after: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "values": [{"id": project_id, "createdAt": "2026-01-01T00:00:00.000Z"} for project_id in ids],
            "pagination": {"after": after, "before": None},
        }
    )


def _runs_page(runs: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"runs": runs, "nextPage": None, "previousPage": None, "traceId": "t"})


class TestValidateCredentials:
    def test_custom_workspace_url_is_used(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("https://acme.hex.tech", "tok") == (True, None)

        assert network.requests_log[0].origin == "https://acme.hex.tech"
        assert network.requests_log[0].path == "/api/v1/projects"
        assert network.requests_log[0].param("limit") == "1"

    def test_403_at_source_create_is_accepted(self) -> None:
        with scripted_network([ScriptedResponse(status=403)]):
            assert validate_credentials(None, "tok", schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self) -> None:
        with scripted_network([ScriptedResponse(status=403)]):
            valid, msg = validate_credentials(None, "tok", schema_name="projects")

        assert valid is False
        assert msg is not None

    def test_invalid_host_short_circuits(self) -> None:
        valid, msg = validate_credentials("not a host!", "tok")
        assert valid is False
        assert msg == "Invalid Hex workspace URL"

    def test_rejects_redirect_response(self) -> None:
        # A workspace host that 3xx-redirects (potentially to an internal address) must be
        # rejected, not followed (SSRF).
        with scripted_network(
            [ScriptedResponse(status=302, headers={"Location": "https://other.example.com/"})]
        ) as network:
            valid, msg = validate_credentials("acme.hex.tech", "tok")

        assert valid is False
        assert msg == hex_module.HOST_NOT_ALLOWED_ERROR
        assert len(network.requests_log) == 1

    def test_blocks_unsafe_host(self) -> None:
        # When a team_id is supplied, a host that resolves to an internal address is rejected
        # before any HTTP request is made (SSRF guard).
        with (
            mock.patch.object(hex_module, "_is_host_safe", return_value=(False, "internal address")),
            scripted_network([]) as network,
        ):
            valid, msg = validate_credentials("10.0.0.1", "tok", team_id=99)

        assert valid is False
        assert msg == "internal address"
        assert network.requests_log == []


class TestHexCursorPagination:
    def test_empty_page_terminates_even_with_cursor(self) -> None:
        # An `after` token on an empty page must end pagination rather than loop forever.
        result = _driver().run("projects", [_projects_page([], after="cur-1")])

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1

    def test_custom_workspace_url_reaches_requests(self) -> None:
        result = _driver("https://acme.hex.tech").run("projects", [_projects_page(["p1"])])

        assert result.raised is None
        assert result.requests[0].origin == "https://acme.hex.tech"
        assert result.requests[0].path == "/api/v1/projects"


class TestProjectRunsFanout:
    def test_resume_skips_completed_projects(self) -> None:
        result = _driver().run(
            "project_runs",
            [
                _projects_page(["p1", "p2"]),
                _runs_page([{"runId": "r-b", "projectId": "p2", "status": "COMPLETED"}]),
            ],
            resume_state=HexResumeConfig(
                paginator_state={"completed": ["/v1/projects/p1/runs"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert [row["runId"] for row in result.rows] == ["r-b"]
        assert result.paths == ["/api/v1/projects", "/api/v1/projects/p2/runs"]


class TestPerProjectCursorFanout:
    def test_queried_tables_follow_child_cursor_and_carry_project_id(self) -> None:
        def tables_page(names: list[str], after: str | None = None) -> ScriptedResponse:
            return ScriptedResponse(
                json={
                    "values": [
                        {"dataConnectionId": "dc1", "dataConnectionName": "Warehouse", "tableName": name}
                        for name in names
                    ],
                    "pagination": {"after": after, "before": None},
                    "traceId": "t",
                }
            )

        result = _driver().run(
            "queried_tables",
            [
                _projects_page(["p1", "p2"]),
                tables_page(["orders"], after="cur-1"),
                tables_page(["users"]),
                tables_page(["orders"]),
            ],
        )

        assert result.raised is None
        assert [(row["projectId"], row["tableName"]) for row in result.rows] == [
            ("p1", "orders"),
            ("p1", "users"),
            ("p2", "orders"),
        ]
        assert all("_projects_id" not in row for row in result.rows)
        assert result.paths[1] == "/api/v1/projects/p1/queriedTables"
        assert result.requests[2].param("after") == "cur-1"
        assert result.paths[3] == "/api/v1/projects/p2/queriedTables"
        assert result.requests[3].param("after") is None


class TestRuntimeHostCheck:
    def test_blocks_unsafe_workspace_host_before_any_request(self) -> None:
        # The configured host is re-checked at run time (DNS rebinding) before any request.
        with mock.patch.object(hex_module, "_is_host_safe", return_value=(False, "internal address")):
            result = _driver().run("projects", [])

        assert isinstance(result.raised, hex_module.HexHostNotAllowedError)
        assert result.requests == []
