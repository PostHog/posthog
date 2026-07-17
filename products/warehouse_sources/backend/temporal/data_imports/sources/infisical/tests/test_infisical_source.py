import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import InfisicalSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.infisical.infisical import InfisicalResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.infisical.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.infisical.source import InfisicalSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestInfisicalSource:
    def setup_method(self):
        self.source = InfisicalSource()
        self.team_id = 123
        self.config = InfisicalSourceConfig(
            base_url="https://app.infisical.com",
            organization_id="org-123",
            client_id="cid",
            client_secret="csecret",
        )

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.INFISICAL

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Infisical"
        assert config.label == "Infisical"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/infisical.svg"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/infisical"

        field_names = [f.name for f in config.fields]
        assert field_names == ["base_url", "organization_id", "client_id", "client_secret"]

        secret_field = config.fields[-1]
        assert isinstance(secret_field, SourceFieldInputConfig)
        assert secret_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_field.secret is True
        assert all(
            isinstance(f, SourceFieldInputConfig) and f.secret is False and f.required is True
            for f in config.fields[:-1]
        )

    def test_connection_host_fields_require_credential_reentry(self):
        # Both the host and the org selector gate the stored credential: changing either must
        # force re-entry so an editor who can't read the secret can't repoint it.
        assert self.source.connection_host_fields == ["base_url", "organization_id"]

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error",
            "403 Client Error",
            "Invalid Infisical machine identity credentials",
            "Infisical host is not allowed",
        ],
    )
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, incremental",
        [
            ("audit_logs", True),
            ("projects", False),
            ("identities", False),
            ("organization_memberships", False),
            ("project_memberships", False),
        ],
    )
    def test_schema_incremental_support(self, endpoint, incremental):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is incremental
        assert schemas[endpoint].supports_append is incremental

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["audit_logs"])
        assert [s.name for s in schemas] == ["audit_logs"]
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return",
        [
            (True, None),
            (False, "Invalid Infisical machine identity credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.infisical.source.validate_infisical_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="audit_logs")

        assert result == mock_return
        mock_validate.assert_called_once_with(
            "https://app.infisical.com", "cid", "csecret", "org-123", "audit_logs", 123
        )

    def test_get_resumable_source_manager(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is InfisicalResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.infisical.source.infisical_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_infisical_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "audit_logs"
        inputs.team_id = 42
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00.000Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_infisical_source.call_args.kwargs
        assert kwargs["base_url"] == "https://app.infisical.com"
        assert kwargs["client_id"] == "cid"
        assert kwargs["client_secret"] == "csecret"
        assert kwargs["organization_id"] == "org-123"
        assert kwargs["endpoint"] == "audit_logs"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 42
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00.000Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.infisical.source.infisical_source")
    def test_source_for_pipeline_omits_last_value_when_not_incremental(self, mock_infisical_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "projects"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_infisical_source.call_args.kwargs["db_incremental_field_last_value"] is None
