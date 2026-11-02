from datetime import UTC, date, datetime
from typing import Any, Literal, cast

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.asaas.asaas import (
    PRODUCTION_BASE_URL,
    SANDBOX_BASE_URL,
    AsaasResumeConfig,
    base_url,
    format_date_param,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.asaas.source import AsaasSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.asaas import AsaasSourceConfig

_INCREMENTAL_ENDPOINTS = [
    ("Payments", "dateCreated[ge]"),
    ("Transfers", "dateCreated[ge]"),
    ("FinancialTransactions", "startDate"),
]
_FULL_REFRESH_ENDPOINTS = {
    "Customers",
    "Subscriptions",
    "Installments",
    "ReceivedSplits",
    "Invoices",
    "PixTransactions",
}

VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.asaas.source.validate_asaas_credentials"
)
ASAAS_SOURCE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.asaas.source.asaas_source"


def _driver(environment: Literal["production", "sandbox"] = "production") -> SourceDriver:
    return SourceDriver(AsaasSource(), AsaasSourceConfig(api_key="test-key", environment=environment))


def _page(rows: list[dict[str, Any]], total: int) -> ScriptedResponse:
    return ScriptedResponse(json={"data": rows, "hasMore": len(rows) == 100, "totalCount": total})


class TestBaseUrl:
    @parameterized.expand(
        [
            ("production", PRODUCTION_BASE_URL),
            ("sandbox", SANDBOX_BASE_URL),
            ("unknown_defaults_to_sandbox", SANDBOX_BASE_URL),
        ]
    )
    def test_resolves_environment(self, environment: str, expected: str) -> None:
        assert base_url(environment) == expected


class TestFormatDateParam:
    @parameterized.expand(
        [
            ("datetime_utc", datetime(2026, 1, 15, 10, 30, tzinfo=UTC), "2026-01-15"),
            ("naive_datetime", datetime(2026, 1, 15, 10, 30), "2026-01-15"),
            ("date_object", date(2026, 1, 15), "2026-01-15"),
            ("date_string_passthrough", "2026-01-15", "2026-01-15"),
            ("datetime_string_truncated", "2026-01-15T10:30:00Z", "2026-01-15"),
        ]
    )
    def test_formats_to_date_only_string(self, _name: str, value, expected: str) -> None:
        assert format_date_param(value) == expected


class TestGetResource:
    @parameterized.expand(_INCREMENTAL_ENDPOINTS)
    def test_incremental_endpoint_adds_date_filter_when_requested(self, endpoint: str, date_param: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=True)

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        endpoint_config = cast(Endpoint, resource["endpoint"])
        params = endpoint_config["params"]
        assert params is not None
        assert date_param in params
        assert params[date_param]["type"] == "incremental"

    @parameterized.expand(_INCREMENTAL_ENDPOINTS)
    def test_incremental_endpoint_omits_filter_when_not_requested(self, endpoint: str, date_param: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=False)

        assert resource["write_disposition"] == "replace"
        endpoint_config = cast(Endpoint, resource["endpoint"])
        assert date_param not in (endpoint_config["params"] or {})

    @parameterized.expand(sorted(_FULL_REFRESH_ENDPOINTS))
    def test_full_refresh_endpoint_never_adds_date_filter(self, endpoint: str) -> None:
        # These endpoints don't document a server-side date filter; requesting incremental
        # must not fabricate one that the API would silently ignore or reject.
        resource = get_resource(endpoint, should_use_incremental_field=True)

        assert resource["write_disposition"] == "replace"
        endpoint_config = cast(Endpoint, resource["endpoint"])
        assert endpoint_config["params"] == {}


