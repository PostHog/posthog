import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.crunchbase import (
    CrunchbaseResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.source import CrunchbaseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CrunchbaseSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCrunchbaseSource:
    def setup_method(self):
        self.source = CrunchbaseSource()
        self.team_id = 123
        self.config = CrunchbaseSourceConfig(api_key="user-key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CRUNCHBASE

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Crunchbase"
        assert config.label == "Crunchbase"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/crunchbase.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.crunchbase.com/v4/data/searches/organizations",
            "403 Client Error: Forbidden for url: https://api.crunchbase.com/v4/data/searches/people",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.crunchbase.com/v4/data/searches/organizations",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Every collection search supports the updated_at gte predicate.
        assert all(schema.supports_incremental for schema in schemas)
        assert all(schema.supports_append for schema in schemas)

    def test_schemas_advertise_updated_at_cursor(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["organizations"].incremental_fields == INCREMENTAL_FIELDS["organizations"]
        assert [f["field"] for f in schemas["organizations"].incremental_fields] == ["updated_at"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["organizations"])
        assert len(schemas) == 1
        assert schemas[0].name == "organizations"

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
        "products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.source.validate_crunchbase_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert "Enterprise/Applications" in (error_message or "")
        mock_validate.assert_called_once_with(self.config.api_key)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CrunchbaseResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.source.crunchbase_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_cb_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "organizations"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_cb_source.assert_called_once()
        kwargs = mock_cb_source.call_args.kwargs
        assert kwargs["api_key"] == "user-key"
        assert kwargs["endpoint"] == "organizations"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.source.crunchbase_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_cb_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "organizations"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_cb_source.call_args.kwargs["db_incremental_field_last_value"] is None
