import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.jfrogartifactory import (
    JfrogArtifactorySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jfrog_artifactory.source import (
    JfrogArtifactorySource,
)


class TestJfrogArtifactorySource:
    def setup_method(self):
        self.source = JfrogArtifactorySource()
        self.team_id = 123
        self.config = JfrogArtifactorySourceConfig(base_url="https://acme.jfrog.io", access_token="token")

    def test_base_url_listed_as_connection_host_field(self):
        # The access token is sent to base_url, so retargeting it must re-require the token.
        assert self.source.connection_host_fields == ["base_url"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["artifacts"])
        assert len(schemas) == 1
        assert schemas[0].name == "artifacts"

    @pytest.mark.parametrize(
        "probe_return, schema_name, expected_valid, expected_message_part",
        [
            ((True, 200), None, True, None),
            ((False, 401), None, False, "Invalid JFrog access token"),
            # A 403 at source-create means the token is genuine but not fully scoped — accept it.
            ((False, 403), None, True, None),
            ((False, 403), "builds", False, "admin"),
            ((False, 403), "artifacts", False, "missing the permissions"),
            ((False, 403), "build_promotions", False, "admin"),
            ((False, 404), "xray_violations", False, "Requires JFrog Xray"),
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
            ((False, 403), "build_artifacts", "admin"),
            ((False, 404), "xray_violations", "Requires JFrog Xray"),
            ((False, 404), "artifacts", None),
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
