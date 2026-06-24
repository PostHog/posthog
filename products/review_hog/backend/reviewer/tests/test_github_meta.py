import os

import pytest
from unittest.mock import MagicMock, Mock, patch

from github import GithubException

from products.review_hog.backend.reviewer.tools.github_meta import PRFetcher, PRFilter, PRParser


class TestParseGithubPrUrl:
    """Test parse_github_pr_url function."""

    def test_parse_valid_url(self) -> None:
        """Test parsing a valid GitHub PR URL."""
        url = "https://github.com/owner/repo/pull/123"
        parser = PRParser()
        result = parser.parse_github_pr_url(url)

        assert result["owner"] == "owner"
        assert result["repo"] == "repo"
        assert result["pr_number"] == 123

    def test_parse_valid_url_with_complex_names(self) -> None:
        """Test parsing with complex owner and repo names."""
        url = "https://github.com/user-name_123/repo.with-dots_and-dashes/pull/9999"
        parser = PRParser()
        result = parser.parse_github_pr_url(url)

        assert result["owner"] == "user-name_123"
        assert result["repo"] == "repo.with-dots_and-dashes"
        assert result["pr_number"] == 9999

    def test_parse_invalid_url_format(self) -> None:
        """Test parsing an invalid URL format."""
        invalid_urls = [
            "https://github.com/owner/repo/issues/123",  # issues instead of pull
            "https://gitlab.com/owner/repo/pull/123",  # wrong domain
            "github.com/owner/repo/pull/123",  # missing protocol
            "https://github.com/owner/pull/123",  # missing repo
            "https://github.com/owner/repo/pull/abc",  # non-numeric PR number
            "https://github.com/owner/repo/pull/",  # missing PR number
            "not-a-url",  # completely invalid
        ]

        for url in invalid_urls:
            with pytest.raises(ValueError, match="Invalid GitHub PR URL format"):
                parser = PRParser()
                parser.parse_github_pr_url(url)


class TestIsFilteredFile:
    """Test is_filtered_file function."""

    def test_lock_files(self) -> None:
        """Test that lock files are correctly filtered."""
        pr_filter = PRFilter()
        lock_files = [
            "package-lock.json",
            "yarn.lock",
            "Cargo.lock",
            "poetry.lock",
            "Gemfile.lock",
            "composer.lock",
            "pnpm-lock.yaml",  # pnpm lock file
            "pnpm-lock.yml",  # alternative extension
            "Podfile.lock",  # iOS/macOS
            "Pipfile.lock",  # Python pipenv
            "flake.lock",  # Nix flake
            "deno.lock",  # Deno
            "bun.lock",
            "bun.lockb",  # Bun binary lock file
            "npm-shrinkwrap.json",  # npm alternative to package-lock
            "path/to/package-lock.json",
            "some/deep/path/yarn.lock",
            "project/pnpm-lock.yaml",
        ]

        for filename in lock_files:
            assert pr_filter.is_filtered_file(filename) is True, f"Failed to filter {filename}"

    def test_sum_files(self) -> None:
        """Test that sum/hash files are correctly filtered."""
        pr_filter = PRFilter()
        sum_files = [
            "go.sum",
            "checksum.sum",
            "path/to/go.sum",
        ]

        for filename in sum_files:
            assert pr_filter.is_filtered_file(filename) is True, f"Failed to filter {filename}"

    def test_minified_files(self) -> None:
        """Test that minified files are correctly filtered."""
        pr_filter = PRFilter()
        minified_files = [
            "bundle.min.js",
            "styles.min.css",
            "data.min.json",
            "vendor.min.js",
            "path/to/app.min.js",
            "assets/css/main.min.css",
        ]

        for filename in minified_files:
            assert pr_filter.is_filtered_file(filename) is True, f"Failed to filter {filename}"

    def test_source_map_files(self) -> None:
        """Test that source map files are correctly filtered."""
        pr_filter = PRFilter()
        map_files = [
            "bundle.js.map",
            "styles.css.map",
            "app.map",
            "vendor.min.js.map",
            "path/to/code.js.map",
        ]

        for filename in map_files:
            assert pr_filter.is_filtered_file(filename) is True, f"Failed to filter {filename}"

    def test_build_directories(self) -> None:
        """Test that files in build directories are correctly filtered."""
        pr_filter = PRFilter()
        build_files = [
            "dist/bundle.js",
            "dist/index.html",
            "build/app.js",
            "build/styles.css",
            "out/compiled.js",
            "target/release/app",
            "src/dist/bundle.js",
            "app/build/index.js",
            "project/target/debug/main",
        ]

        for filename in build_files:
            assert pr_filter.is_filtered_file(filename) is True, f"Failed to filter {filename}"

    def test_non_filtered_files(self) -> None:
        """Test that regular source files are not filtered."""
        pr_filter = PRFilter()
        regular_files = [
            "index.js",
            "app.py",
            "main.rs",
            "styles.css",
            "README.md",
            "package.json",
            "Cargo.toml",
            "go.mod",
            "src/components/Button.tsx",
            "lib/utils.js",
            "locked.py",  # Contains 'lock' but not a lock file
            "minimal.js",  # Contains 'min' but not minified
            "mapper.py",  # Contains 'map' but not a source map
        ]

        for filename in regular_files:
            assert pr_filter.is_filtered_file(filename) is False, f"Incorrectly filtered {filename}"


