from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bugsnag.settings import (
    BUGSNAG_ENDPOINTS,
    BugsnagScope,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bugsnag.source import BugsnagSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bugsnag import (
    BugsnagSourceConfig,
)


def _source_inputs(schema_name: str = "errors") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestBugsnagSource:
    def setup_method(self) -> None:
        self.source = BugsnagSource()
        self.team_id = 1

    @parameterized.expand(
        [
            ("organizations", True),
            ("projects", True),
            ("errors", True),
            ("events", False),
            ("pivots", False),
            ("event_fields", False),
            ("trace_fields", False),
            ("stability_trend", True),
            ("trend", True),
            ("release_groups", True),
            ("pivot_values", False),
            ("error_trend", False),
            ("error_pivot_values", False),
            ("span_groups", True),
            ("span_group_spans", False),
        ]
    )
    def test_should_sync_default(self, endpoint: str, expected_default: bool) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(MagicMock(), team_id=self.team_id)}
        assert schemas[endpoint].should_sync_default is expected_default

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=self.team_id, names=["errors", "projects"])
        assert {s.name for s in schemas} == {"errors", "projects"}

    @parameterized.expand(
        [
            ("organizations", ["id"]),
            ("projects", ["id", "organization_id"]),
            ("collaborators", ["id", "organization_id"]),
            ("errors", ["id", "project_id"]),
            ("event_fields", ["display_id", "project_id"]),
            ("stability_trend", ["project_id", "bucket_start"]),
            ("trend", ["project_id", "from"]),
            ("release_groups", ["id", "project_id"]),
            ("pivot_values", ["project_id", "event_field_display_id", "event_field_value"]),
            ("error_trend", ["project_id", "error_id", "from"]),
            ("error_pivot_values", ["project_id", "error_id", "event_field_display_id", "event_field_value"]),
            ("span_groups", ["id", "project_id"]),
            ("span_group_spans", ["project_id", "span_group_id", "id"]),
        ]
    )
    def test_source_response_primary_keys(self, endpoint: str, expected_keys: list[str]) -> None:
        manager = self.source.get_resumable_source_manager(_source_inputs(endpoint))
        response = self.source.source_for_pipeline(
            BugsnagSourceConfig(auth_token="tok"), manager, _source_inputs(endpoint)
        )
        assert response.primary_keys == expected_keys

    def test_fan_out_children_carry_parent_id_in_primary_key(self) -> None:
        # Fan-out children aggregate rows from every parent, so the parent id injected into each row
        # must be part of the primary key — otherwise per-parent-unique ids collide table-wide and
        # seed duplicate rows that slow every subsequent merge.
        project_scopes = {
            BugsnagScope.PER_PROJECT,
            BugsnagScope.PER_PROJECT_RELEASE_STAGE,
            BugsnagScope.PER_PROJECT_PIVOT,
            BugsnagScope.PER_PROJECT_ERROR,
            BugsnagScope.PER_PROJECT_ERROR_PIVOT,
            BugsnagScope.PER_PROJECT_SPAN_GROUP,
        }
        for config in BUGSNAG_ENDPOINTS.values():
            if config.scope is BugsnagScope.PER_ORG:
                assert "organization_id" in config.primary_keys, config.name
            elif config.scope in project_scopes:
                assert "project_id" in config.primary_keys, config.name

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.bugsnag.com/projects/abc/errors?per_page=100",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.bugsnag.com/user/organizations?per_page=1",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://api.bugsnag.com/projects/abc/errors",
            ),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.bugsnag.com/user/organizations",
            ),
            ("read_timeout", "HTTPSConnectionPool(host='api.bugsnag.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_error_grain_endpoints_bound_their_error_fan_out(self) -> None:
        # Error-grain endpoints cost one request per error and BugSnag exposes no filter to narrow
        # the error list, so an uncapped one would walk every error a project has ever recorded.
        error_scopes = {BugsnagScope.PER_PROJECT_ERROR, BugsnagScope.PER_PROJECT_ERROR_PIVOT}
        error_grain = [c for c in BUGSNAG_ENDPOINTS.values() if c.scope in error_scopes]
        assert error_grain
        for config in error_grain:
            assert config.max_errors_per_project is not None, config.name
