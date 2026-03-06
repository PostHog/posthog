import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, call, patch

import pytest
from github import GithubException

from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.tools.github_meta import (
    PRFetcher,
    PRFilter,
    PRParser,
    switch_to_pr_branch,
)


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
            assert (
                pr_filter.is_filtered_file(filename) is True
            ), f"Failed to filter {filename}"

    def test_sum_files(self) -> None:
        """Test that sum/hash files are correctly filtered."""
        pr_filter = PRFilter()
        sum_files = [
            "go.sum",
            "checksum.sum",
            "path/to/go.sum",
        ]

        for filename in sum_files:
            assert (
                pr_filter.is_filtered_file(filename) is True
            ), f"Failed to filter {filename}"

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
            assert (
                pr_filter.is_filtered_file(filename) is True
            ), f"Failed to filter {filename}"

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
            assert (
                pr_filter.is_filtered_file(filename) is True
            ), f"Failed to filter {filename}"

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
            assert (
                pr_filter.is_filtered_file(filename) is True
            ), f"Failed to filter {filename}"

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
            "summary.txt",  # Contains 'sum' but not a sum file
            "minimal.js",  # Contains 'min' but not minified
            "mapper.py",  # Contains 'map' but not a source map
        ]

        for filename in regular_files:
            assert (
                pr_filter.is_filtered_file(filename) is False
            ), f"Incorrectly filtered {filename}"


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
            assert (
                pr_filter.is_test_file(filename) is True
            ), f"Failed to identify {filename} as test file"

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
            assert (
                pr_filter.is_test_file(filename) is False
            ), f"Incorrectly identified {filename} as test file"


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


