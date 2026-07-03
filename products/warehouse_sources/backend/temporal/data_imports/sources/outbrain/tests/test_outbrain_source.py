import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OutbrainSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.outbrain import OutbrainResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.source import OutbrainSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestOutbrainSource:
    def setup_method(self):
        self.source = OutbrainSource()
        self.team_id = 123
        self.config = OutbrainSourceConfig(username="u@x.com", password="pw")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.OUTBRAIN

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Outbrain"
        assert config.label == "Outbrain"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/outbrain.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["username", "password"]

    def test_password_field_is_secret(self):
        config = self.source.get_source_config
        password_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "password"
        )
        assert password_field.type == SourceFieldInputConfigType.PASSWORD
        assert password_field.secret is True
        assert password_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.outbrain.com/amplify/v0.1/login",
            "403 Client Error: Forbidden for url: https://api.outbrain.com/amplify/v0.1/marketers",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error for url: https://api.outbrain.com/amplify/v0.1/marketers",
            # Mid-sync 401s on data endpoints are handled by token re-mint.
            "401 Client Error: Unauthorized for url: https://api.outbrain.com/amplify/v0.1/marketers",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # Only the daily periodic report has a real server-side date filter
        # with a per-row date.
        incremental = {name for name, schema in schemas.items() if schema.supports_incremental}
        assert incremental == {"marketer_performance_daily"}
        assert (
            schemas["marketer_performance_daily"].incremental_fields == INCREMENTAL_FIELDS["marketer_performance_daily"]
        )
        assert schemas["campaigns"].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["marketers"])
        assert len(schemas) == 1
        assert schemas[0].name == "marketers"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.source.validate_outbrain_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error_message == "Invalid Outbrain credentials"
        mock_validate.assert_called_once_with("u@x.com", "pw")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is OutbrainResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.source.outbrain_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_outbrain_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "marketer_performance_daily"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-06-01"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_outbrain_source.assert_called_once()
        kwargs = mock_outbrain_source.call_args.kwargs
        assert kwargs["username"] == "u@x.com"
        assert kwargs["password"] == "pw"
        assert kwargs["endpoint"] == "marketer_performance_daily"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-06-01"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.source.outbrain_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_outbrain_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "marketers"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-06-01"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_outbrain_source.call_args.kwargs["db_incremental_field_last_value"] is None