class TestIsTestFile:
    """Test is_test_file function."""

    def test_test_file_patterns(self) -> None:
        """Test various test file patterns are correctly identified."""
        pr_filter = PRFilter()
        test_files = [
            "test_module.py",
            "module_test.py",
            "test-module.js",
            "module-test.js",
            "module.test.js",
            "module.spec.js",
            "TestModule.java",
            "tests/module.py",
            "test/module.py",
            "src/tests/module.py",
            "path/to/test/file.py",
            "__tests__/module.js",
            "src/__tests__/component.jsx",
            "module_test_utils.py",
            "test_utils_module.py",
        ]

        for filename in test_files:
            assert pr_filter.is_test_file(filename) is True, f"Failed to identify {filename} as test file"

    def test_non_test_file_patterns(self) -> None:
        """Test that non-test files are correctly identified."""
        pr_filter = PRFilter()
        non_test_files = [
            "module.py",
            "main.js",
            "utils.py",
            "config.yaml",
            "README.md",
            "setup.py",
            "package.json",
            "latest.txt",  # contains 'test' but not in test pattern
            "contest.py",  # contains 'test' but not in test pattern
            "attestation.py",  # contains 'test' but not in test pattern
        ]

        for filename in non_test_files:
            assert pr_filter.is_test_file(filename) is False, f"Incorrectly identified {filename} as test file"


class TestParsePatch:
    """Test parse_patch function."""

    def test_parse_empty_patch(self) -> None:
        """Test parsing an empty patch."""
        parser = PRParser()
        result = parser.parse_patch("")
        assert result == []

    def test_parse_single_addition(self) -> None:
        """Test parsing a patch with a single addition."""
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
        """Test parsing a patch with a single deletion."""
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
        """Test parsing a patch with mixed additions and deletions."""
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
        """Test parsing a patch with multiple hunks."""
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
        """Test parsing a complex real-world style patch."""
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
        """Test parsing a patch with 'No newline at end of file' marker."""
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
        """Test parsing handles invalid hunk headers gracefully."""
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
    mock_pr.head.ref = "feature-branch"
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
    """Test PRFetcher.fetch_pr_data — returns everything in-process, writes no files."""

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"})
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

        fetcher = PRFetcher("owner", "repo", 456)
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

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"})
    @patch("products.review_hog.backend.reviewer.tools.github_meta.Github")
    def test_writes_no_files(self, mock_github_class: Mock, tmp_path) -> None:
        # The fetcher has no review-dir / output path — nothing should land on disk.
        mock_pr = _build_mock_pr(files=[_build_mock_file(filename="src/module.py", patch="@@ -1,1 +1,1 @@\n+x")])
        mock_repo = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        mock_github_class.return_value.get_repo.return_value = mock_repo

        before = set(tmp_path.iterdir())
        fetcher = PRFetcher("owner", "repo", 123)
        fetcher.fetch_pr_data()

        assert set(tmp_path.iterdir()) == before

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"})
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

        fetcher = PRFetcher("owner", "repo", 789)
        _, _, files, diff = fetcher.fetch_pr_data()

        assert [f.filename for f in files] == ["src/module.py"]
        assert "tests/test_module.py" not in diff
        assert "yarn.lock" not in diff
        assert "=== src/module.py [modified] ===" in diff

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"})
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

        fetcher = PRFetcher("owner", "repo", 999)
        _, _, files, diff = fetcher.fetch_pr_data()

        assert files[0].filename == "old_module.py"
        assert files[0].changes == []
        assert "=== old_module.py [removed] ===" in diff
        assert "(no patch available" in diff

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"})
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

        fetcher = PRFetcher("owner", "repo", 123)
        metadata, _, _, _ = fetcher.fetch_pr_data()

        assert metadata.assignee == "assignee-user"
        assert metadata.labels == ["bug"]
        assert metadata.requested_reviewers == ["reviewer1"]

    def test_no_github_token_raises(self) -> None:
        # Token check happens in the constructor (client init), before any API call.
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(ValueError, match="GITHUB_TOKEN environment variable not set"),
        ):
            PRFetcher("owner", "repo", 123)

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"})
    @patch("products.review_hog.backend.reviewer.tools.github_meta.Github")
    def test_github_api_errors_propagate(self, mock_github_class: Mock) -> None:
        # A 404 (or 401) from the API surfaces as GithubException, not a swallowed empty result.
        mock_repo = MagicMock()
        mock_repo.get_pull.side_effect = GithubException(404, {"message": "Not found"})
        mock_github_class.return_value.get_repo.return_value = mock_repo

        fetcher = PRFetcher("owner", "repo", 123)
        with pytest.raises(GithubException):
            fetcher.fetch_pr_data()
