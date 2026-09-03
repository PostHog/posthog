from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.railway import (
    RailwaySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.railway.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.railway.source import RailwaySource


class TestRailwaySource:
    def setup_method(self):
        self.source = RailwaySource()
        self.team_id = 123
        self.config = RailwaySourceConfig(api_token="railway-token")

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Railway has no server-side time filters; only deployments (newest-first, watermark-stop)
        # can sync incrementally.
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        assert incremental == {"deployments"}

    def test_deployments_schema_incremental_settings(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        deployments = schemas["deployments"]
        assert [f["field"] for f in deployments.incremental_fields] == ["createdAt"]
        # Deployment rows mutate (status) — merge-only, with a lookback so recent statuses settle.
        assert deployments.supports_append is False
        assert deployments.default_incremental_lookback_seconds == 86400

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["deployments", "nope"])

        assert [schema.name for schema in schemas] == ["deployments"]

    @parameterized.expand(
        [
            ("rate_limit", "Railway API error (retryable): status=429, retry_after=60"),
            ("server_error", "Railway API error (retryable): status=500, retry_after=None"),
            (
                "problem_processing_request",
                "Railway API error (retryable): Problem processing request. GraphQL errors: Problem processing request",
            ),
            (
                "connection_error",
                "HTTPSConnectionPool(host='backboard.railway.com', port=443): Max retries exceeded with url: "
                '/graphql/v2 (Caused by ReadTimeoutError("HTTPSConnectionPool'
                "(host='backboard.railway.com', port=443): Read timed out. (read timeout=60)\"))",
            ),
            (
                "read_timeout",
                "HTTPSConnectionPool(host='backboard.railway.com', port=443): Read timed out. (read timeout=60)",
            ),
        ]
    )
    def test_retryable_errors_match_transient_failures(self, _name, observed_error):
        # `_execute` already retries these in-process; once that budget exhausts, this keeps the
        # benign, self-recovering failure out of error tracking (see the ReadTimeout that used to
        # slip through and get reported as a tracked exception).
        retryable_errors = self.source.get_retryable_errors()
        assert any(key in observed_error for key in retryable_errors)
