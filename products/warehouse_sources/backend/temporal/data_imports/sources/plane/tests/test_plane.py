from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.plane import PlaneSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.plane.plane import (
    INVALID_KEY_MESSAGE,
    INVALID_URL_MESSAGE,
    SLUG_MESSAGE,
    WORKSPACE_MESSAGE,
    PlaneResumeConfig,
    normalize_base_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plane.source import PlaneSource

CONFIG = PlaneSourceConfig(api_key="plane_api_test", workspace_slug="my-team")


def cursor_page(rows: list[dict[str, Any]], next_cursor: str | None) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "data": rows,
            "next_cursor": next_cursor,
            "has_more": next_cursor is not None,
            "pagination": {"style": "cursor"},
        }
    )


def _driver(config: PlaneSourceConfig = CONFIG) -> SourceDriver:
    return SourceDriver(PlaneSource(), config)


def test_work_items_walk_cursor_pages_to_the_last_page() -> None:
    result = _driver().run(
        "work_items",
        [cursor_page([{"id": "w1"}, {"id": "w2"}], "c2"), cursor_page([{"id": "w3"}], None)],
    )

    assert result.raised is None
    assert [row["id"] for row in result.rows] == ["w1", "w2", "w3"]
    assert result.paths == ["/api/v2/workspaces/my-team/work-items/"] * 2
    assert result.params("cursor") == [None, "c2"]
    for request in result.requests:
        assert request.headers["x-api-key"] == "plane_api_test"
        assert request.param("paginate") == "cursor"
        assert request.param("order_by") == "created_at"
        assert request.param("archived") == "true"
        assert request.param("is_draft") == "false"
        assert request.param("updated_at__gte") is None
    assert result.committed_states == [PlaneResumeConfig(paginator_state={"cursor": "c2"})]


@pytest.mark.parametrize("field", ["updated_at", "created_at"])
def test_incremental_work_items_filter_and_climb_the_chosen_field_on_every_page(field: str) -> None:
    result = _driver().run(
        "work_items",
        [cursor_page([{"id": "w1", field: "2024-01-03T00:00:00Z"}], "c2"), cursor_page([], None)],
        incremental_field=field,
        db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
    )

    assert result.raised is None
    assert result.params(f"{field}__gte") == ["2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"]
    assert result.params("order_by") == [field, field]
    assert result.response is not None
    assert result.response.sort_mode == "asc"


def test_resume_continues_from_the_saved_cursor() -> None:
    result = _driver().run(
        "work_items",
        [cursor_page([{"id": "w9"}], None)],
        resume_state=PlaneResumeConfig(paginator_state={"cursor": "c9"}),
    )

    assert result.params("cursor") == ["c9"]
    assert [row["id"] for row in result.rows] == ["w9"]


@pytest.mark.parametrize(("table", "order_by"), [("projects", "created_at"), ("members", "id")])
def test_lists_walk_cursor_pages_on_a_cursor_eligible_ordering(table: str, order_by: str) -> None:
    result = _driver().run(table, [cursor_page([{"id": "a"}], "c2"), cursor_page([{"id": "b"}], None)])

    assert result.raised is None
    assert [row["id"] for row in result.rows] == ["a", "b"]
    assert result.params("cursor") == [None, "c2"]
    assert result.params("paginate") == ["cursor", "cursor"]
    assert result.params("order_by") == [order_by, order_by]


def test_first_incremental_sync_sends_no_filter_but_orders_by_the_field() -> None:
    result = _driver().run("work_items", [cursor_page([{"id": "w1"}], None)], incremental_field="updated_at")

    assert result.raised is None
    assert result.params("updated_at__gte") == [None]
    assert result.params("order_by") == ["updated_at"]


