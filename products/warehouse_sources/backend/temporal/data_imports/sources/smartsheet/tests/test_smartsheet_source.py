import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SmartsheetSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.smartsheet import (
    SmartsheetResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.source import SmartsheetSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSmartsheetSource:
    def setup_method(self):
        self.source = SmartsheetSource()
        self.team_id = 123
        self.config = SmartsheetSourceConfig(access_token="token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.SMARTSHEET

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Smartsheet"
        assert config.label == "Smartsheet"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/smartsheet.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["access_token"]

    def test_access_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "access_token"
        )
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.smartsheet.com/2.0/sheets?page=1&pageSize=100",
            "403 Client Error: Forbidden for url: https://api.smartsheet.com/2.0/users",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.smartsheet.com/2.0/sheets",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_get_schemas_are_full_refresh(self):
        # No Smartsheet list endpoint exposes an order-stable server-side timestamp filter,
        # so every schema ships as full refresh.
        for schema in self.source.get_schemas(self.config, self.team_id):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == INCREMENTAL_FIELDS[schema.name]
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["sheets"])
        assert len(schemas) == 1
        assert schemas[0].name == "sheets"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Smartsheet access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.source.validate_smartsheet_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.access_token)

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SmartsheetResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.source.smartsheet_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_smartsheet_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "sheets"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_smartsheet_source.assert_called_once()
        kwargs = mock_smartsheet_source.call_args.kwargs
        assert kwargs["access_token"] == "token"
        assert kwargs["endpoint"] == "sheets"
        assert kwargs["resumable_source_manager"] is manager
