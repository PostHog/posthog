import pytest

import structlog

from products.warehouse_sources.sources.bing_webmaster_tools._config import BingWebmasterToolsSourceConfig
from products.warehouse_sources.sources.bing_webmaster_tools.settings import ENDPOINT_CONFIGS, ENDPOINTS
from products.warehouse_sources.sources.bing_webmaster_tools.source import BingWebmasterToolsSource
from products.warehouse_sources.sources.sdk import SourceInputs
from products.warehouse_sources.sources.sdk.testing import error_message_matches


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

    @pytest.mark.parametrize("fault", ["ThrottleUser", "ThrottleIP"])
    def test_throttle_fault_is_retryable_not_disabling(self, fault):
        # A rate-limit fault must keep Temporal retrying the activity (it is not a permanent
        # account/credential problem) and must stay out of error tracking as noise.
        error_message = f"Bing Webmaster Tools GetUserSites failed with status 400: ERROR!!! {fault}"

        assert error_message_matches(error_message, self.source.get_retryable_errors())
        assert not error_message_matches(error_message, self.source.get_non_retryable_errors())

    @pytest.mark.parametrize("fault", ["ThrottleUser", "ThrottleIP"])
    def test_throttle_fault_gets_clear_message_when_retries_run_out(self, fault):
        raised = f"Bing Webmaster Tools GetQueryStats failed with status 400: ERROR!!! {fault}"

        messages = [
            message
            for key, message in self.source.get_retry_exhausted_errors().items()
            if error_message_matches(raised, [key])
        ]

        assert len(messages) == 1
        assert "rate limit" in messages[0]
        assert "Throttle" not in messages[0]
        assert "400" not in messages[0]
        assert error_message_matches(raised, self.source.get_retryable_errors())

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_for_pipeline_plumbs_schema_name(self, endpoint):
        response = self.source.source_for_pipeline(self.config, _make_inputs(endpoint))

        assert response.name == endpoint
        assert response.primary_keys == ENDPOINT_CONFIGS[endpoint].primary_keys
