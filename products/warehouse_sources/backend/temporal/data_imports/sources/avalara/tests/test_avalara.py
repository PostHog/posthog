from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.avalara.avalara import (
    AVALARA_ENVIRONMENT_HOSTS,
    AvalaraResumeConfig,
    _format_filter_date,
    _incremental_config_factory,
    base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.avalara.settings import AVALARA_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.avalara.source import AvalaraSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.avalara import (
    AvalaraSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(
        AvalaraSource(), AvalaraSourceConfig(account_id="12345", license_key="key", environment="production")
    )


def _page(items: list[dict[str, Any]], recordset_count: int) -> ScriptedResponse:
    return ScriptedResponse(json={"value": items, "@recordsetCount": recordset_count})


class TestBaseUrl:
    @parameterized.expand(
        [
            ("production", "https://rest.avatax.com"),
            ("sandbox", "https://sandbox-rest.avatax.com"),
        ]
    )
    def test_known_environments(self, environment: str, expected_host: str) -> None:
        assert base_url(environment) == expected_host
        assert AVALARA_ENVIRONMENT_HOSTS[environment] == expected_host

    def test_unknown_environment_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown Avalara environment"):
            base_url("staging")


class TestFormatFilterDate:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_filter_date(value) == expected


class TestIncrementalConfigFactory:
    def test_builds_odata_filter_expression(self) -> None:
        config = _incremental_config_factory("modifiedDate")
        assert config["start_param"] == "$filter"
        convert = config["convert"]
        assert convert is not None
        assert convert(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)) == "modifiedDate gt '2026-03-04T02:58:14Z'"


class TestAvalaraSourceNonFanout:
    @mock.patch.object(AVALARA_ENDPOINTS["Companies"], "page_size", 2)
    def test_paginates_until_recordset_count_reached(self) -> None:
        # A full (page_size-length) first page is required: OffsetPaginator treats a page shorter
        # than the limit as terminal even when @recordsetCount says more remain.
        result = _driver().run(
            "Companies",
            [
                _page([{"id": 1}, {"id": 2}], 3),
                _page([{"id": 3}], 3),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2, 3]
        assert result.params("$skip") == ["0", "2"]
        assert result.requests[0].param("$orderBy") == "modifiedDate ASC"

    def test_incremental_cursor_added_as_filter(self) -> None:
        result = _driver().run(
            "Companies",
            [_page([{"id": 1}], 1)],
            incremental_field="modifiedDate",
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("$filter") == "modifiedDate gt '2026-03-04T02:58:14Z'"

    def test_full_refresh_never_sends_filter(self) -> None:
        result = _driver().run("Companies", [_page([{"id": 1}], 1)])

        assert result.raised is None
        assert result.requests[0].param("$filter") is None

    @mock.patch.object(AVALARA_ENDPOINTS["Companies"], "page_size", 1)
    def test_saves_resume_state_only_while_pages_remain(self) -> None:
        result = _driver().run(
            "Companies",
            [
                _page([{"id": 1}], 2),
                _page([{"id": 2}], 2),
            ],
        )

        assert result.raised is None
        assert result.saved_states == [AvalaraResumeConfig(next_offset=1)]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "Companies",
            [_page([{"id": 2}], 2)],
            resume_state=AvalaraResumeConfig(next_offset=1),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [2]
        assert result.params("$skip") == ["1"]


class TestAvalaraSourceFanout:
    @parameterized.expand(["Transactions", "Nexus", "Customers", "ExemptionCertificates"])
    def test_fanout_wires_selectors_and_page_size_param(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [
                _page([{"id": 7, "companyCode": "EXAMPLE"}], 1),
                _page([{"id": 1, "companyId": 7}], 1),
            ],
        )

        assert result.raised is None
        assert result.paths[0] == "/api/v2/companies"
        assert result.paths[1].endswith(AVALARA_ENDPOINTS[endpoint].path.rsplit("/", 1)[-1])
        assert result.params("$top") == ["500", "500"]
        assert result.params("$skip") == ["0", "0"]
        assert result.requests[1].param("$orderBy") == "modifiedDate ASC"
        assert [row["id"] for row in result.rows] == [1]

    def test_transactions_resolves_on_company_code(self) -> None:
        result = _driver().run(
            "Transactions",
            [_page([{"id": 7, "companyCode": "EXAMPLE"}], 1), _page([{"id": 1}], 1)],
        )

        assert result.raised is None
        assert result.paths[1] == "/api/v2/companies/EXAMPLE/transactions"
        assert result.requests[1].param("companyCode") is None

    @parameterized.expand(["Nexus", "Customers", "ExemptionCertificates"])
    def test_company_scoped_endpoints_resolve_on_company_id(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [_page([{"id": 7, "companyCode": "EXAMPLE"}], 1), _page([{"id": 1, "companyId": 7}], 1)],
        )

        assert result.raised is None
        assert result.paths[1].startswith("/api/v2/companies/7/")
        assert result.requests[1].param("companyId") is None

    def test_incremental_fanout_uses_incremental_config_factory(self) -> None:
        result = _driver().run(
            "Transactions",
            [
                _page([{"id": 7, "companyCode": "EXAMPLE"}], 1),
                _page([{"id": 1, "modifiedDate": "2026-03-05T00:00:00Z"}], 1),
            ],
            incremental_field="modifiedDate",
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("$filter") is None
        assert result.requests[1].param("$filter") == "modifiedDate gt '2026-03-04T00:00:00Z'"
        assert result.requests[1].param("$orderBy") == "modifiedDate ASC"


class TestValidateCredentials:
    def test_authenticated_ok(self) -> None:
        with scripted_network([ScriptedResponse(json={"authenticated": True})]):
            assert validate_credentials("12345", "key", "production") == (True, None)

    def test_unauthenticated_ping_reports_bad_credentials(self) -> None:
        with scripted_network([ScriptedResponse(json={"authenticated": False})]):
            is_valid, message = validate_credentials("12345", "wrong-key", "production")
        assert is_valid is False
        assert message == "Avalara authentication failed. Check your account ID and license key."

    def test_unexpected_status_code(self) -> None:
        with scripted_network(always(ScriptedResponse(status=500))) as network:
            is_valid, message = validate_credentials("12345", "key", "production")
        assert is_valid is False
        assert message is not None and "500" in message
        assert {request.path for request in network.requests_log} == {"/api/v2/utilities/ping"}

    def test_probes_ping_endpoint_for_selected_environment(self) -> None:
        with scripted_network([ScriptedResponse(json={"authenticated": True})]) as network:
            validate_credentials("12345", "key", "sandbox")

        assert network.requests_log[0].url == "https://sandbox-rest.avatax.com/api/v2/utilities/ping"
        assert network.requests_log[0].headers["authorization"] == "Basic MTIzNDU6a2V5"

    def test_unknown_environment_fails_without_a_request(self) -> None:
        with scripted_network([]) as network:
            is_valid, message = validate_credentials("12345", "key", "staging")
        assert is_valid is False
        assert message is not None and "Unknown Avalara environment" in message
        assert network.requests_log == []
        assert network.session_options == []
