from typing import Any, Optional

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.nager_date.nager_date import (
    BACKFILL_YEARS_BACK,
    BASE_URL,
    FORWARD_YEARS,
    MAX_COUNTRY_CODES,
    NagerDateResumeConfig,
    _get,
    _holiday_id,
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
    def test_empty_is_invalid(self) -> None:
        assert check_country_codes([]) is not None

    def test_too_many_is_invalid(self) -> None:
        codes = [f"C{i}" for i in range(MAX_COUNTRY_CODES + 1)]
        message = check_country_codes(codes)
        assert message is not None
        assert "Too many" in message

    def test_at_the_cap_is_valid(self) -> None:
        codes = [chr(ord("A") + (i % 26)) * 2 for i in range(MAX_COUNTRY_CODES)]
        assert check_country_codes(codes) is None

    @parameterized.expand([(["USA"],), (["1G"],), (["U"],)])
    def test_malformed_code_is_invalid(self, codes: list[str]) -> None:
        message = check_country_codes(codes)
        assert message is not None
        assert "valid two-letter" in message

    def test_valid_codes_pass(self) -> None:
        assert check_country_codes(["US", "GB"]) is None


class TestHolidayId:
    def test_stable_for_identical_rows(self) -> None:
        row = {"countryCode": "US", "date": "2026-04-03", "name": "Good Friday", "subdivisionCodes": ["US-TX"]}
        assert _holiday_id(row) == _holiday_id(dict(row))

    def test_differs_when_subdivisions_differ(self) -> None:
        # The same holiday can be split across multiple rows with different subdivisionCodes and
        # holidayTypes (e.g. Good Friday is Public in most states and Optional in Texas) — without
        # a synthetic key these would collide on (countryCode, date, name).
        row_a = {
            "countryCode": "US",
            "date": "2026-04-03",
            "name": "Good Friday",
            "subdivisionCodes": ["US-CT"],
            "holidayTypes": ["Public"],
        }
        row_b = {
            "countryCode": "US",
            "date": "2026-04-03",
            "name": "Good Friday",
            "subdivisionCodes": ["US-TX"],
            "holidayTypes": ["Optional"],
        }
        assert _holiday_id(row_a) != _holiday_id(row_b)

    def test_handles_null_subdivisions_and_types(self) -> None:
        row = {"countryCode": "US", "date": "2026-01-01", "name": "New Year's Day", "subdivisionCodes": None}
        assert _holiday_id(row) == "US|2026-01-01|New Year's Day||"


class TestGet:
    @parameterized.expand([(204,), (400,), (404,)])
    def test_returns_none_for_no_data_statuses(self, status: int) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(status)

        assert _get(session, "/Holidays/US/2026") is None

    def test_returns_json_body_on_200(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(200, [{"countryCode": "US"}])

        assert _get(session, "/Countries/Available") == [{"countryCode": "US"}]

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
    @freeze_time("2026-06-15")
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
    def test_countries_yields_the_full_list_in_one_batch(self) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200, [{"countryCode": "US"}, {"countryCode": "GB"}])

            batches = list(nager_date_source(COUNTRIES, [], _make_manager()))

        assert batches == [[{"countryCode": "US"}, {"countryCode": "GB"}]]

    def test_country_info_yields_one_batch_per_country_and_saves_state(self) -> None:
        manager = _make_manager()
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = [
                _response(200, {"countryCode": "US", "commonName": "United States"}),
                _response(200, {"countryCode": "GB", "commonName": "United Kingdom"}),
            ]

            batches = list(nager_date_source(COUNTRY_INFO, ["US", "GB"], manager))

        assert batches == [
            [{"countryCode": "US", "commonName": "United States"}],
            [{"countryCode": "GB", "commonName": "United Kingdom"}],
        ]
        assert [call.args[0].index for call in manager.save_state.call_args_list] == [1, 2]
        manager.clear_state.assert_called_once()

    def test_country_info_resumes_from_saved_index(self) -> None:
        manager = _make_manager(index=1)
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200, {"countryCode": "GB"})

            batches = list(nager_date_source(COUNTRY_INFO, ["US", "GB"], manager))

        # Only the country at (and after) the saved index is fetched.
        assert batches == [[{"countryCode": "GB"}]]
        called_url = mock_session.return_value.get.call_args[0][0]
        assert called_url == f"{BASE_URL}/Countries/GB"

    def test_public_holidays_requests_every_configured_year_per_country(self) -> None:
        manager = _make_manager()
        with (
            mock.patch(f"{MODULE}.make_tracked_session") as mock_session,
            mock.patch(f"{MODULE}._holiday_years", return_value=[2025, 2026]),
        ):
            mock_session.return_value.get.return_value = _response(
                200, [{"countryCode": "US", "date": "2026-01-01", "name": "New Year's Day"}]
            )

            list(nager_date_source(PUBLIC_HOLIDAYS, ["US"], manager))

            called_urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]

        assert called_urls == [f"{BASE_URL}/Holidays/US/2025", f"{BASE_URL}/Holidays/US/2026"]

    def test_public_holidays_skips_years_outside_the_supported_window(self) -> None:
        manager = _make_manager()
        with (
            mock.patch(f"{MODULE}.make_tracked_session") as mock_session,
            mock.patch(f"{MODULE}._holiday_years", return_value=[2020, 2026]),
        ):
            mock_session.return_value.get.side_effect = [
                _response(400),  # 2020 is outside the community window
                _response(200, [{"countryCode": "US", "date": "2026-01-01", "name": "New Year's Day"}]),
            ]

            batches = list(nager_date_source(PUBLIC_HOLIDAYS, ["US"], manager))

        assert len(batches) == 1
        assert batches[0][0]["date"] == "2026-01-01"

    def test_public_holidays_rows_get_a_synthetic_id(self) -> None:
        manager = _make_manager()
        with (
            mock.patch(f"{MODULE}.make_tracked_session") as mock_session,
            mock.patch(f"{MODULE}._holiday_years", return_value=[2026]),
        ):
            mock_session.return_value.get.return_value = _response(
                200, [{"countryCode": "US", "date": "2026-01-01", "name": "New Year's Day"}]
            )

            batches = list(nager_date_source(PUBLIC_HOLIDAYS, ["US"], manager))

        assert batches[0][0]["id"] == "US|2026-01-01|New Year's Day||"

    def test_next_public_holidays_requests_once_per_country(self) -> None:
        manager = _make_manager()
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(
                200, [{"countryCode": "US", "date": "2026-09-07", "name": "Labour Day"}]
            )

            list(nager_date_source(NEXT_PUBLIC_HOLIDAYS, ["US"], manager))

            called_urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]

        assert called_urls == [f"{BASE_URL}/Holidays/US/Next"]

    def test_next_public_holidays_resumes_from_saved_index(self) -> None:
        manager = _make_manager(index=1)
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(
                200, [{"countryCode": "GB", "date": "2026-12-25", "name": "Christmas Day"}]
            )

            batches = list(nager_date_source(NEXT_PUBLIC_HOLIDAYS, ["US", "GB"], manager))

        # The country before the saved index (US) is skipped entirely.
        assert len(batches) == 1
        called_urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert called_urls == [f"{BASE_URL}/Holidays/GB/Next"]

    def test_public_holidays_resumes_from_saved_index(self) -> None:
        manager = _make_manager(index=1)
        with (
            mock.patch(f"{MODULE}.make_tracked_session") as mock_session,
            mock.patch(f"{MODULE}._holiday_years", return_value=[2025, 2026]),
        ):
            mock_session.return_value.get.return_value = _response(
                200, [{"countryCode": "US", "date": "2026-01-01", "name": "New Year's Day"}]
            )

            batches = list(nager_date_source(PUBLIC_HOLIDAYS, ["US"], manager))

        # The work item before the saved index (US/2025) is skipped entirely.
        assert len(batches) == 1
        called_urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert called_urls == [f"{BASE_URL}/Holidays/US/2026"]

    @parameterized.expand([(COUNTRY_INFO,), (NEXT_PUBLIC_HOLIDAYS,), (PUBLIC_HOLIDAYS,)])
    def test_raises_when_country_codes_are_misconfigured(self, endpoint: str) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session"):
            with pytest.raises(ValueError, match="Nager.Date source misconfigured"):
                list(nager_date_source(endpoint, [], _make_manager()))

    def test_unknown_endpoint_raises(self) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session"):
            with pytest.raises(ValueError, match="Unknown Nager.Date endpoint"):
                list(nager_date_source("NotARealEndpoint", ["US"], _make_manager()))


class TestValidateCredentials:
    @parameterized.expand([(200, True), (404, False), (500, False)])
    def test_status_mapping(self, status: int, expected_valid: bool) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(status, {"countryCode": "US"})

            is_valid, _ = validate_credentials(["US"])

        assert is_valid is expected_valid

    def test_empty_codes_is_invalid_without_a_request(self) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            is_valid, message = validate_credentials([])

        assert is_valid is False
        assert message is not None
        mock_session.return_value.get.assert_not_called()

    def test_network_error_is_invalid(self) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")

            is_valid, message = validate_credentials(["US"])

        assert is_valid is False
        assert message is not None
