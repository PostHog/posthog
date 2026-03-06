"""Tests for the main run.py module."""

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import Mock, patch

from pydantic import ValidationError

from products.review_hog.backend.reviewer.models.chunk_analysis import ChunkAnalysis
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.run import main

_RUN = "products.review_hog.backend.reviewer.run"


@pytest.fixture
def mock_tool_functions(tmp_path: Path) -> Generator[dict[str, Mock], None, None]:
    """Create mocked versions of all tool functions used in main()."""
    with (
        patch(f"{_RUN}.PRParser") as mock_parser_class,
        patch(f"{_RUN}.PRFetcher") as mock_fetcher_class,
        patch(f"{_RUN}.generate_all_schemas") as mock_schemas,
        patch(f"{_RUN}.split_pr_into_chunks") as mock_split,
        patch(f"{_RUN}.analyze_chunks") as mock_analyze,
        patch(f"{_RUN}.review_chunks") as mock_review,
        patch(f"{_RUN}.combine_issues") as mock_combine,
        patch(f"{_RUN}.clean_issues") as mock_clean,
        patch(f"{_RUN}.deduplicate_issues") as mock_deduplicate,
        patch(f"{_RUN}.validate_issues") as mock_validate,
        patch(f"{_RUN}.prepare_validation_markdown") as mock_prepare_validation,
        patch(f"{_RUN}._REVIEW_HOG_DIR", tmp_path),
    ):
        yield {
            "parser_class": mock_parser_class,
            "fetcher_class": mock_fetcher_class,
            "schemas": mock_schemas,
            "split": mock_split,
            "analyze": mock_analyze,
            "review": mock_review,
            "combine": mock_combine,
            "clean": mock_clean,
            "deduplicate": mock_deduplicate,
            "validate": mock_validate,
            "prepare_validation": mock_prepare_validation,
        }


def _setup_parser_and_fetcher(
    mock_tool_functions: dict[str, Mock],
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
    owner: str = "owner",
    repo: str = "repo",
    pr_number: int = 123,
) -> None:
    """Helper to configure parser and fetcher mocks."""
    mock_parser = Mock()
    mock_parser.parse_github_pr_url.return_value = {
        "owner": owner,
        "repo": repo,
        "pr_number": pr_number,
    }
    mock_tool_functions["parser_class"].return_value = mock_parser

    mock_fetcher = Mock()
    mock_fetcher.fetch_pr_data.return_value = (pr_metadata, pr_comments, pr_files)
    mock_tool_functions["fetcher_class"].return_value = mock_fetcher


