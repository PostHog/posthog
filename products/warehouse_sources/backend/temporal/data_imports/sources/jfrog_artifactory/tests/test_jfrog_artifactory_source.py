import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    JfrogArtifactorySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jfrog_artifactory.jfrog_artifactory import (
    JfrogArtifactoryResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jfrog_artifactory.settings import (
    ENDPOINTS,
    JFROG_ARTIFACTORY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jfrog_artifactory.source import (
    JfrogArtifactorySource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# AQL endpoints expose server-side timestamp filters; the REST list endpoints don't.
_INCREMENTAL_ENDPOINTS = {"artifacts", "builds"}
_FULL_REFRESH_ENDPOINTS = {"repositories", "storage_summary"}


class TestJfrogArtifactorySource:
    def setup_method(self):
        self.source = JfrogArtifactorySource()
        self.team_id = 123
        self.config = JfrogArtifactorySourceConfig(base_url="https://acme.jfrog.io", access_token="token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.JFROGARTIFACTORY

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "JfrogArtifactory"
        assert config.label == "JFrog (Artifactory / JFrog Platform)"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/jfrog_artifactory.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/jfrog-artifactory"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["base_url", "access_token"]

    def test_access_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "access_token"
        )
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_base_url_listed_as_connection_host_field(self):
        # The access token is sent to base_url, so retargeting it must re-require the token.
        assert self.source.connection_host_fields == ["base_url"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://acme.jfrog.io/artifactory/api/search/aql",
            "403 Client Error: Forbidden for url: https://acme.jfrog.io/artifactory/api/storageinfo",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://acme.jfrog.io/artifactory/api/search/aql",
            "500 Server Error: Internal Server Error for url: https://acme.jfrog.io/artifactory/api/repositories",
            "HTTPSConnectionPool(host='acme.jfrog.io', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in _INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert len(schemas[name].incremental_fields) > 0
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_admin_endpoints_not_selected_by_default(self):
        # builds/storage_summary need an admin token; syncing them by default would fail most
        # non-admin connections.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["builds"].should_sync_default is False
        assert schemas["storage_summary"].should_sync_default is False
        assert schemas["repositories"].should_sync_default is True
        assert schemas["artifacts"].should_sync_default is True

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["artifacts"])
        assert len(schemas) == 1
        assert schemas[0].name == "artifacts"

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(JFROG_ARTIFACTORY_ENDPOINTS)

    @pytest.mark.parametrize(
        "probe_return, schema_name, expected_valid, expected_message_part",
        [
            ((True, 200), None, True, None),
            ((False, 401), None, False, "Invalid JFrog access token"),
            # A 403 at source-create means the token is genuine but not fully scoped — accept it.
            ((False, 403), None, True, None),
            ((False, 403), "builds", False, "admin"),
            ((False, 403), "artifacts", False, "missing the permissions"),
            ((False, None), None, False, "Could not connect"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.jfrog_artifactory.source.probe_endpoint"
    )
    @mock.patch.object(JfrogArtifactorySource, "is_database_host_valid")
    def test_validate_credentials(
        self, mock_host_valid, mock_probe, probe_return, schema_name, expected_valid, expected_message_part
    ):
        mock_host_valid.return_value = (True, None)
        mock_probe.return_value = probe_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, schema_name)

        assert is_valid is expected_valid
        if expected_message_part is None:
            assert error_message is None
        else:
            assert expected_message_part in (error_message or "")

    @mock.patch.object(JfrogArtifactorySource, "is_database_host_valid")
    def test_validate_credentials_rejects_unsafe_host(self, mock_host_valid):
        mock_host_valid.return_value = (False, "Host is not allowed")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Host is not allowed"

    def test_validate_credentials_surfaces_bad_url(self):
        config = JfrogArtifactorySourceConfig(base_url="https://acme.jfrog.io/evil/path", access_token="token")

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert "Invalid JFrog platform URL" in (error_message or "")

    @pytest.mark.parametrize(
        "probe_return, endpoint, expected_reason_part",
        [
            ((True, 200), "artifacts", None),
            ((False, 403), "builds", "admin"),
            ((False, 401), "artifacts", "cannot read"),
            # A throttle or transient failure is not a missing scope.
            ((False, 429), "artifacts", None),
            ((False, None), "builds", None),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.jfrog_artifactory.source.probe_endpoint"
    )
    def test_get_endpoint_permissions(self, mock_probe, probe_return, endpoint, expected_reason_part):
        mock_probe.return_value = probe_return

        permissions = self.source.get_endpoint_permissions(self.config, self.team_id, [endpoint])

        if expected_reason_part is None:
            assert permissions[endpoint] is None
        else:
            assert expected_reason_part in (permissions[endpoint] or "")

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is JfrogArtifactoryResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.jfrog_artifactory.source.jfrog_artifactory_source"
    )
    @mock.patch.object(JfrogArtifactorySource, "is_database_host_valid")
    def test_source_for_pipeline_plumbs_arguments(self, mock_host_valid, mock_source_fn):
        mock_host_valid.return_value = (True, None)
        inputs = mock.MagicMock()
        inputs.schema_name = "artifacts"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00+00:00"
        inputs.incremental_field = "modified"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source_fn.assert_called_once()
        kwargs = mock_source_fn.call_args.kwargs
        assert kwargs["base_url"] == "https://acme.jfrog.io"
        assert kwargs["access_token"] == "token"
        assert kwargs["endpoint"] == "artifacts"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00+00:00"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.jfrog_artifactory.source.jfrog_artifactory_source"
    )
    @mock.patch.object(JfrogArtifactorySource, "is_database_host_valid")
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_host_valid, mock_source_fn):
        mock_host_valid.return_value = (True, None)
        inputs = mock.MagicMock()
        inputs.schema_name = "repositories"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00+00:00"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source_fn.call_args.kwargs["db_incremental_field_last_value"] is None

    @mock.patch.object(JfrogArtifactorySource, "is_database_host_valid")
    def test_source_for_pipeline_rejects_unsafe_host(self, mock_host_valid):
        mock_host_valid.return_value = (False, "Host is not allowed")
        inputs = mock.MagicMock()
        inputs.schema_name = "artifacts"
        inputs.team_id = self.team_id

        with pytest.raises(ValueError, match="Host is not allowed"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
