"""Tests for the main run.py module."""

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from products.review_hog.backend.reviewer.models.chunk_analysis import ChunkAnalysis
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.run import main


@pytest.fixture
def mock_tool_functions() -> Generator[dict[str, Mock], None, None]:
    """Create mocked versions of all tool functions used in main()."""
    with (
        patch("app.run.PRParser") as mock_parser_class,
        patch("app.run.PRFetcher") as mock_fetcher_class,
        patch("app.run.switch_to_pr_branch") as mock_switch,
        patch("app.run.generate_all_schemas") as mock_schemas,
        patch("app.run.split_pr_into_chunks") as mock_split,
        patch("app.run.analyze_chunks") as mock_analyze,
        patch("app.run.review_chunks") as mock_review,
        patch("app.run.combine_issues") as mock_combine,
        patch("app.run.clean_issues") as mock_clean,
        patch("app.run.deduplicate_issues") as mock_deduplicate,
        patch("app.run.validate_issues") as mock_validate,
        patch("app.run.prepare_validation_markdown") as mock_prepare_validation,
    ):
        yield {
            "parser_class": mock_parser_class,
            "fetcher_class": mock_fetcher_class,
            "switch": mock_switch,
            "schemas": mock_schemas,
            "split": mock_split,
            "analyze": mock_analyze,
            "review": mock_review,
            "combine": mock_combine,
            "clean": mock_clean,
            "deduplicate": mock_deduplicate,
            "validate": mock_validate,
            "prepare_validation": mock_prepare_validation,
            "calculate_token": mock_calculate_token,
        }


@pytest.fixture
def valid_pr_args(tmp_path: Path) -> list[str]:
    """Create valid command-line arguments for testing."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    return [
        "run.py",
        "--pr-url",
        "https://github.com/owner/repo/pull/123",
        "--project-dir",
        str(project_dir),
    ]


class TestArgumentParsing:
    """Test command-line argument parsing and validation."""

    @pytest.mark.asyncio
    async def test_invalid_pr_url(self, tmp_path: Path) -> None:
        """Test that invalid PR URL format raises ValueError."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        test_args = [
            "run.py",
            "--pr-url",
            "not-a-valid-url",
            "--project-dir",
            str(project_dir),
        ]

        with (
            patch("sys.argv", test_args),
            patch("app.run.PRParser") as mock_parser_class,
            pytest.raises(ValueError, match="Invalid GitHub PR URL format"),
        ):
            mock_parser = Mock()
            mock_parser.parse_github_pr_url.side_effect = ValueError(
                "Invalid GitHub PR URL format"
            )
            mock_parser_class.return_value = mock_parser
            await main()

    @pytest.mark.asyncio
    async def test_nonexistent_project_directory(self) -> None:
        """Test that non-existent project directory raises ValueError."""
        test_args = [
            "run.py",
            "--pr-url",
            "https://github.com/owner/repo/pull/123",
            "--project-dir",
            "/nonexistent/directory",
        ]

        with (
            patch("sys.argv", test_args),
            pytest.raises(ValueError, match="Project directory does not exist"),
        ):
            await main()

    @pytest.mark.asyncio
    async def test_missing_required_arguments(self) -> None:
        """Test that missing required arguments causes SystemExit."""
        test_args = ["run.py"]

        with (
            patch("sys.argv", test_args),
            pytest.raises(SystemExit),
        ):
            await main()


