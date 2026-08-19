import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.housecallpro import (
    HousecallProSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.housecall_pro.housecall_pro import (
    HousecallProResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.housecall_pro.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.housecall_pro.source import HousecallProSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestHousecallProSource:
    def setup_method(self) -> None:
        self.source = HousecallProSource()
        self.team_id = 123
        self.config = HousecallProSourceConfig(api_key="key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.HOUSECALLPRO

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "HousecallPro"
        assert config.label == "Housecall Pro"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/housecall-pro"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True
        assert len(self.source.get_documented_tables()) == len(ENDPOINTS)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.housecallpro.com/customers?page=1",
            "403 Client Error: Forbidden for url: https://api.housecallpro.com/jobs",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.housecallpro.com/customers",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_only_invoices_is_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        incremental = {name for name, s in schemas.items() if s.supports_incremental}
        # Only Invoices documents a genuine server-side timestamp filter (created_at_min).
        assert incremental == {"invoices"}

    def test_incremental_schema_advertises_its_fields(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["invoices"].incremental_fields == INCREMENTAL_FIELDS["invoices"]
        assert schemas["customers"].incremental_fields == []
        assert schemas["customers"].supports_append is False

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["customers"])
        assert len(schemas) == 1
        assert schemas[0].name == "customers"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_get_canonical_descriptions_keys_match_endpoints(self) -> None:
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical).issubset(set(ENDPOINTS))

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Housecall Pro API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.housecall_pro.source.validate_housecall_pro_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: bool,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is HousecallProResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.housecall_pro.source.housecall_pro_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_housecall_pro_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "invoices"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_housecall_pro_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "invoices"
        assert kwargs["team_id"] is inputs.team_id
        assert kwargs["job_id"] is inputs.job_id
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.housecall_pro.source.housecall_pro_source"
    )
    def test_source_for_pipeline_omits_last_value_on_full_refresh(
        self, mock_housecall_pro_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "customers"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1700000000

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_housecall_pro_source.call_args.kwargs["db_incremental_field_last_value"] is None
