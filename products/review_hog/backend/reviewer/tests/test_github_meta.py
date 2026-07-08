import pytest
from unittest.mock import MagicMock, Mock, patch

from github import GithubException
from parameterized import parameterized

from products.review_hog.backend.reviewer.tools.github_meta import PRFetcher, PRFilter, PRParser


class TestParseGithubPrUrl:
    @parameterized.expand(
        [
            ("simple", "https://github.com/owner/repo/pull/123", "owner", "repo", 123),
            (
                "complex_names",
                "https://github.com/user-name_123/repo.with-dots_and-dashes/pull/9999",
                "user-name_123",
                "repo.with-dots_and-dashes",
                9999,
            ),
        ]
    )
    def test_parse_valid_url(self, _name: str, url: str, owner: str, repo: str, number: int) -> None:
        assert PRParser().parse_github_pr_url(url) == {"owner": owner, "repo": repo, "pr_number": number}

    @parameterized.expand(
        [
            ("issues_not_pull", "https://github.com/owner/repo/issues/123"),
            ("wrong_domain", "https://gitlab.com/owner/repo/pull/123"),
            ("missing_protocol", "github.com/owner/repo/pull/123"),
            ("missing_repo", "https://github.com/owner/pull/123"),
            ("non_numeric_pr", "https://github.com/owner/repo/pull/abc"),
            ("missing_pr_number", "https://github.com/owner/repo/pull/"),
            ("not_a_url", "not-a-url"),
        ]
    )
    def test_parse_invalid_url_raises(self, _name: str, url: str) -> None:
        with pytest.raises(ValueError, match="Invalid GitHub PR URL format"):
            PRParser().parse_github_pr_url(url)


class TestIsFilteredFile:
    @parameterized.expand(
        [
            # Lock files
            ("package_lock", "package-lock.json", True),
            ("yarn_lock", "yarn.lock", True),
            ("cargo_lock", "Cargo.lock", True),
            ("poetry_lock", "poetry.lock", True),
            ("gemfile_lock", "Gemfile.lock", True),
            ("composer_lock", "composer.lock", True),
            ("pnpm_lock_yaml", "pnpm-lock.yaml", True),
            ("pnpm_lock_yml", "pnpm-lock.yml", True),
            ("podfile_lock", "Podfile.lock", True),
            ("pipfile_lock", "Pipfile.lock", True),
            ("flake_lock", "flake.lock", True),
            ("deno_lock", "deno.lock", True),
            ("bun_lock", "bun.lock", True),
            ("bun_lockb", "bun.lockb", True),
            ("npm_shrinkwrap", "npm-shrinkwrap.json", True),
            ("nested_package_lock", "path/to/package-lock.json", True),
            ("deep_yarn_lock", "some/deep/path/yarn.lock", True),
            ("nested_pnpm_lock", "project/pnpm-lock.yaml", True),
            # Sum/hash files
            ("go_sum", "go.sum", True),
            ("checksum_sum", "checksum.sum", True),
            ("nested_go_sum", "path/to/go.sum", True),
            # Minified files
            ("min_js", "bundle.min.js", True),
            ("min_css", "styles.min.css", True),
            ("min_json", "data.min.json", True),
            ("vendor_min_js", "vendor.min.js", True),
            ("nested_min_js", "path/to/app.min.js", True),
            ("nested_min_css", "assets/css/main.min.css", True),
            # Source maps
            ("js_map", "bundle.js.map", True),
            ("css_map", "styles.css.map", True),
            ("bare_map", "app.map", True),
            ("min_js_map", "vendor.min.js.map", True),
            ("nested_js_map", "path/to/code.js.map", True),
            # Build directories
            ("dist_js", "dist/bundle.js", True),
            ("dist_html", "dist/index.html", True),
            ("build_js", "build/app.js", True),
            ("build_css", "build/styles.css", True),
            ("out_js", "out/compiled.js", True),
            ("target_app", "target/release/app", True),
            ("nested_dist", "src/dist/bundle.js", True),
            ("nested_build", "app/build/index.js", True),
            ("nested_target", "project/target/debug/main", True),
            # Regular source files — 'lock'/'min'/'map' substrings but not filtered
            ("index_js", "index.js", False),
            ("app_py", "app.py", False),
            ("main_rs", "main.rs", False),
            ("styles_css", "styles.css", False),
            ("readme", "README.md", False),
            ("package_json", "package.json", False),
            ("cargo_toml", "Cargo.toml", False),
            ("go_mod", "go.mod", False),
            ("button_tsx", "src/components/Button.tsx", False),
            ("utils_js", "lib/utils.js", False),
            ("locked_py", "locked.py", False),
            ("minimal_js", "minimal.js", False),
            ("mapper_py", "mapper.py", False),
        ]
    )
    def test_is_filtered_file(self, _name: str, filename: str, expected: bool) -> None:
        assert PRFilter().is_filtered_file(filename) is expected


