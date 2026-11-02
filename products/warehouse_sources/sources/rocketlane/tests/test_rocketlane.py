from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rocketlane import (
    RocketlaneSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.rocketlane import (
    RocketlaneResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.source import RocketlaneSource


def _driver() -> SourceDriver:
    return SourceDriver(RocketlaneSource(), RocketlaneSourceConfig(api_key="rl-key"))


def _response(
    rows: list[dict[str, Any]] | None, *, has_more: bool, next_token: str | None, drop_data: bool = False
) -> ScriptedResponse:
    body: dict[str, Any] = {
        "pagination": {
            "pageSize": 100,
            "hasMore": has_more,
            "totalRecordCount": len(rows or []),
            "nextPageToken": next_token,
        },
    }
    if not drop_data:
        body["data"] = rows or []
    return ScriptedResponse(json=body)


class TestPagination:
    def test_resumes_from_saved_token(self) -> None:
        # The first page (token None) must never be fetched on resume.
        result = _driver().run(
            "projects",
            [
                _response([{"projectId": 2}], has_more=True, next_token="t3"),
                _response([{"projectId": 3}], has_more=False, next_token=None),
            ],
            resume_state=RocketlaneResumeConfig(page_token="t2"),
        )

        assert result.rows == [{"projectId": 2}, {"projectId": 3}]
        # The seeded resume cursor is sent on the very first request.
        assert result.requests[0].param("pageToken") == "t2"

    def test_empty_page_does_not_yield_and_terminates(self) -> None:
        # An empty page terminates the stream even if the API keeps advertising a cursor.
        result = _driver().run("projects", [_response([], has_more=True, next_token="t2")])

        assert result.rows == []
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_missing_data_key_raises_loudly(self) -> None:
        result = _driver().run("projects", [_response(None, has_more=False, next_token=None, drop_data=True)])

        # A 200 body without "data" means the response shape changed — fail loud, not silently 0 rows.
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestFanout:
    @parameterized.expand(
        [
            (
                "phases",
                "projects",
                "projectId",
                ["/api/1.0/projects", "/api/1.0/phases", "/api/1.0/phases", "/api/1.0/phases"],
                [None, "1", "1", "2"],
                [{"phaseId": 10}, {"phaseId": 11}],
            ),
            (
                "invoice_line_items",
                "invoices",
                "invoiceId",
                [
                    "/api/1.0/invoices",
                    "/api/1.0/invoices/1/lines",
                    "/api/1.0/invoices/1/lines",
                    "/api/1.0/invoices/2/lines",
                ],
                [None, None, None, None],
                [{"invoiceLineItemId": 10, "invoiceId": 1}, {"invoiceLineItemId": 11, "invoiceId": 1}],
            ),
        ]
    )
    def test_walks_child_pages_per_parent_and_skips_missing_parent(
        self,
        endpoint: str,
        _parent: str,
        parent_key: str,
        expected_paths: list[str],
        expected_project_ids: list[str | None],
        expected_rows: list[dict[str, Any]],
    ) -> None:
        child_key = next(iter(expected_rows[0]))
        result = _driver().run(
            endpoint,
            [
                _response([{parent_key: 1}, {parent_key: 2}], has_more=False, next_token=None),
                _response([{child_key: 10}], has_more=True, next_token="p2"),
                _response([{child_key: 11}], has_more=False, next_token=None),
                # The second parent was deleted after the parent listing.
                ScriptedResponse(status=404, json={"errors": []}),
            ],
        )

        assert result.raised is None
        assert result.rows == expected_rows
        assert result.paths == expected_paths
        assert result.params("projectId") == expected_project_ids
        assert result.params("pageToken") == [None, None, "p2", None]
        assert result.params("pageSize") == ["100", "100", "100", "100"]

    @parameterized.expand(
        [
            (
                "skips_completed_parent",
                {"completed": ["/phases?projectId=1"], "current": None, "child_state": None},
                ["2"],
                [None],
                [{"phaseId": 20}],
            ),
            (
                "continues_parent_in_progress",
                {"completed": [], "current": "/phases?projectId=1", "child_state": {"page_token": "p2"}},
                ["1", "2"],
                ["p2", None],
                [{"phaseId": 20}, {"phaseId": 20}],
            ),
        ]
    )
    def test_resumes_from_saved_fanout_state(
        self,
        _name: str,
        fanout_state: dict[str, Any],
        expected_project_ids: list[str],
        expected_page_tokens: list[str | None],
        expected_rows: list[dict[str, Any]],
    ) -> None:
        result = _driver().run(
            "phases",
            [
                _response([{"projectId": 1}, {"projectId": 2}], has_more=False, next_token=None),
                *[_response([{"phaseId": 20}], has_more=False, next_token=None) for _ in expected_project_ids],
            ],
            resume_state=RocketlaneResumeConfig(fanout_state=fanout_state),
        )

        assert result.rows == expected_rows
        assert result.params("projectId")[1:] == expected_project_ids
        assert result.params("pageToken")[1:] == expected_page_tokens
        assert result.saved_states[-1].fanout_state["completed"] == ["/phases?projectId=1", "/phases?projectId=2"]


class TestRocketlaneSourceResponse:
    @parameterized.expand(
        [
            ("projects", ["projectId"], "createdAt"),
            ("tasks", ["taskId"], "createdAt"),
            ("time_entries", ["timeEntryId"], "createdAt"),
            ("users", ["userId"], "createdAt"),
            ("fields", ["fieldId"], "createdAt"),
            ("invoices", ["invoiceId"], "createdAt"),
            ("invoice_line_items", ["invoiceId", "invoiceLineItemId"], None),
            ("time_entry_categories", ["categoryId"], None),
            ("phases", ["phaseId"], "createdAt"),
        ]
    )
    def test_response_uses_endpoint_primary_key(
        self, endpoint: str, primary_keys: list[str], partition_key: str | None
    ) -> None:
        result = _driver().run(endpoint, [_response([], has_more=False, next_token=None)])

        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_mode == ("datetime" if partition_key else None)
        assert response.partition_keys == ([partition_key] if partition_key else None)
