from parameterized import parameterized

from products.review_hog.backend.reviewer.tools.github_meta import PRFilter


class TestIsTestFile:
    @parameterized.expand(
        [
            ("root_test_prefix", "test_models.py"),
            ("nested_test_prefix", "posthog/api/test_dashboard.py"),
            ("dash_test_prefix", "src/test-utils.ts"),
            ("test_suffix", "pkg/handler_test.go"),
            ("dash_test_suffix", "src/utils-test.ts"),
            ("tests_suffix", "app/models_tests.py"),
            ("js_dot_test", "src/thing.test.ts"),
            ("js_dot_spec", "src/thing.spec.tsx"),
            ("tests_dir", "products/foo/tests/factories.py"),
            ("root_tests_dir", "tests/helpers.py"),
            ("uppercase_tests_dir", "Tests/Foo.cs"),
            ("dunder_tests_dir", "frontend/src/lib/__tests__/utils.ts"),
        ]
    )
    def test_recognizes_test_files(self, _name: str, filename: str) -> None:
        assert PRFilter.is_test_file(filename)

    # Production files whose names merely contain "test" as a substring used to be silently
    # excluded from review (fetch_pr_files drops them before the reviewer ever sees them).
    @parameterized.expand(
        [
            ("latest_dash", "frontend/src/queries/latest-versions.ts"),
            ("latest_underscore_migration", "posthog/migrations/0116_plugin_latest_tag.py"),
            ("test_infix_migration", "posthog/migrations/0132_team_test_account_filters.py"),
            ("latest_script", "bin/build-schema-latest-versions.py"),
            ("contest", "products/foo/contest-winners.py"),
            ("conftest", "posthog/conftest.py"),
            ("testing_doc", "testing-guide.md"),
        ]
    )
    def test_keeps_production_lookalikes(self, _name: str, filename: str) -> None:
        assert not PRFilter.is_test_file(filename)
