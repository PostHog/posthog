from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pulumicloud import (
    PulumiCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pulumi_cloud import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.pulumi_cloud.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.pulumi_cloud.source import PulumiCloudSource


class TestPulumiCloudSource:
    def setup_method(self) -> None:
        self.source = PulumiCloudSource()

    def test_get_schemas_returns_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1, names=["stacks"])
        assert [s.name for s in schemas] == ["stacks"]

    @parameterized.expand(
        [
            # audit_logs has a server-side startTime lower bound; stack_updates pages newest-first
            # and stops client-side at the watermark. The snapshot/index endpoints are full refresh.
            ("stacks", False, [], True),
            ("stack_updates", True, ["startTime"], True),
            ("deployments", False, [], True),
            ("audit_logs", True, ["timestamp"], False),
            ("resources", False, [], True),
        ]
    )
    def test_incremental_support_per_endpoint(
        self, endpoint: str, supports_incremental: bool, incremental_fields: list[str], sync_default: bool
    ) -> None:
        schema = next(s for s in self.source.get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is supports_incremental
        # Incremental runs re-pull an overlap window that merge dedupes; append would duplicate it.
        assert schema.supports_append is False
        assert [f["field"] for f in schema.incremental_fields] == incremental_fields
        # audit_logs is tier-gated in Pulumi Cloud; defaulting it on would fail most first syncs.
        assert schema.should_sync_default is sync_default

    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials(self, _name: str, probe_result: bool, expected_ok: bool) -> None:
        config = PulumiCloudSourceConfig(access_token="pul-test", organization="my-org")
        with patch.object(source_module, "validate_pulumi_cloud_credentials", return_value=probe_result):
            ok, error = self.source.validate_credentials(config, team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok
