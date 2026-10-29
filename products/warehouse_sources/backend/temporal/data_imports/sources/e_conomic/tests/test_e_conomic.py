from datetime import UTC, date, datetime
from typing import Any

import pytest

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.e_conomic import (
    E_CONOMIC_BASE_URL,
    EConomicResumeConfig,
    _assert_trusted_url,
    _format_incremental_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.settings import (
    E_CONOMIC_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.source import EConomicSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.economic import (
    EConomicSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(EConomicSource(), EConomicSourceConfig(app_secret_token="app", agreement_grant_token="grant"))


def _page(
    collection: list[dict[str, Any]] | None,
    *,
    next_page: str | None = None,
    status_code: int = 200,
) -> ScriptedResponse:
    body: dict[str, Any] = {"pagination": {}}
    if next_page is not None:
        body["pagination"]["nextPage"] = next_page
    body["collection"] = collection or []
    return ScriptedResponse(status=status_code, json=body)


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04"),
            ("integer_cursor", 1052, "1052"),
            ("string_passthrough", "abc", "abc"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestAssertTrustedUrl:
    @parameterized.expand(
        [
            ("other_host", "https://evil.example.com/customers"),
            ("subdomain_spoof", "https://restapi.e-conomic.com.evil.example.com/customers"),
            ("http_scheme", "http://restapi.e-conomic.com/customers"),
            ("no_scheme", "//restapi.e-conomic.com/customers"),
        ]
    )
    def test_untrusted_url_raises(self, _name: str, url: str) -> None:
        with pytest.raises(ValueError):
            _assert_trusted_url(url)


class TestFirstRequestParams:
    def test_incremental_datetime_builds_gte_filter(self) -> None:
        result = _driver().run(
            "customers",
            [_page([{"customerNumber": 1}])],
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            incremental_field="lastUpdated",
        )

        assert result.raised is None
        assert result.requests[0].param("filter") == "lastUpdated$gte:2026-01-02T03:04:05Z"
        assert result.requests[0].param("sort") == "lastUpdated"


class TestPagination:
    def test_follows_next_page_links_until_absent(self) -> None:
        next_url = f"{E_CONOMIC_BASE_URL}/customers?skippages=1"
        result = _driver().run(
            "customers",
            [
                _page([{"customerNumber": 1}], next_page=next_url),
                _page([{"customerNumber": 2}]),
            ],
        )

        assert result.raised is None
        assert [row["customerNumber"] for row in result.rows] == [1, 2]
        assert len(result.requests) == 2

    def test_resumes_from_saved_state(self) -> None:
        resume_url = f"{E_CONOMIC_BASE_URL}/customers?skippages=5"
        result = _driver().run(
            "customers", [_page([{"customerNumber": 99}])], resume_state=EConomicResumeConfig(next_url=resume_url)
        )

        # First (and only) fetch starts at the resumed URL, not the endpoint's first page.
        assert result.raised is None
        assert result.urls == [resume_url]


class TestAccountingYearEntriesFanout:
    def _years_page(self) -> ScriptedResponse:
        return _page(
            [
                {"year": "2022", "entries": f"{E_CONOMIC_BASE_URL}/accounting-years/2022/entries"},
                {"year": "2022/2023", "entries": f"{E_CONOMIC_BASE_URL}/accounting-years/2022_6_2023/entries"},
            ]
        )

    def test_walks_each_year_through_its_entries_link(self) -> None:
        second_page = f"{E_CONOMIC_BASE_URL}/accounting-years/2022/entries?skippages=1"
        result = _driver().run(
            "accounting_year_entries",
            [
                self._years_page(),
                _page([{"entryNumber": 1}], next_page=second_page),
                _page([{"entryNumber": 2}]),
                _page([{"entryNumber": 1}]),
            ],
        )

        assert result.raised is None
        assert [(r["accountingYear"], r["entryNumber"]) for r in result.rows] == [
            ("2022", 1),
            ("2022", 2),
            ("2022/2023", 1),
        ]
        assert [url.split("?")[0] for url in result.urls] == [
            f"{E_CONOMIC_BASE_URL}/accounting-years",
            f"{E_CONOMIC_BASE_URL}/accounting-years/2022/entries",
            f"{E_CONOMIC_BASE_URL}/accounting-years/2022/entries",
            f"{E_CONOMIC_BASE_URL}/accounting-years/2022_6_2023/entries",
        ]
        assert result.urls[2] == second_page
        assert result.params("sort")[1] == "entryNumber"

    def test_resume_skips_completed_years(self) -> None:
        result = _driver().run(
            "accounting_year_entries",
            [self._years_page(), _page([{"entryNumber": 5}])],
            resume_state=EConomicResumeConfig(
                fanout_state={"completed": ["/accounting-years/2022/entries"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert [(r["accountingYear"], r["entryNumber"]) for r in result.rows] == [("2022/2023", 5)]
        assert result.paths[-1] == "/accounting-years/2022_6_2023/entries"
        assert "/accounting-years/2022_6_2023/entries" in result.saved_states[-1].fanout_state["completed"]


class TestTotalsAndVouchersFanout:
    def test_year_totals_walk_each_year_through_its_totals_link(self) -> None:
        result = _driver().run(
            "accounting_year_totals",
            [
                _page(
                    [
                        {"year": "2022", "totals": f"{E_CONOMIC_BASE_URL}/accounting-years/2022/totals"},
                        {"year": "2022/2023", "totals": f"{E_CONOMIC_BASE_URL}/accounting-years/2022_6_2023/totals"},
                    ]
                ),
                _page([{"account": {"accountNumber": 1000}, "totalInBaseCurrency": 5}]),
                _page([{"account": {"accountNumber": 1000}, "totalInBaseCurrency": 7}]),
            ],
        )

        assert result.raised is None
        assert [(r["accountingYear"], r["accountNumber"], r["totalInBaseCurrency"]) for r in result.rows] == [
            ("2022", 1000, 5),
            ("2022/2023", 1000, 7),
        ]
        assert result.paths[1:] == ["/accounting-years/2022/totals", "/accounting-years/2022_6_2023/totals"]

    def test_period_totals_walk_years_then_periods_then_totals(self) -> None:
        def period(number: int) -> dict[str, Any]:
            return {
                "periodNumber": number,
                "accountingYear": {"year": "2024"},
                # The API echoes the parent request's query string into these links.
                "totals": f"{E_CONOMIC_BASE_URL}/accounting-years/2024/periods/{number}/totals?pagesize=1000",
            }

        second_page = f"{E_CONOMIC_BASE_URL}/accounting-years/2024/periods/25/totals?skippages=1"
        result = _driver().run(
            "accounting_period_totals",
            [
                _page([{"year": "2024", "periods": f"{E_CONOMIC_BASE_URL}/accounting-years/2024/periods"}]),
                _page([period(25), period(26)]),
                _page([{"account": {"accountNumber": 1000}}], next_page=second_page),
                _page([{"account": {"accountNumber": 1010}}]),
                _page([{"account": {"accountNumber": 1000}}]),
            ],
        )

        assert result.raised is None
        assert [(r["accountingYear"], r["periodNumber"], r["accountNumber"]) for r in result.rows] == [
            ("2024", 25, 1000),
            ("2024", 25, 1010),
            ("2024", 26, 1000),
        ]
        assert result.paths == [
            "/accounting-years",
            "/accounting-years/2024/periods",
            "/accounting-years/2024/periods/25/totals",
            "/accounting-years/2024/periods/25/totals",
            "/accounting-years/2024/periods/26/totals",
        ]
        assert result.urls[3] == second_page

    def test_vouchers_carry_journal_and_flat_accounting_year(self) -> None:
        result = _driver().run(
            "journal_vouchers",
            [
                _page([{"journalNumber": 3}, {"journalNumber": 11}]),
                _page([{"voucherNumber": 20001, "accountingYear": {"year": "2022"}}]),
                _page([{"voucherNumber": 0, "accountingYear": {"year": "2024"}}]),
            ],
        )

        assert result.raised is None
        assert [(r["journalNumber"], r["accountingYear"], r["voucherNumber"]) for r in result.rows] == [
            (3, "2022", 20001),
            (11, "2024", 0),
        ]
        assert result.paths[1:] == ["/journals/3/vouchers", "/journals/11/vouchers"]
        # The vouchers endpoint rejects every sort field with a 400.
        assert result.params("sort")[1:] == [None, None]


class TestErrorHandling:
    @parameterized.expand([("server_error", 500), ("bad_gateway", 503), ("throttled", 429)])
    def test_retryable_status_is_retried(self, _name: str, status_code: int) -> None:
        result = _driver().run(
            "customers",
            [_page(None, status_code=status_code), _page([{"customerNumber": 7}])],
        )

        assert result.raised is None
        assert [row["customerNumber"] for row in result.rows] == [7]
        assert len(result.requests) == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_error_raises_http_error(self, _name: str, status_code: int) -> None:
        result = _driver().run("customers", [_page(None, status_code=status_code)])

        assert isinstance(result.raised, requests.HTTPError)

    def test_redirect_is_rejected(self) -> None:
        # Redirects are disabled so a bounce can't carry the auth headers to another host.
        result = _driver().run(
            "customers",
            [ScriptedResponse(status=302, headers={"Location": "https://evil.example.com/"})],
        )

        assert isinstance(result.raised, ValueError)
        assert result.paths == ["/customers"]

    @parameterized.expand(
        [
            ("other_host", "https://evil.example.com/customers"),
            ("subdomain_spoof", "https://restapi.e-conomic.com.evil.example.com/customers"),
            ("http_scheme", "http://restapi.e-conomic.com/customers"),
        ]
    )
    def test_off_host_next_page_link_is_rejected(self, _name: str, bad_next_page: str) -> None:
        # A `nextPage` link pointing off-host or over plain http must abort before it is fetched.
        result = _driver().run("customers", [_page([{"customerNumber": 1}], next_page=bad_next_page)])

        assert isinstance(result.raised, ValueError)
        # Only the first (valid) request was sent; the bad link was never fetched.
        assert result.paths == ["/customers"]


class TestSourceResponse:
    @parameterized.expand(sorted(ENDPOINTS))
    def test_primary_keys_and_sort_mode(self, endpoint: str) -> None:
        config = E_CONOMIC_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [_page([])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.primary_keys == config.primary_keys
        # Only sortable endpoints advertise ascending order; unsortable ones (e.g. payment_terms) don't.
        assert result.response.sort_mode == ("asc" if config.sort else None)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_code_maps_to_bool(self, _name: str, status_code: int, expected: bool) -> None:
        answer = ScriptedResponse(status=status_code)
        script = always(answer) if status_code >= 500 else [answer]
        with scripted_network(script) as network:
            assert validate_credentials("app", "grant") is expected

        assert network.requests_log
        assert {request.path for request in network.requests_log} == {"/self"}

    def test_probe_does_not_follow_redirects(self) -> None:
        # Credentials ride in X-AppSecretToken / X-AgreementGrantToken headers, which requests does
        # not strip on a cross-origin redirect — so the probe must not follow one and replay them.
        response = ScriptedResponse(status=302, headers={"Location": "https://evil.example.com/"})
        with scripted_network([response]) as network:
            assert validate_credentials("app", "grant") is False

        assert [request.path for request in network.requests_log] == ["/self"]
