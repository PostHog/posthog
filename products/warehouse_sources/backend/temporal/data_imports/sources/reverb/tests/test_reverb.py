from datetime import UTC, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.reverb import ReverbSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.reverb import (
    ReverbResumeConfig,
    _format_datetime,
    _inject_payment_id,
    _inject_payout_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.settings import PER_PAGE
from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.source import ReverbSource


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("string_passthrough", "not-a-date", "not-a-date"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestInjectIdFromLink:
    @parameterized.expand(
        [
            (
                "payout_well_formed_href",
                _inject_payout_id,
                {"_links": {"line_items": {"href": "https://api.reverb.com/api/my/payouts/54/line_items"}}},
                54,
            ),
            ("payout_missing_links", _inject_payout_id, {}, None),
            ("payout_missing_line_items", _inject_payout_id, {"_links": {}}, None),
            ("payout_malformed_href", _inject_payout_id, {"_links": {"line_items": {"href": "not-a-url"}}}, None),
            (
                "payment_well_formed_href",
                _inject_payment_id,
                {"_links": {"self": {"href": "https://reverb.com/api/my/payments/selling/812"}}},
                812,
            ),
            (
                "payment_ignores_order_link",
                _inject_payment_id,
                {"_links": {"order": {"href": "https://reverb.com/api/my/orders/selling/3"}}},
                None,
            ),
            ("payment_null_links", _inject_payment_id, {"_links": None}, None),
        ]
    )
    def test_id_extraction(self, _name: str, inject: Any, row: dict[str, Any], expected_id: int | None) -> None:
        result = inject(dict(row))
        assert result.get("id") == expected_id


def _response(
    response_key: str,
    items: list[dict[str, Any]] | None,
    *,
    current_page: int | None = None,
    total_pages: int | None = None,
    drop_key: bool = False,
) -> ScriptedResponse:
    body: dict[str, Any] = {}
    if not drop_key:
        body[response_key] = items or []
    if current_page is not None:
        body["current_page"] = current_page
    if total_pages is not None:
        body["total_pages"] = total_pages
    return ScriptedResponse(json=body)


def _driver() -> SourceDriver:
    return SourceDriver(ReverbSource(), ReverbSourceConfig(api_token="token"))


class TestReverbSourceOrders:
    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "Orders",
            [_response("orders", [{"order_number": "2"}], current_page=2, total_pages=2)],
            resume_state=ReverbResumeConfig(next_page=2),
        )

        assert [r["order_number"] for r in result.rows] == ["2"]
        assert len(result.requests) == 1
        assert result.requests[0].param("page") == "2"

    def test_missing_metadata_full_page_continues(self) -> None:
        full_page = [{"order_number": str(i)} for i in range(PER_PAGE)]
        result = _driver().run(
            "Orders", [_response("orders", full_page), _response("orders", [{"order_number": "last"}])]
        )

        assert len(result.rows) == PER_PAGE + 1
        assert len(result.requests) == 2


_REFUND_STATES = ("pending_seller_response", "conditionally_approved", "approved", "denied")


class TestReverbSourceRequestShaping:
    @parameterized.expand(
        [
            ("payouts_incremental", "Payouts", "payouts", True, "created_start_date", "created_end_date", ()),
            (
                "refunds_incremental",
                "RefundRequests",
                "refund_requests",
                True,
                "updated_start_date",
                "updated_end_date",
                _REFUND_STATES,
            ),
            (
                "refunds_full_refresh",
                "RefundRequests",
                "refund_requests",
                False,
                "updated_start_date",
                "updated_end_date",
                _REFUND_STATES,
            ),
        ]
    )
    def test_window_and_state_params(
        self,
        _name: str,
        endpoint: str,
        response_key: str,
        incremental: bool,
        start_param: str,
        end_param: str,
        expected_states: tuple[str, ...],
    ) -> None:
        result = _driver().run(
            endpoint,
            [_response(response_key, [], total_pages=1)],
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC) if incremental else None,
        )

        request = result.requests[0]
        assert request.param(start_param) == ("2026-03-04T00:00:00Z" if incremental else None)
        assert (request.param(end_param) is not None) is incremental
        assert request.query.get("state[]", ()) == expected_states


def _payout(payout_id: int) -> dict[str, Any]:
    return {
        "created_at": "2026-02-01T10:00:00-06:00",
        "_links": {"line_items": {"href": f"https://api.reverb.com/api/my/payouts/{payout_id}/line_items"}},
    }


class TestReverbSourceRows:
    @parameterized.expand(
        [
            (
                "payout_line_items_walk_every_child_page_per_payout",
                "PayoutLineItems",
                {
                    "/my/payouts": [
                        _response("payouts", [_payout(31)], current_page=1, total_pages=2),
                        _response("payouts", [_payout(32)], current_page=2, total_pages=2),
                    ],
                    "/my/payouts/31/line_items": [
                        _response("payout_line_items", [{"order_id": 901}], current_page=1, total_pages=2),
                        _response("payout_line_items", [{"order_id": 902}], current_page=2, total_pages=2),
                    ],
                    "/my/payouts/32/line_items": [
                        _response("payout_line_items", [{"order_id": 903}], current_page=1, total_pages=1),
                    ],
                },
                [
                    {"order_id": 901, "payout_id": 31},
                    {"order_id": 902, "payout_id": 31},
                    {"order_id": 903, "payout_id": 32},
                ],
            ),
            (
                "bump_statistics_one_row_per_listing_and_skip_missing_listing",
                "BumpStatistics",
                {
                    "/my/listings": [_response("listings", [{"id": 71}, {"id": 72}, {"id": 73}], total_pages=1)],
                    "/listings/71/bump": [ScriptedResponse(json={"bump_v2_stats": {"impressions": 15}, "bids": []})],
                    "/listings/72/bump": [ScriptedResponse(status=404, json={"message": "Not found"})],
                    "/listings/73/bump": [ScriptedResponse(json={"budgets": [], "bids": []})],
                },
                [
                    {"bump_v2_stats": {"impressions": 15}, "bids": [], "listing_id": 71},
                    {"budgets": [], "bids": [], "listing_id": 73},
                ],
            ),
            (
                "payments_get_id_from_self_link",
                "Payments",
                {
                    "/my/payments/selling": [
                        _response(
                            "payments",
                            [
                                {
                                    "status": "completed",
                                    "_links": {"self": {"href": "https://reverb.com/api/my/payments/selling/44"}},
                                }
                            ],
                            total_pages=1,
                        )
                    ],
                },
                [
                    {
                        "status": "completed",
                        "_links": {"self": {"href": "https://reverb.com/api/my/payments/selling/44"}},
                        "id": 44,
                    }
                ],
            ),
        ]
    )
    def test_rows(
        self,
        _name: str,
        endpoint: str,
        table: dict[str, list[ScriptedResponse]],
        expected_rows: list[dict[str, Any]],
    ) -> None:
        result = _driver().run(endpoint, route(table))

        assert result.raised is None
        assert result.rows == expected_rows
