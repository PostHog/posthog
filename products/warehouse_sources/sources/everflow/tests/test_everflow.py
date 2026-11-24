from datetime import UTC, date, datetime
from typing import Any, Literal

import pytest
import time_machine

from products.warehouse_sources.sources.everflow._config import EverflowSourceConfig
from products.warehouse_sources.sources.everflow.everflow import (
    EverflowResumeConfig,
    flatten_entity_row,
    validate_credentials,
)
from products.warehouse_sources.sources.everflow.settings import EVERFLOW_ENDPOINTS
from products.warehouse_sources.sources.everflow.source import EverflowSource
from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)

NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)


def _run(endpoint: str, script: Any, region: Literal["us", "eu"] = "us", **inputs: Any) -> DriveResult:
    config = EverflowSourceConfig(api_key="ef_key", region=region, currency_code=None)
    return SourceDriver(EverflowSource(), config).run(endpoint, script, **inputs)


def _table_page(key: str, rows: list[dict[str, Any]], total: int) -> ScriptedResponse:
    return ScriptedResponse(json={key: rows, "paging": {"page": 1, "page_size": 2000, "total_count": total}})


def _entity_row(offer_id: str, affiliate_id: str, clicks: int) -> dict[str, Any]:
    return {
        "columns": [
            {"column_type": "offer", "id": offer_id, "label": f"Offer {offer_id}"},
            {"column_type": "affiliate", "id": affiliate_id, "label": f"Partner {affiliate_id}"},
        ],
        "reporting": {"total_click": clicks, "cv": 1, "payout": 2.5, "revenue": 4.0},
    }


