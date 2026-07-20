import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SpaceliftSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.source import SpaceliftSource
from products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.spacelift import SpaceliftResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.source"


class TestSpaceliftSource:
    def setup_method(self):
        self.source = SpaceliftSource()
        self.team_id = 123
        self.config = SpaceliftSourceConfig(account_name="my-company", api_key_id="key-id", api_key_secret="key-secret")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.SPACELIFT

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Spacelift"
        assert config.label == "Spacelift"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/spacelift.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/spacelift"

        field_names = [f.name for f in config.fields]
        assert field_names == ["account_name", "api_key_id", "api_key_secret"]

    def test_api_key_secret_field_is_secret_password(self):
        config = self.source.get_source_config
        secret_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key_secret"
        )
        assert secret_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_field.secret is True
        assert secret_field.required is True

    def test_account_name_is_a_connection_host_field(self):
        # Retargeting the account subdomain must force re-entering the API secret,
        # otherwise a PATCH could redirect the stored secret to an attacker's host.
        assert self.source.connection_host_fields == ["account_name"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "Invalid Spacelift API key: the API key ID or secret is incorrect",
            "Spacelift API returned unauthorized: the API key lacks access to this data (unauthorized)",
            "Invalid Spacelift account name: 'evil.com/x'",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "Spacelift: retryable HTTP error 503",
            "Spacelift GraphQL error: internal error",
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient_failures(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_only_runs_supports_incremental(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["runs"].supports_incremental is True
        assert [f["field"] for f in schemas["runs"].incremental_fields] == ["createdAt"]
        assert schemas["runs"].incremental_fields == INCREMENTAL_FIELDS["runs"]
        for name, schema in schemas.items():
            # Incremental re-pulls a lookback window that only merge dedupes.
            assert schema.supports_append is False
            if name != "runs":
                assert schema.supports_incremental is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["runs", "stacks"])
        assert {schema.name for schema in schemas} == {"runs", "stacks"}

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_without_credentials(self):
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return",
        [
            (True, None),
            (False, "Invalid Spacelift API key: the API key ID or secret is incorrect"),
        ],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_spacelift_credentials")
    def test_validate_credentials(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        assert self.source.validate_credentials(self.config, self.team_id) == mock_return
        mock_validate.assert_called_once_with("my-company", "key-id", "key-secret")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SpaceliftResumeConfig

    @mock.patch(f"{_SOURCE_MODULE}.spacelift_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "runs"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        inputs.incremental_field = "createdAt"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["account_name"] == "my-company"
        assert kwargs["api_key_id"] == "key-id"
        assert kwargs["api_key_secret"] == "key-secret"
        assert kwargs["endpoint"] == "runs"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000
        assert kwargs["incremental_field"] == "createdAt"

    @mock.patch(f"{_SOURCE_MODULE}.spacelift_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "runs"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1700000000

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
