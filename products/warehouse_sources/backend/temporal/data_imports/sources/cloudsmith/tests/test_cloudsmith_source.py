import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.settings import CLOUDSMITH_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.source import CloudsmithSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudsmith import (
    CloudsmithSourceConfig,
)


class TestCloudsmithSource:
    def setup_method(self) -> None:
        self.source = CloudsmithSource()
        self.team_id = 123
        self.config = CloudsmithSourceConfig(api_key="cloudsmith-key", workspace="acme")

    @pytest.mark.parametrize(
        "endpoint",
        ["packages", "entitlements", "webhooks"],
    )
    def test_fanout_primary_keys_include_parent_repository(self, endpoint) -> None:
        # These tables aggregate rows from every repository in the workspace, and Cloudsmith
        # only documents `slug_perm` as unique within a repository - a key without the parent
        # would seed duplicate rows that every later merge multi-matches.
        assert CLOUDSMITH_ENDPOINTS[endpoint].primary_key == ["repository_slug", "slug_perm"]
