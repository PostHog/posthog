from datetime import UTC, datetime
from typing import Any

import pytest

from products.warehouse_sources.sources.samcart._config import SamCartSourceConfig
from products.warehouse_sources.sources.samcart.samcart import SamCartResumeConfig, add_utm_columns
from products.warehouse_sources.sources.samcart.source import SamCartSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, route, scripted_network

ORDER_A = "01J0000000000000000000000A"
ORDER_B = "01J0000000000000000000000B"


def _driver() -> SourceDriver:
    return SourceDriver(SamCartSource(), SamCartSourceConfig(api_key="sc_test_key"))


def _page(rows: list[dict[str, Any]], next_cursor: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(
        json={"data": rows, "meta": {"next_cursor": next_cursor, "prev_cursor": None, "limit": 100}}
    )


def _order_detail(order_id: str) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "id": order_id,
            "status": "charged",
            "total": 4900,
            "created_at": "2026-01-02T03:04:05Z",
            "cart_items": [{"product_id": "01J00000000000000000000P01", "quantity": 1, "status": "charged"}],
            "attribution": {"utm_parameters": {"source": "newsletter", "medium": "email"}},
            "attribution_enhanced": {"utm_parameters": {"source": "google", "campaign": "spring"}},
        }
    )


class TestListEndpoints:
    def test_walks_cursor_pages_to_the_end_and_stages_the_next_cursor(self) -> None:
        result = _driver().run(
            "Charges",
            [
                _page([{"id": "ch_1", "created_at": "2026-01-01T00:00:00Z"}], next_cursor="cur_2"),
                _page([{"id": "ch_2", "created_at": "2026-01-02T00:00:00Z"}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["ch_1", "ch_2"]
        assert result.paths == ["/v2/charges", "/v2/charges"]
        assert result.params("cursor") == [None, "cur_2"]
        assert result.params("limit") == ["100", "100"]
        assert result.params("sort") == ["id", "id"]
        assert result.requests[0].headers["sc-api"] == "sc_test_key"
        assert result.saved_states == [SamCartResumeConfig(cursor="cur_2")]

    @pytest.mark.parametrize(
        ("inputs", "expected_created_at_min"),
        [
            (
                {"incremental_field": "created_at", "db_incremental_field_last_value": datetime(2026, 1, 2, 3, 4, 5)},
                "2026-01-02T03:04:05Z",
            ),
            (
                {
                    "incremental_field": "created_at",
                    "db_incremental_field_last_value": datetime(2026, 1, 2, 4, 4, 5, tzinfo=UTC),
                },
                "2026-01-02T04:04:05Z",
            ),
            # The first incremental sync sends no filter, so records with no created_at still land.
            ({"incremental_field": "created_at", "db_incremental_field_last_value": None}, None),
            (
                {
                    "incremental_field": "created_at",
                    "should_use_incremental_field": False,
                    "db_incremental_field_last_value": datetime(2026, 1, 2),
                },
                None,
            ),
        ],
    )
    def test_sends_the_watermark_only_on_an_incremental_sync(
        self, inputs: dict[str, Any], expected_created_at_min: str | None
    ) -> None:
        result = _driver().run("Refunds", [_page([{"id": "re_1"}])], **inputs)

        assert result.raised is None
        assert result.params("created_at_min") == [expected_created_at_min]

    def test_resumes_from_the_saved_cursor(self) -> None:
        result = _driver().run(
            "Subscriptions",
            [_page([{"id": "sub_9"}])],
            resume_state=SamCartResumeConfig(cursor="cur_9"),
        )

        assert result.raised is None
        assert result.params("cursor") == ["cur_9"]
        assert [row["id"] for row in result.rows] == ["sub_9"]

    def test_refuses_a_redirect_so_the_api_key_stays_on_samcart(self) -> None:
        result = _driver().run(
            "Charges",
            [
                ScriptedResponse(status=302, headers={"Location": "https://attacker.example.com/v2/charges"}),
                _page([{"id": "ch_1"}]),
            ],
        )

        assert result.raised is not None
        assert "refusing to follow" in str(result.raised)
        assert [request.origin for request in result.requests] == ["https://api.samcart.com"]


class TestOrders:
    def test_reads_each_listed_order_from_the_detail_endpoint_and_skips_deleted_ones(self) -> None:
        result = _driver().run(
            "Orders",
            route(
                {
                    "/v2/orders": [
                        _page([{"id": ORDER_A}], next_cursor="cur_2"),
                        _page([{"id": ORDER_B}]),
                    ],
                    f"/v2/orders/{ORDER_A}": [_order_detail(ORDER_A)],
                    f"/v2/orders/{ORDER_B}": [
                        ScriptedResponse(status=404, json={"error": {"code": "not_found", "message": "Not found"}})
                    ],
                }
            ),
            incremental_field="created_at",
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [ORDER_A]
        assert result.rows[0]["cart_items"][0]["product_id"] == "01J00000000000000000000P01"
        assert result.rows[0]["utm_source"] == "google"
        assert result.paths == ["/v2/orders", f"/v2/orders/{ORDER_A}", "/v2/orders", f"/v2/orders/{ORDER_B}"]
        assert result.params("cursor") == [None, None, "cur_2", None]
        # The watermark and page size go on the list requests, not on the detail requests.
        assert result.params("created_at_min") == ["2026-01-01T00:00:00Z", None, "2026-01-01T00:00:00Z", None]
        assert result.params("limit") == ["100", None, "100", None]


class TestUtmColumns:
    @pytest.mark.parametrize(
        ("order", "expected"),
        [
            (
                {
                    "attribution": {"utm_parameters": {"source": "newsletter", "medium": "email", "content": "hero"}},
                    "attribution_enhanced": {"utm_parameters": {"source": "google", "medium": None}},
                },
                {
                    "utm_source": "google",
                    "utm_medium": "email",
                    "utm_campaign": None,
                    "utm_content": "hero",
                    "lead_source": None,
                },
            ),
            (
                {"attribution": None, "attribution_enhanced": {"utm_parameters": None}},
                {
                    "utm_source": None,
                    "utm_medium": None,
                    "utm_campaign": None,
                    "utm_content": None,
                    "lead_source": None,
                },
            ),
            (
                {"attribution": {"utm_parameters": {"campaign": "launch", "lead_source": "webinar"}}},
                {
                    "utm_source": None,
                    "utm_medium": None,
                    "utm_campaign": "launch",
                    "utm_content": None,
                    "lead_source": "webinar",
                },
            ),
        ],
    )
    def test_prefers_enhanced_attribution_and_falls_back_to_legacy(
        self, order: dict[str, Any], expected: dict[str, Any]
    ) -> None:
        row = add_utm_columns(dict(order))

        assert {column: row[column] for column in expected} == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (200, (True, None)),
            (401, (False, "Invalid SamCart API key")),
            (403, (False, "Your SamCart plan doesn't include API access, or your SamCart account isn't active")),
            (404, (False, "SamCart returned HTTP 404")),
        ],
    )
    def test_maps_the_probe_status(self, status: int, expected: tuple[bool, str | None]) -> None:
        with scripted_network([ScriptedResponse(status=status, json={"data": [], "meta": {}})]) as network:
            assert SamCartSource().validate_credentials(SamCartSourceConfig(api_key="sc_test_key"), 1) == expected

        assert network.requests_log[0].headers["sc-api"] == "sc_test_key"
