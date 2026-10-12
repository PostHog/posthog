from types import SimpleNamespace
from typing import cast

from unittest import mock

from sources.helicone._config import HeliconeSourceConfig
from sources.helicone.settings import REQUESTS_ENDPOINT, SESSIONS_ENDPOINT
from sources.helicone.source import HeliconeSource
from sources.sdk import ResumableSourceManager, SourceInputs


class TestHeliconeSource:
    def setup_method(self):
        self.source = HeliconeSource()
        self.team_id = 123
        self.config = HeliconeSourceConfig(api_key="sk-helicone-key", region="us")

    def test_region_is_a_connection_host_field(self):
        # Changing the regional host must force re-entry of the API key (credential retargeting guard).
        assert self.source.connection_host_fields == ["region"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=[REQUESTS_ENDPOINT])
        assert [schema.name for schema in schemas] == [REQUESTS_ENDPOINT]

    @mock.patch("sources.helicone.source.helicone_source")
    def test_source_for_pipeline_drops_last_value_on_full_refresh(self, mock_helicone_source):
        mock_helicone_source.return_value = SimpleNamespace(name=SESSIONS_ENDPOINT)
        inputs = SimpleNamespace(
            schema_name=SESSIONS_ENDPOINT,
            team_id=self.team_id,
            job_id="job-2",
            logger=mock.MagicMock(),
            should_use_incremental_field=False,
            incremental_field=None,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        self.source.source_for_pipeline(
            self.config, mock.MagicMock(spec=ResumableSourceManager), cast(SourceInputs, inputs)
        )

        # When the user isn't running incrementally, no watermark should leak through.
        assert mock_helicone_source.call_args.kwargs["db_incremental_field_last_value"] is None