class TestIsTestFile:
    @parameterized.expand(
        [
            ("test_prefix_py", "test_module.py", True),
            ("suffix_test_py", "module_test.py", True),
            ("test_prefix_js", "test-module.js", True),
            ("suffix_test_js", "module-test.js", True),
            ("dot_test_js", "module.test.js", True),
            ("dot_spec_js", "module.spec.js", True),
            ("tests_dir", "tests/module.py", True),
            ("test_dir", "test/module.py", True),
            ("uppercase_tests_dir", "Tests/Foo.cs", True),
            ("nested_tests_dir", "src/tests/module.py", True),
            ("deep_test_dir", "path/to/test/file.py", True),
            ("dunder_tests", "__tests__/module.js", True),
            ("nested_dunder_tests", "src/__tests__/component.jsx", True),
            ("test_prefix_utils", "test_utils_module.py", True),
            ("nested_test_prefix", "posthog/api/test_dashboard.py", True),
            ("dash_test_prefix", "src/test-utils.ts", True),
            ("go_test_suffix", "pkg/handler_test.go", True),
            ("tests_suffix", "app/models_tests.py", True),
            ("plain_module", "module.py", False),
            ("main_js", "main.js", False),
            ("utils_py", "utils.py", False),
            ("config_yaml", "config.yaml", False),
            ("readme", "README.md", False),
            ("setup_py", "setup.py", False),
            ("package_json", "package.json", False),
            ("latest_txt", "latest.txt", False),
            ("contest_py", "contest.py", False),
            ("attestation_py", "attestation.py", False),
            # Production files whose names merely contain "test" as a substring used to be silently
            # excluded from review — the anchored patterns must keep them in.
            ("latest_dash", "frontend/src/queries/latest-versions.ts", False),
            ("latest_underscore_migration", "posthog/migrations/0116_plugin_latest_tag.py", False),
            ("test_infix_migration", "posthog/migrations/0132_team_test_account_filters.py", False),
            ("latest_script", "bin/build-schema-latest-versions.py", False),
            ("testing_doc", "testing-guide.md", False),
            # Deliberately no longer excluded: the _test_ infix matched production names (see the
            # migration above) and IGNORECASE ^Test matched any root file starting with "test".
            # Erring toward reviewing a test file beats silently skipping production code.
            ("test_infix_helper", "module_test_utils.py", False),
            ("capital_test_java", "TestModule.java", False),
        ]
    )
    def test_is_test_file(self, _name: str, filename: str, expected: bool) -> None:
        assert PRFilter().is_test_file(filename) is expected


