import json
from typing import Any, Optional

from parameterized import parameterized
from requests import RequestException, Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ukcompanieshouse import (
    UkCompaniesHouseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uk_companies_house.settings import (
    CHARGES,
    COMPANIES,
    FILING_HISTORY,
    INSOLVENCY,
    OFFICERS,
    PERSONS_WITH_SIGNIFICANT_CONTROL,
    PSC_STATEMENTS,
    UK_ESTABLISHMENTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uk_companies_house.source import (
    UkCompaniesHouseSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uk_companies_house.uk_companies_house import (
    CompaniesHouseOffsetPaginator,
    UkCompaniesHouseResumeConfig,
    invalid_company_numbers,
    parse_company_numbers,
    validate_credentials,
)


def _response(body: Any, status_code: int = 200) -> Response:
    response = Response()
    response.status_code = status_code
    response.url = "https://api.company-information.service.gov.uk/company/00006400"
    response._content = json.dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    return response


class TestParseCompanyNumbers:
    @parameterized.expand(
        [
            ("newlines", "00006400\nSC123456", ["00006400", "SC123456"]),
            ("commas_and_spaces", "00006400, sc123456 ;OC301365", ["00006400", "SC123456", "OC301365"]),
            ("zero_pads_short_numeric", "6400", ["00006400"]),
            ("keeps_alphanumeric_as_typed", "br000123", ["BR000123"]),
            ("dedupes_preserving_order", "00006400\n6400\nSC123456", ["00006400", "SC123456"]),
            ("blank", "   \n , ", []),
            ("none", None, []),
        ]
    )
    def test_parse(self, _label: str, raw: Optional[str], expected: list[str]) -> None:
        assert parse_company_numbers(raw) == expected

    @parameterized.expand(
        [
            ("valid_numeric", ["00006400"], []),
            ("valid_prefixed", ["SC123456", "OC301365", "NI123456"], []),
            ("too_short", ["ABC123"], ["ABC123"]),
            ("too_long", ["000064000"], ["000064000"]),
            ("punctuation", ["0000-640"], ["0000-640"]),
        ]
    )
    def test_invalid_company_numbers(self, _label: str, numbers: list[str], expected: list[str]) -> None:
        assert invalid_company_numbers(numbers) == expected


class TestCompaniesHouseOffsetPaginator:
    @parameterized.expand(
        [
            ("stops_at_total", {"total_results": 2}, [{"n": 1}, {"n": 2}], 2, False),
            ("continues_below_total", {"total_results": 9}, [{"n": 1}, {"n": 2}], 2, True),
            ("stops_on_empty_page", {"total_results": 9}, [], 0, False),
            ("stops_on_short_page_without_total", {}, [{"n": 1}], 1, False),
            ("continues_on_full_page_without_total", {}, [{"n": 1}, {"n": 2}], 2, True),
            ("ignores_non_integer_total", {"total_results": "many"}, [{"n": 1}], 1, False),
        ]
    )
    def test_update_state(
        self,
        _label: str,
        body: dict[str, Any],
        rows: list[dict[str, Any]],
        expected_start_index: int,
        expected_has_next: bool,
    ) -> None:
        paginator = CompaniesHouseOffsetPaginator(total_key="total_results", items_per_page=2)
        paginator.update_state(_response(body), rows)

        assert paginator.start_index == expected_start_index
        assert paginator.has_next_page is expected_has_next

    def test_resume_state_round_trip(self) -> None:
        paginator = CompaniesHouseOffsetPaginator(total_key="total_results", items_per_page=2)
        paginator.update_state(_response({"total_results": 9}), [{"n": 1}, {"n": 2}])
        state = paginator.get_resume_state()
        assert state == {"start_index": 2}

        resumed = CompaniesHouseOffsetPaginator(total_key="total_results", items_per_page=2)
        resumed.set_resume_state(state or {})
        assert resumed.start_index == 2
        assert resumed.has_next_page is True


class TestUkCompaniesHouseSource:
    @staticmethod
    def _driver(company_numbers: str = "00006400") -> SourceDriver:
        return SourceDriver(
            UkCompaniesHouseSource(), UkCompaniesHouseSourceConfig(api_key="key", company_numbers=company_numbers)
        )

    @parameterized.expand(
        [
            (
                "profile_is_one_row_untouched",
                COMPANIES,
                {"company_number": "00006400", "company_name": "Acme"},
                [{"company_number": "00006400", "company_name": "Acme"}],
            ),
            (
                "single_object_endpoint_gets_company_number",
                INSOLVENCY,
                {"status": "liquidation", "cases": [{"type": "compulsory-liquidation"}]},
                [
                    {
                        "status": "liquidation",
                        "cases": [{"type": "compulsory-liquidation"}],
                        "company_number": "00006400",
                    }
                ],
            ),
            (
                "officers_get_appointment_id_from_self_link",
                OFFICERS,
                {
                    "total_results": 1,
                    "items": [{"name": "A Person", "links": {"self": "/company/00006400/appointments/xyz"}}],
                },
                [
                    {
                        "name": "A Person",
                        "links": {"self": "/company/00006400/appointments/xyz"},
                        "company_number": "00006400",
                        "appointment_id": "xyz",
                    }
                ],
            ),
            (
                "officers_without_self_link_get_no_id",
                OFFICERS,
                {"total_results": 1, "items": [{"name": "A Person"}]},
                [{"name": "A Person", "company_number": "00006400", "appointment_id": None}],
            ),
            (
                "establishments_keep_their_own_company_number",
                UK_ESTABLISHMENTS,
                {"items": [{"company_number": "BR000123", "company_name": "Branch"}]},
                [
                    {
                        "company_number": "BR000123",
                        "company_name": "Branch",
                        "parent_company_number": "00006400",
                    }
                ],
            ),
        ]
    )
    def test_row_normalization_per_endpoint(
        self, _label: str, endpoint: str, body: dict[str, Any], expected: list[dict[str, Any]]
    ) -> None:
        result = self._driver().run(endpoint, [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.items == [expected]

    def test_paginates_one_company_until_the_total_is_reached(self) -> None:
        result = self._driver().run(
            FILING_HISTORY,
            [
                ScriptedResponse(json={"total_count": 3, "items": [{"transaction_id": "a"}, {"transaction_id": "b"}]}),
                ScriptedResponse(json={"total_count": 3, "items": [{"transaction_id": "c"}]}),
            ],
        )

        assert result.raised is None
        assert result.params("start_index") == ["0", "2"]
        assert [row["transaction_id"] for row in result.rows] == ["a", "b", "c"]

    @parameterized.expand([(CHARGES,), (PERSONS_WITH_SIGNIFICANT_CONTROL,), (PSC_STATEMENTS,)])
    def test_missing_resource_does_not_fail_the_table(self, endpoint: str) -> None:
        # Companies House 404s both for "this company has nothing filed" and for an unknown
        # company number, and most companies have nothing filed for these resources.
        result = self._driver("00006400\nSC123456").run(
            endpoint,
            [
                ScriptedResponse(status=404, json={}),
                ScriptedResponse(json={"total_results": 1, "items": [{"id": "1"}]}),
            ],
        )

        assert result.raised is None
        assert len(result.requests) == 2
        assert [row["company_number"] for row in result.rows] == ["SC123456"]

    def test_auth_failure_is_not_swallowed(self) -> None:
        result = self._driver().run(OFFICERS, [ScriptedResponse(status=401, json={})])

        assert isinstance(result.raised, HTTPError)
        assert result.raised.response is not None
        assert result.raised.response.status_code == 401

    def test_resume_skips_completed_companies_and_seeds_the_offset(self) -> None:
        result = self._driver("00006400\nSC123456\nOC301365").run(
            OFFICERS,
            [
                ScriptedResponse(json={"total_results": 101, "items": [{"name": "Resumed"}]}),
                ScriptedResponse(json={"total_results": 1, "items": [{"name": "Third"}]}),
            ],
            resume_state=UkCompaniesHouseResumeConfig(company_index=1, start_index=100),
        )

        assert result.raised is None
        assert [
            (request.path.rsplit("/company/", 1)[1], request.param("start_index")) for request in result.requests
        ] == [
            ("SC123456/officers", "100"),
            ("OC301365/officers", "0"),
        ]


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True),
            (401, False),
            (403, False),
            (404, False),
            (429, False),
            (500, False),
        ]
    )
    def test_status_mapping(self, status_code: int, expected_ok: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            ok, error = validate_credentials("key", "00006400")

        assert network.requests_log
        assert all(request.path == "/company/00006400" for request in network.requests_log)
        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_unreachable_api_is_reported_not_raised(self) -> None:
        def fail(_request: Any) -> ScriptedResponse:
            raise RequestException("boom")

        with scripted_network(fail):
            ok, error = validate_credentials("key", "00006400")

        assert ok is False
        assert error is not None and "Could not reach" in error