class TestFetchPrData:
    """Test fetch_pr_data function."""

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"})
    @patch("app.tools.github_meta.Github")
    def test_fetch_pr_data_success(
        self, mock_github_class: Mock, temp_review_dir: Path
    ) -> None:
        """Test successful PR data fetching."""
        # Setup mocks
        mock_github = MagicMock()
        mock_github_class.return_value = mock_github

        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo

        mock_pr = MagicMock()
        mock_pr.number = 123
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
        mock_pr.mergeable_state = "clean"
        mock_pr.get_review_requests.return_value = ([], [])  # users, teams
        mock_pr.assignee = None
        mock_pr.labels = []
        mock_pr.commits = 5
        mock_pr.additions = 100
        mock_pr.deletions = 50
        mock_pr.changed_files = 10
        mock_pr.get_review_comments.return_value = []
        mock_pr.get_files.return_value = []

        mock_repo.get_pull.return_value = mock_pr

        # Execute
        fetcher = PRFetcher("owner", "repo", 123, str(temp_review_dir))
        metadata, comments, files = fetcher.fetch_pr_data()

        # Verify
        assert metadata.number == 123
        assert metadata.title == "Test PR"
        assert metadata.author == "test-user"
        assert len(comments) == 0
        assert len(files) == 0

        # Check files were created
        assert (temp_review_dir / "pr_meta.json").exists()
        assert (temp_review_dir / "pr_comments.jsonl").exists()
        assert (temp_review_dir / "pr_files.jsonl").exists()
        assert (temp_review_dir / "pr_files_scope.jsonl").exists()

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"})
    @patch("app.tools.github_meta.Github")
    def test_fetch_pr_data_with_comments_and_files(
        self, mock_github_class: Mock, temp_review_dir: Path
    ) -> None:
        """Test fetching PR data with comments and files."""
        # Setup mocks
        mock_github = MagicMock()
        mock_github_class.return_value = mock_github

        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo

        mock_pr = MagicMock()
        mock_pr.number = 456
        mock_pr.title = "PR with content"
        mock_pr.body = "Description"
        mock_pr.state = "open"
        mock_pr.draft = False
        mock_pr.created_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_pr.updated_at.isoformat.return_value = "2024-01-02T00:00:00"
        mock_pr.user.login = "author"
        mock_pr.raw_data = {"author_association": "MEMBER"}
        mock_pr.base.ref = "main"
        mock_pr.head.ref = "feature"
        mock_pr.mergeable_state = "clean"
        mock_pr.get_review_requests.return_value = ([], [])
        mock_pr.assignee = None
        mock_pr.labels = []
        mock_pr.commits = 2
        mock_pr.additions = 50
        mock_pr.deletions = 20
        mock_pr.changed_files = 3

        # Mock comment
        mock_comment = MagicMock()
        mock_comment.path = "file.py"
        mock_comment.line = 10
        mock_comment.start_line = None
        mock_comment.body = "Review comment"
        mock_comment.diff_hunk = "@@ -1,3 +1,3 @@"
        mock_comment.user.login = "reviewer"
        mock_comment.created_at.isoformat.return_value = "2024-01-01T12:00:00"
        mock_pr.get_review_comments.return_value = [mock_comment]

        # Mock file
        mock_file = MagicMock()
        mock_file.filename = "src/module.py"
        mock_file.status = "modified"
        mock_file.additions = 10
        mock_file.deletions = 5
        mock_file.patch = "@@ -1,3 +1,4 @@\n line1\n line2\n+new line\n line3"
        mock_pr.get_files.return_value = [mock_file]

        mock_repo.get_pull.return_value = mock_pr

        # Execute
        fetcher = PRFetcher("owner", "repo", 456, str(temp_review_dir))
        metadata, comments, files = fetcher.fetch_pr_data()

        # Verify
        assert metadata.number == 456
        assert len(comments) == 1
        assert comments[0].body == "Review comment"
        assert len(files) == 1
        assert files[0].filename == "src/module.py"
        assert len(files[0].changes) > 0

        # Verify pr_files_scope.jsonl was created without code fields
        assert (temp_review_dir / "pr_files_scope.jsonl").exists()
        with (temp_review_dir / "pr_files_scope.jsonl").open() as f:
            scope_files = [json.loads(line) for line in f.readlines()]

        assert len(scope_files) == len(files)
        assert scope_files[0]["filename"] == files[0].filename
        assert scope_files[0]["status"] == files[0].status
        assert len(scope_files[0]["changes"]) == len(files[0].changes)
        # Verify code field is completely absent
        for change in scope_files[0]["changes"]:
            assert "code" not in change
        # Verify line numbers are preserved
        assert (
            scope_files[0]["changes"][0]["new_start_line"]
            == files[0].changes[0].new_start_line
        )

    def test_fetch_pr_data_no_github_token(self, temp_review_dir: Path) -> None:
        """Test that fetching fails without GitHub token."""
        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(
                ValueError, match="GITHUB_TOKEN environment variable not set"
            ),
        ):
            fetcher = PRFetcher("owner", "repo", 123, str(temp_review_dir))
            fetcher.fetch_pr_data()

    @patch.dict(os.environ, {"GITHUB_TOKEN": "invalid-token"})
    @patch("app.tools.github_meta.Github")
    def test_fetch_pr_data_invalid_token(
        self, mock_github_class: Mock, temp_review_dir: Path
    ) -> None:
        """Test handling of invalid GitHub token."""
        mock_github = MagicMock()
        mock_github_class.return_value = mock_github

        # Simulate 401 error on get_repo call
        mock_github.get_repo.side_effect = GithubException(
            401, {"message": "Bad credentials"}
        )

        # PRFetcher initialization succeeds (token validation happens later)
        fetcher = PRFetcher("owner", "repo", 123, str(temp_review_dir))

        # The error should be raised when fetch_pr_data is called
        with pytest.raises(GithubException):
            fetcher.fetch_pr_data()

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"})
    @patch("app.tools.github_meta.Github")
    def test_fetch_pr_data_pr_not_found(
        self, mock_github_class: Mock, temp_review_dir: Path
    ) -> None:
        """Test handling when PR is not found."""
        mock_github = MagicMock()
        mock_github_class.return_value = mock_github

        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo

        # Simulate 404 error
        mock_repo.get_pull.side_effect = GithubException(404, {"message": "Not found"})

        fetcher = PRFetcher("owner", "repo", 123, str(temp_review_dir))

        with pytest.raises(GithubException):
            fetcher.fetch_pr_data()

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"})
    @patch("app.tools.github_meta.Github")
    def test_fetch_pr_data_skip_existing_files(
        self, mock_github_class: Mock, temp_review_dir: Path, pr_metadata: PRMetadata
    ) -> None:
        """Test that existing files are not overwritten."""
        # Create existing files
        pr_meta_path = temp_review_dir / "pr_meta.json"
        pr_comments_path = temp_review_dir / "pr_comments.jsonl"
        pr_files_path = temp_review_dir / "pr_files.jsonl"
        pr_files_scope_path = temp_review_dir / "pr_files_scope.jsonl"

        with pr_meta_path.open("w") as f:
            json.dump(pr_metadata.model_dump(), f)

        with pr_comments_path.open("w") as f:
            f.write(
                '{"path":"existing.py","line":null,"start_line":null,"body":"existing comment","diff_hunk":"@@ -1,3 +1,3 @@","user":"test-user","created_at":"2024-01-01T00:00:00"}\n'
            )

        with pr_files_path.open("w") as f:
            f.write(
                '{"filename":"existing.py","status":"modified","additions":10,"deletions":5,"changes":[]}\n'
            )

        with pr_files_scope_path.open("w") as f:
            f.write(
                '{"filename":"existing.py","status":"modified","additions":10,"deletions":5,"changes":[]}\n'
            )

        # Mock should not be called
        mock_github = MagicMock()
        mock_github_class.return_value = mock_github

        # Execute
        fetcher = PRFetcher("owner", "repo", 123, str(temp_review_dir))
        metadata, comments, files = fetcher.fetch_pr_data()

        # Verify existing data is loaded
        assert metadata.number == pr_metadata.number
        assert metadata.title == pr_metadata.title

        # GitHub API should not be called for PR data
        mock_github.get_repo.assert_called_once()

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"})
    @patch("app.tools.github_meta.Github")
    def test_fetch_pr_data_handles_test_files(
        self, mock_github_class: Mock, temp_review_dir: Path
    ) -> None:
        """Test that test files are properly identified."""
        # Setup mocks
        mock_github = MagicMock()
        mock_github_class.return_value = mock_github

        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo

        mock_pr = MagicMock()
        # Set required PR attributes
        mock_pr.number = 789
        mock_pr.title = "Test PR"
        mock_pr.body = "Description"
        mock_pr.state = "open"
        mock_pr.draft = False
        mock_pr.created_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_pr.updated_at.isoformat.return_value = "2024-01-02T00:00:00"
        mock_pr.user.login = "author"
        mock_pr.raw_data = {"author_association": "MEMBER"}
        mock_pr.base.ref = "main"
        mock_pr.head.ref = "feature"
        mock_pr.mergeable_state = "clean"
        mock_pr.get_review_requests.return_value = ([], [])
        mock_pr.assignee = None
        mock_pr.labels = []
        mock_pr.commits = 1
        mock_pr.additions = 100
        mock_pr.deletions = 0
        mock_pr.changed_files = 2
        mock_pr.get_review_comments.return_value = []

        # Mock files - one test, one non-test
        mock_test_file = MagicMock()
        mock_test_file.filename = "tests/test_module.py"
        mock_test_file.status = "added"
        mock_test_file.additions = 50
        mock_test_file.deletions = 0
        mock_test_file.patch = None

        mock_regular_file = MagicMock()
        mock_regular_file.filename = "src/module.py"
        mock_regular_file.status = "added"
        mock_regular_file.additions = 50
        mock_regular_file.deletions = 0
        mock_regular_file.patch = None

        mock_pr.get_files.return_value = [mock_test_file, mock_regular_file]
        mock_repo.get_pull.return_value = mock_pr

        # Execute
        fetcher = PRFetcher("owner", "repo", 789, str(temp_review_dir))
        metadata, comments, files = fetcher.fetch_pr_data()

        # Verify that test file was skipped
        assert len(files) == 1


