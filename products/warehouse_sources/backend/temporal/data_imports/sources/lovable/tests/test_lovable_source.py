from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lovable import (
    LovableSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lovable.lovable import LovableResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lovable.source import LovableSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.lovable.source"

DATED_ENDPOINTS = [
    "Workspaces",
    "Projects",
    "WorkspaceMembers",
    "ProjectSecurityScans",
    "ProjectPiiLabels",
    "WorkspaceGroups",
    "ProjectSecurityScanFindings",
    "ProjectAnalytics",
    "WorkspaceAnalytics",
]


class TestLovableSource:
    def setup_method(self) -> None:
        self.source = LovableSource()
        self.config = LovableSourceConfig(api_key="lov_key")

    @parameterized.expand(
        [
            (
                "v1",
                "v1",
                [
                    "Workspaces",
                    "Projects",
                    "WorkspaceMembers",
                    "WorkspaceCreditHistory",
                    "ProjectCollaborators",
                    "ProjectSecurityScans",
                    "ProjectPiiLabels",
                ],
            ),
            ("dated", "2026-09-11", DATED_ENDPOINTS),
            ("unpinned_uses_the_default", None, DATED_ENDPOINTS),
        ]
    )
    def test_get_schemas_lists_the_pinned_versions_endpoints(
        self, _name: str, api_version: str | None, expected: list[str]
    ) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, api_version=api_version)

        assert [schema.name for schema in schemas] == expected
        # Only the analytics endpoints take a timestamp filter, so nothing else can sync incrementally.
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        assert incremental == {"ProjectAnalytics", "WorkspaceAnalytics"} & set(expected)
        # Each analytics run rereads the watermark day, which append would duplicate.
        assert all(not schema.supports_append for schema in schemas)

    @parameterized.expand(
        [
            ("402", "402 Client Error: Payment Required for url: https://api.lovable.dev/v1/workspaces/ws-1/members"),
        ]
    )
    def test_non_retryable_errors_match_permanent_failures(self, _name: str, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @parameterized.expand(
        [
            ("server_error", "HTTP 503 for https://api.lovable.dev/v1/workspaces"),
            ("timeout", "Request timed out (ConnectTimeout) for https://api.lovable.dev/v1/workspaces"),
        ]
    )
    def test_non_retryable_errors_do_not_match_transient_failures(self, _name: str, other_error: str) -> None:
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_resumable_manager_is_bound_to_the_resume_config(self) -> None:
        inputs = mock.MagicMock()
        inputs.team_id = 1
        inputs.job_id = "job-1"

        manager = self.source.get_resumable_source_manager(inputs)

        assert manager._data_class is LovableResumeConfig

    @parameterized.expand([("pinned_v1", "v1", "v1"), ("unpinned_uses_the_default", None, "2026-09-11")])
    @mock.patch(f"{SOURCE_MODULE}.lovable_source")
    def test_source_for_pipeline_plumbs_arguments(
        self, _name: str, pinned: str | None, expected_version: str, mock_lovable_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "ProjectAnalytics"
        inputs.api_version = pinned
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-10-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_lovable_source.call_args.kwargs
        assert kwargs == {
            "api_key": "lov_key",
            "api_version": expected_version,
            "endpoint": "ProjectAnalytics",
            "resumable_source_manager": manager,
            "should_use_incremental_field": True,
            "db_incremental_field_last_value": "2026-10-01T00:00:00Z",
        }

    @mock.patch(f"{SOURCE_MODULE}.validate_lovable_credentials", return_value=(True, None))
    def test_validate_credentials_resolves_the_api_version(self, mock_validate: mock.MagicMock) -> None:
        assert self.source.validate_credentials(self.config, team_id=1) == (True, None)
        assert mock_validate.call_args.args == ("lov_key", "2026-09-11")

    @mock.patch(f"{SOURCE_MODULE}.check_endpoint_permissions", return_value={"Projects": None})
    def test_endpoint_permissions_delegate_to_the_probe(self, mock_check: mock.MagicMock) -> None:
        assert self.source.get_endpoint_permissions(self.config, team_id=1, endpoints=["Projects"]) == {
            "Projects": None
        }
        assert mock_check.call_args.args == ("lov_key", "2026-09-11", ["Projects"])
