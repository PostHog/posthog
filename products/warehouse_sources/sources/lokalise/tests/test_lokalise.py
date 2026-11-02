from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lokalise import (
    LokaliseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lokalise.source import LokaliseSource


def driver() -> SourceDriver:
    return SourceDriver(LokaliseSource(), LokaliseSourceConfig(api_token="test-token"))


def page(name: str, rows: list[dict[str, Any]], pages: int = 1, cursor: str | None = None) -> ScriptedResponse:
    headers = {"X-Pagination-Page-Count": str(pages)}
    if cursor is not None:
        headers["X-Pagination-Next-Cursor"] = cursor
    return ScriptedResponse(json={name: rows}, headers=headers)


@pytest.mark.parametrize(("endpoint", "id_field"), [("keys", "key_id"), ("translations", "translation_id")])
def test_cursor_fanout_walk_preserves_project_identity(endpoint: str, id_field: str) -> None:
    result = driver().run(
        endpoint,
        [
            page("projects", [{"project_id": "project-a"}], pages=2),
            page(endpoint, [{id_field: 1, "metadata": {"value": None}}], cursor="next-a"),
            page(endpoint, [{id_field: 2}]),
            page("projects", [{"project_id": "project-b"}], pages=2),
            page(endpoint, [{id_field: 1}]),
        ],
    )
    assert result.raised is None
    assert result.paths == [
        "/api2/projects",
        f"/api2/projects/project-a/{endpoint}",
        f"/api2/projects/project-a/{endpoint}",
        "/api2/projects",
        f"/api2/projects/project-b/{endpoint}",
    ]
    assert result.params("cursor") == [None, None, "next-a", None, None]
    assert result.params("pagination") == [None, "cursor", "cursor", None, "cursor"]
    assert result.rows == [
        {id_field: 1, "metadata": {"value": None}, "project_id": "project-a"},
        {id_field: 2, "project_id": "project-a"},
        {id_field: 1, "project_id": "project-b"},
    ]
    assert result.response is not None
    assert len({tuple(row[key] for key in result.response.primary_keys or []) for row in result.rows}) == 3
    assert all(request.headers["x-api-token"] == "test-token" for request in result.requests)
    assert all(request.param("limit") == "100" for request in result.requests)


@pytest.mark.parametrize(
    ("endpoint", "id_field"),
    [
        ("languages", "lang_id"),
        ("contributors", "user_id"),
        ("comments", "comment_id"),
        ("screenshots", "screenshot_id"),
        ("tasks", "task_id"),
    ],
)
def test_page_fanout_walk_stops_at_page_count(endpoint: str, id_field: str) -> None:
    result = driver().run(
        endpoint,
        [
            page("projects", [{"project_id": "project-a"}, {"project_id": "project-b"}]),
            page(endpoint, [{id_field: 1}], pages=2),
            page(endpoint, [{id_field: 2}], pages=2),
            page(endpoint, [{id_field: 1}]),
        ],
    )
    assert result.raised is None
    assert result.params("page") == ["1", "1", "2", "1"]
    assert result.rows == [
        {id_field: 1, "project_id": "project-a"},
        {id_field: 2, "project_id": "project-a"},
        {id_field: 1, "project_id": "project-b"},
    ]


@pytest.mark.parametrize("endpoint", ["projects", "keys", "contributors"])
def test_resume_keeps_written_page_and_skips_completed_projects(endpoint: str) -> None:
    parent = page("projects", [{"project_id": "project-a"}, {"project_id": "project-b"}])
    if endpoint == "projects":
        first_script = [page("projects", [{"project_id": "project-a"}], pages=2)]
        resumed_script = [page("projects", [{"project_id": "project-b"}], pages=2)]
    else:
        first_script = [parent, page(endpoint, [{"id": "completed"}])]
        first_script.append(
            page(endpoint, [{"id": "written"}], pages=2, cursor="saved" if endpoint == "keys" else None)
        )
        resumed_script = [parent, page(endpoint, [{"id": "remaining"}])]
    first_script.append(ScriptedResponse(status=403, json={"error": {"code": 403, "message": "Forbidden"}}))
    first = driver().run(endpoint, first_script)
    assert first.raised is not None
    assert first.committed_states
    resumed = driver().run(endpoint, resumed_script, resume_state=first.committed_states[-1])
    assert resumed.raised is None
    if endpoint == "projects":
        assert resumed.params("page") == ["2"]
        assert resumed.rows == [{"project_id": "project-b"}]
    else:
        assert resumed.paths == ["/api2/projects", f"/api2/projects/project-b/{endpoint}"]
        assert resumed.requests[1].param("cursor" if endpoint == "keys" else "page") == (
            "saved" if endpoint == "keys" else "2"
        )
        assert resumed.rows == [{"id": "remaining", "project_id": "project-b"}]


@pytest.mark.parametrize("endpoint", ["keys", "tasks"])
def test_empty_project_children_do_not_stop_later_projects(endpoint: str) -> None:
    result = driver().run(
        endpoint,
        [
            page("projects", [{"project_id": "empty"}, {"project_id": "populated"}]),
            page(endpoint, []),
            page(endpoint, [{"id": "row"}]),
        ],
    )
    assert result.raised is None
    assert result.rows == [{"id": "row", "project_id": "populated"}]
    assert result.committed_states[-1].paginator_state["completed"] == [
        f"/projects/empty/{endpoint}",
        f"/projects/populated/{endpoint}",
    ]


def test_repeated_cursor_fails_instead_of_repeating_rows() -> None:
    result = driver().run(
        "keys",
        [
            page("projects", [{"project_id": "project-a"}]),
            page("keys", [{"key_id": 1}], cursor="repeated"),
            page("keys", [{"key_id": 1}], cursor="repeated"),
        ],
    )
    assert isinstance(result.raised, ValueError)
    assert result.rows == [{"key_id": 1, "project_id": "project-a"}]


def test_empty_cursor_page_with_next_cursor_continues() -> None:
    result = driver().run(
        "keys",
        [
            page("projects", [{"project_id": "project-a"}]),
            page("keys", [], cursor="after-empty"),
            page("keys", [{"key_id": 2}]),
        ],
    )
    assert result.raised is None
    assert result.params("cursor") == [None, None, "after-empty"]
    assert result.rows == [{"key_id": 2, "project_id": "project-a"}]
    assert result.committed_states[0].paginator_state["child_state"] == {"cursor": "after-empty"}


@pytest.mark.parametrize("malformed_parent", [True, False])
def test_missing_response_collection_fails_instead_of_completing_empty(malformed_parent: bool) -> None:
    script = [] if malformed_parent else [page("projects", [{"project_id": "project-a"}])]
    script.append(ScriptedResponse(json={"unexpected": []}))
    result = driver().run("keys", script)
    assert result.raised is not None
    assert result.rows == []
    assert result.committed_states == []
