import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.settings import EVENTS_ENDPOINT
from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.source import AmplitudeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amplitude import (
    AmplitudeSourceConfig,
)


class TestAmplitudeSource:
    def setup_method(self) -> None:
        self.source = AmplitudeSource()
        self.team_id = 123
        self.config = AmplitudeSourceConfig(api_key="key", secret_key="secret", region="us")

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=[EVENTS_ENDPOINT])
        assert len(schemas) == 1
        assert schemas[0].name == EVENTS_ENDPOINT

    @time_machine.travel("2026-06-04 12:00:00", tick=False)
    def test_source_for_pipeline_drops_last_value_on_full_refresh(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            EVENTS_ENDPOINT,
            always(ScriptedResponse(status=404)),
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        # When the user isn't running incrementally, no watermark should leak through.
        assert result.requests[0].param("start") == "20260505T10"
        assert result.raised is None
