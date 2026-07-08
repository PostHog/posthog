import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RollbarSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.rollbar import RollbarResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.source import RollbarSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestRollbarSource:
    def setup_method(self):
        self.source = RollbarSource()
        self.team_id = 123
        self.config = RollbarSourceConfig(access_token="access-token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.ROLLBAR

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Rollbar"
        assert config.label == "Rollbar"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/rollbar.png"

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
            "401 Client Error: Unauthorized for url: https://api.rollbar.com/api/1/items?page=1",
            "403 Client Error: Forbidden for url: https://api.rollbar.com/api/1/instances",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.rollbar.com/api/1/items",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only occurrences have a usable high-water-mark cursor (descending id
        # keyset); items mutate in place and deploys/environments are small.
        assert incremental == {"occurrences"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["occurrences"].incremental_fields == INCREMENTAL_FIELDS["occurrences"]
        assert [f["field"] for f in schemas["occurrences"].incremental_fields] == ["id"]
        assert schemas["items"].incremental_fields == []
        assert schemas["items"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["occurrences"])
        assert len(schemas) == 1
        assert schemas[0].name == "occurrences"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Rollbar project access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.source.validate_rollbar_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.access_token)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is RollbarResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.source.rollbar_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_rollbar_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "occurrences"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 12345
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_rollbar_source.assert_called_once()
        kwargs = mock_rollbar_source.call_args.kwargs
        assert kwargs["access_token"] == "access-token"
        assert kwargs["endpoint"] == "occurrences"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 12345

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.source.rollbar_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_rollbar_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "items"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 12345

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_rollbar_source.call_args.kwargs["db_incremental_field_last_value"] is None