class TestAsaasSourceResumeBehavior:
    """`asaas_source` plumbing: resume seeding and checkpoint persistence."""

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = _driver().run("Payments", [_page([{"id": "payment-1"}], 1)])

        assert result.raised is None
        assert result.params("offset") == ["0"]

    def test_seeds_initial_offset_from_saved_state(self) -> None:
        result = _driver().run(
            "Payments", [_page([{"id": "payment-201"}], 201)], resume_state=AsaasResumeConfig(offset=200)
        )

        assert result.raised is None
        assert result.params("offset") == ["200"]

    def test_resume_hook_saves_offset_when_present(self) -> None:
        result = _driver().run(
            "Payments",
            [
                _page([{"id": f"payment-{index}"} for index in range(200, 300)], 301),
                _page([{"id": "payment-300"}], 301),
            ],
            resume_state=AsaasResumeConfig(offset=200),
        )

        assert result.raised is None
        assert result.params("offset") == ["200", "300"]
        assert result.saved_states == [AsaasResumeConfig(offset=300)]
        assert result.committed_states == [AsaasResumeConfig(offset=300)]

    @parameterized.expand([("production", PRODUCTION_BASE_URL), ("sandbox", SANDBOX_BASE_URL)])
    def test_client_config_targets_the_selected_environment(
        self, environment: Literal["production", "sandbox"], expected_base_url: str
    ) -> None:
        result = _driver(environment).run("Payments", [_page([{"id": "payment-1"}], 1)])

        assert result.raised is None
        assert result.urls[0].startswith(f"{expected_base_url}/v3/payments?")
        assert result.requests[0].headers["access_token"] == "test-key"


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True),
        ]
    )
    def test_status_code_maps_to_validity(self, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("test-key", "production") is expected

        assert network.requests_log[0].path == "/v3/customers"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["access_token"] == "test-key"


class TestAsaasSource:
    def setup_method(self) -> None:
        self.source = AsaasSource()
        self.team_id = 123
        self.config = AsaasSourceConfig(api_key="test-key", environment="production")

    def test_api_version_metadata(self) -> None:
        assert self.source.supported_versions == ("v3",)
        assert self.source.default_version == "v3"
        assert self.source.api_docs_url is not None and self.source.api_docs_url.startswith("https://")

    @parameterized.expand([(True, True, None), (False, False, "Invalid credentials")])
    def test_validate_credentials(self, mock_return: bool, expected_valid: bool, expected_message) -> None:
        with mock.patch(VALIDATE_PATCH, return_value=mock_return) as mock_validate:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert (is_valid, error_message) == (expected_valid, expected_message)
        mock_validate.assert_called_once_with("test-key", "production")

    @parameterized.expand(
        [
            ("Payments", "/v3/payments", {"dateCreated[ge]": "2026-01-01"}),
            ("FinancialTransactions", "/v3/financialTransactions", {"startDate": "2026-01-01", "order": "asc"}),
        ]
    )
    def test_source_for_pipeline_plumbs_arguments(
        self, endpoint: str, expected_path: str, expected_params: dict[str, str]
    ) -> None:
        result = _driver().run(
            endpoint,
            [_page([{"id": "row-1", "dateCreated": "2026-01-01", "date": "2026-01-01"}], 1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01",
        )

        assert result.raised is None
        assert result.paths == [expected_path]
        assert result.requests[0].headers["access_token"] == "test-key"
        for name, value in expected_params.items():
            assert result.requests[0].param(name) == value

    @parameterized.expand(
        [
            ("ReceivedSplits", "/v3/payments/splits/received", {}),
            ("Invoices", "/v3/invoices", {}),
            ("PixTransactions", "/v3/pix/transactions", {}),
            ("PaymentLinks", "/v3/paymentLinks", {"includeDeleted": "true"}),
            ("PaymentDunnings", "/v3/paymentDunnings", {}),
            ("BillPayments", "/v3/bill", {}),
        ]
    )
    def test_full_refresh_endpoint_requests_vendor_path(
        self, endpoint: str, expected_path: str, expected_params: dict[str, str]
    ) -> None:
        result = _driver().run(endpoint, [_page([{"id": "row-1"}], 1)])

        assert result.raised is None
        assert result.paths == [expected_path]
        for name, value in expected_params.items():
            assert result.requests[0].param(name) == value

    def test_dunning_history_fans_out_per_dunning_and_tags_rows_with_the_dunning(self) -> None:
        result = _driver().run(
            "PaymentDunningHistory",
            [
                _page([{"id": "dunning-1"}, {"id": "dunning-2"}], 2),
                _page([{"status": "IN_NEGOTIATION", "description": "Started", "eventDate": "2026-01-02"}], 1),
                _page([{"status": "PAID", "description": "Paid", "eventDate": "2026-01-05"}], 1),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/v3/paymentDunnings",
            "/v3/paymentDunnings/dunning-1/history",
            "/v3/paymentDunnings/dunning-2/history",
        ]
        assert [(row["paymentDunning"], row["status"]) for row in result.rows] == [
            ("dunning-1", "IN_NEGOTIATION"),
            ("dunning-2", "PAID"),
        ]
        assert all("_PaymentDunnings_id" not in row for row in result.rows)
        assert result.response is not None
        assert result.response.primary_keys == ["paymentDunning", "eventDate", "status", "description"]
        assert result.response.supports_resume is False

    def test_source_for_pipeline_omits_cursor_when_not_incremental(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Customers"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01"

        with mock.patch(ASAAS_SOURCE_PATCH) as mock_asaas_source:
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_asaas_source.call_args.kwargs["db_incremental_field_last_value"] is None
