from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hyros import HyrosSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hyros.hyros import (
    HyrosResumeConfig,
    _format_hyros_date,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hyros.source import HyrosSource


def _driver() -> SourceDriver:
    return SourceDriver(HyrosSource(), HyrosSourceConfig(api_key="key"))


def _response(result: list[dict[str, Any]], next_page_id: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"request_id": "req-1", "result": result}
    if next_page_id is not None:
        body["nextPageId"] = next_page_id
    return ScriptedResponse(json=body)


class TestFormatHyrosDate:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "2026-03-04T02:58:14-05:00", "2026-03-04T02:58:14-05:00"),
            ("none_passthrough", None, None),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str | None) -> None:
        assert _format_hyros_date(value) == expected


class TestHyrosSourcePagination:
    def test_paginates_until_no_next_page_id(self) -> None:
        result = _driver().run(
            "Leads",
            [
                _response([{"id": "1"}, {"id": "2"}], next_page_id="cursor-1"),
                _response([{"id": "3"}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2", "3"]
        assert len(result.requests) == 2
        assert result.requests[0].url == "https://api.hyros.com/v1/api/v1.0/leads?pageSize=250"
        assert result.queries == [
            {"pageSize": ("250",)},
            {"pageSize": ("250",), "pageId": ("cursor-1",)},
        ]

    def test_does_not_follow_redirects(self) -> None:
        # A redirect off the validated Hyros host would carry the API-Key header with it to an
        # attacker-controlled origin; the client must refuse to follow it (credential-leak guard).
        result = _driver().run(
            "Stages", [ScriptedResponse(status=302, headers={"Location": "https://example.com/elsewhere"})]
        )

        assert result.paths == ["/v1/api/v1.0/stages"]
        assert result.raised is not None
        assert "redirect" in str(result.raised).lower()

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run("Leads", [_response([{"id": "2"}])], resume_state=HyrosResumeConfig(cursor="cursor-1"))

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["2"]
        assert len(result.requests) == 1
        assert result.requests[0].param("pageId") == "cursor-1"

    @parameterized.expand(
        [
            ("Leads", "updatedFromDate"),
            ("Sales", "fromDate"),
            ("Calls", "fromDate"),
            ("Subscriptions", "fromDate"),
        ]
    )
    def test_incremental_endpoint_sends_expected_date_param(self, endpoint: str, param_name: str) -> None:
        result = _driver().run(
            endpoint,
            [_response([{"id": "1"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param(param_name) == "2026-03-04T02:58:14+00:00"

    @parameterized.expand(
        [
            ("sale_full_refresh", "SaleConversionPaths", "SALE", False, False),
            ("call_incremental", "CallConversionPaths", "CALL", True, True),
            ("lead_never_filters_by_join_date", "LeadConversionPaths", "LEAD", True, False),
        ]
    )
    def test_conversion_paths_send_conversion_type(
        self, _name: str, endpoint: str, conversion_type: str, incremental: bool, expect_from_date: bool
    ) -> None:
        result = _driver().run(
            endpoint,
            [_response([{"id": "1"}], next_page_id="cursor-1"), _response([{"id": "2"}])],
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC) if incremental else None,
        )

        assert result.raised is None
        assert result.paths == ["/v1/api/v1.0/conversion-paths"] * 2
        expected: dict[str, tuple[str, ...]] = {"conversionType": (conversion_type,), "pageSize": ("250",)}
        if expect_from_date:
            expected["fromDate"] = ("2026-03-04T00:00:00+00:00",)
        assert result.queries == [expected, {**expected, "pageId": ("cursor-1",)}]

    def test_ads_lift_ad_source_keys_to_row_root(self) -> None:
        result = _driver().run(
            "Ads",
            [
                _response(
                    [
                        {"name": "ad", "adSource": {"adSourceId": "238", "adAccountId": "887", "platform": "FACEBOOK"}},
                        {"name": "orphan"},
                    ]
                )
            ],
        )

        assert result.raised is None
        assert [(row["platform"], row["adSourceId"]) for row in result.rows] == [("FACEBOOK", "238"), (None, None)]

    @parameterized.expand(
        [
            ("Stages", "/v1/api/v1.0/stages"),
            ("Carts", "/v1/api/v1.0/carts"),
            ("CustomCosts", "/v1/api/v1.0/custom-costs"),
        ]
    )
    def test_full_refresh_endpoint_never_filters_by_date(self, endpoint: str, path: str) -> None:
        result = _driver().run(
            endpoint,
            [_response([{"id": "1"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.paths == [path]
        assert result.queries == [{"pageSize": ("250",)}]


class TestValidateCredentials:
    def test_ok(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("key") == (True, 200)

        assert [request.path for request in network.requests_log] == ["/v1/api/v1.0/user-info"]
        assert network.requests_log[0].headers["api-key"] == "key"
