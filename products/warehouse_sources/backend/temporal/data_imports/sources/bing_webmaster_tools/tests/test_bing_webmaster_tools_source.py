import pytest

import structlog

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.settings import (
    ENDPOINT_CONFIGS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.source import (
    BingWebmasterToolsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bingwebmastertools import (
    BingWebmasterToolsSourceConfig,
)

_STATS_ENDPOINTS = [name for name, endpoint in ENDPOINT_CONFIGS.items() if endpoint.per_site]


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

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "BingWebmasterTools"
        assert config.label == "Bing Webmaster Tools"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # `unreleasedSource` hides the connector from users entirely; a finished source must not
        # carry it.
        assert not config.unreleasedSource

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O; must opt in so public docs render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", _STATS_ENDPOINTS)
    def test_stats_schemas_are_merge_only(self, endpoint):
        # Every sync refetches the same ~6-month window, so append would duplicate it; merge on
        # the primary key is the only safe incremental method.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas[endpoint].supports_incremental is True
        assert schemas[endpoint].supports_append is False
        assert [field["field"] for field in schemas[endpoint].incremental_fields] == ["date"]

    def test_sites_schema_is_full_refresh_only(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["sites"].supports_incremental is False
        assert schemas["sites"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["query_stats"])

        assert [schema.name for schema in schemas] == ["query_stats"]

    @pytest.mark.parametrize(
        "error_message",
        [
            "Bing Webmaster Tools GetUserSites failed with status 400: InvalidApiKey",
            "Bing Webmaster Tools GetQueryStats failed with status 400: NotAuthorized",
            "401 Client Error: Unauthorized for url: https://ssl.bing.com/webmaster/api.svc/json/GetUserSites?apikey=REDACTED",
            "400 Client Error: Bad Request for url: https://ssl.bing.com/webmaster/api.svc/json/GetQueryStats?apikey=REDACTED",
        ],
    )
    def test_non_retryable_errors_cover_credential_failures(self, error_message):
        assert error_message_matches(error_message, self.source.get_non_retryable_errors())

    def test_throttling_faults_stay_retryable(self):
        # A throttling fault must be retried by Temporal, not permanently fail the sync.
        message = "Bing Webmaster Tools GetQueryStats failed with status 429: ThrottleUser"

        assert not error_message_matches(message, self.source.get_non_retryable_errors())

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_for_pipeline_plumbs_schema_name(self, endpoint):
        response = self.source.source_for_pipeline(self.config, _make_inputs(endpoint))

        assert response.name == endpoint
        assert response.primary_keys == ENDPOINT_CONFIGS[endpoint].primary_keys