class TestArgumentParsing:
    """Test PR URL parsing and error handling."""

    @pytest.mark.asyncio
    async def test_invalid_pr_url(self, mock_tool_functions: dict[str, Mock]) -> None:
        mock_parser = Mock()
        mock_parser.parse_github_pr_url.side_effect = ValueError("Invalid GitHub PR URL format")
        mock_tool_functions["parser_class"].return_value = mock_parser

        with pytest.raises(ValueError, match="Invalid GitHub PR URL format"):
            await main("not-a-valid-url")


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
        _setup_parser_and_fetcher(mock_tool_functions, pr_metadata, pr_comments, pr_files, pr_number=456)

        for key in ["split", "analyze", "review", "deduplicate", "validate", "prepare_validation"]:
            mock_tool_functions[key].return_value = None

        async def mock_split_func(*args: Any, **kwargs: Any) -> None:
            review_dir = kwargs["review_dir"]
            with (review_dir / "chunks.json").open("w") as f:
                f.write('{"chunks": []}')

        mock_tool_functions["split"].side_effect = mock_split_func

        await main("https://github.com/owner/repo/pull/456")

        review_dir = tmp_path / "reviews" / "456"
        assert review_dir.exists()
        assert review_dir.is_dir()

    @pytest.mark.asyncio
    async def test_fetch_pr_data_error_handling(
        self,
        mock_tool_functions: dict[str, Mock],
    ) -> None:
        mock_parser = Mock()
        mock_parser.parse_github_pr_url.return_value = {"owner": "owner", "repo": "repo", "pr_number": 123}
        mock_tool_functions["parser_class"].return_value = mock_parser

        mock_fetcher = Mock()
        mock_fetcher.fetch_pr_data.side_effect = Exception("GitHub API error")
        mock_tool_functions["fetcher_class"].return_value = mock_fetcher

        with pytest.raises(Exception, match="GitHub API error"):
            await main("https://github.com/owner/repo/pull/123")

    @pytest.mark.asyncio
    async def test_chunks_file_loading_and_validation(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        expected_chunks: ChunksList,
        tmp_path: Path,
        mock_tool_functions: dict[str, Mock],
    ) -> None:
        _setup_parser_and_fetcher(mock_tool_functions, pr_metadata, pr_comments, pr_files)

        for key in ["split", "analyze", "review", "deduplicate", "validate", "prepare_validation"]:
            mock_tool_functions[key].return_value = None

        review_dir = tmp_path / "reviews" / "123"
        review_dir.mkdir(parents=True, exist_ok=True)
        with (review_dir / "chunks.json").open("w") as f:
            f.write(expected_chunks.model_dump_json())

        await main("https://github.com/owner/repo/pull/123")

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
        assert review_chunks_arg.chunks[0].chunk_id == expected_chunks.chunks[0].chunk_id

    @pytest.mark.asyncio
    async def test_review_chunks_error_propagation(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        expected_chunks: ChunksList,
        tmp_path: Path,
        mock_tool_functions: dict[str, Mock],
    ) -> None:
        _setup_parser_and_fetcher(mock_tool_functions, pr_metadata, pr_comments, pr_files)
        mock_tool_functions["review"].side_effect = RuntimeError("Review failed")

        review_dir = tmp_path / "reviews" / "123"
        review_dir.mkdir(parents=True, exist_ok=True)
        with (review_dir / "chunks.json").open("w") as f:
            f.write(expected_chunks.model_dump_json())

        with pytest.raises(RuntimeError, match="Review failed"):
            await main("https://github.com/owner/repo/pull/123")

    @pytest.mark.asyncio
    async def test_invalid_chunks_json_validation(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        tmp_path: Path,
        mock_tool_functions: dict[str, Mock],
    ) -> None:
        _setup_parser_and_fetcher(mock_tool_functions, pr_metadata, pr_comments, pr_files)

        review_dir = tmp_path / "reviews" / "123"
        review_dir.mkdir(parents=True, exist_ok=True)
        with (review_dir / "chunks.json").open("w") as f:
            f.write('{"invalid": "json structure"}')

        with pytest.raises(ValidationError):
            await main("https://github.com/owner/repo/pull/123")


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
    ) -> None:
        _setup_parser_and_fetcher(mock_tool_functions, pr_metadata, pr_comments, pr_files)

        for key in ["split", "analyze", "review", "deduplicate", "validate", "prepare_validation"]:
            mock_tool_functions[key].return_value = None

        review_dir = tmp_path / "reviews" / "123"
        review_dir.mkdir(parents=True, exist_ok=True)
        with (review_dir / "chunks.json").open("w") as f:
            f.write(expected_chunks.model_dump_json())

        await main("https://github.com/owner/repo/pull/123")

        assert mock_tool_functions["parser_class"].call_count == 1
        assert mock_tool_functions["fetcher_class"].call_count == 1
        assert mock_tool_functions["schemas"].call_count == 1
        assert mock_tool_functions["split"].call_count == 1
        assert mock_tool_functions["analyze"].call_count == 1
        assert mock_tool_functions["review"].call_count == 1
        assert mock_tool_functions["combine"].call_count == 1
        assert mock_tool_functions["clean"].call_count == 1
        assert mock_tool_functions["deduplicate"].call_count == 1
        assert mock_tool_functions["validate"].call_count == 1
        assert mock_tool_functions["prepare_validation"].call_count == 1

    @pytest.mark.asyncio
    async def test_workflow_stops_on_intermediate_failure(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        mock_tool_functions: dict[str, Mock],
    ) -> None:
        _setup_parser_and_fetcher(mock_tool_functions, pr_metadata, pr_comments, pr_files)
        mock_tool_functions["split"].side_effect = RuntimeError("Split failed")

        with pytest.raises(RuntimeError, match="Split failed"):
            await main("https://github.com/owner/repo/pull/123")

        mock_tool_functions["analyze"].assert_not_called()
        mock_tool_functions["review"].assert_not_called()
        mock_tool_functions["combine"].assert_not_called()
        mock_tool_functions["clean"].assert_not_called()
        mock_tool_functions["deduplicate"].assert_not_called()
        mock_tool_functions["validate"].assert_not_called()
        mock_tool_functions["prepare_validation"].assert_not_called()

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
        _setup_parser_and_fetcher(
            mock_tool_functions,
            pr_metadata,
            pr_comments,
            pr_files,
            owner="test-owner",
            repo="test-repo",
            pr_number=999,
        )

        pr_metadata_copy = pr_metadata.model_copy()
        pr_metadata_copy.number = 999
        mock_fetcher = Mock()
        mock_fetcher.fetch_pr_data.return_value = (pr_metadata_copy, pr_comments, pr_files)
        mock_tool_functions["fetcher_class"].return_value = mock_fetcher

        async def mock_split_func(*args: Any, **kwargs: Any) -> None:
            chunks_path = kwargs["review_dir"] / "chunks.json"
            with chunks_path.open("w") as f:
                f.write(expected_chunks.model_dump_json())

        mock_tool_functions["split"].side_effect = mock_split_func

        async def mock_review_func(*args: Any, **kwargs: Any) -> None:
            review_path = kwargs["review_dir"] / "review_pass_1.json"
            with review_path.open("w") as f:
                json.dump([sample_chunk_analysis_complex.model_dump(mode="json")], f, indent=2)

        mock_tool_functions["review"].side_effect = mock_review_func

        for key in ["analyze", "deduplicate", "validate", "prepare_validation"]:
            mock_tool_functions[key].return_value = None

        await main("https://github.com/test-owner/test-repo/pull/999")

        assert mock_tool_functions["parser_class"].call_count == 1
        assert mock_tool_functions["fetcher_class"].call_count == 1
        assert mock_tool_functions["split"].call_count == 1
        assert mock_tool_functions["analyze"].call_count == 1
        assert mock_tool_functions["review"].call_count == 1
        assert mock_tool_functions["combine"].call_count == 1
        assert mock_tool_functions["clean"].call_count == 1
        assert mock_tool_functions["deduplicate"].call_count == 1
        assert mock_tool_functions["validate"].call_count == 1
        assert mock_tool_functions["prepare_validation"].call_count == 1

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
    ) -> None:
        _setup_parser_and_fetcher(mock_tool_functions, pr_metadata, pr_comments, pr_files)

        for key in ["split", "analyze", "review", "deduplicate", "validate", "prepare_validation"]:
            mock_tool_functions[key].return_value = None

        review_dir = tmp_path / "reviews" / "123"
        review_dir.mkdir(parents=True, exist_ok=True)
        with (review_dir / "chunks.json").open("w") as f:
            f.write(expected_chunks.model_dump_json())

        await main("https://github.com/owner/repo/pull/123")

        assert mock_tool_functions["combine"].call_count == 1
        assert mock_tool_functions["clean"].call_count == 1
        mock_tool_functions["clean"].assert_called_with(review_dir=review_dir)
        assert mock_tool_functions["deduplicate"].call_count == 1

    @pytest.mark.asyncio
    async def test_missing_chunks_file_error(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        mock_tool_functions: dict[str, Mock],
    ) -> None:
        _setup_parser_and_fetcher(mock_tool_functions, pr_metadata, pr_comments, pr_files)

        async def mock_split_func(*args: Any, **kwargs: Any) -> None:
            return None

        mock_tool_functions["split"].side_effect = mock_split_func

        with pytest.raises(FileNotFoundError):
            await main("https://github.com/owner/repo/pull/123")

    @pytest.mark.asyncio
    async def test_branch_passed_to_tools(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        expected_chunks: ChunksList,
        tmp_path: Path,
        mock_tool_functions: dict[str, Mock],
    ) -> None:
        """Verify that branch from pr_metadata.head_branch is passed to all tool calls."""
        _setup_parser_and_fetcher(mock_tool_functions, pr_metadata, pr_comments, pr_files)

        for key in ["split", "analyze", "review", "deduplicate", "validate", "prepare_validation"]:
            mock_tool_functions[key].return_value = None

        review_dir = tmp_path / "reviews" / "123"
        review_dir.mkdir(parents=True, exist_ok=True)
        with (review_dir / "chunks.json").open("w") as f:
            f.write(expected_chunks.model_dump_json())

        await main("https://github.com/owner/repo/pull/123")

        expected_branch = pr_metadata.head_branch
        for key in ["split", "analyze", "review", "deduplicate", "validate"]:
            call_kwargs = mock_tool_functions[key].call_args.kwargs
            assert call_kwargs["branch"] == expected_branch, f"{key} was not passed the correct branch"