class TestSwitchToPrBranch:
    """Test switch_to_pr_branch function."""

    @patch("app.tools.github_meta.subprocess.run")
    def test_switch_to_pr_branch_success(
        self, mock_run: Mock, pr_metadata: PRMetadata, temp_project_dir: Path
    ) -> None:
        """Test successful branch switching."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        switch_to_pr_branch(pr_metadata, str(temp_project_dir))

        # Verify git commands were called
        assert mock_run.call_count == 2

        # Check fetch command
        fetch_call = mock_run.call_args_list[0]
        assert fetch_call == call(
            ["git", "fetch", "origin"],
            cwd=str(temp_project_dir),
            check=True,
            capture_output=True,
            text=True,
        )

        # Check checkout command
        checkout_call = mock_run.call_args_list[1]
        assert checkout_call == call(
            ["git", "checkout", pr_metadata.head_branch],
            cwd=str(temp_project_dir),
            check=True,
            capture_output=True,
            text=True,
        )

    @patch("app.tools.github_meta.subprocess.run")
    def test_switch_to_pr_branch_fetch_failure(
        self, mock_run: Mock, pr_metadata: PRMetadata, temp_project_dir: Path
    ) -> None:
        """Test handling of git fetch failure."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["git", "fetch", "origin"], stderr="fetch failed"
        )

        with pytest.raises(subprocess.CalledProcessError):
            switch_to_pr_branch(pr_metadata, str(temp_project_dir))

        # Should only call fetch, not checkout
        assert mock_run.call_count == 1

    @patch("app.tools.github_meta.subprocess.run")
    def test_switch_to_pr_branch_checkout_failure(
        self, mock_run: Mock, pr_metadata: PRMetadata, temp_project_dir: Path
    ) -> None:
        """Test handling of git checkout failure."""
        # First call (fetch) succeeds, second call (checkout) fails
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            subprocess.CalledProcessError(
                1, ["git", "checkout"], stderr="checkout failed"
            ),
        ]

        with pytest.raises(subprocess.CalledProcessError):
            switch_to_pr_branch(pr_metadata, str(temp_project_dir))

        # Should call both fetch and checkout
        assert mock_run.call_count == 2


