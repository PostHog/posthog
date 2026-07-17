import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TaboolaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.taboola.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.taboola.source import TaboolaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.taboola.taboola import TaboolaResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestTaboolaSource:
    def setup_method(self):
        self.source = TaboolaSource()
        self.team_id = 123
        self.config = TaboolaSourceConfig(client_id="cid", client_secret="sec", account_id="acct")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.TABOOLA

    def test_connection_host_fields_includes_account_id(self):
        assert self.source.connection_host_fields == ["account_id"]

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Taboola"
        assert config.label == "Taboola"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/taboola.png"

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
            "400 Client Error: Bad Request for url: https://backstage.taboola.com/backstage/oauth/token",
            "401 Client Error: Unauthorized for url: https://backstage.taboola.com/backstage/api/1.0/acct/campaigns/",
            "403 Client Error: Forbidden for url: https://backstage.taboola.com/backstage/api/1.0/acct/campaigns/",
            "404 Client Error: Not Found for url: https://backstage.taboola.com/backstage/api/1.0/bad-acct/campaigns/",
        ],
    )
    def test_non_retryable_errors_match_known_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_server_errors(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        error = "500 Server Error for url: https://backstage.taboola.com/backstage/api/1.0/acct/campaigns/"
        assert not any(key in error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # Only the date-windowed report has a real server-side date filter.
        incremental = {name for name, schema in schemas.items() if schema.supports_incremental}
        assert incremental == {"campaign_summary_by_day"}
        assert schemas["campaign_summary_by_day"].incremental_fields == INCREMENTAL_FIELDS["campaign_summary_by_day"]
        assert schemas["campaigns"].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["campaigns"])
        assert len(schemas) == 1
        assert schemas[0].name == "campaigns"

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
        "products.warehouse_sources.backend.temporal.data_imports.sources.taboola.source.validate_taboola_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error_message == "Invalid Taboola credentials"
        mock_validate.assert_called_once_with("cid", "sec")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is TaboolaResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.taboola.source.taboola_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_taboola_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "campaign_summary_by_day"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_taboola_source.assert_called_once()
        kwargs = mock_taboola_source.call_args.kwargs
        assert kwargs["client_id"] == "cid"
        assert kwargs["client_secret"] == "sec"
        assert kwargs["account_id"] == "acct"
        assert kwargs["endpoint"] == "campaign_summary_by_day"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.taboola.source.taboola_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_taboola_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "campaigns"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_taboola_source.call_args.kwargs["db_incremental_field_last_value"] is None