@pytest.mark.parametrize("table", ["cycles", "states"])
def test_per_project_lists_fan_out_and_carry_the_project_id(table: str) -> None:
    result = _driver().run(
        table,
        route(
            {
                "/workspaces/my-team/projects/": [cursor_page([{"id": "proj-1"}, {"id": "proj-2"}], None)],
                f"/projects/proj-1/{table}/": [cursor_page([{"id": "row-1", "project_id": None}], None)],
                f"/projects/proj-2/{table}/": [
                    ScriptedResponse(
                        status=404, json={"type": "not_found", "code": "not_found", "detail": "Not found."}
                    )
                ],
            }
        ),
    )

    assert result.raised is None
    assert result.rows == [{"id": "row-1", "project_id": "proj-1"}]


def test_a_server_that_repeats_its_cursor_stops_the_walk() -> None:
    result = _driver().run("projects", always(cursor_page([{"id": "p1"}], "same")))

    assert result.raised is not None
    assert len(result.requests) == 2


@pytest.mark.parametrize("table", ["members", "cycles"])
def test_a_response_without_the_data_envelope_fails_instead_of_syncing_nothing(table: str) -> None:
    result = _driver().run(table, always(ScriptedResponse(json={"results": []})))

    assert result.raised is not None


ME = {"id": "u-1", "display_name": "Example User"}
UNAUTHORIZED = {"type": "unauthorized", "code": "unauthorized", "detail": "Authentication credentials were not valid."}
NOT_FOUND = {"type": "not_found", "code": "not_found", "detail": "The requested resource was not found."}


@pytest.mark.parametrize(
    ("me", "projects", "expected"),
    [
        (ScriptedResponse(json=ME), cursor_page([], None), None),
        (ScriptedResponse(status=401, json=UNAUTHORIZED), None, INVALID_KEY_MESSAGE),
        (ScriptedResponse(json=ME), ScriptedResponse(status=404, json=NOT_FOUND), WORKSPACE_MESSAGE),
    ],
)
def test_validate_credentials_checks_the_key_before_the_workspace(
    me: ScriptedResponse, projects: ScriptedResponse | None, expected: str | None
) -> None:
    script = route({"/users/me/": [me], "/workspaces/my-team/projects/": [projects] if projects else []})

    with scripted_network(script) as network:
        assert PlaneSource().validate_credentials(CONFIG, team_id=1) == (expected is None, expected)

    assert network.requests_log[0].url == "https://api.plane.so/api/v2/users/me/"
    assert len(network.requests_log) == (1 if projects is None else 2)


MIXINS = "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins"


def test_an_internal_instance_url_is_refused_on_connect_and_on_sync_without_a_request() -> None:
    config = PlaneSourceConfig(api_key="plane_api_test", workspace_slug="my-team", base_url="https://10.0.0.1")

    with patch(f"{MIXINS}.is_cloud", return_value=True), patch(f"{MIXINS}.get_instance_region", return_value="US"):
        with scripted_network(always(ScriptedResponse(json={}))) as network:
            valid, message = PlaneSource().validate_credentials(config, team_id=1)
        result = _driver(config).run("projects", always(ScriptedResponse(json={})))

    assert valid is False and message
    assert network.requests_log == []
    assert isinstance(result.raised, ValueError)
    assert result.requests == []


def test_validate_credentials_refuses_a_slug_that_changes_the_path_without_a_request() -> None:
    config = PlaneSourceConfig(api_key="plane_api_test", workspace_slug="../users/me")

    with scripted_network(always(ScriptedResponse(status=200, json={}))) as network:
        assert PlaneSource().validate_credentials(config, team_id=1) == (False, SLUG_MESSAGE)

    assert network.requests_log == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "https://api.plane.so"),
        ("", "https://api.plane.so"),
        ("plane.example.com/", "https://plane.example.com"),
        ("https://plane.example.com:8443", "https://plane.example.com:8443"),
        ("http://plane.example.com", None),
        ("https://user@plane.example.com", None),
        ("https://169.254.169.254\\@plane.example.com", None),
        ("https://plane.example.com/?next=evil", None),
    ],
)
def test_instance_url_normalizes_or_is_refused(value: str | None, expected: str | None) -> None:
    if expected is None:
        with pytest.raises(ValueError, match=INVALID_URL_MESSAGE):
            normalize_base_url(value)
    else:
        assert normalize_base_url(value) == expected
