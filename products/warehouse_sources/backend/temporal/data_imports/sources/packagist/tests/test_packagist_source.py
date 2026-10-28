from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.packagist import (
    PackagistSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.packagist.source import PackagistSource


class TestPackagistSource:
    def setup_method(self):
        self.source = PackagistSource()
        self.team_id = 123
        self.config = PackagistSourceConfig(packages="monolog/monolog\nsymfony/console")

    def test_source_for_pipeline_drops_watermark_when_not_incremental(self):
        # A stale watermark from a previous incremental run must not leak into a full refresh.
        result = SourceDriver(self.source, self.config).run(
            "downloads",
            [
                ScriptedResponse(json={"labels": [], "values": {}}),
                ScriptedResponse(json={"labels": [], "values": {}}),
            ],
            db_incremental_field_last_value="2026-07-01",
        )

        assert result.raised is None
        assert result.queries == [{"average": ("daily",)}, {"average": ("daily",)}]
