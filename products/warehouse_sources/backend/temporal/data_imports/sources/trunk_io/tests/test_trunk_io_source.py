from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import SourceDriver
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trunkio import (
    TrunkIoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.source import TrunkIoSource


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
            result = self.source.validate_credentials(self.config, self.team_id, api_version="v1")

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
            ("UnhealthyTests", "/v1/flaky-tests/list-unhealthy-tests", "v1"),
            ("QuarantinedTests", "/v1/flaky-tests/list-quarantined-tests", "v1"),
            ("FailingTests", "/v1/flaky-tests/list-failing-tests", "v1"),
            ("MergeQueuePullRequests", "/v1/listPullRequests", "v1"),
            ("UnhealthyTests", "/v2/tests", "v2"),
            ("QuarantinedTests", "/v2/tests", "v2"),
            ("FailingTests", "/v2/tests", "v2"),
            ("MergeQueuePullRequests", "/v1/listPullRequests", "v2"),
            ("TestCollections", "/v2/test-collections", "v2"),
            ("Tests", "/v2/tests", "v2"),
        ]
    )
    def test_source_for_pipeline_dispatches_to_expected_transport(
        self, schema_name: str, expected_path: str, api_version: str
    ):
        result = SourceDriver(self.source, self.config).run(schema_name, [], api_version=api_version)

        assert result.response is not None
        assert result.response.name == schema_name
        assert result.paths[0] == expected_path

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
        result = SourceDriver(self.source, self.config).run(schema_name, [], api_version=api_version)

        assert isinstance(result.raised, ValueError)
        assert result.requests == []

    @parameterized.expand(
        [
            ("v1", ["name", "parent", "file", "classname", "variant"]),
            ("v2", ["id"]),
        ]
    )
    def test_quarantined_tests_primary_key_follows_the_pin(self, api_version: str, expected_keys: list[str]):
        result = SourceDriver(self.source, self.config).run("QuarantinedTests", [], api_version=api_version)

        assert result.response is not None
        assert result.response.primary_keys == expected_keys

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
        result = SourceDriver(self.source, config).run("MergeQueuePullRequests", [])

        assert isinstance(result.raised, ValueError)
        assert any(key in str(result.raised) for key in self.source.get_non_retryable_errors())
