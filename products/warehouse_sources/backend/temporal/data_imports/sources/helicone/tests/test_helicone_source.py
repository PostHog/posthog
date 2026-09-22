from types import SimpleNamespace
from typing import cast

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.helicone import (
    HeliconeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.helicone.settings import (
    ENDPOINTS,
    PROMPTS_ENDPOINT,
    REQUESTS_ENDPOINT,
    SESSIONS_ENDPOINT,
    USERS_ENDPOINT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.helicone.source import HeliconeSource

FULL_REFRESH_ENDPOINTS = [SESSIONS_ENDPOINT, USERS_ENDPOINT, PROMPTS_ENDPOINT]


class TestHeliconeSource:
    def setup_method(self):
        self.source = HeliconeSource()
        self.team_id = 123
        self.config = HeliconeSourceConfig(api_key="sk-helicone-key", region="us")

    def test_region_is_a_connection_host_field(self):
        # Changing the regional host must force re-entry of the API key (credential retargeting guard).
        assert self.source.connection_host_fields == ["region"]

    @pytest.mark.parametrize("status_text", ["401 Client Error: Unauthorized", "403 Client Error: Forbidden"])
    @pytest.mark.parametrize("host", ["https://api.helicone.ai", "https://eu.api.helicone.ai"])
    def test_non_retryable_errors_cover_both_regional_hosts(self, status_text, host):
        assert f"{status_text} for url: {host}" in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_every_endpoint(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_requests_endpoint_advertises_incremental(self):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == REQUESTS_ENDPOINT)
        assert schema.supports_incremental is True
        assert schema.supports_append is True
        assert {field["field"] for field in schema.incremental_fields} == {"request_created_at"}

    @pytest.mark.parametrize("endpoint", FULL_REFRESH_ENDPOINTS)
    def test_full_refresh_endpoints_do_not_advertise_incremental(self, endpoint):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=[REQUESTS_ENDPOINT])
        assert [schema.name for schema in schemas] == [REQUESTS_ENDPOINT]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.helicone.source.helicone_source")
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
