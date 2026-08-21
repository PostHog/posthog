from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.source import DagsterCloudSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.dagster_cloud.source"


class TestDagsterCloudSchemas:
    def test_schema_incremental_flags(self) -> None:
        schemas = {s.name: s for s in DagsterCloudSource().get_schemas(MagicMock(), team_id=1)}
        assert set(schemas) == {"runs", "backfills", "assets"}
        assert schemas["runs"].supports_incremental is True
        assert {f["field"] for f in schemas["runs"].incremental_fields} == {"updateTime", "creationTime"}
        assert schemas["backfills"].supports_incremental is False
        assert schemas["assets"].supports_incremental is False
        # Runs mutate after creation, so append-only would duplicate rows — merge only, everywhere.
        assert all(s.supports_append is False for s in schemas.values())

    def test_names_filter(self) -> None:
        schemas = DagsterCloudSource().get_schemas(MagicMock(), team_id=1, names=["runs"])
        assert [s.name for s in schemas] == ["runs"]
