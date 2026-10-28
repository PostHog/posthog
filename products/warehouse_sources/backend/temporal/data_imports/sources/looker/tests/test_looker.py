from urllib.parse import parse_qs

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    route,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.looker import LookerSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.looker.looker import LookerResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.looker.source import LookerSource


def driver(instance_url: str = "https://example.looker.com:19999") -> SourceDriver:
    return SourceDriver(
        LookerSource(),
        LookerSourceConfig(instance_url=instance_url, client_id="example-client", client_secret="example-secret"),
    )


@pytest.mark.parametrize(
    ("endpoint", "path", "sorts", "deleted"),
    [
        ("users", "users", "id", None),
        ("looks", "looks/search", "id", "false"),
        ("dashboards", "dashboards/search", "id", "false"),
        ("folders", "folders/search", "id", None),
        ("lookml_models", "lookml_models", None, None),
    ],
)
def test_paginated_tables_use_documented_paths_and_login(
    endpoint: str, path: str, sorts: str | None, deleted: str | None
) -> None:
    rows = [{"id": str(index), "name": f"model_{index}"} for index in range(200)]
    result = driver().run(
        endpoint,
        route(
            {
                "/login": [ScriptedResponse(json={"access_token": "example-token", "expires_in": 3600})],
                f"/{path}": [
                    ScriptedResponse(json=rows[:100]),
                    ScriptedResponse(json=rows[100:]),
                    ScriptedResponse(json=[]),
                ],
            }
        ),
    )
    assert result.raised is None
    assert result.rows == rows
    login, *pages = result.requests
    assert login.method == "POST"
    assert login.path == "/api/4.0/login"
    assert login.query == {}
    assert parse_qs((login.body or b"").decode()) == {
        "client_id": ["example-client"],
        "client_secret": ["example-secret"],
    }
    assert login.headers["content-type"] == "application/x-www-form-urlencoded"
    assert [request.param("offset") for request in pages] == ["0", "100", "200"]
    assert [request.param("limit") for request in pages] == ["100"] * 3
    for request in pages:
        assert request.origin == "https://example.looker.com:19999"
        assert request.headers["authorization"] == "token example-token"
        assert request.param("sorts") == sorts
        assert request.param("deleted") == deleted
    if endpoint == "users":
        fields = (pages[0].param("fields") or "").split(",")
        assert {"id", "email", "group_ids", "role_ids"} <= set(fields)
        assert not any(field.startswith("credentials_") or field == "sessions" for field in fields)
    assert result.committed_states == [LookerResumeConfig(offset=100), LookerResumeConfig(offset=200)]


def test_resume_continues_after_the_last_written_page() -> None:
    result = driver("https://example.looker.com/api/4.0/").run(
        "looks",
        [
            ScriptedResponse(json={"access_token": "example-token", "expires_in": 3600}),
            ScriptedResponse(json=[{"id": "last-look", "query_id": None}]),
        ],
        resume_state=LookerResumeConfig(offset=200),
    )
    assert result.raised is None
    assert result.rows == [{"id": "last-look", "query_id": None}]
    assert result.params("offset") == [None, "200"]
    assert result.paths == ["/api/4.0/login", "/api/4.0/looks/search"]


def test_projects_use_an_unpaginated_request() -> None:
    rows = [{"id": f"project-{index}", "name": f"Project {index}"} for index in range(101)]
    result = driver().run(
        "projects",
        [
            ScriptedResponse(json={"access_token": "example-token", "expires_in": 3600}),
            ScriptedResponse(json=rows),
        ],
    )
    assert result.raised is None
    assert result.rows == rows
    assert result.paths == ["/api/4.0/login", "/api/4.0/projects"]
    assert result.requests[-1].query == {}
    assert result.saved_states == []


def test_long_sync_refreshes_the_token_with_looker_login() -> None:
    rows = [{"id": str(index)} for index in range(100)]
    with time_machine.travel("2026-01-01T00:00:00Z", tick=False) as clock:
        logins = 0

        def respond(request: RecordedRequest) -> ScriptedResponse:
            nonlocal logins
            if request.path == "/api/4.0/login":
                logins += 1
                return ScriptedResponse(json={"access_token": f"example-token-{logins}", "expires_in": 3600})
            if request.param("offset") == "0":
                clock.shift(3600)
                return ScriptedResponse(json=rows)
            return ScriptedResponse(json=[])

        result = driver().run("users", respond)
    assert result.raised is None
    assert result.rows == rows
    assert result.paths == ["/api/4.0/login", "/api/4.0/users", "/api/4.0/login", "/api/4.0/users"]
    assert result.requests[1].headers["authorization"] == "token example-token-1"
    assert result.requests[3].headers["authorization"] == "token example-token-2"
    assert result.requests[2].body == result.requests[0].body
