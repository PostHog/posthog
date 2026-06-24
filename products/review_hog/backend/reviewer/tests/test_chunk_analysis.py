from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.review_hog.backend.reviewer.models.chunk_analysis import ChunkAnalysis
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.tests.conftest import create_mock_run_sandbox_review
from products.review_hog.backend.reviewer.tools.chunk_analysis import analyze_chunks

MODULE = "products.review_hog.backend.reviewer.tools.chunk_analysis"


class TestAnalyzeChunks:
    @pytest.mark.asyncio
    async def test_analyzes_every_chunk_and_persists(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        sample_chunk_analysis_simple: ChunkAnalysis,
    ) -> None:
        # Nothing loaded -> every chunk runs through the sandbox, result keyed by chunk_id, all persisted.
        load_mock = MagicMock(return_value={})
        persist_mock = MagicMock()
        with (
            patch(f"{MODULE}.load_chunk_analyses", load_mock),
            patch(f"{MODULE}.persist_chunk_analyses", persist_mock),
            patch(f"{MODULE}.run_sandbox_review", create_mock_run_sandbox_review(sample_chunk_analysis_simple)),
        ):
            result = await analyze_chunks(
                team_id=1,
                report_id="r1",
                head_sha="abc123",
                chunks_data=expected_chunks,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                branch="test-branch",
                repository="test/repo",
            )

        expected_ids = {chunk.chunk_id for chunk in expected_chunks.chunks}
        assert set(result.keys()) == expected_ids
        # persist receives the freshly-analysed chunks (the resume layer separates new from existing).
        persist_mock.assert_called_once()
        assert set(persist_mock.call_args.kwargs["analyses"].keys()) == expected_ids

    @pytest.mark.asyncio
    async def test_resume_skips_sandbox_for_already_analysed_chunks(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        sample_chunk_analysis_simple: ChunkAnalysis,
    ) -> None:
        # A single-chunk PR whose only chunk is already loaded -> no sandbox work, existing result returned.
        single_chunk = ChunksList(chunks=[expected_chunks.chunks[0]])
        existing = {single_chunk.chunks[0].chunk_id: sample_chunk_analysis_simple}
        sandbox_mock = MagicMock(wraps=create_mock_run_sandbox_review(sample_chunk_analysis_simple))
        persist_mock = MagicMock()
        with (
            patch(f"{MODULE}.load_chunk_analyses", MagicMock(return_value=existing)),
            patch(f"{MODULE}.persist_chunk_analyses", persist_mock),
            patch(f"{MODULE}.run_sandbox_review", sandbox_mock),
        ):
            result = await analyze_chunks(
                team_id=1,
                report_id="r1",
                head_sha="abc123",
                chunks_data=single_chunk,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                branch="test-branch",
                repository="test/repo",
            )

        sandbox_mock.assert_not_called()
        persist_mock.assert_not_called()
        assert result == existing

    @pytest.mark.asyncio
    async def test_partial_failure_drops_chunk_but_run_succeeds(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        sample_chunk_analysis_simple: ChunkAnalysis,
    ) -> None:
        # Analysis is informational: a chunk whose sandbox call returns None is simply omitted.
        failing_chunk_id = expected_chunks.chunks[1].chunk_id

        async def flaky_sandbox(**kwargs: Any) -> ChunkAnalysis | None:
            if kwargs["step_name"] == f"chunk-analysis-{failing_chunk_id}":
                return None
            return sample_chunk_analysis_simple

        persist_mock = MagicMock()
        with (
            patch(f"{MODULE}.load_chunk_analyses", MagicMock(return_value={})),
            patch(f"{MODULE}.persist_chunk_analyses", persist_mock),
            patch(f"{MODULE}.run_sandbox_review", flaky_sandbox),
        ):
            result = await analyze_chunks(
                team_id=1,
                report_id="r1",
                head_sha="abc123",
                chunks_data=expected_chunks,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                branch="test-branch",
                repository="test/repo",
            )

        expected_ids = {chunk.chunk_id for chunk in expected_chunks.chunks}
        assert failing_chunk_id not in result
        assert set(result.keys()) == expected_ids - {failing_chunk_id}
        # Only the chunks that succeeded are persisted; the failed one is not.
        assert failing_chunk_id not in persist_mock.call_args.kwargs["analyses"]
