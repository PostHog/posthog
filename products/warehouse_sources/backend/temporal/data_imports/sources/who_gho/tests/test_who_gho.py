from datetime import datetime
from typing import Any, Optional

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientNonRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.whogho import WhoGhoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.who_gho.source import WhoGhoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.who_gho.who_gho import (
    MAX_INDICATOR_CODES,
    WhoGhoResumeConfig,
    check_indicator_codes,
    parse_indicator_codes,
    validate_credentials,
)


def _http_response(body: Any, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


class TestParseIndicatorCodes:
    @parameterized.expand(
        [
            ("WHOSIS_000001", ["WHOSIS_000001"]),
            ("WHOSIS_000001\nWHOSIS_000002", ["WHOSIS_000001", "WHOSIS_000002"]),
            ("WHOSIS_000001, WHOSIS_000002", ["WHOSIS_000001", "WHOSIS_000002"]),
            ("WHOSIS_000001;WHOSIS_000002", ["WHOSIS_000001", "WHOSIS_000002"]),
            ("  WHOSIS_000001  \n\n  WHOSIS_000001 ", ["WHOSIS_000001"]),
            ("", []),
            (None, []),
        ]
    )
    def test_parses_and_deduplicates(self, raw: Optional[str], expected: list[str]) -> None:
        assert parse_indicator_codes(raw) == expected


class TestCheckIndicatorCodes:
    def test_rejects_an_empty_list(self) -> None:
        error = check_indicator_codes([])

        assert error is not None and "WHOSIS_000001" in error

    def test_rejects_a_list_over_the_cap(self) -> None:
        codes = [f"CODE.{index}" for index in range(MAX_INDICATOR_CODES + 1)]

        error = check_indicator_codes(codes)

        assert error is not None
        assert str(MAX_INDICATOR_CODES) in error
        assert str(len(codes)) in error


class TestWhoGhoSourceTransport:
    @staticmethod
    def _driver(indicator_codes: str = "") -> SourceDriver:
        return SourceDriver(WhoGhoSource(), WhoGhoSourceConfig(indicator_codes=indicator_codes))

    def test_catalog_endpoint_paginates_using_skip_and_checkpoints_each_non_terminal_page(self) -> None:
        full_page = [{"IndicatorCode": f"CODE{index}"} for index in range(1000)]
        result = self._driver().run(
            "indicators",
            [
                _http_response({"value": full_page}),
                _http_response({"value": []}),
            ],
        )

        # A full page (== $top) means there may be more; a short page below the $top cap is what
        # actually signals the end.
        assert result.params("$skip") == ["0", "1000"]
        assert result.params("$top") == ["1000", "1000"]
        assert result.urls[0].startswith("https://ghoapi.azureedge.net/api/Indicator?")
        # The empty final page still drives pagination/checkpointing, but the resource wrapper
        # only yields non-empty pages downstream.
        assert result.items == [full_page]

        assert result.saved_states == [WhoGhoResumeConfig(offset=1000)]
        # Walking to the end clears the checkpoint.
        assert result.final_state is None

    def test_indicator_data_applies_the_date_filter_only_on_an_incremental_sync(self) -> None:
        incremental = self._driver("WHOSIS_000001").run(
            "indicator_data",
            [_http_response({"value": []})],
            incremental_field="Date",
            db_incremental_field_last_value=datetime(2024, 8, 2, 9, 43, 39),
        )
        full = self._driver("WHOSIS_000001").run(
            "indicator_data",
            [_http_response({"value": []})],
            db_incremental_field_last_value=datetime(2024, 8, 2, 9, 43, 39),
        )

        assert incremental.requests[0].param("$filter") == "date(Date) gt 2024-08-02"
        assert full.requests[0].param("$filter") is None

    def test_indicator_data_checkpoints_the_next_code_when_one_finishes(self) -> None:
        result = self._driver("A\nB").run(
            "indicator_data",
            [
                _http_response({"value": [{"IndicatorCode": "A", "Id": index} for index in range(1000)]}),
                _http_response({"value": [{"IndicatorCode": "A", "Id": 1001}]}),
                _http_response({"value": [{"IndicatorCode": "B", "Id": 1}]}),
            ],
        )

        # A full 1000-row page means there may be more, so the mid-code checkpoint carries the
        # next offset; finishing a code moves to the next one so a restart doesn't re-walk it.
        assert result.saved_states == [
            WhoGhoResumeConfig(offset=1000, item_index=0),
            WhoGhoResumeConfig(offset=0, item_index=1),
            WhoGhoResumeConfig(offset=0, item_index=2),
        ]

    def test_indicator_data_resume_skips_completed_codes(self) -> None:
        result = self._driver("A\nB").run(
            "indicator_data",
            [_http_response({"value": [{"IndicatorCode": "B", "Id": 1}]})],
            resume_state=WhoGhoResumeConfig(offset=3000, item_index=1),
        )

        assert result.paths == ["/api/B"]
        assert result.params("$skip")[0] == "3000"

    @parameterized.expand(
        [
            ("",),
            ("\n".join(f"CODE.{index}" for index in range(MAX_INDICATOR_CODES + 1)),),
        ]
    )
    def test_indicator_data_refuses_an_out_of_bounds_code_list_before_requesting_anything(
        self, indicator_codes: str
    ) -> None:
        result = self._driver(indicator_codes).run("indicator_data", [])

        assert isinstance(result.raised, ValueError)
        assert "WHO GHO source misconfigured" in str(result.raised)
        assert result.requests == []

    def test_dimension_values_fans_out_over_every_discovered_dimension_code(self) -> None:
        result = self._driver().run(
            "dimension_values",
            [
                _http_response({"value": [{"Code": "COUNTRY"}, {"Code": "SEX"}]}),
                _http_response({"value": [{"Code": "AFG", "Dimension": "COUNTRY"}]}),
                _http_response({"value": [{"Code": "SEX_MLE", "Dimension": "SEX"}]}),
            ],
        )

        assert result.paths == [
            "/api/DIMENSION",
            "/api/DIMENSION/COUNTRY/DimensionValues",
            "/api/DIMENSION/SEX/DimensionValues",
        ]
        assert [row["Code"] for row in result.rows] == ["AFG", "SEX_MLE"]

    def test_dimension_values_fails_cleanly_when_discovery_returns_an_html_page(self) -> None:
        maintenance_page = ScriptedResponse(
            body=b" <!DOCTYPE html><html><head><title>Sorry</title></head></html>",
            headers={"Content-Type": "text/html; charset=utf-8"},
        )

        result = self._driver().run("dimension_values", [maintenance_page])

        assert isinstance(result.raised, RESTClientNonRetryableError)
        assert "Non-JSON response from" in str(result.raised)


class TestValidateCredentials:
    def test_rejects_an_empty_code_list(self) -> None:
        ok, error = validate_credentials([])

        assert ok is False
        assert error is not None and "WHOSIS_000001" in error

    def test_rejects_a_code_list_over_the_cap_without_probing(self) -> None:
        ok, error = validate_credentials([f"CODE.{index}" for index in range(MAX_INDICATOR_CODES + 1)])

        assert ok is False
        assert error is not None and str(MAX_INDICATOR_CODES) in error

    def test_accepts_known_codes(self) -> None:
        with scripted_network([_http_response({"value": [{"IndicatorCode": "WHOSIS_000001"}]})]):
            ok, error = validate_credentials(["WHOSIS_000001"])

        assert (ok, error) == (True, None)

    def test_names_the_codes_that_do_not_exist(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("NOT_A_REAL_CODE"):
                return _http_response({}, status_code=404)
            return _http_response({"value": [{"IndicatorCode": "WHOSIS_000001"}]})

        with scripted_network(respond):
            ok, error = validate_credentials(["WHOSIS_000001", "NOT_A_REAL_CODE"])

        assert ok is False
        assert error == "These indicator codes were not found: NOT_A_REAL_CODE."

    @parameterized.expand([(503,), (429,)])
    def test_reports_an_unreachable_api(self, status_code: int) -> None:
        with scripted_network(always(_http_response({}, status_code=status_code))):
            ok, error = validate_credentials(["WHOSIS_000001"])

        assert ok is False
        assert error == "Could not reach the WHO Global Health Observatory API. Please try again."
