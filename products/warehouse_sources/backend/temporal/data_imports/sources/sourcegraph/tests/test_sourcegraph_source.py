import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SourcegraphSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sourcegraph.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.sourcegraph.source import SourcegraphSource
from products.warehouse_sources.backend.temporal.data_imports.sources.sourcegraph.sourcegraph import (
    SourcegraphResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSourcegraphSource:
    def setup_method(self):
        self.source = SourcegraphSource()
        self.team_id = 123
        self.config = SourcegraphSourceConfig(host="https://sourcegraph.example.com", access_token="sgp_token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.SOURCEGRAPH

    def test_connection_host_fields_force_token_reentry_on_host_change(self):
        # `host` is where the access token is sent; changing it must re-require the
        # token so the stored secret can't be redirected to an attacker-controlled host.
        assert self.source.connection_host_fields == ["host"]

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Sourcegraph"
        assert config.label == "Sourcegraph"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/sourcegraph.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["host", "access_token"]

        host_field, token_field = config.fields
        assert isinstance(host_field, SourceFieldInputConfig)
        assert host_field.type == SourceFieldInputConfigType.TEXT
        assert host_field.secret is False

        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error",
            "403 Client Error",
            "Sourcegraph GraphQL error: not authenticated",
            "Sourcegraph GraphQL error: must be site admin",
        ],
    )
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_all_schemas_are_full_refresh_only(self):
        # No Sourcegraph connection has a server-side updated-since filter; advertising
        # incremental sync would silently re-fetch everything each run.
        for schema in self.source.get_schemas(self.config, self.team_id):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    @pytest.mark.parametrize("endpoint", ["users", "organizations"])
    def test_admin_scoped_schemas_mention_site_admin(self, endpoint):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert "site-admin" in (schemas[endpoint].description or "")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["repositories"])
        assert len(schemas) == 1
        assert schemas[0].name == "repositories"

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return",
        [
            (True, None),
            (False, "Invalid Sourcegraph access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.sourcegraph.source.validate_sourcegraph_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="users")

        assert result == mock_return
        mock_validate.assert_called_once_with(self.config.host, self.config.access_token, "users", self.team_id)

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SourcegraphResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.sourcegraph.source.sourcegraph_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_sourcegraph_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "repositories"
        inputs.team_id = 42
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_sourcegraph_source.assert_called_once()
        kwargs = mock_sourcegraph_source.call_args.kwargs
        assert kwargs["host"] == "https://sourcegraph.example.com"
        assert kwargs["access_token"] == "sgp_token"
        assert kwargs["endpoint"] == "repositories"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 42
