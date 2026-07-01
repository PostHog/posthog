import pytest
from unittest.mock import AsyncMock, patch

from products.review_hog.backend.reviewer.constants import REVIEW_MODEL, REVIEW_REASONING_EFFORT, REVIEW_RUNTIME_ADAPTER
from products.review_hog.backend.reviewer.models.issues_review import IssuesReview
from products.review_hog.backend.temporal.activities import ReviewChunkInput, review_chunk_activity

_MODULE = "products.review_hog.backend.temporal.activities"


def _review_input() -> ReviewChunkInput:
    return ReviewChunkInput(
        team_id=1,
        user_id=2,
        report_id="rep-1",
        head_sha="sha1",
        repository="o/r",
        branch="feat",
        run_index=1,
        chunk_id=3,
        pass_number=1,
        skill_name="s-logic",
        skill_version=1,
    )


@pytest.mark.asyncio
async def test_review_chunk_activity_pins_codex_for_the_perspective_review() -> None:
    # The change's core contract: the perspective-review sandbox turn runs on Codex gpt-5.5 @ xhigh. The
    # pin kwargs default to None, so dropping them at this one call site is a silent revert to the Claude
    # default that every plumbing-level test still passes — this activity is the only guard on the routing.
    mock_review = AsyncMock(return_value=IssuesReview(issues=[]))
    with (
        patch(f"{_MODULE}.Heartbeater"),
        patch(f"{_MODULE}._prepare_review_prompt", return_value="review-prompt"),
        patch(f"{_MODULE}.persist_perspective_results"),
        patch(f"{_MODULE}.run_sandbox_review", mock_review),
    ):
        assert await review_chunk_activity(_review_input()) is True

    kwargs = mock_review.call_args.kwargs
    assert (kwargs["runtime_adapter"], kwargs["model"], kwargs["reasoning_effort"]) == (
        REVIEW_RUNTIME_ADAPTER,
        REVIEW_MODEL,
        REVIEW_REASONING_EFFORT,
    )