class TestTables:
    @pytest.mark.parametrize(("region", "host"), [("us", "api.eflow.team"), ("eu", "api-eu.eflow.team")])
    def test_walks_pages_until_total_count_is_read(self, region: Literal["us", "eu"], host: str) -> None:
        result = _run(
            "offers",
            [
                _table_page("offers", [{"network_offer_id": 1}], total=2500),
                _table_page("offers", [{"network_offer_id": 2}], total=2500),
            ],
            region=region,
        )

        assert result.raised is None
        assert {request.origin for request in result.requests} == {f"https://{host}"}
        assert [request.method for request in result.requests] == ["POST", "POST"]
        assert result.paths == ["/v1/networks/offerstable"] * 2
        assert result.params("page") == ["1", "2"]
        assert result.params("page_size") == ["2000", "2000"]
        assert result.requests[0].headers["x-eflow-api-key"] == "ef_key"
        assert [row["network_offer_id"] for row in result.rows] == [1, 2]
        assert result.saved_states == [EverflowResumeConfig(next_page=2)]

    def test_advertisers_drop_the_postback_verification_token(self) -> None:
        result = _run(
            "advertisers",
            [
                _table_page(
                    "advertisers",
                    [{"network_advertiser_id": 135, "name": "Brand", "verification_token": "updatedtoken123"}],
                    total=1,
                )
            ],
        )

        assert result.raised is None
        assert result.rows == [{"network_advertiser_id": 135, "name": "Brand"}]

    @pytest.mark.parametrize(
        ("endpoint", "row", "expected_types"),
        [
            (
                "conversions",
                {"conversion_id": "c1", "payout": 30, "revenue": None, "sale_amount": 0},
                {"conversion_id": str, "payout": float, "revenue": type(None), "sale_amount": float},
            ),
            (
                "offers",
                {
                    "network_offer_id": 1,
                    "payout_amount": 30,
                    "revenue_amount": 4.5,
                    "today_payout_amount": 0,
                    "today_revenue_amount": None,
                },
                {
                    "network_offer_id": int,
                    "payout_amount": float,
                    "revenue_amount": float,
                    "today_payout_amount": float,
                    "today_revenue_amount": type(None),
                },
            ),
            (
                "affiliate_tiers",
                {"network_affiliate_tier_id": 2, "payout_margin": 10},
                {"network_affiliate_tier_id": int, "payout_margin": float},
            ),
            (
                "partner_invoices",
                {"network_affiliate_invoice_id": 7, "balance": 0, "billed": 120, "paid": 120.5},
                {"network_affiliate_invoice_id": int, "balance": float, "billed": float, "paid": float},
            ),
            (
                "reporting_adjustments",
                {
                    "network_reporting_adjustment_id": 9,
                    "conversions": 3,
                    "payout": -15,
                    "revenue": 22.5,
                    "gross_sales": 0,
                    "media_buying_cost": None,
                },
                {
                    "network_reporting_adjustment_id": int,
                    "conversions": int,
                    "payout": float,
                    "revenue": float,
                    "gross_sales": float,
                    "media_buying_cost": type(None),
                },
            ),
        ],
    )
    def test_whole_amounts_arrive_as_floats(
        self, endpoint: str, row: dict[str, Any], expected_types: dict[str, type]
    ) -> None:
        result = _run(endpoint, [_table_page(EVERFLOW_ENDPOINTS[endpoint].data_selector, [row], total=1)])

        assert result.raised is None
        assert result.rows == [row]
        assert [{column: type(value) for column, value in mapped.items()} for mapped in result.rows] == [expected_types]

    @pytest.mark.parametrize(
        ("endpoint", "path", "key", "id_field", "page_size"),
        [
            (
                "partner_invoices",
                "/v1/networks/billings/affiliates/invoicestable",
                "invoices",
                "network_affiliate_invoice_id",
                500,
            ),
            ("creatives", "/v1/networks/creativestable", "creatives", "network_offer_creative_id", 2000),
        ],
    )
    def test_post_tables_page_until_total_count(
        self, endpoint: str, path: str, key: str, id_field: str, page_size: int
    ) -> None:
        result = _run(
            endpoint,
            [
                _table_page(key, [{id_field: 1}], total=page_size + 1),
                _table_page(key, [{id_field: 2}], total=page_size + 1),
            ],
        )

        assert result.raised is None
        assert [request.method for request in result.requests] == ["POST", "POST"]
        assert result.paths == [path] * 2
        assert result.params("page") == ["1", "2"]
        assert result.params("page_size") == [str(page_size)] * 2
        assert [row[id_field] for row in result.rows] == [1, 2]

    @pytest.mark.parametrize(
        ("endpoint", "path", "key", "row"),
        [
            (
                "categories",
                "/v1/networks/categories",
                "categories",
                {"network_category_id": 6, "name": "Gaming", "status": "active"},
            ),
            (
                "affiliate_tiers",
                "/v1/networks/affiliatetiers",
                "tiers",
                {"network_affiliate_tier_id": 2, "network_affiliate_ids": [14, 21], "is_default_tier": False},
            ),
            (
                "labels",
                "/v1/networks/labels",
                "labels",
                {"label": "vip", "offer_ids": [882], "affiliate_ids": None},
            ),
            (
                "traffic_sources",
                "/v1/networks/trafficsource",
                "traffic_sources",
                {
                    "network_traffic_source_id": 3,
                    "name": "Newsletter",
                    "relationship": {"parameters": {"total": 1, "entries": [{"tracking_parameter": "sub1"}]}},
                },
            ),
        ],
    )
    def test_lookups_read_one_unpaged_get(self, endpoint: str, path: str, key: str, row: dict[str, Any]) -> None:
        # The lookups return no `paging` object, so a page loop would ask for the same rows again.
        result = _run(endpoint, always(ScriptedResponse(json={key: [row]})))

        assert result.raised is None
        assert [(request.method, request.path) for request in result.requests] == [("GET", path)]
        assert result.params("page") == [None]
        assert result.params("page_size") == [None]
        assert result.requests[0].body in (b"", None)
        assert result.rows == [row]

    def test_a_rejected_key_fails_the_run_with_the_status_the_error_map_matches(self) -> None:
        result = _run(
            "affiliates", always(ScriptedResponse(status=401, json={"Error": "Unable to authenticate request"}))
        )

        assert result.raised is not None
        assert "401 Client Error: Unauthorized for url" in str(result.raised)


class TestAffiliateUsers:
    def test_reads_the_users_of_every_partner_on_every_page(self) -> None:
        result = _run(
            "affiliate_users",
            route(
                {
                    "/networks/affiliatestable": [
                        _table_page("affiliates", [{"network_affiliate_id": 101}, {"network_affiliate_id": 102}], 2001),
                        _table_page("affiliates", [{"network_affiliate_id": 203}], 2001),
                    ],
                    "/networks/affiliates/101/users": [
                        ScriptedResponse(
                            json={"users": [{"network_affiliate_user_id": 1, "network_affiliate_id": 101}]}
                        )
                    ],
                    # A partner deleted after the listing.
                    "/networks/affiliates/102/users": [ScriptedResponse(status=404, json={"Error": "Not found"})],
                    "/networks/affiliates/203/users": [
                        ScriptedResponse(
                            json={"users": [{"network_affiliate_user_id": 2, "network_affiliate_id": 203}]}
                        )
                    ],
                }
            ),
        )

        assert result.raised is None
        parent_requests = [request for request in result.requests if request.path == "/v1/networks/affiliatestable"]
        assert [request.method for request in parent_requests] == ["POST", "POST"]
        assert [request.param("page") for request in parent_requests] == ["1", "2"]
        assert {request.method for request in result.requests if request.path.endswith("/users")} == {"GET"}
        assert sorted((row["network_affiliate_id"], row["network_affiliate_user_id"]) for row in result.rows) == [
            (101, 1),
            (203, 2),
        ]


