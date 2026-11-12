from unittest import mock

from products.warehouse_sources.sources.spot_io._config import SpotIoSourceConfig
from products.warehouse_sources.sources.spot_io.source import SpotIoSource


class TestSpotIoSource:
    def setup_method(self) -> None:
        self.source = SpotIoSource()
        self.team_id = 123
        self.config = SpotIoSourceConfig(api_token="spot-token")

    @mock.patch("products.warehouse_sources.sources.spot_io.source.spot_io_source")
    def test_source_for_pipeline_omits_watermark_when_not_incremental(
        self, mock_spot_io_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "elastigroups"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_spot_io_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None

    def test_get_schemas_events_are_merge_only(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        events = schemas["elastigroup_events"]
        assert events.supports_incremental is True
        assert events.supports_append is False
        assert [f["field"] for f in events.incremental_fields] == ["createdAt"]

        for name, schema in schemas.items():
            if name != "elastigroup_events":
                assert schema.supports_incremental is False
                assert schema.supports_append is False
