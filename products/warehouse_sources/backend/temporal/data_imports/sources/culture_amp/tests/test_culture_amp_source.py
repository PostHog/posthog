import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.culture_amp import (
    CultureAmpResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.source import CultureAmpSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CultureAmpSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCultureAmpSource:
    def setup_method(self):
        self.source = CultureAmpSource()
        self.team_id = 123
        self.config = CultureAmpSourceConfig(client_id="cid", client_secret="sec", account_id="entity-1")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CULTUREAMP

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "CultureAmp"
        assert config.label == "Culture Amp"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/culture_amp.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["client_id", "client_secret", "account_id"]

    def test_client_secret_field_is_secret_password(self):
        config = self.source.get_source_config
        secret_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "client_secret"
        )
        assert secret_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_field.secret is True
        assert secret_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "400 Client Error: Bad Request for url: https://api.cultureamp.com/v1/oauth2/token",
            "401 Client Error: Unauthorized for url: https://api.cultureamp.com/v1/oauth2/token",
            "403 Client Error: Forbidden for url: https://api.cultureamp.com/v1/employees",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error for url: https://api.cultureamp.com/v1/employees",
            # Mid-sync 401s on data endpoints are handled by token re-mint.
            "401 Client Error: Unauthorized for url: https://api.cultureamp.com/v1/employees",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # Only the performance streams expose the server-side after_date filter.
        incremental = {name for name, schema in schemas.items() if schema.supports_incremental}
        assert incremental == {"performance_cycles", "manager_reviews"}
        assert schemas["manager_reviews"].incremental_fields == INCREMENTAL_FIELDS["manager_reviews"]
        assert [f["field"] for f in schemas["performance_cycles"].incremental_fields] == ["processedAt"]
        assert schemas["employees"].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["employees"])
        assert len(schemas) == 1
        assert schemas[0].name == "employees"

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
        "products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.source.validate_culture_amp_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert "employees read permission" in (error_message or "")
        mock_validate.assert_called_once_with("cid", "sec", "entity-1")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CultureAmpResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.source.culture_amp_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_culture_amp_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "manager_reviews"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_culture_amp_source.assert_called_once()
        kwargs = mock_culture_amp_source.call_args.kwargs
        assert kwargs["client_id"] == "cid"
        assert kwargs["client_secret"] == "sec"
        assert kwargs["account_id"] == "entity-1"
        assert kwargs["endpoint"] == "manager_reviews"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05Z"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.source.culture_amp_source"
    )
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_culture_amp_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "employees"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_culture_amp_source.call_args.kwargs["db_incremental_field_last_value"] is None
