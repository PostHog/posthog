import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    TailscaleAuthMethodConfig,
    TailscaleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tailscale.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tailscale.source import TailscaleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tailscale.tailscale import (
    OAUTH_CREDENTIALS_ERROR,
    TailscaleResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestTailscaleSource:
    def setup_method(self):
        self.source = TailscaleSource()
        self.team_id = 123
        self.config = TailscaleSourceConfig(
            auth_method=TailscaleAuthMethodConfig(selection="api_key", api_key="tskey-api-test"),
            tailnet="example.com",
        )

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.TAILSCALE

    def test_tailnet_change_requires_reentering_secrets(self):
        # The update serializer keys off this to force re-entry of the stored credential
        # when the tailnet is retargeted.
        assert self.source.connection_host_fields == ["tailnet"]

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Tailscale"
        assert config.label == "Tailscale"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/tailscale.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/tailscale"

        field_names = [f.name for f in config.fields]
        assert field_names == ["auth_method", "tailnet"]

        auth_field, tailnet_field = config.fields
        assert isinstance(auth_field, SourceFieldSelectConfig)
        assert [option.value for option in auth_field.options] == ["oauth_client", "api_key"]

        secret_fields = {
            sub_field.name: sub_field.secret
            for option in auth_field.options
            for sub_field in option.fields or []
            if isinstance(sub_field, SourceFieldInputConfig)
        }
        assert secret_fields == {"client_id": False, "client_secret": True, "api_key": True}

        assert isinstance(tailnet_field, SourceFieldInputConfig)
        assert tailnet_field.required is False

    @pytest.mark.parametrize(
        "expected_key",
        ["401 Client Error", "403 Client Error", "404 Client Error", OAUTH_CREDENTIALS_ERROR],
    )
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, supports_append",
        [
            ("devices", False),
            ("users", False),
            ("keys", False),
            ("configuration_audit_logs", True),
        ],
    )
    def test_schema_sync_support(self, endpoint, supports_append):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        # Audit log records have no unique id, so merge-based incremental syncs must never
        # be offered — the time filter powers append syncs only.
        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is supports_append
        assert bool(schemas[endpoint].incremental_fields) is supports_append

    def test_audit_logs_schema_mentions_retention(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert "90 days" in (schemas["configuration_audit_logs"].description or "")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["devices"])
        assert [s.name for s in schemas] == ["devices"]

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.tailscale.source.validate_tailscale_credentials"
    )
    def test_validate_credentials_plumbs_config(self, mock_validate):
        mock_validate.return_value = (True, None)

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="devices")

        assert result == (True, None)
        mock_validate.assert_called_once_with(
            api_key="tskey-api-test",
            client_id=None,
            client_secret=None,
            tailnet="example.com",
            schema_name="devices",
        )

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is TailscaleResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.tailscale.source.tailscale_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_tailscale_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "configuration_audit_logs"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_tailscale_source.call_args.kwargs
        assert kwargs["api_key"] == "tskey-api-test"
        assert kwargs["tailnet"] == "example.com"
        assert kwargs["endpoint"] == "configuration_audit_logs"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.tailscale.source.tailscale_source")
    def test_source_for_pipeline_omits_last_value_when_not_incremental(self, mock_tailscale_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "devices"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_tailscale_source.call_args.kwargs["db_incremental_field_last_value"] is None
