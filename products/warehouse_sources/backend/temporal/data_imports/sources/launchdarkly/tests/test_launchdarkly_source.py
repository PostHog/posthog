import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.launchdarkly import (
    LaunchDarklySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.source import LaunchDarklySource


class TestLaunchDarklySource:
    def setup_method(self):
        self.source = LaunchDarklySource()
        self.team_id = 123
        self.config = LaunchDarklySourceConfig(access_token="api-token")

    @pytest.mark.parametrize(
        "status, schema_name, expected_valid",
        [
            (200, None, True),
            (401, None, False),
            # A valid token may lack scope for an unselected endpoint — accept 403 at source-create.
            (403, None, True),
            # But reject 403 when validating a specific schema.
            (403, "flags", False),
            (500, None, False),
            (None, None, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.source.validate_launchdarkly_credentials"
    )
    def test_validate_credentials_status_mapping(self, mock_validate, status, schema_name, expected_valid):
        mock_validate.return_value = status

        is_valid, _error = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.source.validate_launchdarkly_credentials"
    )
    def test_validate_credentials_probes_projects_for_fanout_schema(self, mock_validate):
        mock_validate.return_value = 200
        self.source.validate_credentials(self.config, self.team_id, schema_name="flags")
        assert mock_validate.call_args.args[1] == "/projects"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.source.validate_launchdarkly_credentials"
    )
    def test_validate_credentials_probes_endpoint_path_for_toplevel_schema(self, mock_validate):
        mock_validate.return_value = 200
        self.source.validate_credentials(self.config, self.team_id, schema_name="members")
        assert mock_validate.call_args.args[1] == "/members"
