from typing import Optional

import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.paypal import PayPalSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.paypal.paypal import PayPalResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.paypal.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TRANSACTIONS_INCREMENTAL_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paypal.source import PayPalSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.paypal.source"


class TestPayPalSource:
    def setup_method(self) -> None:
        self.source = PayPalSource()
        self.team_id = 123
        self.config = PayPalSourceConfig(environment="live", client_id="cid", client_secret="secret")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.PAYPAL

    def test_source_config_is_released_in_alpha(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "PayPal"
        assert config.label == "PayPal"
        assert config.category == DataWarehouseSourceCategory.PAYMENTS___BILLING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/paypal.png"
        assert [field.name for field in config.fields] == ["environment", "client_id", "client_secret"]

    def test_environment_field_offers_live_and_sandbox(self) -> None:
        environment = next(f for f in self.source.get_source_config.fields if f.name == "environment")

        assert isinstance(environment, SourceFieldSelectConfig)
        assert environment.defaultValue == "live"
        assert {option.value for option in environment.options} == {"live", "sandbox"}

    def test_client_secret_is_a_secret_password_field(self) -> None:
        secret = next(
            f
            for f in self.source.get_source_config.fields
            if isinstance(f, SourceFieldInputConfig) and f.name == "client_secret"
        )

        assert secret.type == SourceFieldInputConfigType.PASSWORD
        assert secret.secret is True
        assert secret.required is True

    def test_client_id_is_not_marked_secret(self) -> None:
        client_id = next(
            f
            for f in self.source.get_source_config.fields
            if isinstance(f, SourceFieldInputConfig) and f.name == "client_id"
        )

        assert client_id.type == SourceFieldInputConfigType.TEXT
        assert client_id.secret is False

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api-m.paypal.com/v1/oauth2/token",
            "400 Client Error: Bad Request for url: https://api-m.sandbox.paypal.com/v1/oauth2/token",
            "403 Client Error: Forbidden for url: https://api-m.paypal.com/v1/reporting/transactions",
            # A too-large transaction window returns 400 and never succeeds on retry, so it must
            # surface as an actionable error instead of looping through Temporal retries forever.
            "400 Client Error: Bad Request for url: https://api-m.paypal.com/v1/reporting/transactions",
        ],
    )
    def test_permanent_auth_failures_are_non_retryable(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "observed_error",
        [
            "429 Client Error: Too Many Requests for url: https://api-m.paypal.com/v1/reporting/transactions",
            "500 Server Error for url: https://api-m.paypal.com/v2/invoicing/invoices",
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
        ],
    )
    def test_transient_and_unrelated_errors_stay_retryable(self, observed_error: str) -> None:
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_only_endpoints_with_a_server_side_filter_are_incremental(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas if schema.supports_incremental} == {"transactions", "disputes"}

    @pytest.mark.parametrize(
        "endpoint, expected_field",
        [
            ("transactions", "transaction_initiation_date"),
            ("disputes", "update_time"),
        ],
    )
    def test_incremental_endpoints_advertise_their_cursor(self, endpoint: str, expected_field: str) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas[endpoint].incremental_fields == INCREMENTAL_FIELDS[endpoint]
        assert [f["field"] for f in schemas[endpoint].incremental_fields] == [expected_field]

    @pytest.mark.parametrize("endpoint", ["balances", "invoices", "plans", "products"])
    def test_full_refresh_endpoints_advertise_no_cursor(self, endpoint: str) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas[endpoint].incremental_fields == []
        assert schemas[endpoint].supports_append is False

    def test_transactions_re_read_a_trailing_window_to_cover_paypals_reporting_delay(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["transactions"].default_incremental_lookback_seconds == TRANSACTIONS_INCREMENTAL_LOOKBACK_SECONDS
        assert schemas["disputes"].default_incremental_lookback_seconds is None

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["transactions", "disputes"])

        assert {schema.name for schema in schemas} == {"transactions", "disputes"}

    def test_get_schemas_filtered_by_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["subscriptions"]) == []

    def test_documented_tables_are_published_without_credentials(self) -> None:
        tables = self.source.get_documented_tables()

        assert {table["name"] for table in tables} == set(ENDPOINTS)
        assert all(table["description"] for table in tables)

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions) == set(ENDPOINTS)
        for endpoint in ENDPOINTS:
            assert descriptions[endpoint].get("columns")

    @pytest.mark.parametrize(
        "transport_result",
        [(True, None), (False, "PayPal rejected these credentials.")],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_paypal_credentials")
    def test_validate_credentials_passes_the_transport_result_through(
        self, mock_validate: mock.MagicMock, transport_result: tuple[bool, Optional[str]]
    ) -> None:
        mock_validate.return_value = transport_result

        assert self.source.validate_credentials(self.config, self.team_id) == transport_result
        mock_validate.assert_called_once_with("live", "cid", "secret")

    @mock.patch(f"{_SOURCE_MODULE}.check_endpoint_permissions")
    @mock.patch(f"{_SOURCE_MODULE}.validate_paypal_credentials", return_value=(True, None))
    def test_source_create_validates_the_token_without_probing_tables(
        self, _mock_validate: mock.MagicMock, mock_permissions: mock.MagicMock
    ) -> None:
        # A missing per-table feature must never block connecting the source.
        assert self.source.validate_credentials(self.config, self.team_id, schema_name=None) == (True, None)
        mock_permissions.assert_not_called()

    @mock.patch(
        f"{_SOURCE_MODULE}.check_endpoint_permissions", return_value={"transactions": "Enable Transaction Search."}
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_paypal_credentials", return_value=(True, None))
    def test_per_schema_validation_surfaces_a_missing_feature(
        self, _mock_validate: mock.MagicMock, _mock_permissions: mock.MagicMock
    ) -> None:
        valid, reason = self.source.validate_credentials(self.config, self.team_id, schema_name="transactions")

        assert valid is False
        assert reason == "Enable Transaction Search."

    @mock.patch(f"{_SOURCE_MODULE}.check_endpoint_permissions", return_value={"transactions": None})
    @mock.patch(f"{_SOURCE_MODULE}.validate_paypal_credentials", return_value=(True, None))
    def test_per_schema_validation_passes_when_the_table_is_reachable(
        self, _mock_validate: mock.MagicMock, _mock_permissions: mock.MagicMock
    ) -> None:
        assert self.source.validate_credentials(self.config, self.team_id, schema_name="transactions") == (True, None)

    @mock.patch(f"{_SOURCE_MODULE}.check_endpoint_permissions", return_value={"transactions": None})
    def test_get_endpoint_permissions_delegates_to_the_transport(self, mock_permissions: mock.MagicMock) -> None:
        result = self.source.get_endpoint_permissions(self.config, self.team_id, ["transactions"])

        assert result == {"transactions": None}
        mock_permissions.assert_called_once_with("live", "cid", "secret", ["transactions"])

    def test_changing_environment_requires_re_entering_secrets(self) -> None:
        # `environment` selects the live vs sandbox host, so a change must re-require the secret.
        assert self.source.connection_host_fields == ["environment"]

    def test_get_resumable_source_manager_binds_the_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PayPalResumeConfig

    @mock.patch(f"{_SOURCE_MODULE}.paypal_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_paypal_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "transactions"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-05-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_paypal_source.call_args.kwargs
        assert kwargs["environment"] == "live"
        assert kwargs["client_id"] == "cid"
        assert kwargs["client_secret"] == "secret"
        assert kwargs["endpoint"] == "transactions"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-05-01T00:00:00Z"

    @mock.patch(f"{_SOURCE_MODULE}.paypal_source")
    def test_source_for_pipeline_drops_the_watermark_on_full_refresh(self, mock_paypal_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "invoices"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-05-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_paypal_source.call_args.kwargs["db_incremental_field_last_value"] is None
