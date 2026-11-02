from typing import Any, Optional

import pytest
import time_machine
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.nagerdate import (
    NagerDateSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.nager_date.nager_date import (
    BACKFILL_YEARS_BACK,
    FORWARD_YEARS,
    MAX_COUNTRY_CODES,
    NagerDateResumeConfig,
    _get,
    _holiday_years,
    check_country_codes,
    nager_date_source,
    parse_country_codes,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.nager_date.settings import (
    COUNTRIES,
    COUNTRY_INFO,
    NEXT_PUBLIC_HOLIDAYS,
    PUBLIC_HOLIDAYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.nager_date.source import NagerDateSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.nager_date.nager_date"


def _response(status: int = 200, body: Optional[Any] = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.content = b"[]" if status not in (204,) else b""
    resp.json.return_value = body
    if status >= 500 or status not in (200, 204, 400, 404):
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status} error", response=resp)
    return resp


class TestParseCountryCodes:
    @parameterized.expand(
        [
            ("US", ["US"]),
            ("us", ["US"]),
            ("US,GB", ["US", "GB"]),
            ("US\nGB\nDE", ["US", "GB", "DE"]),
            ("  US , GB \n DE ", ["US", "GB", "DE"]),
            ("US\nUS\nGB", ["US", "GB"]),
            ("US\n\n  \nGB", ["US", "GB"]),
            (None, []),
            ("", []),
        ]
    )
    def test_parses_and_dedupes(self, raw: Optional[str], expected: list[str]) -> None:
        assert parse_country_codes(raw) == expected


class TestCheckCountryCodes:
    def test_too_many_is_invalid(self) -> None:
        codes = [f"C{i}" for i in range(MAX_COUNTRY_CODES + 1)]
        message = check_country_codes(codes)
        assert message is not None
        assert "Too many" in message

    @parameterized.expand([(["USA"],), (["1G"],), (["U"],)])
    def test_malformed_code_is_invalid(self, codes: list[str]) -> None:
        message = check_country_codes(codes)
        assert message is not None
        assert "valid two-letter" in message


class TestGet:
    @parameterized.expand([(204,), (400,), (404,)])
    def test_returns_none_for_no_data_statuses(self, status: int) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(status)

        assert _get(session, "/Holidays/US/2026") is None

    def test_returns_none_for_empty_body_on_200(self) -> None:
        # A 200 with no body is distinct from the documented "no data" statuses, but should
        # still come back as None rather than raising on `.json()`.
        session = mock.MagicMock()
        response = _response(200)
        response.content = b""
        session.get.return_value = response

        assert _get(session, "/Countries/Available") is None

    def test_raises_for_server_error(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(500)

        with pytest.raises(requests.HTTPError):
            _get(session, "/Countries/Available")


class TestHolidayYears:
    @time_machine.travel("2026-06-15", tick=False)
    def test_spans_the_configured_backfill_and_forward_window(self) -> None:
        years = _holiday_years()

        assert years == list(range(2026 - BACKFILL_YEARS_BACK, 2026 + FORWARD_YEARS + 1))
        assert years[0] == 2025
        assert years[-1] == 2031


def _make_manager(index: Optional[int] = None) -> mock.MagicMock:
    manager = mock.MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = index is not None
    manager.load_state.return_value = NagerDateResumeConfig(index=index) if index is not None else None
    return manager


class TestNagerDateSource:
    @staticmethod
    def _driver(country_codes: str = "US\nGB") -> SourceDriver:
        return SourceDriver(NagerDateSource(), NagerDateSourceConfig(country_codes=country_codes))

    def test_countries_yields_the_full_list_in_one_batch(self) -> None:
        result = self._driver("").run(
            COUNTRIES, [ScriptedResponse(json=[{"countryCode": "US"}, {"countryCode": "GB"}])]
        )

        assert result.items == [[{"countryCode": "US"}, {"countryCode": "GB"}]]
        assert result.paths == ["/api/v4/Countries/Available"]
        assert result.raised is None

    def test_country_info_resumes_from_saved_index(self) -> None:
        result = self._driver().run(
            COUNTRY_INFO,
            [ScriptedResponse(json={"countryCode": "GB"})],
            resume_state=NagerDateResumeConfig(index=1),
        )

        # Only the country at (and after) the saved index is fetched.
        assert result.items == [[{"countryCode": "GB"}]]
        assert result.urls == ["https://date.nager.at/api/v4/Countries/GB"]
        assert result.raised is None

    def test_next_public_holidays_resumes_from_saved_index(self) -> None:
        result = self._driver().run(
            NEXT_PUBLIC_HOLIDAYS,
            [ScriptedResponse(json=[{"countryCode": "GB", "date": "2026-12-25", "name": "Christmas Day"}])],
            resume_state=NagerDateResumeConfig(index=1),
        )

        # The country before the saved index (US) is skipped entirely.
        assert len(result.items) == 1
        assert result.urls == ["https://date.nager.at/api/v4/Holidays/GB/Next"]
        assert result.raised is None

    @time_machine.travel("2026-06-15", tick=False)
    def test_public_holidays_resumes_from_saved_index(self) -> None:
        result = self._driver("US").run(
            PUBLIC_HOLIDAYS,
            [
                ScriptedResponse(json=[{"countryCode": "US", "date": "2026-01-01", "name": "New Year's Day"}]),
                *[ScriptedResponse(status=204) for _ in range(FORWARD_YEARS)],
            ],
            resume_state=NagerDateResumeConfig(index=1),
        )

        # The work item before the saved index (US/2025) is skipped entirely.
        assert len(result.items) == 1
        assert result.paths == [f"/api/v4/Holidays/US/{year}" for year in range(2026, 2032)]
        assert result.raised is None

    @parameterized.expand([(COUNTRY_INFO,), (NEXT_PUBLIC_HOLIDAYS,), (PUBLIC_HOLIDAYS,)])
    def test_raises_when_country_codes_are_misconfigured(self, endpoint: str) -> None:
        result = self._driver("").run(endpoint, [])

        assert isinstance(result.raised, ValueError)
        assert "Nager.Date source misconfigured" in str(result.raised)
        assert result.requests == []

    def test_unknown_endpoint_raises(self) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session"):
            with pytest.raises(ValueError, match="Unknown Nager.Date endpoint"):
                list(nager_date_source("NotARealEndpoint", ["US"], _make_manager()))


class TestValidateCredentials:
    @parameterized.expand([(200, True), (404, False), (500, False)])
    def test_status_mapping(self, status: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={"countryCode": "US"}))) as network:
            is_valid, _ = validate_credentials(["US"])

        assert is_valid is expected_valid
        assert {request.path for request in network.requests_log} == {"/api/v4/Countries/US"}

    def test_empty_codes_is_invalid_without_a_request(self) -> None:
        with scripted_network([]) as network:
            is_valid, message = validate_credentials([])

        assert is_valid is False
        assert message is not None
        assert network.requests_log == []

    def test_network_error_is_invalid(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            is_valid, message = validate_credentials(["US"])

        assert is_valid is False
        assert message is not None
        assert {request.path for request in network.requests_log} == {"/api/v4/Countries/US"}
