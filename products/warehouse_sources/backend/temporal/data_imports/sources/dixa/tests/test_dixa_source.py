import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dixa.dixa import DixaResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.dixa.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.dixa.source import DixaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DixaSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestDixaSource:
    def setup_method(self):
        self.source = DixaSource()
        self.team_id = 123
        self.config = DixaSourceConfig(api_token="api-token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.DIXA

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Dixa"
        assert config.label == "Dixa"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/dixa.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_token"]

    def test_api_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://dev.dixa.io/v1/agents",
            "401 Client Error: Unauthorized for url: https://exports.dixa.io/v1/conversation_export",
            "403 Client Error: Forbidden for url: https://exports.dixa.io/v1/conversation_export",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://dev.dixa.io/v1/agents",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only the exports surface has server-side updated_after filtering.
        assert incremental == {"conversations"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["conversations"].incremental_fields == INCREMENTAL_FIELDS["conversations"]
        assert [f["field"] for f in schemas["conversations"].incremental_fields] == ["updated_at"]
        assert schemas["agents"].incremental_fields == []
        assert schemas["agents"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["conversations"])
        assert len(schemas) == 1
        assert schemas[0].name == "conversations"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Invalid Dixa API token"), False, "Invalid Dixa API token"),
            (
                (False, "Could not reach Dixa to validate the API token. Please try again."),
                False,
                "Could not reach Dixa to validate the API token. Please try again.",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.dixa.source.validate_dixa_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_token)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DixaResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.source.dixa_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_dixa_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "conversations"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000000
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_dixa_source.assert_called_once()
        kwargs = mock_dixa_source.call_args.kwargs
        assert kwargs["api_token"] == "api-token"
        assert kwargs["endpoint"] == "conversations"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000000

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dixa.source.dixa_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_dixa_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "agents"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1700000000000

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_dixa_source.call_args.kwargs["db_incremental_field_last_value"] is None
