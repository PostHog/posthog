from datetime import UTC, datetime

from unittest import mock

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

    def test_connection_host_fields_includes_project_slugs(self):
        # The token is sent to circleci.com scoped to <project_slugs>, so retargeting the
        # project slugs must force re-entry of the token.
        assert self.source.connection_host_fields == ["project_slugs"]

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_only_workflow_runs_advertises_incremental(self, endpoint):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        expected = endpoint == "workflow_runs"

        # Only the runs endpoint has a server-side timestamp filter (start-date); the
        # aggregate endpoints are rolling-window snapshots and stay full refresh.
        assert schemas[endpoint].supports_incremental is expected
        assert bool(INCREMENTAL_FIELDS.get(endpoint)) is expected

    def test_org_summary_is_deselected_by_default(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["org_summary_metrics"].should_sync_default is False
        assert schemas["workflow_runs"].should_sync_default is True

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["flaky_tests"])
        assert [schema.name for schema in schemas] == ["flaky_tests"]

        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://circleci.com/api/v2/insights/gh/a/b/workflows", True),
            ("403 Client Error: Forbidden for url: https://circleci.com/api/v2/insights/gh/a/summary", True),
            ("404 Client Error: Not Found for url: https://circleci.com/api/v2/insights/gh/a/b/flaky-tests", True),
            ("401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers", False),
            ("500 Server Error for url: https://circleci.com/api/v2/insights/gh/a/b/workflows", False),
            ("429 Client Error: Too Many Requests for url: https://circleci.com/api/v2/insights", False),
        ]
    )
    def test_non_retryable_errors_match_only_permanent_failures(self, observed_error, should_match):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors) is should_match

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.circleci_insights.source.circleci_insights_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "workflow_runs"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = datetime(2026, 7, 1, tzinfo=UTC)
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "circle-token"
        assert kwargs["project_slugs_raw"] == self.config.project_slugs
        assert kwargs["endpoint"] == "workflow_runs"
        assert kwargs["reporting_window"] == "last-90-days"
        assert kwargs["all_branches"] is True
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == datetime(2026, 7, 1, tzinfo=UTC)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.circleci_insights.source.circleci_insights_source"
    )
    def test_source_for_pipeline_drops_cursor_on_full_refresh(self, mock_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "workflow_runs"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = datetime(2026, 7, 1, tzinfo=UTC)

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None
