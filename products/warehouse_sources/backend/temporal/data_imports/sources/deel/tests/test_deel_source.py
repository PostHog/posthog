import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.deel.deel import DeelResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.deel.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.deel.source import DeelSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DeelSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestDeelSource:
    def setup_method(self):
        self.source = DeelSource()
        self.team_id = 123
        self.config = DeelSourceConfig(api_token="api-token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.DEEL

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Deel"
        assert config.label == "Deel"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/deel.png"

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
            "401 Client Error: Unauthorized for url: https://api.letsdeel.com/rest/v2/people?limit=50",
            "403 Client Error: Forbidden for url: https://api.letsdeel.com/rest/v2/contracts",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.letsdeel.com/rest/v2/people",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # No Deel core object exposes an updated-since filter; full refresh only.
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["people"])
        assert len(schemas) == 1
        assert schemas[0].name == "people"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return",
        [
            (True, None),
            (False, "Invalid Deel API token"),
            (False, "Could not reach Deel: boom"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.deel.source.validate_deel_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id)

        assert result == mock_return
        mock_validate.assert_called_once_with(self.config.api_token)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DeelResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.deel.source.deel_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_deel_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "people"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_deel_source.assert_called_once()
        kwargs = mock_deel_source.call_args.kwargs
        assert kwargs["api_token"] == "api-token"
        assert kwargs["endpoint"] == "people"
        assert kwargs["resumable_source_manager"] is manager
