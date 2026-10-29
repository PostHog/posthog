from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.linode import LinodeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.linode.source import LinodeSource


class TestLinodeSourceClass:
    def setup_method(self) -> None:
        self.source = LinodeSource()
        self.team_id = 123

    @parameterized.expand(
        [
            # (endpoint, supports_incremental, supports_append)
            # Events are immutable/append-only: offer append but never merge.
            ("events", False, True),
            # Invoices have a genuine server-side date filter: merge-incremental.
            ("invoices", True, True),
            # No server-side filter -> full refresh only.
            ("linodes", False, False),
            ("volumes", False, False),
            ("domains", False, False),
            ("users", False, False),
            ("payments", False, False),
        ]
    )
    def test_schema_sync_modes(self, endpoint: str, supports_incremental: bool, supports_append: bool) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(LinodeSourceConfig(api_token="tok"), self.team_id)}
        assert endpoint in schemas
        schema = schemas[endpoint]
        assert schema.supports_incremental is supports_incremental
        assert schema.supports_append is supports_append

    def test_source_for_pipeline_omits_watermark_when_not_incremental(self) -> None:
        # A full refresh must ignore an old cursor value. Otherwise, the transport adds an
        # X-Filter and limits the results.
        result = SourceDriver(self.source, LinodeSourceConfig(api_token="tok")).run(
            "invoices",
            [ScriptedResponse(json={"page": 1, "pages": 1, "results": 1, "data": [{"id": 1}]})],
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00",
        )

        assert result.raised is None
        assert result.requests[0].headers.get("x-filter") is None
