from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.review_hog.backend.reviewer.models.chunk_analysis import ChunkAnalysis, ChunkMeta
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.issues_review import IssuesReview
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.tests.conftest import create_mock_run_sandbox_review
from products.review_hog.backend.reviewer.tools.issues_review import review_chunks

# Every (perspective, chunk) pair produced for a single-chunk list — three perspectives × chunk 1.
ALL_PERSPECTIVE_KEYS = {(1, 1), (2, 1), (3, 1)}


def _analyses(chunk_id: int) -> dict[int, ChunkAnalysis]:
    # The analysis is injected as prompt context per chunk; keyed by chunk id.
    return {
        chunk_id: ChunkAnalysis(
            goal="Authentication logic",
            chunk_meta=ChunkMeta(chunk_id=chunk_id, files_in_this_chunk=["src/auth/login.py"]),
        )
    }


def _single_chunk(expected_chunks: ChunksList) -> ChunksList:
    return ChunksList(chunks=[expected_chunks.chunks[0]])


async def _run(
    *, chunks: ChunksList, analyses: dict[int, ChunkAnalysis], pr_metadata: PRMetadata
) -> dict[tuple[int, int], IssuesReview]:
    return await review_chunks(
        team_id=1,
        report_id="report-1",
        head_sha="abc123",
        chunks_data=chunks,
        analyses=analyses,
        pr_metadata=pr_metadata,
        pr_comments=[],
        pr_files=[],
        branch="test-branch",
        repository="test/repo",
    )


class TestReviewChunks:
    @pytest.mark.asyncio
    async def test_runs_all_three_perspectives_and_persists(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        sample_issues_review_simple: IssuesReview,
    ) -> None:
        # Nothing persisted yet → all three perspectives run for the one chunk and the results persist.
        load = MagicMock(return_value={})
        persist = MagicMock()
        with (
            patch("products.review_hog.backend.reviewer.tools.issues_review.load_perspective_results", load),
            patch("products.review_hog.backend.reviewer.tools.issues_review.persist_perspective_results", persist),
            patch(
                "products.review_hog.backend.reviewer.tools.issues_review.run_sandbox_review",
                create_mock_run_sandbox_review(sample_issues_review_simple),
            ),
        ):
            result = await _run(chunks=_single_chunk(expected_chunks), analyses=_analyses(1), pr_metadata=pr_metadata)

        assert set(result) == ALL_PERSPECTIVE_KEYS
        assert all(r is sample_issues_review_simple for r in result.values())
        # Persisted exactly the newly computed (perspective, chunk) pairs.
        assert set(persist.call_args.kwargs["results"]) == ALL_PERSPECTIVE_KEYS

    @pytest.mark.asyncio
    async def test_resume_skips_sandbox_when_all_loaded(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        sample_issues_review_simple: IssuesReview,
    ) -> None:
        # All (perspective, chunk) pairs already in the DB → sandbox is never invoked and load is returned.
        existing = dict.fromkeys(ALL_PERSPECTIVE_KEYS, sample_issues_review_simple)
        load = MagicMock(return_value=dict(existing))
        persist = MagicMock()
        sandbox_spy = MagicMock(side_effect=create_mock_run_sandbox_review(sample_issues_review_simple))
        with (
            patch("products.review_hog.backend.reviewer.tools.issues_review.load_perspective_results", load),
            patch("products.review_hog.backend.reviewer.tools.issues_review.persist_perspective_results", persist),
            patch("products.review_hog.backend.reviewer.tools.issues_review.run_sandbox_review", sandbox_spy),
        ):
            result = await _run(chunks=_single_chunk(expected_chunks), analyses=_analyses(1), pr_metadata=pr_metadata)

        sandbox_spy.assert_not_called()
        persist.assert_not_called()
        assert result == existing

    @pytest.mark.asyncio
    async def test_partial_failure_drops_only_the_failed_pair(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        sample_issues_review_simple: IssuesReview,
    ) -> None:
        # One perspective fails (returns None); that pair is dropped while the other two survive and persist.
        async def flaky_sandbox(**kwargs: Any) -> IssuesReview | None:
            if kwargs["step_name"] == "issues-review-p2-c1":
                return None
            return sample_issues_review_simple

        load = MagicMock(return_value={})
        persist = MagicMock()
        with (
            patch("products.review_hog.backend.reviewer.tools.issues_review.load_perspective_results", load),
            patch("products.review_hog.backend.reviewer.tools.issues_review.persist_perspective_results", persist),
            patch("products.review_hog.backend.reviewer.tools.issues_review.run_sandbox_review", flaky_sandbox),
        ):
            result = await _run(chunks=_single_chunk(expected_chunks), analyses=_analyses(1), pr_metadata=pr_metadata)

        assert set(result) == {(1, 1), (3, 1)}
        assert set(persist.call_args.kwargs["results"]) == {(1, 1), (3, 1)}
