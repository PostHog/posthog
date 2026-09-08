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

    @parameterized.expand(
        [
            ("UnhealthyTests", "unhealthy_tests"),
            ("QuarantinedTests", "quarantined_tests"),
            ("FailingTests", "failing_tests"),
            ("MergeQueuePullRequests", "merge_queue_pull_requests"),
        ]
    )
    def test_source_for_pipeline_dispatches_to_expected_transport(self, schema_name: str, transport_fn: str):
        inputs = _make_inputs(schema_name)
        manager = MagicMock(spec=ResumableSourceManager)

        with patch(
            f"products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.source.{transport_fn}"
        ) as mock_transport:
            mock_transport.return_value = iter([])
            response = self.source.source_for_pipeline(self.config, manager, inputs)

        mock_transport.assert_called_once()
        assert response.name == schema_name

    def test_source_for_pipeline_unknown_endpoint_raises(self):
        inputs = _make_inputs("NotARealEndpoint")
        manager = MagicMock(spec=ResumableSourceManager)

        try:
            self.source.source_for_pipeline(self.config, manager, inputs)
            raised = False
        except ValueError:
            raised = True

        assert raised

    @parameterized.expand(
        [
            ("UnhealthyTests", ["id"]),
            ("QuarantinedTests", ["name", "parent", "file", "classname", "variant"]),
            ("FailingTests", ["id"]),
            ("MergeQueuePullRequests", ["id"]),
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
