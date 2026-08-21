import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.source import CoverallsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coveralls import (
    CoverallsSourceConfig,
)


class TestCoverallsSource:
    def setup_method(self):
        self.source = CoverallsSource()
        self.team_id = 123
        self.config = CoverallsSourceConfig(repositories="acme/widgets\nacme/gadgets", service="github")

    @pytest.mark.parametrize(
        "api_token, expected_reason",
        [
            (None, "Requires a personal API token from your Coveralls account settings."),
            ("tok", None),
        ],
    )
    def test_endpoint_permissions_gate_repositories_on_token(self, api_token, expected_reason):
        config = CoverallsSourceConfig(repositories="acme/widgets", service="github", api_token=api_token)

        permissions = self.source.get_endpoint_permissions(config, self.team_id, list(ENDPOINTS))

        assert permissions["builds"] is None
        assert permissions["repositories"] == expected_reason