class TestConversions:
    @time_machine.travel(NOW, tick=False)
    @pytest.mark.parametrize(
        ("incremental_field", "last_value", "expected_from"),
        [
            (None, None, "2025-10-16"),
            # Statuses and payouts change after the conversion, so the window re-reads 30 days.
            ("conversion_unix_timestamp", int(datetime(2026, 9, 1, 23, tzinfo=UTC).timestamp()), "2026-08-02"),
            ("conversion_unix_timestamp", int(datetime(2024, 1, 1, tzinfo=UTC).timestamp()), "2025-10-16"),
        ],
    )
    def test_requests_a_window_inside_the_reports_365_day_reach(
        self, incremental_field: str | None, last_value: Any, expected_from: str
    ) -> None:
        inputs: dict[str, Any] = {"db_incremental_field_last_value": last_value}
        if incremental_field:
            inputs["incremental_field"] = incremental_field
        result = _run("conversions", [_table_page("conversions", [{"conversion_id": "c1"}], total=1)], **inputs)

        assert result.raised is None
        assert result.params("page_size") == ["500"]
        assert result.requests[0].json() == {
            "from": expected_from,
            "to": "2026-10-16",
            "timezone_id": 67,
            "show_conversions": True,
            "show_events": True,
        }
        assert result.response is not None and result.response.sort_mode == "desc"

    @time_machine.travel(NOW, tick=False)
    @pytest.mark.parametrize(
        ("incremental_field", "last_value", "expected_from"),
        [
            (None, None, "2025-10-16"),
            # The pipeline applies the lookback, so the source sends the shifted cursor as it is.
            ("date_adjustment", "2026-09-01", "2026-09-01"),
            ("date_adjustment", "2024-01-01", "2025-10-16"),
        ],
    )
    def test_reporting_adjustments_request_a_window_without_conversion_flags(
        self, incremental_field: str | None, last_value: Any, expected_from: str
    ) -> None:
        inputs: dict[str, Any] = {"db_incremental_field_last_value": last_value}
        if incremental_field:
            inputs["incremental_field"] = incremental_field
        result = _run(
            "reporting_adjustments",
            [
                _table_page("adjustments", [{"network_reporting_adjustment_id": 1}], total=501),
                _table_page("adjustments", [{"network_reporting_adjustment_id": 2}], total=501),
            ],
            **inputs,
        )

        assert result.raised is None
        assert result.paths == ["/v1/networks/reportingadjustments/table"] * 2
        assert result.params("page_size") == ["500", "500"]
        assert [request.json() for request in result.requests] == [
            {"from": expected_from, "to": "2026-10-16", "timezone_id": 67}
        ] * 2
        assert [row["network_reporting_adjustment_id"] for row in result.rows] == [1, 2]
        assert result.saved_states == [
            EverflowResumeConfig(next_page=2, window_start=expected_from, window_end="2026-10-16")
        ]

    @time_machine.travel(NOW, tick=False)
    @pytest.mark.parametrize(
        ("endpoint", "inputs"),
        [
            (
                "conversions",
                {
                    "incremental_field": "conversion_unix_timestamp",
                    "db_incremental_field_last_value": int(datetime(2026, 10, 1, tzinfo=UTC).timestamp()),
                },
            ),
            ("reporting_adjustments", {}),
        ],
    )
    def test_resume_keeps_the_interrupted_window_and_page(self, endpoint: str, inputs: dict[str, Any]) -> None:
        result = _run(
            endpoint,
            [_table_page(EVERFLOW_ENDPOINTS[endpoint].data_selector, [], total=0)],
            resume_state=EverflowResumeConfig(next_page=4, window_start="2026-08-01", window_end="2026-10-15"),
            **inputs,
        )

        assert result.raised is None
        assert result.params("page") == ["4"]
        # A resume after midnight keeps the interrupted window, so page offsets still line up.
        assert (result.requests[0].json()["from"], result.requests[0].json()["to"]) == ("2026-08-01", "2026-10-15")


