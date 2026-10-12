from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.railway import (
    RailwaySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.railway.source import RailwaySource


class TestRailwaySource:
    def setup_method(self):
        self.source = RailwaySource()
        self.team_id = 123
        self.config = RailwaySourceConfig(api_token="railway-token")

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
