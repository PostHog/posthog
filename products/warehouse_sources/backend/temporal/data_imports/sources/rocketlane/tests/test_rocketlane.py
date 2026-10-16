from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rocketlane import (
    RocketlaneSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rocketlane.rocketlane import (
    RocketlaneResumeConfig,
    check_access,
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


class TestCheckAccess:
    @parameterized.expand(
        [
            ("ok", 200, 200, None),
            ("unauthorized", 401, 401, None),
            ("forbidden", 403, 403, None),
            ("server_error", 500, 500, "Rocketlane returned HTTP 500"),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_status: int, expected_message: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            assert check_access("rl-key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))):
            status, message = check_access("rl-key")
        assert status == 0
        assert message is not None and "boom" in message


class TestRocketlaneSourceResponse:
    @parameterized.expand(
        [
            ("projects", ["projectId"]),
            ("tasks", ["taskId"]),
            ("time_entries", ["timeEntryId"]),
            ("users", ["userId"]),
            ("fields", ["fieldId"]),
        ]
    )
    def test_response_uses_endpoint_primary_key(self, endpoint: str, primary_keys: list[str]) -> None:
        result = _driver().run(endpoint, [_response([], has_more=False, next_token=None)])

        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        # Every endpoint exposes a stable `createdAt`, so all partition by datetime.
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]
