from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cdc_open_data.cdc_open_data import (
    CdcOpenDataResumeConfig,
    _auth_config,
    _format_where_value,
    _probe_url,
    validate_cdc_open_data_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cdc_open_data.settings import (
    PAGE_SIZE,
    SODA2_API_VERSION,
    SODA3_API_VERSION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cdc_open_data.source import CdcOpenDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cdcopendata import (
    CdcOpenDataSourceConfig,
)


class TestFormatWhereValue:
    @parameterized.expand(
        [
            ("naive_datetime", datetime(2024, 6, 1, 12, 30, 0), "2024-06-01T12:30:00"),
            (
                "aware_datetime_converted_to_utc",
                datetime(2024, 6, 1, 12, 30, 0, tzinfo=UTC) + timedelta(hours=0),
                "2024-06-01T12:30:00",
            ),
            ("date_only", date(2024, 6, 1), "2024-06-01T00:00:00"),
            ("string_passthrough", "2024-06-01T12:30:00", "2024-06-01T12:30:00"),
        ]
    )
    def test_formats_value_for_soql_comparison(self, _name: str, value: Any, expected: str) -> None:
        assert _format_where_value(value) == expected


class TestAuthConfig:
    def test_app_token_becomes_header_auth(self) -> None:
        auth = _auth_config("my-token")
        assert auth == {"type": "api_key", "api_key": "my-token", "name": "X-App-Token", "location": "header"}


class TestProbeUrl:
    @parameterized.expand(
        [
            (SODA2_API_VERSION, "https://data.cdc.gov/resource/9bhg-hcku.json?%24limit=1"),
            (
                SODA3_API_VERSION,
                "https://data.cdc.gov/api/v3/views/9bhg-hcku/query.json?query=SELECT+%2A&pageNumber=1&pageSize=1",
            ),
        ]
    )
    def test_probe_url_reads_one_row_from_the_versioned_endpoint(self, api_version: str, expected: str) -> None:
        assert _probe_url("9bhg-hcku", api_version) == expected

    def test_unknown_version_raises_instead_of_falling_back(self) -> None:
        with pytest.raises(ValueError):
            _probe_url("9bhg-hcku", "v2")


class TestValidateCdcOpenDataCredentials:
    @parameterized.expand(
        [
            ("reachable", 200, (True, None)),
            (
                "missing_dataset",
                404,
                (
                    False,
                    "Dataset 'aaaa-aaaa' was not found on data.cdc.gov. Check the dataset ID in its data.cdc.gov URL.",
                ),
            ),
            (
                "invalid_app_token",
                403,
                (
                    False,
                    "Invalid CDC Open Data app token. Check the token, or leave it blank to use the shared public pool.",
                ),
            ),
            (
                "unreachable",
                None,
                (False, "Could not reach data.cdc.gov. Check your network connection and try again."),
            ),
            ("unexpected_status", 500, (False, "data.cdc.gov returned HTTP 500 for dataset 'aaaa-aaaa'.")),
        ]
    )
    def test_maps_probe_status_to_message(
        self, _name: str, probe_status: int | None, expected: tuple[bool, str | None]
    ) -> None:
        answer = (
            always(ConnectionError("unreachable"))
            if probe_status is None
            else always(ScriptedResponse(status=probe_status))
        )
        with scripted_network(answer) as network:
            assert validate_cdc_open_data_credentials("some-token", "aaaa-aaaa", SODA2_API_VERSION) == expected
        assert {request.path for request in network.requests_log} == {"/resource/aaaa-aaaa.json"}
        assert {request.param("$limit") for request in network.requests_log} == {"1"}

    def test_redacts_app_token_from_captured_samples(self) -> None:
        with scripted_network([ScriptedResponse(status=302, headers={"Location": "https://example.com/"})]) as network:
            assert validate_cdc_open_data_credentials("super-secret-token", "9bhg-hcku", SODA3_API_VERSION) == (
                False,
                "data.cdc.gov returned HTTP 302 for dataset '9bhg-hcku'.",
            )
        assert network.session_options == [{"redact_values": ("super-secret-token",)}]
        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/api/v3/views/9bhg-hcku/query.json"
        assert network.requests_log[0].headers["x-app-token"] == "super-secret-token"

    def test_soda3_rejects_missing_app_token_without_probing(self) -> None:
        with scripted_network([]) as network:
            valid, message = validate_cdc_open_data_credentials("", "9bhg-hcku", SODA3_API_VERSION)
        assert valid is False
        assert message is not None and "app token" in message
        assert network.requests_log == []


class TestCdcOpenDataSourceResumeBehavior:
    """End-to-end resume behaviour of ``cdc_open_data_source`` via ``rest_api_resource``."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(CdcOpenDataSource(), CdcOpenDataSourceConfig(dataset_ids="9bhg-hcku"))

    def test_full_refresh_orders_by_id_with_no_where_filter(self) -> None:
        result = self._driver().run(
            "9bhg-hcku", [ScriptedResponse(json=[{":id": "row-1"}])], api_version=SODA2_API_VERSION
        )

        assert result.raised is None
        assert result.rows == [{":id": "row-1"}]
        assert result.paths == ["/resource/9bhg-hcku.json"]
        assert result.params("$order") == [":id"]
        assert result.params("$where") == [None]
        assert result.params("$$exclude_system_fields") == ["false"]

    def test_incremental_sync_adds_where_filter_and_orders_by_updated_at(self) -> None:
        result = self._driver().run(
            "9bhg-hcku",
            [ScriptedResponse(json=[{":id": "row-1", ":updated_at": "2024-06-02T00:00:00.000"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 6, 1, 0, 0, 0),
            api_version=SODA2_API_VERSION,
        )

        assert result.raised is None
        assert result.params("$order") == [":updated_at,:id"]
        assert result.params("$where") == [":updated_at > '2024-06-01T00:00:00'"]

    @parameterized.expand(
        [
            ("full_refresh", False, None, "SELECT * ORDER BY :id"),
            ("incremental_first_sync", True, None, "SELECT * ORDER BY :updated_at, :id"),
            (
                "incremental_with_watermark",
                True,
                datetime(2024, 6, 1, 0, 0, 0),
                "SELECT * WHERE :updated_at > '2024-06-01T00:00:00' ORDER BY :updated_at, :id",
            ),
        ]
    )
    def test_soda3_posts_soql_query_to_views_endpoint(
        self, _name: str, should_use_incremental_field: bool, last_value: Any, expected_query: str
    ) -> None:
        result = self._driver().run(
            "9bhg-hcku",
            [ScriptedResponse(json=[{":id": "row-1"}])],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
            api_version=SODA3_API_VERSION,
        )

        assert result.raised is None
        assert result.requests[0].method == "POST"
        assert result.paths == ["/api/v3/views/9bhg-hcku/query.json"]
        assert result.requests[0].query == {}
        assert result.requests[0].json() == {
            "query": expected_query,
            "includeSystem": True,
            "page": {"pageNumber": 1, "pageSize": PAGE_SIZE},
        }

    def test_incremental_sync_without_last_value_omits_where_filter(self) -> None:
        # First-ever incremental sync has no watermark yet, so it must not filter anything out.
        result = self._driver().run(
            "9bhg-hcku",
            [ScriptedResponse(json=[{":id": "row-1"}])],
            should_use_incremental_field=True,
            api_version=SODA2_API_VERSION,
        )

        assert result.raised is None
        assert result.params("$where") == [None]

    @parameterized.expand(
        [
            (SODA2_API_VERSION, [0, PAGE_SIZE]),
            (SODA3_API_VERSION, [1, 2]),
        ]
    )
    def test_fresh_run_saves_offset_after_each_non_terminal_page(
        self, api_version: str, expected_sent: list[int]
    ) -> None:
        full_page = [{":id": f"row-{i}"} for i in range(PAGE_SIZE)]
        result = self._driver().run(
            "9bhg-hcku",
            [ScriptedResponse(json=full_page), ScriptedResponse(json=[{":id": "row-last"}])],
            api_version=api_version,
        )

        assert result.raised is None
        if api_version == SODA2_API_VERSION:
            assert result.params("$offset") == [str(position) for position in expected_sent]
        else:
            assert [request.json()["page"]["pageNumber"] for request in result.requests] == expected_sent
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.saved_states == [CdcOpenDataResumeConfig(next_offset=PAGE_SIZE)]

    @parameterized.expand(
        [
            (SODA2_API_VERSION, 40_000),
            (SODA3_API_VERSION, 40_000 // PAGE_SIZE + 1),
        ]
    )
    def test_resume_seeds_paginator_with_saved_offset(self, api_version: str, expected_sent: int) -> None:
        result = self._driver().run(
            "9bhg-hcku",
            [ScriptedResponse(json=[{":id": "row-1"}])],
            resume_state=CdcOpenDataResumeConfig(next_offset=40_000),
            api_version=api_version,
        )

        assert result.raised is None
        if api_version == SODA2_API_VERSION:
            assert result.params("$offset") == [str(expected_sent)]
        else:
            assert result.requests[0].json()["page"]["pageNumber"] == expected_sent

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = self._driver().run("9bhg-hcku", [ScriptedResponse(json=[{":id": "a"}])], api_version=SODA2_API_VERSION)

        assert result.raised is None
        assert result.params("$offset") == ["0"]