class TestDailyPerformance:
    @time_machine.travel(NOW, tick=False)
    def test_requests_one_day_at_a_time_and_stages_the_next_day(self) -> None:
        result = _run(
            "daily_performance",
            [
                ScriptedResponse(json={"table": [_entity_row("882", "102", 7)], "incomplete_results": False}),
                ScriptedResponse(json={"table": []}),
                ScriptedResponse(json={"table": [_entity_row("882", "103", 2)]}),
            ],
            incremental_field="date",
            db_incremental_field_last_value=date(2026, 10, 13),
        )

        assert result.raised is None
        assert [(request.json()["from"], request.json()["to"]) for request in result.requests] == [
            ("2026-10-13", "2026-10-14"),
            ("2026-10-14", "2026-10-15"),
            ("2026-10-15", "2026-10-16"),
        ]
        assert result.requests[0].json()["currency_id"] == "USD"
        assert [(row["date"], row["network_affiliate_id"], row["total_click"]) for row in result.rows] == [
            ("2026-10-13", 102, 7),
            ("2026-10-15", 103, 2),
        ]
        assert result.saved_states == [
            EverflowResumeConfig(next_day="2026-10-14"),
            EverflowResumeConfig(next_day="2026-10-15"),
        ]
        # The empty day still commits its cursor through the safe point.
        assert EverflowResumeConfig(next_day="2026-10-15") in result.committed_states

    @time_machine.travel(NOW, tick=False)
    def test_a_truncated_day_fails_before_its_cursor_moves_past_it(self) -> None:
        result = _run(
            "daily_performance",
            [ScriptedResponse(json={"table": [_entity_row("882", "102", 7)], "incomplete_results": True})],
            incremental_field="date",
            db_incremental_field_last_value=date(2026, 10, 14),
        )

        assert result.raised is not None
        assert "daily report for 2026-10-14" in str(result.raised)
        assert result.rows == []
        assert result.saved_states == []

    @time_machine.travel(NOW, tick=False)
    def test_resume_starts_at_the_saved_day(self) -> None:
        result = _run(
            "daily_performance",
            [ScriptedResponse(json={"table": []})],
            resume_state=EverflowResumeConfig(next_day="2026-10-15"),
        )

        assert result.raised is None
        assert [request.json()["from"] for request in result.requests] == ["2026-10-15"]

    @time_machine.travel(NOW, tick=False)
    def test_whole_amounts_arrive_as_floats(self) -> None:
        row = _entity_row("882", "102", 7) | {
            "reporting": {"total_click": 7, "cv": 1, "payout": 30, "cpm": 2, "rpm": None}
        }
        result = _run(
            "daily_performance",
            [ScriptedResponse(json={"table": [row]})],
            incremental_field="date",
            db_incremental_field_last_value=date(2026, 10, 15),
        )

        assert result.raised is None
        assert [
            {column: type(value) for column, value in flat.items() if column in row["reporting"]}
            for flat in result.rows
        ] == [{"total_click": int, "cv": int, "payout": float, "cpm": float, "rpm": type(None)}]


class TestFlattenEntityRow:
    @pytest.mark.parametrize(
        ("row", "expected"),
        [
            (
                _entity_row("882", "102", 3),
                {
                    "date": "2026-10-01",
                    "currency_id": "EUR",
                    "network_offer_id": 882,
                    "offer_name": "Offer 882",
                    "network_affiliate_id": 102,
                    "affiliate_name": "Partner 102",
                    "total_click": 3,
                    "cv": 1,
                    "payout": 2.5,
                    "revenue": 4.0,
                },
            ),
            (
                {"columns": None, "reporting": None},
                {"date": "2026-10-01", "currency_id": "EUR", "network_offer_id": None, "network_affiliate_id": None},
            ),
        ],
    )
    def test_flattens_columns_and_metrics(self, row: dict[str, Any], expected: dict[str, Any]) -> None:
        assert flatten_entity_row(row, "2026-10-01", "EUR") == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("response", "expected_valid", "message_fragment"),
        [
            (ScriptedResponse(json={"offers": [], "paging": {"total_count": 0}}), True, None),
        ],
    )
    def test_maps_the_probe_result(self, response: Any, expected_valid: bool, message_fragment: str | None) -> None:
        with scripted_network(always(response)) as network:
            is_valid, message = validate_credentials("ef_key", "us")

        assert is_valid is expected_valid
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message
        assert {request.path for request in network.requests_log} == {"/v1/networks/offerstable"}

    @pytest.mark.parametrize(
        ("currency_code", "valid"), [("USD", True), (" eur ", True), (None, True), ("US", False), ("EURO", False)]
    )
    def test_setup_refuses_a_currency_that_is_not_a_three_letter_code(
        self, currency_code: str | None, valid: bool
    ) -> None:
        config = EverflowSourceConfig(api_key="ef_key", region="us", currency_code=currency_code)
        with scripted_network(always(ScriptedResponse(json={"offers": [], "paging": {"total_count": 0}}))):
            is_valid, message = EverflowSource().validate_credentials(config, team_id=1)

        assert is_valid is valid
        assert valid or (message is not None and "three-letter code" in message)
