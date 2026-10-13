import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googlepagespeedinsights import (
    GooglePageSpeedInsightsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_pagespeed_insights.source import (
    GooglePageSpeedInsightsSource,
)


class TestGooglePageSpeedInsightsSource:
    def setup_method(self):
        self.source = GooglePageSpeedInsightsSource()
        self.team_id = 123
        self.config = GooglePageSpeedInsightsSourceConfig(api_key="test-key", urls="https://posthog.com")

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O — must opt in so public docs render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["pagespeed_mobile"])

        assert [schema.name for schema in schemas] == ["pagespeed_mobile"]

    @pytest.mark.parametrize(
        "error_message",
        [
            "PageSpeed Insights API error (retryable): status=429",
            "PageSpeed Insights API error (retryable): status=500",
        ],
    )
    def test_retryable_errors_match_exhausted_backoff(self, error_message):
        # `_fetch` already retries 429/5xx internally with backoff; once those attempts are
        # exhausted, this must stay classified as retryable so it doesn't get tracked as noise.
        retryable_errors = self.source.get_retryable_errors()
        assert any(pattern in error_message for pattern in retryable_errors)
