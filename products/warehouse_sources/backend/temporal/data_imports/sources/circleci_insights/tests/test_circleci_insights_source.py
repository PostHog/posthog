from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.circleci_insights.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.circleci_insights.source import (
    CircleciInsightsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.circleciinsights import (
    CircleciInsightsSourceConfig,
)


class TestCircleciInsightsSource:
    def setup_method(self):
        self.source = CircleciInsightsSource()
        self.team_id = 123
        self.config = CircleciInsightsSourceConfig(
            api_token="circle-token",
            project_slugs="gh/posthog/posthog, gh/posthog/posthog.com",
            reporting_window="last-90-days",
            branch_scope="all_branches",
        )

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_only_workflow_runs_advertises_incremental(self, endpoint):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        expected = endpoint == "workflow_runs"

        # Only the runs endpoint has a server-side timestamp filter (start-date); the
        # aggregate endpoints are rolling-window snapshots and stay full refresh.
        assert schemas[endpoint].supports_incremental is expected
        assert bool(INCREMENTAL_FIELDS.get(endpoint)) is expected
