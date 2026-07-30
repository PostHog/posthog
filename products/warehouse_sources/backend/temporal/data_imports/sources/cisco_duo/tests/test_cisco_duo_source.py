import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_duo.cisco_duo import CiscoDuoResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_duo.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_duo.source import CiscoDuoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CiscoDuoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCiscoDuoSource:
    def setup_method(self):
        self.source = CiscoDuoSource()
        self.team_id = 123
        self.config = CiscoDuoSourceConfig(
            api_hostname="api-xxxxxxxx.duosecurity.com",
            integration_key="DIWJ8X6AEYOR5OMC6TQ1",
            secret_key="secret",
        )

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CISCODUO

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "CiscoDuo"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/cisco_duo.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["api_hostname", "integration_key", "secret_key"]

        hostname_field, ikey_field, skey_field = config.fields
        assert isinstance(hostname_field, SourceFieldInputConfig)
        assert hostname_field.secret is False

        assert isinstance(ikey_field, SourceFieldInputConfig)
        assert ikey_field.secret is False

        assert isinstance(skey_field, SourceFieldInputConfig)
        assert skey_field.type == SourceFieldInputConfigType.PASSWORD
        assert skey_field.secret is True
        assert skey_field.required is True

    def test_connection_host_fields_covers_api_hostname(self):
        # Retargeting api_hostname must re-require the secret key, or a member could point
        # the stored credential at a host they control.
        assert self.source.connection_host_fields == ["api_hostname"]

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, incremental, append",
        [
            ("authentication_logs", True, False),
            # No unique event id: merging would multi-match, so the admin log is append-only.
            ("administrator_logs", False, True),
            ("telephony_logs", True, False),
            ("activity_logs", True, False),
            ("users", False, False),
            ("groups", False, False),
            ("phones", False, False),
            ("admins", False, False),
            ("integrations", False, False),
        ],
    )
    def test_schema_sync_modes(self, endpoint, incremental, append):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is incremental
        assert schemas[endpoint].supports_append is append

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["users", "nope"])
        assert [s.name for s in schemas] == ["users"]

    @pytest.mark.parametrize(
        "mock_return",
        [(True, None), (False, "Invalid Cisco Duo credentials")],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cisco_duo.source.validate_cisco_duo_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="users")

        assert result == mock_return
        mock_validate.assert_called_once_with(
            self.config.api_hostname, self.config.integration_key, self.config.secret_key, "users", self.team_id
        )

    def test_get_resumable_source_manager(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CiscoDuoResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.cisco_duo.source.cisco_duo_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_cisco_duo_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "authentication_logs"
        inputs.team_id = 42
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_cisco_duo_source.call_args.kwargs
        assert kwargs["api_hostname"] == "api-xxxxxxxx.duosecurity.com"
        assert kwargs["integration_key"] == "DIWJ8X6AEYOR5OMC6TQ1"
        assert kwargs["secret_key"] == "secret"
        assert kwargs["endpoint"] == "authentication_logs"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 42
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.cisco_duo.source.cisco_duo_source")
    def test_source_for_pipeline_omits_last_value_when_not_incremental(self, mock_cisco_duo_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "users"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_cisco_duo_source.call_args.kwargs["db_incremental_field_last_value"] is None