class TestParsePatch:
    def test_parse_empty_patch(self) -> None:
        parser = PRParser()
        result = parser.parse_patch("")
        assert result == []

    def test_parse_single_addition(self) -> None:
        parser = PRParser()
        patch = """@@ -1,3 +1,4 @@
 line1
 line2
+new line
 line3"""

        result = parser.parse_patch(patch)
        assert len(result) == 3  # 3 context lines + 1 addition

        # Find the addition
        addition = next((r for r in result if r.type == "addition"), None)
        assert addition is not None
        assert addition.code == "new line"
        assert addition.new_start_line == 3
        assert addition.new_end_line == 3

    def test_parse_single_deletion(self) -> None:
        parser = PRParser()
        patch = """@@ -1,4 +1,3 @@
 line1
-deleted line
 line2
 line3"""

        result = parser.parse_patch(patch)
        deletions = [r for r in result if r.type == "deletion"]
        assert len(deletions) == 1
        assert deletions[0].code == "deleted line"
        assert deletions[0].old_start_line == 2
        assert deletions[0].old_end_line == 2

    def test_parse_mixed_changes(self) -> None:
        parser = PRParser()
        patch = """@@ -10,4 +10,5 @@
 context line
-old line 1
-old line 2
+new line 1
+new line 2
+new line 3
 another context"""

        result = parser.parse_patch(patch)

        deletions = [r for r in result if r.type == "deletion"]
        additions = [r for r in result if r.type == "addition"]
        contexts = [r for r in result if r.type == "context"]

        assert len(deletions) == 1
        assert len(additions) == 1
        assert len(contexts) == 2

        # Check deletion block
        assert deletions[0].code == "old line 1\nold line 2"
        assert deletions[0].old_start_line == 11
        assert deletions[0].old_end_line == 12

        # Check addition block
        assert additions[0].code == "new line 1\nnew line 2\nnew line 3"
        assert additions[0].new_start_line == 11
        assert additions[0].new_end_line == 13

    def test_parse_multiple_hunks(self) -> None:
        parser = PRParser()
        patch = """@@ -1,2 +1,3 @@
 line1
+addition1
 line2
@@ -10,3 +11,2 @@
 line10
-deletion1
 line11"""

        result = parser.parse_patch(patch)

        additions = [r for r in result if r.type == "addition"]
        deletions = [r for r in result if r.type == "deletion"]

        assert len(additions) == 1
        assert len(deletions) == 1
        assert additions[0].new_start_line == 2
        assert deletions[0].old_start_line == 11

    def test_parse_complex_patch(self) -> None:
        patch = """@@ -30,7 +30,10 @@ class MyClass:
     def method1(self):
         # This is a comment
-        old_implementation = True
+        new_implementation = False
+        additional_line = "test"
+        another_addition = 123
         return result

    def method2(self):
@@ -45,3 +48,4 @@ class MyClass:
         pass

# End of file
+# New comment at end"""

        parser = PRParser()
        result = parser.parse_patch(patch)

        # Should have various types of changes
        assert any(r.type == "addition" for r in result)
        assert any(r.type == "deletion" for r in result)
        assert any(r.type == "context" for r in result)

    def test_parse_patch_with_no_newline_marker(self) -> None:
        patch = """@@ -1,2 +1,2 @@
 line1
-line2
\\ No newline at end of file
+line2 modified
\\ No newline at end of file"""

        parser = PRParser()
        result = parser.parse_patch(patch)

        # The 'No newline' markers should be ignored
        deletions = [r for r in result if r.type == "deletion"]
        additions = [r for r in result if r.type == "addition"]

        assert len(deletions) == 1
        assert deletions[0].code == "line2"
        assert len(additions) == 1
        assert additions[0].code == "line2 modified"

    def test_parse_invalid_hunk_header(self) -> None:
        patch = """@@ invalid header @@
+new line
-old line
@@ -1,1 +1,1 @@
-valid change
+valid new"""

        parser = PRParser()
        result = parser.parse_patch(patch)

        # Should skip invalid hunk and process valid one
        assert len(result) > 0
        # Should have processed the valid hunk
        assert any(r.code == "valid change" for r in result if r.type == "deletion")
        assert any(r.code == "valid new" for r in result if r.type == "addition")


def _build_mock_pr(
    *,
    number: int = 123,
    head_sha: str = "abc123",
    comments: list[Mock] | None = None,
    files: list[Mock] | None = None,
    review_requests: tuple[list[Mock], list[Mock]] = ([], []),
    assignee: Mock | None = None,
    labels: list[Mock] | None = None,
    is_fork: bool = False,
) -> MagicMock:
    """A PyGithub PullRequest mock wired with the attributes fetch_pr_data reads."""
    mock_pr = MagicMock()
    mock_pr.number = number
    mock_pr.title = "Test PR"
    mock_pr.body = "Test description"
    mock_pr.state = "open"
    mock_pr.draft = False
    mock_pr.created_at.isoformat.return_value = "2024-01-01T00:00:00"
    mock_pr.updated_at.isoformat.return_value = "2024-01-02T00:00:00"
    mock_pr.user.login = "test-user"
    mock_pr.raw_data = {"author_association": "CONTRIBUTOR"}
    mock_pr.base.ref = "main"
    mock_pr.base.repo.full_name = "owner/repo"
    mock_pr.head.ref = "feature-branch"
    mock_pr.head.repo.full_name = "forker/repo" if is_fork else "owner/repo"
    mock_pr.head.sha = head_sha
    mock_pr.mergeable_state = "clean"
    mock_pr.get_review_requests.return_value = review_requests
    mock_pr.assignee = assignee
    mock_pr.labels = labels or []
    mock_pr.commits = 5
    mock_pr.additions = 100
    mock_pr.deletions = 50
    mock_pr.changed_files = 10
    mock_pr.get_review_comments.return_value = comments or []
    mock_pr.get_files.return_value = files or []
    return mock_pr


