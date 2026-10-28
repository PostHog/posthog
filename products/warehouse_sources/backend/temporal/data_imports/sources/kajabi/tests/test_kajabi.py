from typing import Any
from urllib.parse import parse_qs

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RunStopped,
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kajabi import KajabiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kajabi.kajabi import (
    KajabiResumeConfig,
    flatten_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kajabi.source import KajabiSource


def token() -> ScriptedResponse:
    return ScriptedResponse(json={"access_token": "test-access-token", "expires_in": 3600, "token_type": "Bearer"})


def driver() -> SourceDriver:
    return SourceDriver(
        KajabiSource(), KajabiSourceConfig(client_id="test-client", client_secret="test-secret", site_id="123")
    )


def test_purchases_pagination_preserves_site_and_flattens_attributes() -> None:
    result = driver().run(
        "purchases",
        [
            token(),
            ScriptedResponse(
                json={
                    "data": [
                        {
                            "id": "p1",
                            "type": "purchases",
                            "attributes": {"amount_in_cents": 19900, "created_at": "2026-01-01T00:00:00Z"},
                            "relationships": {"offer": {"data": {"id": "o1", "type": "offers"}}},
                        }
                    ],
                    "meta": {"total_pages": 2},
                    "links": {"next": "https://app.kajabi.com/api/v1/purchases?page[number]=2"},
                }
            ),
            ScriptedResponse(
                json={"data": [{"id": "p2", "attributes": {"amount_in_cents": 0}}], "meta": {"total_pages": 2}}
            ),
        ],
    )
    assert result.raised is None
    assert result.paths == ["/v1/oauth/token", "/v1/purchases", "/v1/purchases"]
    assert result.params("page[number]")[1:] == ["1", "2"]
    assert result.params("filter[site_id]")[1:] == ["123", "123"]
    assert result.rows == [
        {
            "id": "p1",
            "type": "purchases",
            "amount_in_cents": 19900,
            "created_at": "2026-01-01T00:00:00Z",
            "relationships": {"offer": {"data": {"id": "o1", "type": "offers"}}},
        },
        {"id": "p2", "amount_in_cents": 0},
    ]
    assert result.committed_states == [KajabiResumeConfig(paginator_state={"page": 2})]
    assert parse_qs((result.requests[0].body or b"").decode()) == {
        "grant_type": ["client_credentials"],
        "client_id": ["test-client"],
        "client_secret": ["test-secret"],
    }
    assert result.requests[1].headers["authorization"] == "Bearer test-access-token"
    assert result.requests[1].headers["accept"] == "application/vnd.api+json"


def test_resume_starts_at_saved_page_without_a_timestamp_filter() -> None:
    result = driver().run(
        "contacts",
        [token(), ScriptedResponse(json={"data": [{"id": "c3"}], "meta": {"total_pages": 3}})],
        resume_state=KajabiResumeConfig(paginator_state={"page": 3}),
    )
    assert result.raised is None
    assert result.params("page[number]")[1:] == ["3"]
    assert result.requests[1].param("filter[site_id]") == "123"
    assert result.requests[1].param("filter[created_in_last]") is None
    assert result.rows == [{"id": "c3"}]


@pytest.mark.parametrize(("schema", "sort"), [("products", "title"), ("transactions", None)])
def test_full_refresh_uses_only_the_endpoint_sort_parameter(schema: str, sort: str | None) -> None:
    result = driver().run(
        schema,
        [token(), ScriptedResponse(json={"data": [{"id": "1"}], "meta": {"total_pages": 1}})],
    )
    assert result.raised is None
    assert result.requests[1].path == f"/v1/{schema}"
    assert result.requests[1].param("sort") == sort
    assert result.requests[1].param("filter[updated_at_gte]") is None
    assert result.requests[1].param("filter[start_date]") is None


@pytest.mark.parametrize(
    ("schema", "relationship", "resource_type"),
    [
        ("contact_offers", "offers", "offers"),
        ("contact_taggings", "tags", "contact_tags"),
    ],
)
def test_contact_relationships_keep_shared_ids_and_resume_completed_contacts(
    schema: str, relationship: str, resource_type: str
) -> None:
    parents = ScriptedResponse(json={"data": [{"id": "c1"}, {"id": "c/2"}], "meta": {"total_pages": 1}})
    child = ScriptedResponse(json={"data": [{"id": "shared", "type": resource_type}]})
    first = driver().run(schema, [token(), parents, child, RunStopped()])
    assert isinstance(first.raised, RunStopped)
    assert first.rows == [{"contact_id": "c1", "id": "shared", "type": resource_type}]
    state = first.committed_states[-1]
    assert state.paginator_state["completed"] == [f"contacts/c1/relationships/{relationship}"]

    resumed = driver().run(schema, [token(), parents, child], resume_state=state)
    assert resumed.raised is None
    assert resumed.paths == ["/v1/oauth/token", "/v1/contacts", f"/v1/contacts/c%2F2/relationships/{relationship}"]
    assert resumed.rows == [{"contact_id": "c/2", "id": "shared", "type": resource_type}]
    assert resumed.requests[1].param("filter[site_id]") == "123"
    assert resumed.requests[2].query == {}
    assert resumed.response is not None
    assert resumed.response.primary_keys == ["contact_id", "id"]


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"id": "1", "attributes": None}, {"id": "1"}),
        (
            {"id": "1", "attributes": {"id": "wrong", "custom": {"choice": None}}},
            {"id": "1", "custom": {"choice": None}},
        ),
    ],
)
def test_flattening_preserves_resource_identity(row: dict[str, Any], expected: dict[str, Any]) -> None:
    assert flatten_resource(row) == expected