class TestEndToEnd:
    """End-to-end tests for github_meta module."""

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"})
    @patch("app.tools.github_meta.subprocess.run")
    @patch("app.tools.github_meta.Github")
    def test_complete_pr_workflow(
        self,
        mock_github_class: Mock,
        mock_subprocess: Mock,
        temp_review_dir: Path,
        temp_project_dir: Path,
    ) -> None:
        """Test complete workflow: parse URL, fetch data, switch branch."""
        # Parse URL
        url = "https://github.com/test-owner/test-repo/pull/999"
        parser = PRParser()
        parsed = parser.parse_github_pr_url(url)

        assert parsed["owner"] == "test-owner"
        assert parsed["repo"] == "test-repo"
        assert parsed["pr_number"] == 999

        # Setup GitHub mocks
        mock_github = MagicMock()
        mock_github_class.return_value = mock_github

        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo

        mock_pr = MagicMock()
        mock_pr.number = parsed["pr_number"]
        mock_pr.title = "E2E Test PR"
        mock_pr.body = "This is an end-to-end test"
        mock_pr.state = "open"
        mock_pr.draft = False
        mock_pr.created_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_pr.updated_at.isoformat.return_value = "2024-01-02T00:00:00"
        mock_pr.user.login = "e2e-author"
        mock_pr.raw_data = {"author_association": "OWNER"}
        mock_pr.base.ref = "main"
        mock_pr.head.ref = "e2e-feature-branch"
        mock_pr.mergeable_state = "clean"

        # Add assignee and labels for more complete test
        mock_assignee = MagicMock()
        mock_assignee.login = "assignee-user"
        mock_pr.assignee = mock_assignee

        mock_label1 = MagicMock()
        mock_label1.name = "bug"
        mock_label2 = MagicMock()
        mock_label2.name = "priority-high"
        mock_pr.labels = [mock_label1, mock_label2]

        # Add requested reviewers
        mock_reviewer = MagicMock()
        mock_reviewer.login = "reviewer1"
        mock_pr.get_review_requests.return_value = ([mock_reviewer], [])  # users, teams

        mock_pr.commits = 3
        mock_pr.additions = 150
        mock_pr.deletions = 75
        mock_pr.changed_files = 5

        # Add multiple comments
        mock_comment1 = MagicMock()
        mock_comment1.path = "src/main.py"
        mock_comment1.line = 25
        mock_comment1.start_line = 20
        mock_comment1.body = "This needs refactoring"
        mock_comment1.diff_hunk = "@@ -20,10 +20,10 @@"
        mock_comment1.user.login = "reviewer1"
        mock_comment1.created_at.isoformat.return_value = "2024-01-01T10:00:00"

        mock_comment2 = MagicMock()
        mock_comment2.path = "src/utils.py"
        mock_comment2.line = 50
        mock_comment2.start_line = None
        mock_comment2.body = "Add error handling"
        mock_comment2.diff_hunk = "@@ -45,10 +45,15 @@"
        mock_comment2.user.login = "reviewer2"
        mock_comment2.created_at.isoformat.return_value = "2024-01-01T11:00:00"

        mock_pr.get_review_comments.return_value = [mock_comment1, mock_comment2]

        # Add multiple files with different statuses
        mock_file1 = MagicMock()
        mock_file1.filename = "src/main.py"
        mock_file1.status = "modified"
        mock_file1.additions = 50
        mock_file1.deletions = 25
        mock_file1.patch = """@@ -10,5 +10,6 @@ def main():
     print("Hello")
-    old_code = True
+    new_code = False
+    extra_line = "test"
     return result"""

        mock_file2 = MagicMock()
        mock_file2.filename = "tests/test_main.py"
        mock_file2.status = "added"
        mock_file2.additions = 100
        mock_file2.deletions = 0
        mock_file2.patch = """@@ -0,0 +1,10 @@
+def test_main():
+    assert main() == expected"""

        mock_file3 = MagicMock()
        mock_file3.filename = "old_module.py"
        mock_file3.status = "removed"
        mock_file3.additions = 0
        mock_file3.deletions = 50
        mock_file3.patch = None

        mock_pr.get_files.return_value = [mock_file1, mock_file2, mock_file3]

        mock_repo.get_pull.return_value = mock_pr

        # Fetch PR data
        fetcher = PRFetcher(
            str(parsed["owner"]),
            str(parsed["repo"]),
            int(parsed["pr_number"]),
            str(temp_review_dir),
        )
        metadata, comments, files = fetcher.fetch_pr_data()

        # Verify fetched data
        assert metadata.number == 999
        assert metadata.title == "E2E Test PR"
        assert metadata.author == "e2e-author"
        assert metadata.assignee == "assignee-user"
        assert "bug" in metadata.labels
        assert "priority-high" in metadata.labels
        assert metadata.requested_reviewers == ["reviewer1"]

        assert len(comments) == 2
        assert comments[0].body == "This needs refactoring"
        assert comments[1].body == "Add error handling"

        assert len(files) == 2
        modified_file = next(f for f in files if f.status == "modified")
        removed_file = next(f for f in files if f.status == "removed")

        assert modified_file.filename == "src/main.py"
        assert len(modified_file.changes) > 0

        assert removed_file.filename == "old_module.py"
        assert removed_file.deletions == 50

        # Verify files were saved
        assert (temp_review_dir / "pr_meta.json").exists()
        assert (temp_review_dir / "pr_comments.jsonl").exists()
        assert (temp_review_dir / "pr_files.jsonl").exists()
        assert (temp_review_dir / "pr_files_scope.jsonl").exists()

        # Verify pr_files_scope.jsonl content
        with (temp_review_dir / "pr_files_scope.jsonl").open() as f:
            scope_files = [json.loads(line) for line in f.readlines()]

        assert len(scope_files) == 2
        for scope_file in scope_files:
            # All changes should have no code field
            for change in scope_file.get("changes", []):
                assert "code" not in change

        # Setup subprocess mock for branch switching
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="", stderr="")

        # Switch to PR branch
        switch_to_pr_branch(metadata, str(temp_project_dir))

        # Verify git commands
        assert mock_subprocess.call_count == 2
        fetch_call = mock_subprocess.call_args_list[0]
        checkout_call = mock_subprocess.call_args_list[1]

        assert "fetch" in fetch_call[0][0]
        assert "checkout" in checkout_call[0][0]
        assert "e2e-feature-branch" in checkout_call[0][0]
