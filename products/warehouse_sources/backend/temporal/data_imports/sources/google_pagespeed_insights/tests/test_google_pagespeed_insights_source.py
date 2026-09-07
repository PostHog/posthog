import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googlepagespeedinsights import (
    GooglePageSpeedInsightsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_pagespeed_insights.settings import (
    ENDPOINTS,
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

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_get_schemas_supports_append_not_incremental(self, endpoint):
        # The API has no server-side change cursor, so nothing is truly incremental; all tables support
        # append so users can accumulate score snapshots over time.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is True
        assert [f["field"] for f in schemas[endpoint].incremental_fields] == ["analysis_timestamp"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["pagespeed_mobile"])

        assert [schema.name for schema in schemas] == ["pagespeed_mobile"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

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

    def test_transport_timeout_is_retryable_not_terminal(self):
        # A read timeout / connection reset to the API host exhausts `_fetch`'s internal retries and
        # re-raises as a urllib3 `HTTPSConnectionPool(...)` message (key already redacted). It is
        # transient and self-recovering, so it must classify as retryable and never match the
        # auth-failure patterns that would permanently stop the sync.
        error_message = (
            "HTTPSConnectionPool(host='pagespeedonline.googleapis.com', port=443): Max retries exceeded "
            "with url: /pagespeedonline/v5/runPagespeed?url=https%3A%2F%2Fexample.com&strategy=DESKTOP&key=REDACTED "
            "(Caused by ReadTimeoutError(\"HTTPSConnectionPool(host='pagespeedonline.googleapis.com', port=443): "
            'Read timed out. (read timeout=120)"))'
        )

        assert any(pattern in error_message for pattern in self.source.get_retryable_errors())
        assert not any(pattern in error_message for pattern in self.source.get_non_retryable_errors())

    def test_documented_tables_render_without_credentials(self):
        # Exercises the public-docs path: a credential-free placeholder config must list every table.
        tables = self.source.get_documented_tables()

        assert {table["name"] for table in tables} == set(ENDPOINTS)
