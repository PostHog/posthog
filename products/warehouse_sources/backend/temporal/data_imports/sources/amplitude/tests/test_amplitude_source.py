from types import SimpleNamespace
from typing import cast

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.settings import (
    ANNOTATIONS_ENDPOINT,
    COHORTS_ENDPOINT,
    ENDPOINTS,
    EVENTS_ENDPOINT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.source import AmplitudeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amplitude import (
    AmplitudeSourceConfig,
)

FULL_REFRESH_ENDPOINTS = [COHORTS_ENDPOINT, ANNOTATIONS_ENDPOINT]


class TestAmplitudeSource:
    def setup_method(self):
        self.source = AmplitudeSource()
        self.team_id = 123
        self.config = AmplitudeSourceConfig(api_key="key", secret_key="secret", region="us")

    @pytest.mark.parametrize(
        "expected_key",
        ["401 Client Error: Unauthorized", "403 Client Error: Forbidden", "Invalid API Key"],
    )
    def test_non_retryable_errors_includes_auth_keys(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_every_endpoint(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_events_endpoint_advertises_incremental(self):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == EVENTS_ENDPOINT)
        assert schema.supports_incremental is True
        assert schema.supports_append is True
        assert {field["field"] for field in schema.incremental_fields} == {"server_upload_time"}
        assert schema.description == "Only syncs the last 30 days on initial sync"

    @pytest.mark.parametrize("endpoint", FULL_REFRESH_ENDPOINTS)
    def test_full_refresh_endpoints_do_not_advertise_incremental(self, endpoint):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=[EVENTS_ENDPOINT])
        assert len(schemas) == 1
        assert schemas[0].name == EVENTS_ENDPOINT

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

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