class TestMainWorkflow:
    """Test the main workflow and error handling."""

    @pytest.mark.asyncio
    async def test_review_directory_creation(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        tmp_path: Path,
        mock_tool_functions: dict[str, Mock],
    ) -> None:
        """Test that review directory is created correctly."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        test_args = [
            "run.py",
            "--pr-url",
            "https://github.com/owner/repo/pull/456",
            "--project-dir",
            str(project_dir),
        ]

        with (
            patch("sys.argv", test_args),
            patch("app.run.Path.cwd") as mock_cwd,
        ):
            mock_cwd.return_value = tmp_path
            mock_parser = Mock()
            mock_parser.parse_github_pr_url.return_value = {
                "owner": "owner",
                "repo": "repo",
                "pr_number": 456,
            }
            mock_tool_functions["parser_class"].return_value = mock_parser

            mock_fetcher = Mock()
            mock_fetcher.fetch_pr_data.return_value = (
                pr_metadata,
                pr_comments,
                pr_files,
            )
            mock_tool_functions["fetcher_class"].return_value = mock_fetcher

            # Set all async mocks to return None
            for key in [
                "split",
                "analyze",
                "review",
                "deduplicate",
                "validate",
                "prepare_validation",
                "calculate_token",
            ]:
                mock_tool_functions[key].return_value = None

            # Mock split to create chunks.json file
            async def mock_split_func(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
                review_dir = kwargs["review_dir"]
                chunks_path = review_dir / "chunks.json"
                with chunks_path.open("w") as f:
                    f.write('{"chunks": []}')

            mock_tool_functions["split"].side_effect = mock_split_func

            review_dir = tmp_path / "reviews" / "456"

            await main()

            assert review_dir.exists()
            assert review_dir.is_dir()

    @pytest.mark.asyncio
    async def test_fetch_pr_data_error_handling(
        self,
        mock_tool_functions: dict[str, Mock],
        valid_pr_args: list[str],
        tmp_path: Path,
    ) -> None:
        """Test error handling when fetching PR data fails."""
        with (
            patch("sys.argv", valid_pr_args),
            patch("app.run.Path.cwd") as mock_cwd,
        ):
            mock_cwd.return_value = tmp_path
            mock_parser = Mock()
            mock_parser.parse_github_pr_url.return_value = {
                "owner": "owner",
                "repo": "repo",
                "pr_number": 123,
            }
            mock_tool_functions["parser_class"].return_value = mock_parser

            mock_fetcher = Mock()
            mock_fetcher.fetch_pr_data.side_effect = Exception("GitHub API error")
            mock_tool_functions["fetcher_class"].return_value = mock_fetcher

            with pytest.raises(Exception, match="GitHub API error"):
                await main()

    @pytest.mark.asyncio
    async def test_chunks_file_loading_and_validation(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        expected_chunks: ChunksList,
        tmp_path: Path,
        mock_tool_functions: dict[str, Mock],
        valid_pr_args: list[str],
    ) -> None:
        """Test that chunks.json is properly loaded and validated."""
        with (
            patch("sys.argv", valid_pr_args),
            patch("app.run.Path.cwd") as mock_cwd,
        ):
            mock_cwd.return_value = tmp_path
            mock_parser = Mock()
            mock_parser.parse_github_pr_url.return_value = {
                "owner": "owner",
                "repo": "repo",
                "pr_number": 123,
            }
            mock_tool_functions["parser_class"].return_value = mock_parser

            mock_fetcher = Mock()
            mock_fetcher.fetch_pr_data.return_value = (
                pr_metadata,
                pr_comments,
                pr_files,
            )
            mock_tool_functions["fetcher_class"].return_value = mock_fetcher

            # Set all async mocks to return None
            for key in [
                "split",
                "analyze",
                "review",
                "deduplicate",
                "validate",
                "prepare_validation",
                "calculate_token",
            ]:
                mock_tool_functions[key].return_value = None

            review_dir = tmp_path / "reviews" / "123"
            review_dir.mkdir(parents=True, exist_ok=True)
            chunks_path = review_dir / "chunks.json"
            with chunks_path.open("w") as f:
                f.write(expected_chunks.model_dump_json())

            await main()

            # Verify chunks were loaded correctly for analyze_chunks
            analyze_call_args = mock_tool_functions["analyze"].call_args
            assert analyze_call_args is not None
            analyze_chunks_arg = analyze_call_args.kwargs["chunks_data"]
            assert len(analyze_chunks_arg.chunks) == len(expected_chunks.chunks)

            # Verify chunks were loaded correctly for review_chunks
            review_call_args = mock_tool_functions["review"].call_args
            assert review_call_args is not None
            review_chunks_arg = review_call_args.kwargs["chunks_data"]
            assert len(review_chunks_arg.chunks) == len(expected_chunks.chunks)
            assert (
                review_chunks_arg.chunks[0].chunk_id
                == expected_chunks.chunks[0].chunk_id
            )

    @pytest.mark.asyncio
    async def test_review_chunks_error_propagation(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        expected_chunks: ChunksList,
        tmp_path: Path,
        mock_tool_functions: dict[str, Mock],
        valid_pr_args: list[str],
    ) -> None:
        """Test that errors in review_chunks are properly propagated."""
        with (
            patch("sys.argv", valid_pr_args),
            patch("app.run.Path.cwd") as mock_cwd,
        ):
            mock_cwd.return_value = tmp_path
            mock_parser = Mock()
            mock_parser.parse_github_pr_url.return_value = {
                "owner": "owner",
                "repo": "repo",
                "pr_number": 123,
            }
            mock_tool_functions["parser_class"].return_value = mock_parser

            mock_fetcher = Mock()
            mock_fetcher.fetch_pr_data.return_value = (
                pr_metadata,
                pr_comments,
                pr_files,
            )
            mock_tool_functions["fetcher_class"].return_value = mock_fetcher

            mock_tool_functions["review"].side_effect = RuntimeError("Review failed")

            review_dir = tmp_path / "reviews" / "123"
            review_dir.mkdir(parents=True, exist_ok=True)
            chunks_path = review_dir / "chunks.json"
            with chunks_path.open("w") as f:
                f.write(expected_chunks.model_dump_json())

            with pytest.raises(RuntimeError, match="Review failed"):
                await main()

    @pytest.mark.asyncio
    async def test_invalid_chunks_json_validation(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        tmp_path: Path,
        mock_tool_functions: dict[str, Mock],
        valid_pr_args: list[str],
    ) -> None:
        """Test handling of invalid chunks.json file."""
        with (
            patch("sys.argv", valid_pr_args),
            patch("app.run.Path.cwd") as mock_cwd,
        ):
            mock_cwd.return_value = tmp_path
            mock_parser = Mock()
            mock_parser.parse_github_pr_url.return_value = {
                "owner": "owner",
                "repo": "repo",
                "pr_number": 123,
            }
            mock_tool_functions["parser_class"].return_value = mock_parser

            mock_fetcher = Mock()
            mock_fetcher.fetch_pr_data.return_value = (
                pr_metadata,
                pr_comments,
                pr_files,
            )
            mock_tool_functions["fetcher_class"].return_value = mock_fetcher

            review_dir = tmp_path / "reviews" / "123"
            review_dir.mkdir(parents=True, exist_ok=True)
            chunks_path = review_dir / "chunks.json"
            with chunks_path.open("w") as f:
                f.write('{"invalid": "json structure"}')

            with pytest.raises(ValidationError):  # Pydantic validation error
                await main()


class TestIntegrationScenarios:
    """Test complete integration scenarios."""

    @pytest.mark.asyncio
    async def test_successful_workflow_integration(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        expected_chunks: ChunksList,
        tmp_path: Path,
        mock_tool_functions: dict[str, Mock],
        valid_pr_args: list[str],
    ) -> None:
        """Test complete successful workflow with all steps."""
        with (
            patch("sys.argv", valid_pr_args),
            patch("app.run.Path.cwd") as mock_cwd,
        ):
            mock_cwd.return_value = tmp_path
            mock_parser = Mock()
            mock_parser.parse_github_pr_url.return_value = {
                "owner": "owner",
                "repo": "repo",
                "pr_number": 123,
            }
            mock_tool_functions["parser_class"].return_value = mock_parser

            mock_fetcher = Mock()
            mock_fetcher.fetch_pr_data.return_value = (
                pr_metadata,
                pr_comments,
                pr_files,
            )
            mock_tool_functions["fetcher_class"].return_value = mock_fetcher

            # Set all async mocks to return None
            for key in [
                "split",
                "analyze",
                "review",
                "deduplicate",
                "validate",
                "prepare_validation",
                "calculate_token",
            ]:
                mock_tool_functions[key].return_value = None

            review_dir = tmp_path / "reviews" / "123"
            review_dir.mkdir(parents=True, exist_ok=True)
            chunks_path = review_dir / "chunks.json"
            with chunks_path.open("w") as f:
                f.write(expected_chunks.model_dump_json())

            await main()

            # Verify execution order
            assert mock_tool_functions["parser_class"].call_count == 1
            assert mock_tool_functions["fetcher_class"].call_count == 1
            assert mock_tool_functions["switch"].call_count == 1
            assert mock_tool_functions["schemas"].call_count == 1
            assert mock_tool_functions["split"].call_count == 1
            assert mock_tool_functions["analyze"].call_count == 1
            assert mock_tool_functions["review"].call_count == 1
            assert mock_tool_functions["combine"].call_count == 1
            assert mock_tool_functions["clean"].call_count == 1
            assert mock_tool_functions["deduplicate"].call_count == 1
            assert mock_tool_functions["validate"].call_count == 1
            assert mock_tool_functions["prepare_validation"].call_count == 1
            assert mock_tool_functions["calculate_token"].call_count == 1

    @pytest.mark.asyncio
    async def test_workflow_stops_on_intermediate_failure(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        mock_tool_functions: dict[str, Mock],
        valid_pr_args: list[str],
        tmp_path: Path,
    ) -> None:
        """Test that workflow stops when an intermediate step fails."""
        with (
            patch("sys.argv", valid_pr_args),
            patch("app.run.Path.cwd") as mock_cwd,
        ):
            mock_cwd.return_value = tmp_path
            mock_parser = Mock()
            mock_parser.parse_github_pr_url.return_value = {
                "owner": "owner",
                "repo": "repo",
                "pr_number": 123,
            }
            mock_tool_functions["parser_class"].return_value = mock_parser

            mock_fetcher = Mock()
            mock_fetcher.fetch_pr_data.return_value = (
                pr_metadata,
                pr_comments,
                pr_files,
            )
            mock_tool_functions["fetcher_class"].return_value = mock_fetcher

            mock_tool_functions["split"].side_effect = RuntimeError("Split failed")

            with pytest.raises(RuntimeError, match="Split failed"):
                await main()

            # Verify subsequent steps were not called
            mock_tool_functions["analyze"].assert_not_called()
            mock_tool_functions["review"].assert_not_called()
            mock_tool_functions["combine"].assert_not_called()
            mock_tool_functions["clean"].assert_not_called()
            mock_tool_functions["deduplicate"].assert_not_called()
            mock_tool_functions["validate"].assert_not_called()
            mock_tool_functions["prepare_validation"].assert_not_called()
            mock_tool_functions["calculate_token"].assert_not_called()

    @pytest.mark.asyncio
    async def test_complete_e2e_workflow(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        expected_chunks: ChunksList,
        sample_chunk_analysis_complex: ChunkAnalysis,
        tmp_path: Path,
        mock_tool_functions: dict[str, Mock],
    ) -> None:
        """Test complete end-to-end workflow with realistic data flow."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / ".git").mkdir()

        test_args = [
            "run.py",
            "--pr-url",
            "https://github.com/test-owner/test-repo/pull/999",
            "--project-dir",
            str(project_dir),
        ]

        with (
            patch("sys.argv", test_args),
            patch("app.run.Path.cwd") as mock_cwd,
        ):
            mock_cwd.return_value = tmp_path
            mock_parser = Mock()
            mock_parser.parse_github_pr_url.return_value = {
                "owner": "test-owner",
                "repo": "test-repo",
                "pr_number": 999,
            }
            mock_tool_functions["parser_class"].return_value = mock_parser

            pr_metadata_copy = pr_metadata.model_copy()
            pr_metadata_copy.number = 999

            mock_fetcher = Mock()
            mock_fetcher.fetch_pr_data.return_value = (
                pr_metadata_copy,
                pr_comments,
                pr_files,
            )
            mock_tool_functions["fetcher_class"].return_value = mock_fetcher

            # Mock split_pr_into_chunks to create chunks.json
            async def mock_split_func(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
                chunks_path = kwargs["review_dir"] / "chunks.json"
                with chunks_path.open("w") as f:
                    f.write(expected_chunks.model_dump_json())

            mock_tool_functions["split"].side_effect = mock_split_func

            # Mock review_chunks to create review files
            async def mock_review_func(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
                review_path = kwargs["review_dir"] / "review_pass_1.json"
                with review_path.open("w") as f:
                    json.dump(
                        [sample_chunk_analysis_complex.model_dump(mode="json")],
                        f,
                        indent=2,
                    )

            mock_tool_functions["review"].side_effect = mock_review_func

            # Set other async mocks to return None
            for key in [
                "analyze",
                "deduplicate",
                "validate",
                "prepare_validation",
                "calculate_token",
            ]:
                mock_tool_functions[key].return_value = None

            await main()

            # Verify workflow completed successfully
            assert mock_tool_functions["parser_class"].call_count == 1
            assert mock_tool_functions["fetcher_class"].call_count == 1
            assert mock_tool_functions["switch"].call_count == 1
            assert mock_tool_functions["split"].call_count == 1
            assert mock_tool_functions["analyze"].call_count == 1
            assert mock_tool_functions["review"].call_count == 1
            assert mock_tool_functions["combine"].call_count == 1
            assert mock_tool_functions["clean"].call_count == 1
            assert mock_tool_functions["deduplicate"].call_count == 1
            assert mock_tool_functions["validate"].call_count == 1
            assert mock_tool_functions["prepare_validation"].call_count == 1
            assert mock_tool_functions["calculate_token"].call_count == 1

            # Verify data flow
            mock_fetcher.fetch_pr_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_issue_cleaner_workflow_integration(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        expected_chunks: ChunksList,
        tmp_path: Path,
        mock_tool_functions: dict[str, Mock],
        valid_pr_args: list[str],
    ) -> None:
        """Test issue cleaner integration in the workflow."""
        with (
            patch("sys.argv", valid_pr_args),
            patch("app.run.Path.cwd") as mock_cwd,
        ):
            mock_cwd.return_value = tmp_path
            mock_parser = Mock()
            mock_parser.parse_github_pr_url.return_value = {
                "owner": "owner",
                "repo": "repo",
                "pr_number": 123,
            }
            mock_tool_functions["parser_class"].return_value = mock_parser

            mock_fetcher = Mock()
            mock_fetcher.fetch_pr_data.return_value = (
                pr_metadata,
                pr_comments,
                pr_files,
            )
            mock_tool_functions["fetcher_class"].return_value = mock_fetcher

            # Set all async mocks to return None
            for key in [
                "split",
                "analyze",
                "review",
                "deduplicate",
                "validate",
                "prepare_validation",
                "calculate_token",
            ]:
                mock_tool_functions[key].return_value = None

            review_dir = tmp_path / "reviews" / "123"
            review_dir.mkdir(parents=True, exist_ok=True)

            # Create chunks.json
            chunks_path = review_dir / "chunks.json"
            with chunks_path.open("w") as f:
                f.write(expected_chunks.model_dump_json())

            # Mock combine_issues to create issues_found_raw.json
            def mock_combine_func(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
                # Create test issues - some in scope, some out
                from reviewer.models.issue_combination import IssueCombination
                from reviewer.models.issues_review import Issue, IssuePriority, LineRange

                issues = [
                    # In-scope issue (matches PR file and lines)
                    Issue(
                        id="1-1-1",
                        title="Issue in modified file",
                        file="src/components/DataTable.tsx",
                        lines=[LineRange(start=45, end=50)],
                        issue="Test issue in PR scope",
                        suggestion="Fix it",
                        priority=IssuePriority.SHOULD_FIX,
                    ),
                    # Out-of-scope issue (different file)
                    Issue(
                        id="1-1-2",
                        title="Issue in unmodified file",
                        file="src/other/file.py",
                        lines=[LineRange(start=10, end=20)],
                        issue="Test issue outside PR scope",
                        suggestion="Fix it",
                        priority=IssuePriority.SHOULD_FIX,
                    ),
                ]
                raw_issues = IssueCombination(issues=issues)
                with (kwargs["review_dir"] / "issues_found_raw.json").open("w") as f:
                    f.write(raw_issues.model_dump_json())

            mock_tool_functions["combine"].side_effect = mock_combine_func

            # Mock clean_issues to verify it's called and create output files
            def mock_clean_func(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
                from reviewer.models.issue_combination import IssueCombination
                from reviewer.models.issues_review import Issue, IssuePriority, LineRange

                # Simulate cleaning by creating output files
                in_scope = IssueCombination(
                    issues=[
                        Issue(
                            id="1-1-1",
                            title="Issue in modified file",
                            file="src/components/DataTable.tsx",
                            lines=[LineRange(start=45, end=50)],
                            issue="Test issue in PR scope",
                            suggestion="Fix it",
                            priority=IssuePriority.SHOULD_FIX,
                        )
                    ]
                )
                out_scope = IssueCombination(
                    issues=[
                        Issue(
                            id="1-1-2",
                            title="Issue in unmodified file",
                            file="src/other/file.py",
                            lines=[LineRange(start=10, end=20)],
                            issue="Test issue outside PR scope",
                            suggestion="Fix it",
                            priority=IssuePriority.SHOULD_FIX,
                        )
                    ]
                )

                with (kwargs["review_dir"] / "issues_cleaned.json").open("w") as f:
                    f.write(in_scope.model_dump_json())
                with (kwargs["review_dir"] / "issues_outside_scope.json").open(
                    "w"
                ) as f:
                    f.write(out_scope.model_dump_json())

            mock_tool_functions["clean"].side_effect = mock_clean_func

            await main()

            # Verify clean_issues was called after combine_issues
            assert mock_tool_functions["combine"].call_count == 1
            assert mock_tool_functions["clean"].call_count == 1

            # Verify clean_issues was called with correct args
            mock_tool_functions["clean"].assert_called_with(review_dir=review_dir)

            # Verify deduplicate was called after clean
            assert mock_tool_functions["deduplicate"].call_count == 1

    @pytest.mark.asyncio
    async def test_missing_chunks_file_error(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        tmp_path: Path,
        mock_tool_functions: dict[str, Mock],
        valid_pr_args: list[str],
    ) -> None:
        """Test error when chunks.json file is not created."""
        with (
            patch("sys.argv", valid_pr_args),
            patch("app.run.Path.cwd") as mock_cwd,
        ):
            mock_cwd.return_value = tmp_path
            mock_parser = Mock()
            mock_parser.parse_github_pr_url.return_value = {
                "owner": "owner",
                "repo": "repo",
                "pr_number": 123,
            }
            mock_tool_functions["parser_class"].return_value = mock_parser

            mock_fetcher = Mock()
            mock_fetcher.fetch_pr_data.return_value = (
                pr_metadata,
                pr_comments,
                pr_files,
            )
            mock_tool_functions["fetcher_class"].return_value = mock_fetcher

            # Mock split doesn't create chunks.json
            async def mock_split_func(*args: Any, **kwargs: Any) -> None:  # noqa: ARG001
                return None

            mock_tool_functions["split"].side_effect = mock_split_func

            with pytest.raises(FileNotFoundError):
                await main()
