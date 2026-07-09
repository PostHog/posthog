import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GuruSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.guru.guru import GuruResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.guru.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.guru.source import GuruSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestGuruSource:
    def setup_method(self):
        self.source = GuruSource()
        self.team_id = 123
        self.config = GuruSourceConfig(username="user@company.com", api_token="api-token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GURU

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Guru"
        assert config.label == "Guru"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/guru.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["username", "api_token"]

    def test_api_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.getguru.com/api/v1/search/query",
            "403 Client Error: Forbidden for url: https://api.getguru.com/api/v1/collections",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.getguru.com/api/v1/collections",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only the card search surface supports a server-side date filter.
        assert incremental == {"cards"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["cards"].incremental_fields == INCREMENTAL_FIELDS["cards"]
        assert schemas["collections"].incremental_fields == []
        assert schemas["collections"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["cards"])
        assert len(schemas) == 1
        assert schemas[0].name == "cards"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Guru API credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.guru.source.validate_guru_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.username, self.config.api_token)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is GuruResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.guru.source.guru_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_guru_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "cards"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00+00:00"
        inputs.incremental_field = "lastModified"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_guru_source.assert_called_once()
        kwargs = mock_guru_source.call_args.kwargs
        assert kwargs["username"] == "user@company.com"
        assert kwargs["api_token"] == "api-token"
        assert kwargs["endpoint"] == "cards"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00+00:00"
        assert kwargs["incremental_field"] == "lastModified"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.guru.source.guru_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_guru_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "collections"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00+00:00"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_guru_source.call_args.kwargs["db_incremental_field_last_value"] is None
