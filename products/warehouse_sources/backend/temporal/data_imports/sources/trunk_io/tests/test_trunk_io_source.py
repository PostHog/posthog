import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trunkio import (
    TrunkIoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.source import TrunkIoSource


def _make_inputs(schema_name: str, **overrides) -> SourceInputs:
    defaults: dict = {
        "schema_name": schema_name,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestTrunkIoSource:
    def setup_method(self):
        self.source = TrunkIoSource()
        self.team_id = 123
        self.config = TrunkIoSourceConfig(
            api_token="test-token",
            org_url_slug="my-org",
            repo_host="github.com",
            repo_owner="my-org",
            repo_name="my-repo",
            merge_queue_target_branch="main",
        )

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static endpoint catalog with no I/O, so it must be safe for public docs.
        assert self.source.lists_tables_without_credentials is True

    def test_validate_credentials_delegates_with_repo(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.source.validate_trunk_io_credentials"
        ) as mock_validate:
            mock_validate.return_value = (True, None)
            result = self.source.validate_credentials(self.config, self.team_id)

        assert result == (True, None)
        (api_token, org_url_slug, repo), _ = mock_validate.call_args.args, mock_validate.call_args.kwargs
        assert api_token == "test-token"
        assert org_url_slug == "my-org"
        assert repo.host == "github.com"
        assert repo.owner == "my-org"
        assert repo.name == "my-repo"

    def test_new_sources_default_to_v2(self):
        assert self.source.supported_versions == ("v1", "v2")
        assert self.source.default_version == "v2"

    @parameterized.expand(
        [
            ("v1", "v1", ["UnhealthyTests", "QuarantinedTests", "FailingTests", "MergeQueuePullRequests"]),
            (
                "v2",
                "v2",
                [
                    "UnhealthyTests",
                    "QuarantinedTests",
                    "FailingTests",
                    "MergeQueuePullRequests",
                    "TestCollections",
                    "Tests",
                ],
            ),
            (
                "unpinned",
                None,
                [
                    "UnhealthyTests",
                    "QuarantinedTests",
                    "FailingTests",
                    "MergeQueuePullRequests",
                    "TestCollections",
                    "Tests",
                ],
            ),
        ]
    )
    def test_get_schemas_lists_tables_for_pinned_version(
        self, _label: str, api_version: str | None, expected: list[str]
    ):
        schemas = self.source.get_schemas(self.config, self.team_id, api_version=api_version)
        assert [s.name for s in schemas] == expected

    @parameterized.expand(
        [
            ("UnhealthyTests", "unhealthy_tests", "v1"),
            ("QuarantinedTests", "quarantined_tests", "v1"),
            ("FailingTests", "failing_tests", "v1"),
            ("MergeQueuePullRequests", "merge_queue_pull_requests", "v1"),
            ("UnhealthyTests", "unhealthy_tests", "v2"),
            ("QuarantinedTests", "quarantined_tests", "v2"),
            ("FailingTests", "failing_tests", "v2"),
            ("MergeQueuePullRequests", "merge_queue_pull_requests", "v2"),
            ("TestCollections", "list_test_collections", "v2"),
            ("Tests", "list_tests", "v2"),
        ]
    )
    def test_source_for_pipeline_dispatches_to_expected_transport(
        self, schema_name: str, transport_fn: str, api_version: str
    ):
        inputs = _make_inputs(schema_name, api_version=api_version)
        manager = MagicMock(spec=ResumableSourceManager)

        with patch(
            f"products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.source.{transport_fn}"
        ) as mock_transport:
            mock_transport.return_value = iter([])
            response = self.source.source_for_pipeline(self.config, manager, inputs)

        mock_transport.assert_called_once()
        assert response.name == schema_name

    @parameterized.expand(
        [
            ("unknown", "NotARealEndpoint", "v2"),
            ("v2_table_on_v1_pin", "TestCollections", "v1"),
            ("v2_tests_on_v1_pin", "Tests", "v1"),
        ]
    )
    def test_source_for_pipeline_rejects_tables_the_pin_does_not_serve(
        self, _label: str, schema_name: str, api_version: str
    ):
        inputs = _make_inputs(schema_name, api_version=api_version)
        manager = MagicMock(spec=ResumableSourceManager)

        with pytest.raises(ValueError):
            self.source.source_for_pipeline(self.config, manager, inputs)

    @parameterized.expand(
        [
            ("UnhealthyTests", ["id"]),
            ("QuarantinedTests", ["name", "parent", "file", "classname", "variant"]),
            ("FailingTests", ["id"]),
            ("MergeQueuePullRequests", ["id"]),
            ("TestCollections", ["id"]),
            ("Tests", ["id"]),
        ]
    )
    def test_source_for_pipeline_primary_keys(self, schema_name: str, expected_keys: list[str]):
        inputs = _make_inputs(schema_name)
        manager = MagicMock(spec=ResumableSourceManager)
        transport_fn = {
            "UnhealthyTests": "unhealthy_tests",
            "QuarantinedTests": "quarantined_tests",
            "FailingTests": "failing_tests",
            "MergeQueuePullRequests": "merge_queue_pull_requests",
            "TestCollections": "list_test_collections",
            "Tests": "list_tests",
        }[schema_name]

        with patch(
            f"products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.source.{transport_fn}"
        ) as mock_transport:
            mock_transport.return_value = iter([])
            response = self.source.source_for_pipeline(self.config, manager, inputs)

        assert response.primary_keys == expected_keys

    @parameterized.expand([("unset", None), ("blank", "   ")])
    def test_merge_queue_without_target_branch_fails_permanently(self, _label: str, target_branch):
        # Merge Queue is scoped to one branch, so without it the sync would call the API with an
        # empty targetBranch forever. Fail once, with a message the user can act on.
        config = TrunkIoSourceConfig(
            api_token="test-token",
            org_url_slug="my-org",
            repo_host="github.com",
            repo_owner="my-org",
            repo_name="my-repo",
            merge_queue_target_branch=target_branch,
        )
        inputs = _make_inputs("MergeQueuePullRequests")

        with pytest.raises(ValueError) as excinfo:
            self.source.source_for_pipeline(config, MagicMock(spec=ResumableSourceManager), inputs)

        assert any(key in str(excinfo.value) for key in self.source.get_non_retryable_errors())

    def test_merge_queue_table_is_not_synced_by_default(self):
        # Flaky-Tests-only orgs are the majority and have no merge queue, so the table is offered
        # but left unselected rather than failing their syncs.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["MergeQueuePullRequests"].should_sync_default is False
        assert schemas["FailingTests"].should_sync_default is True
