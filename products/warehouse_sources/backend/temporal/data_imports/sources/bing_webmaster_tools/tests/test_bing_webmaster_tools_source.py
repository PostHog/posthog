import pytest

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.settings import (
    ENDPOINT_CONFIGS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.source import (
    BingWebmasterToolsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bingwebmastertools import (
    BingWebmasterToolsSourceConfig,
)


def _make_inputs(schema_name: str) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=123,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestBingWebmasterToolsSource:
    def setup_method(self):
        self.source = BingWebmasterToolsSource()
        self.team_id = 123
        self.config = BingWebmasterToolsSourceConfig(api_key="test-key")

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O; must opt in so public docs render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["query_stats"])

        assert [schema.name for schema in schemas] == ["query_stats"]

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_for_pipeline_plumbs_schema_name(self, endpoint):
        response = self.source.source_for_pipeline(self.config, _make_inputs(endpoint))

        assert response.name == endpoint
        assert response.primary_keys == ENDPOINT_CONFIGS[endpoint].primary_keys
