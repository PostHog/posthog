from datetime import date, datetime
from typing import Any

import pytest

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network
from products.warehouse_sources.sources.telnyx._config import TelnyxSourceConfig
from products.warehouse_sources.sources.telnyx.source import TelnyxSource
from products.warehouse_sources.sources.telnyx.telnyx import (
    TelnyxResumeConfig,
    _format_created_at,
    validate_credentials,
)


class TestFormatCreatedAt:
    def test_aware_datetime_converted_to_utc(self) -> None:
        from datetime import timedelta, timezone

        tz = timezone(timedelta(hours=5))
        assert _format_created_at(datetime(2024, 1, 2, 8, 4, 5, tzinfo=tz)) == "2024-01-02T03:04:05Z"

    def test_date_becomes_midnight_utc(self) -> None:
        assert _format_created_at(date(2024, 1, 2)) == "2024-01-02T00:00:00Z"


def _page(body: Any, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


class TestTelnyxSourceResumeBehavior:
    """End-to-end pagination/resume behaviour of ``telnyx_source`` via ``rest_api_resource``."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(TelnyxSource(), TelnyxSourceConfig(api_key="test-key"))

    def test_fresh_run_walks_pages_until_total_pages(self) -> None:
        result = self._driver().run(
            "MessagingDetailRecords",
            [
                _page({"data": [{"uuid": "1"}], "meta": {"total_pages": 3}}),
                _page({"data": [{"uuid": "2"}], "meta": {"total_pages": 3}}),
                _page({"data": [{"uuid": "3"}], "meta": {"total_pages": 3}}),
            ],
        )

        assert result.params("page[number]") == ["1", "2", "3"]
        assert result.saved_states == [TelnyxResumeConfig(next_page=2), TelnyxResumeConfig(next_page=3)]

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        result = self._driver().run(
            "MessagingDetailRecords",
            [_page({"data": [{"uuid": "2"}], "meta": {"total_pages": 2}})],
            resume_state=TelnyxResumeConfig(next_page=2),
        )

        assert result.params("page[number]") == ["2"]

    def test_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = self._driver().run("MessagingDetailRecords", [_page({"data": [], "meta": {"total_pages": 1}})])

        assert result.params("page[number]") == ["1"]

    def test_incremental_run_filters_by_created_at(self) -> None:
        result = self._driver().run(
            "VerifyDetailRecords",
            [_page({"data": [{"uuid": "1"}], "meta": {"total_pages": 1}})],
            should_use_incremental_field=True,
        )

        assert result.requests[0].param("filter[created_at][gte]") == "1970-01-01T00:00:00Z"
        assert result.requests[0].param("sort") == "created_at"

    @pytest.mark.parametrize(
        ("endpoint", "expected_path", "expected_query"),
        [
            (
                "MessagingDetailRecords",
                "/v2/detail_records",
                {"filter[record_type]": "messaging", "page[size]": "50", "sort": "created_at", "page[number]": "1"},
            ),
            (
                "PhoneNumbers",
                "/v2/phone_numbers",
                {"page[size]": "250", "sort": "phone_number", "page[number]": "1"},
            ),
            ("MessagingProfiles", "/v2/messaging_profiles", {"page[size]": "250", "page[number]": "1"}),
            ("Connections", "/v2/connections", {"page[size]": "250", "sort": "created_at", "page[number]": "1"}),
            ("Conferences", "/v2/conferences", {"page[size]": "250", "page[number]": "1"}),
        ],
    )
    def test_full_refresh_request_shape(
        self, endpoint: str, expected_path: str, expected_query: dict[str, str]
    ) -> None:
        result = self._driver().run(endpoint, [_page({"data": [{"id": "1"}], "meta": {"total_pages": 1}})])

        assert result.paths == [expected_path]
        assert {name: values[0] for name, values in result.queries[0].items()} == expected_query

    @pytest.mark.parametrize(
        ("endpoint", "secret_field"),
        [("MessagingProfiles", "v1_secret"), ("PhoneNumbers", "external_pin")],
    )
    def test_credential_fields_are_dropped(self, endpoint: str, secret_field: str) -> None:
        result = self._driver().run(
            endpoint,
            [
                _page(
                    {
                        "data": [{"id": "r1", "name": "Alerts", secret_field: "fake-secret"}, {"id": "r2"}],
                        "meta": {"total_pages": 1},
                    }
                )
            ],
        )

        assert result.rows == [{"id": "r1", "name": "Alerts"}, {"id": "r2"}]


class TestValidateCredentials:
    def test_probes_detail_records_with_bearer_auth(self) -> None:
        with scripted_network(always(ScriptedResponse(status=200))) as network:
            validate_credentials("api-key")

        assert network.session_options == [{"redact_values": ("api-key",), "capture": False}]
        request = network.requests_log[0]
        assert request.origin + request.path == "https://api.telnyx.com/v2/detail_records"
        assert request.headers["authorization"] == "Bearer api-key"
        assert {name: values[0] for name, values in request.query.items()} == {
            "filter[record_type]": "messaging",
            "page[size]": "1",
        }
