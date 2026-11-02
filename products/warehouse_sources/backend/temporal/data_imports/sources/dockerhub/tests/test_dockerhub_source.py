from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.source import DockerhubSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dockerhub import (
    DockerhubSourceConfig,
)


class TestDockerhubSource:
    def setup_method(self) -> None:
        self.source = DockerhubSource()
        self.team_id = 123
        self.config = DockerhubSourceConfig(username="tom", personal_access_token="dckr_pat_token")

    def test_namespace_is_a_connection_host_field(self) -> None:
        # The stored token pulls data from whatever namespace is configured, so changing it must force
        # secret re-entry — otherwise an editor could retarget the preserved token at another org.
        assert self.source.connection_host_fields == ["namespace"]

    def test_org_scoped_endpoints_report_why_they_are_unavailable(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.source.check_endpoint_access",
            return_value=dict.fromkeys(ENDPOINTS),
        ) as probe:
            self.source.get_endpoint_permissions(self.config, self.team_id, list(ENDPOINTS))

        # A blank namespace means the user's own, so the probe must run against the username.
        assert probe.call_args.args == ("tom", "dckr_pat_token", "tom", list(ENDPOINTS))

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.source.dockerhub_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "repositories"
        manager = mock.MagicMock()
        config = DockerhubSourceConfig(username="tom", personal_access_token="dckr_pat_token", namespace="my-org")

        self.source.source_for_pipeline(config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["username"] == "tom"
        assert kwargs["personal_access_token"] == "dckr_pat_token"
        assert kwargs["namespace"] == "my-org"
        assert kwargs["endpoint"] == "repositories"
        assert kwargs["resumable_source_manager"] is manager
