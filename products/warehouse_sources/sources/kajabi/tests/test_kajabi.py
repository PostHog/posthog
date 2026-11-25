from urllib.parse import parse_qs

import pytest

from products.warehouse_sources.sources.kajabi._config import KajabiSourceConfig
from products.warehouse_sources.sources.kajabi.kajabi import KajabiResumeConfig
from products.warehouse_sources.sources.kajabi.source import KajabiSource
from products.warehouse_sources.sources.sdk.testing import RunStopped, ScriptedResponse, SourceDriver


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


@pytest.mark.parametrize(
    ("schema", "path", "sort", "page_size"),
    [
        ("products", "products", "title", "100"),
        ("transactions", "transactions", None, "100"),
        ("payouts", "kajabi_payments_payouts", None, None),
    ],
)
def test_full_refresh_uses_only_the_endpoint_list_parameters(
    schema: str, path: str, sort: str | None, page_size: str | None
) -> None:
    result = driver().run(
        schema,
        [
            token(),
            ScriptedResponse(json={"data": [{"id": "1"}], "meta": {"total_pages": 1, "pagination": {"last": 1}}}),
        ],
    )
    assert result.raised is None
    assert result.requests[1].path == f"/v1/{path}"
    assert result.requests[1].param("filter[site_id]") == "123"
    assert result.requests[1].param("sort") == sort
    assert result.requests[1].param("page[size]") == page_size
    assert result.requests[1].param("filter[updated_at_gte]") is None
    assert result.requests[1].param("filter[start_date]") is None


def test_payouts_stop_at_the_last_page_from_pagination_meta() -> None:
    def page(number: int) -> ScriptedResponse:
        return ScriptedResponse(
            json={
                "data": [
                    {
                        "id": f"payout_{number}",
                        "type": "kajabi_payments_payouts",
                        "attributes": {"amount": 1500.0, "initiated_date": "2026-01-10T10:00:00.000Z"},
                    }
                ],
                "meta": {"total": 2, "pagination": {"current": number, "first": 1, "last": 2, "records": 1}},
            }
        )

    result = driver().run("payouts", [token(), page(1), page(2)])
    assert result.raised is None
    assert result.paths == ["/v1/oauth/token", "/v1/kajabi_payments_payouts", "/v1/kajabi_payments_payouts"]
    assert result.params("page[number]")[1:] == ["1", "2"]
    assert [row["id"] for row in result.rows] == ["payout_1", "payout_2"]
    assert result.rows[0]["initiated_date"] == "2026-01-10T10:00:00.000Z"


@pytest.mark.parametrize(
    ("schema", "parent", "parent_key", "parent_sort", "relationship", "resource_type"),
    [
        ("contact_offers", "contacts", "contact_id", "created_at", "offers", "offers"),
        ("contact_taggings", "contacts", "contact_id", "created_at", "tags", "contact_tags"),
        ("offer_products", "offers", "offer_id", "title", "products", "products"),
    ],
)
def test_relationships_keep_shared_ids_and_resume_completed_parents(
    schema: str, parent: str, parent_key: str, parent_sort: str, relationship: str, resource_type: str
) -> None:
    parents = ScriptedResponse(json={"data": [{"id": "p1"}, {"id": "p/2"}], "meta": {"total_pages": 1}})
    child = ScriptedResponse(json={"data": [{"id": "shared", "type": resource_type}]})
    first = driver().run(schema, [token(), parents, child, RunStopped()])
    assert isinstance(first.raised, RunStopped)
    assert first.rows == [{parent_key: "p1", "id": "shared", "type": resource_type}]
    state = first.committed_states[-1]
    assert state.paginator_state["completed"] == [f"{parent}/p1/relationships/{relationship}"]

    resumed = driver().run(schema, [token(), parents, child], resume_state=state)
    assert resumed.raised is None
    assert resumed.paths == ["/v1/oauth/token", f"/v1/{parent}", f"/v1/{parent}/p%2F2/relationships/{relationship}"]
    assert resumed.rows == [{parent_key: "p/2", "id": "shared", "type": resource_type}]
    assert resumed.requests[1].param("filter[site_id]") == "123"
    assert resumed.requests[1].param("sort") == parent_sort
    assert resumed.requests[2].query == {}
    assert resumed.response is not None
    assert resumed.response.primary_keys == [parent_key, "id"]
