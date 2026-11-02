from products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms.source import CanvasLmsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.canvaslms import (
    CanvasLmsSourceConfig,
)


class TestCanvasLmsSource:
    def setup_method(self):
        self.source = CanvasLmsSource()
        self.team_id = 123
        self.config = CanvasLmsSourceConfig(canvas_domain="yourschool.instructure.com", account_id="1", api_key="tok")

    def test_connection_host_fields(self):
        assert self.source.connection_host_fields == ["canvas_domain", "account_id"]

    def test_submissions_is_merge_only(self):
        # Submissions mutate in place (grades change), so append-only would duplicate rows.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["submissions"].supports_incremental is True
        assert schemas["submissions"].supports_append is False
