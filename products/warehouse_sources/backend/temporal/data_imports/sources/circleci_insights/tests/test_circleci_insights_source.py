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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
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

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_only_start_date_endpoints_advertise_incremental(self, endpoint):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        expected = endpoint in ("workflow_runs", "job_timeseries")

        # Only the endpoints with a server-side timestamp filter (start-date) can sync
        # incrementally; the aggregate endpoints are rolling-window snapshots and stay
        # full refresh.
        assert schemas[endpoint].supports_incremental is expected
        assert bool(INCREMENTAL_FIELDS.get(endpoint)) is expected

    @parameterized.expand(
        [
            ("404 Client Error: Not Found for url: https://circleci.com/api/v2/insights/gh/a/b/flaky-tests", True),
            ("401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers", False),
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

    def test_source_for_pipeline_drops_cursor_on_full_refresh(self):
        result = SourceDriver(self.source, self.config).run(
            "workflow_runs",
            route(
                {
                    "/api/v2/insights/gh/posthog/posthog/workflows": [
                        ScriptedResponse(json={"items": [{"name": "ci"}], "next_page_token": None})
                    ],
                    "/api/v2/insights/gh/posthog/posthog/workflows/ci": [
                        ScriptedResponse(json={"items": [], "next_page_token": None})
                    ],
                    "/api/v2/insights/gh/posthog/posthog.com/workflows": [
                        ScriptedResponse(json={"items": [], "next_page_token": None})
                    ],
                }
            ),
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 7, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[1].param("start-date") is None
