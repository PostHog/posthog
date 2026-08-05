from typing import Any, Optional

from unittest import mock

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.adyen.adyen import AdyenResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.adyen.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adyen.settings import (
    ADYEN_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adyen.source import AdyenSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adyen import AdyenSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.adyen.source"


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "Transfers",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestAdyenSource:
    def setup_method(self) -> None:
        self.source = AdyenSource()
        self.team_id = 123
        self.config = AdyenSourceConfig(
            api_key="adyen-key",
            environment="live",
            balance_platform="BP123",
            merchant_account="ACME",
            start_date="2026-01-01",
            settlement_report_start_batch=None,
        )

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.ADYEN

    def test_source_config_is_released_in_alpha(self) -> None:
        config = self.source.get_source_config

        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.category == DataWarehouseSourceCategory.PAYMENTS___BILLING
        assert config.iconPath == "/static/services/adyen.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/adyen"

    def test_environment_field_is_a_fixed_choice(self) -> None:
        environment_field = self.source.get_source_config.fields[0]

        assert isinstance(environment_field, SourceFieldSelectConfig)
        assert environment_field.name == "environment"
        assert environment_field.required is True
        assert environment_field.defaultValue == "live"
        assert {option.value for option in environment_field.options} == {"live", "test"}

    @parameterized.expand(
        [
            ("api_key", SourceFieldInputConfigType.PASSWORD, True, True),
            ("balance_platform", SourceFieldInputConfigType.TEXT, False, False),
            ("merchant_account", SourceFieldInputConfigType.TEXT, False, False),
            ("start_date", SourceFieldInputConfigType.TEXT, False, False),
            ("settlement_report_start_batch", SourceFieldInputConfigType.NUMBER, False, False),
        ]
    )
    def test_input_fields(
        self,
        name: str,
        expected_type: SourceFieldInputConfigType,
        required: bool,
        secret: bool,
    ) -> None:
        fields = {
            field.name: field
            for field in self.source.get_source_config.fields
            if isinstance(field, SourceFieldInputConfig)
        }

        field = fields[name]
        assert field.type == expected_type
        assert field.required is required
        assert field.secret is secret

    @parameterized.expand(
        [("unauthorized", "401 Client Error: Unauthorized"), ("forbidden", "403 Client Error: Forbidden")]
    )
    def test_non_retryable_errors(self, _name: str, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_the_whole_catalog(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(schema.description for schema in schemas)

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_incremental_flags_track_the_endpoint_catalog(self, endpoint: str) -> None:
        schema = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}[endpoint]
        expected_fields = INCREMENTAL_FIELDS.get(endpoint, [])

        assert schema.incremental_fields == expected_fields
        assert schema.supports_incremental is bool(expected_fields)

    def test_only_endpoints_with_a_server_side_filter_are_incremental(self) -> None:
        incremental = {s.name for s in self.source.get_schemas(self.config, self.team_id) if s.supports_incremental}

        assert incremental == {"Transactions", "Transfers", "SettlementDetailReports"}

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Transfers"])

        assert [schema.name for schema in schemas] == ["Transfers"]

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["Nope"]) == []

    def test_schemas_list_without_credentials_for_public_docs(self) -> None:
        # The catalog is static, so the public docs endpoint can render it with a blank config.
        assert self.source.lists_tables_without_credentials is True
        blank = AdyenSourceConfig(api_key="")
        assert {schema.name for schema in self.source.get_schemas(blank, self.team_id)} == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("both_identifiers", "BP123", "ACME", set(ENDPOINTS)),
            (
                "platform_only",
                "BP123",
                None,
                {"Transactions", "Transfers", "AccountHolders", "BalanceAccounts", "Companies", "MerchantAccounts"},
            ),
            ("merchant_only", None, "ACME", {"SettlementDetailReports", "Companies", "MerchantAccounts"}),
            ("neither", None, "  ", {"Companies", "MerchantAccounts"}),
        ]
    )
    def test_tables_needing_a_missing_identifier_start_unselected(
        self,
        _name: str,
        balance_platform: Optional[str],
        merchant_account: Optional[str],
        expected_on: set[str],
    ) -> None:
        config = AdyenSourceConfig(
            api_key="adyen-key",
            balance_platform=balance_platform,
            merchant_account=merchant_account,
        )

        schemas = self.source.get_schemas(config, self.team_id)

        assert {schema.name for schema in schemas if schema.should_sync_default} == expected_on

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        assert set(self.source.get_canonical_descriptions()) == set(ENDPOINTS)

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_canonical_descriptions_document_the_primary_key(self, endpoint: str) -> None:
        columns = CANONICAL_DESCRIPTIONS[endpoint]["columns"]

        for key in ADYEN_ENDPOINTS[endpoint].primary_key:
            assert key in columns

    @parameterized.expand(
        [
            ("valid", (True, None), True, None),
            ("invalid", (False, "Adyen rejected the API key."), False, "Adyen rejected the API key."),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        mock_return: tuple[bool, Optional[str]],
        expected_valid: bool,
        expected_message: Optional[str],
    ) -> None:
        with mock.patch(f"{SOURCE_MODULE}.validate_adyen_credentials", return_value=mock_return) as mock_validate:
            is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert message == expected_message
        mock_validate.assert_called_once_with(
            environment="live",
            api_key="adyen-key",
            balance_platform="BP123",
            merchant_account="ACME",
        )

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AdyenResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = _make_inputs(schema_name="Transactions")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        with mock.patch(f"{SOURCE_MODULE}.adyen_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            environment="live",
            api_key="adyen-key",
            endpoint="Transactions",
            logger=inputs.logger,
            resumable_source_manager=manager,
            balance_platform="BP123",
            merchant_account="ACME",
            start_date="2026-01-01",
            settlement_report_start_batch=None,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )

    def test_source_for_pipeline_only_passes_the_watermark_when_incremental(self) -> None:
        inputs = _make_inputs(
            schema_name="Transfers",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-05-01T00:00:00Z",
            incremental_field="createdAt",
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        with mock.patch(f"{SOURCE_MODULE}.adyen_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-05-01T00:00:00Z"

    def test_watermark_is_dropped_when_incremental_is_off(self) -> None:
        inputs = _make_inputs(
            should_use_incremental_field=False, db_incremental_field_last_value="2026-05-01T00:00:00Z"
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        with mock.patch(f"{SOURCE_MODULE}.adyen_source") as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None
