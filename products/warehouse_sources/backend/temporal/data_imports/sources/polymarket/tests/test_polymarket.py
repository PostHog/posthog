from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.polymarket import (
    PolymarketSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.polymarket.polymarket import (
    PolymarketResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.polymarket.settings import POLYMARKET_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.polymarket.source import PolymarketSource


def _driver() -> SourceDriver:
    return SourceDriver(PolymarketSource(), PolymarketSourceConfig())


def _keyset_response(data_key: str, items: list[dict[str, Any]], *, next_cursor: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {data_key: items}
    if next_cursor is not None:
        body["next_cursor"] = next_cursor
    return ScriptedResponse(json=body)


def _data_api_response(items: list[dict[str, Any]], *, next_cursor: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "data": items,
            "pagination": {"limit": 1000, "has_more": next_cursor is not None, "next_cursor": next_cursor},
        }
    )


def _array_response(items: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json=items)


class TestPolymarketTransport:
    @parameterized.expand(["events", "markets", "series", "tags"])
    def test_every_endpoint_pins_an_explicit_order(self, endpoint: str) -> None:
        # Without order=id&ascending=true Gamma returns rows in an unspecified order, so a row
        # inserted mid-sync shifts later pages and silently skips or duplicates rows.
        config = POLYMARKET_ENDPOINTS[endpoint]
        response = _keyset_response(config.data_key or "", []) if config.pagination == "keyset" else _array_response([])

        result = _driver().run(endpoint, [response])

        assert result.requests[0].param("order") == "id"
        assert result.requests[0].param("ascending") == "true"
        assert result.requests[0].param("limit") == str(config.page_size)

    @parameterized.expand(["events", "markets"])
    def test_keyset_pagination_walks_then_stops(self, endpoint: str) -> None:
        data_key = POLYMARKET_ENDPOINTS[endpoint].data_key or ""
        result = _driver().run(
            endpoint,
            [
                _keyset_response(data_key, [{"id": "1"}], next_cursor="c1"),
                _keyset_response(data_key, [{"id": "2"}], next_cursor="c2"),
                # next_cursor is absent on the final page.
                _keyset_response(data_key, [{"id": "3"}]),
            ],
        )

        assert [row["id"] for row in result.rows] == ["1", "2", "3"]
        assert result.params("after_cursor") == [None, "c1", "c2"]

    @parameterized.expand(["series", "tags"])
    def test_offset_pagination_advances_and_stops_on_empty_page(self, endpoint: str) -> None:
        # These endpoints return a bare JSON array with no wrapper and no cursor, so an empty page
        # is the only signal that the walk is done.
        page_size = POLYMARKET_ENDPOINTS[endpoint].page_size
        result = _driver().run(
            endpoint,
            [
                _array_response([{"id": str(i)} for i in range(page_size)]),
                _array_response([]),
            ],
        )

        assert len(result.rows) == page_size
        assert result.params("offset") == ["0", str(page_size)]

    def test_data_api_cursor_pagination_walks_then_stops(self) -> None:
        result = _driver().run(
            "biggest_winners",
            [
                _data_api_response([{"position_id": "1", "user_id": "0xa"}], next_cursor="c1"),
                _data_api_response([{"position_id": "2", "user_id": "0xb"}]),
            ],
        )

        assert [row["position_id"] for row in result.rows] == ["1", "2"]
        assert all(request.path == "/v2/biggest-winners" for request in result.requests)
        assert all(request.origin == "https://data-api.polymarket.com" for request in result.requests)
        # The board defaults to one day; without time_period=all each sync replaces the table with
        # only that day's wins. Sending offset is a 400 on the Data API.
        assert result.queries[0] == {"limit": ("1000",), "time_period": ("all",)}
        assert result.requests[1].param("cursor") == "c1"
        assert all(request.param("offset") is None and request.param("order") is None for request in result.requests)

    @parameterized.expand(
        [
            ("events", _keyset_response("events", [{"id": "9"}]), "after_cursor"),
            ("biggest_winners", _data_api_response([{"position_id": "9", "user_id": "0xa"}]), "cursor"),
        ]
    )
    def test_cursor_resume_seeds_the_cursor(self, endpoint: str, response: ScriptedResponse, cursor_param: str) -> None:
        result = _driver().run(endpoint, [response], resume_state=PolymarketResumeConfig(cursor="saved"))

        assert result.requests[0].param(cursor_param) == "saved"

    def test_offset_resume_seeds_the_offset(self) -> None:
        result = _driver().run("tags", [_array_response([])], resume_state=PolymarketResumeConfig(offset=1000))

        assert result.requests[0].param("offset") == "1000"

    @parameterized.expand([("events", ["id"]), ("markets", ["id"]), ("series", ["id"]), ("tags", ["id"])])
    def test_partitions_on_created_at(self, endpoint: str, expected_keys: list[str]) -> None:
        # createdAt is stable; partitioning on updatedAt would rewrite partitions every sync.
        config = POLYMARKET_ENDPOINTS[endpoint]
        response = _keyset_response(config.data_key or "", []) if config.pagination == "keyset" else _array_response([])

        result = _driver().run(endpoint, [response])

        assert result.response is not None
        assert result.response.primary_keys == expected_keys
        assert result.response.partition_keys == ["createdAt"]

    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_validate_credentials_maps_status(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials() is expected

        assert {request.path for request in network.requests_log} == {"/status"}