def _build_mock_comment(*, comment_id: int, path: str = "src/module.py") -> MagicMock:
    """A review-comment mock with the fields fetch_pr_comments reads."""
    mock_comment = MagicMock()
    mock_comment.id = comment_id
    mock_comment.path = path
    mock_comment.line = 10
    mock_comment.start_line = None
    mock_comment.body = "Review comment"
    mock_comment.diff_hunk = "@@ -1,3 +1,3 @@"
    mock_comment.user.login = "reviewer"
    mock_comment.created_at.isoformat.return_value = "2024-01-01T12:00:00"
    return mock_comment


def _build_mock_file(*, filename: str, status: str = "modified", patch: str | None = None) -> MagicMock:
    """A changed-file mock with the fields fetch_pr_files reads."""
    mock_file = MagicMock()
    mock_file.filename = filename
    mock_file.status = status
    mock_file.additions = 10
    mock_file.deletions = 5
    mock_file.patch = patch
    return mock_file


class TestFetchPrData:
    @patch("products.review_hog.backend.reviewer.tools.github_meta.Github")
    def test_returns_four_tuple_with_metadata_comments_files_diff(self, mock_github_class: Mock) -> None:
        # The reviewable file's patch must surface in the diff snapshot under its header; the
        # comment must carry its GitHub id (feeds the report's last_seen_comment_id watermark).
        patch = "@@ -1,3 +1,4 @@\n line1\n line2\n+new line\n line3"
        mock_pr = _build_mock_pr(
            number=456,
            head_sha="abc123",
            comments=[_build_mock_comment(comment_id=9001)],
            files=[_build_mock_file(filename="src/module.py", status="modified", patch=patch)],
        )
        mock_repo = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        mock_github_class.return_value.get_repo.return_value = mock_repo

        fetcher = PRFetcher("owner", "repo", 456, token="test-token")
        result = fetcher.fetch_pr_data()

        # 4-tuple contract: metadata, comments, files, diff
        assert len(result) == 4
        metadata, comments, files, diff = result

        assert metadata.number == 456
        assert metadata.head_sha == "abc123"

        assert len(comments) == 1
        assert comments[0].id == 9001

        assert len(files) == 1
        assert files[0].filename == "src/module.py"
        assert len(files[0].changes) > 0

        # The diff snapshot anchors findings to the exact reviewed code via the header + raw patch.
        assert "=== src/module.py [modified] ===" in diff
        assert "+new line" in diff

    @patch("products.review_hog.backend.reviewer.tools.github_meta.Github")
    def test_writes_no_files(self, mock_github_class: Mock, tmp_path) -> None:
        # The fetcher has no review-dir / output path — nothing should land on disk.
        mock_pr = _build_mock_pr(files=[_build_mock_file(filename="src/module.py", patch="@@ -1,1 +1,1 @@\n+x")])
        mock_repo = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        mock_github_class.return_value.get_repo.return_value = mock_repo

        before = set(tmp_path.iterdir())
        fetcher = PRFetcher("owner", "repo", 123, token="test-token")
        fetcher.fetch_pr_data()

        assert set(tmp_path.iterdir()) == before

    @patch("products.review_hog.backend.reviewer.tools.github_meta.Github")
    def test_filtered_and_test_files_are_excluded(self, mock_github_class: Mock) -> None:
        # Test files and a lock file must be dropped from both pr_files and the diff snapshot.
        mock_pr = _build_mock_pr(
            files=[
                _build_mock_file(filename="tests/test_module.py", status="added", patch="@@ -0,0 +1,1 @@\n+x"),
                _build_mock_file(filename="yarn.lock", status="modified", patch="@@ -1,1 +1,1 @@\n+y"),
                _build_mock_file(filename="src/module.py", status="modified", patch="@@ -1,1 +1,1 @@\n+z"),
            ],
        )
        mock_repo = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        mock_github_class.return_value.get_repo.return_value = mock_repo

        fetcher = PRFetcher("owner", "repo", 789, token="test-token")
        _, _, files, diff = fetcher.fetch_pr_data()

        assert [f.filename for f in files] == ["src/module.py"]
        assert "tests/test_module.py" not in diff
        assert "yarn.lock" not in diff
        assert "=== src/module.py [modified] ===" in diff

    @patch("products.review_hog.backend.reviewer.tools.github_meta.Github")
    def test_missing_patch_recorded_explicitly_in_diff(self, mock_github_class: Mock) -> None:
        # GitHub omits the patch for binary/large files — the snapshot keeps the header with a marker
        # rather than silently dropping the file.
        mock_pr = _build_mock_pr(
            files=[_build_mock_file(filename="old_module.py", status="removed", patch=None)],
        )
        mock_repo = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        mock_github_class.return_value.get_repo.return_value = mock_repo

        fetcher = PRFetcher("owner", "repo", 999, token="test-token")
        _, _, files, diff = fetcher.fetch_pr_data()

        assert files[0].filename == "old_module.py"
        assert files[0].changes == []
        assert "=== old_module.py [removed] ===" in diff
        assert "(no patch available" in diff

    @patch("products.review_hog.backend.reviewer.tools.github_meta.Github")
    def test_metadata_carries_assignee_labels_and_reviewers(self, mock_github_class: Mock) -> None:
        mock_assignee = MagicMock()
        mock_assignee.login = "assignee-user"
        mock_label = MagicMock()
        mock_label.name = "bug"
        mock_reviewer = MagicMock()
        mock_reviewer.login = "reviewer1"
        mock_pr = _build_mock_pr(
            assignee=mock_assignee,
            labels=[mock_label],
            review_requests=([mock_reviewer], []),
        )
        mock_repo = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        mock_github_class.return_value.get_repo.return_value = mock_repo

        fetcher = PRFetcher("owner", "repo", 123, token="test-token")
        metadata, _, _, _ = fetcher.fetch_pr_data()

        assert metadata.assignee == "assignee-user"
        assert metadata.labels == ["bug"]
        assert metadata.requested_reviewers == ["reviewer1"]

    @parameterized.expand([("non_fork", False), ("fork", True)])
    @patch("products.review_hog.backend.reviewer.tools.github_meta.Github")
    def test_is_fork_reflects_head_vs_base_repo(self, _name: str, is_fork: bool, mock_github_class: Mock) -> None:
        # is_fork drives the activity's fork rejection; it must mirror head.repo != base.repo.
        mock_pr = _build_mock_pr(is_fork=is_fork)
        mock_repo = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        mock_github_class.return_value.get_repo.return_value = mock_repo

        fetcher = PRFetcher("owner", "repo", 123, token="test-token")
        metadata, _, _, _ = fetcher.fetch_pr_data()

        assert metadata.is_fork is is_fork

    def test_no_github_token_raises(self) -> None:
        # An empty installation token is rejected in the constructor, before any API call.
        with pytest.raises(ValueError, match="GitHub installation token is required"):
            PRFetcher("owner", "repo", 123, token="")

    @patch("products.review_hog.backend.reviewer.tools.github_meta.Github")
    def test_github_api_errors_propagate(self, mock_github_class: Mock) -> None:
        # A 404 (or 401) from the API surfaces as GithubException, not a swallowed empty result.
        mock_repo = MagicMock()
        mock_repo.get_pull.side_effect = GithubException(404, {"message": "Not found"})
        mock_github_class.return_value.get_repo.return_value = mock_repo

        fetcher = PRFetcher("owner", "repo", 123, token="test-token")
        with pytest.raises(GithubException):
            fetcher.fetch_pr_data()
