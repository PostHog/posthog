import pytest

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

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

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Cloudsmith"
        assert config.label == "Cloudsmith"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # The source ships visible: unreleasedSource hides the connector from every user.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/cloudsmith.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/cloudsmith"

    def test_get_schemas_incremental_semantics(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        # Only the packages list has a server-side time filter (`query=uploaded:>=...`);
        # everything else would have to fetch every page anyway, so it stays full refresh.
        for name in ("repositories", "entitlements", "webhooks", "vulnerabilities", "audit_log", "members", "teams"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []

        # packages is merge-only: the `uploaded` bound is inclusive, so each run re-reads the
        # boundary packages and append mode would duplicate them.
        assert schemas["packages"].supports_incremental is True
        assert schemas["packages"].supports_append is False
        assert [f["field"] for f in schemas["packages"].incremental_fields] == ["uploaded_at"]

    @pytest.mark.parametrize(
        "endpoint",
        ["packages", "entitlements", "webhooks"],
    )
    def test_fanout_primary_keys_include_parent_repository(self, endpoint) -> None:
        # These tables aggregate rows from every repository in the workspace, and Cloudsmith
        # only documents `slug_perm` as unique within a repository - a key without the parent
        # would seed duplicate rows that every later merge multi-matches.
        assert CLOUDSMITH_ENDPOINTS[endpoint].primary_key == ["repository_slug", "slug_perm"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.cloudsmith.io/v1/repos/acme/",
            "403 Client Error: Forbidden for url: https://api.cloudsmith.io/v1/packages/acme/prod/",
            "402 Client Error: Payment Required for url: https://api.cloudsmith.io/v1/audit-log/acme/",
        ],
    )
    def test_non_retryable_errors_match_permanent_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_non_retryable_errors_ignore_transient_failures(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(
            key in "500 Server Error for url: https://api.cloudsmith.io/v1/repos/acme/" for key in non_retryable
        )
