from types import SimpleNamespace
from typing import cast

from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.settings import (
    COHORTS_ENDPOINT,
    EVENTS_ENDPOINT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.source import AmplitudeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amplitude import (
    AmplitudeSourceConfig,
)


class TestAmplitudeSource:
    def setup_method(self):
        self.source = AmplitudeSource()
        self.team_id = 123
        self.config = AmplitudeSourceConfig(api_key="key", secret_key="secret", region="us")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=[EVENTS_ENDPOINT])
        assert len(schemas) == 1
        assert schemas[0].name == EVENTS_ENDPOINT

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.source.amplitude_source")
    def test_source_for_pipeline_drops_last_value_on_full_refresh(self, mock_amplitude_source):
        mock_amplitude_source.return_value = SimpleNamespace(name=COHORTS_ENDPOINT)
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = SimpleNamespace(
            schema_name=COHORTS_ENDPOINT,
            team_id=self.team_id,
            job_id="job-2",
            logger=mock.MagicMock(),
            should_use_incremental_field=False,
            incremental_field=None,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        self.source.source_for_pipeline(self.config, manager, cast(SourceInputs, inputs))

        # When the user isn't running incrementally, no watermark should leak through.
        assert mock_amplitude_source.call_args.kwargs["db_incremental_field_last_value"] is None
