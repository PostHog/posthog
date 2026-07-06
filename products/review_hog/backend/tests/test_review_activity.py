import pytest
from unittest.mock import AsyncMock, patch

from products.review_hog.backend.reviewer.artefact_content import PRSnapshotArtefact
from products.review_hog.backend.reviewer.constants import (
    CHUNKING_ONESHOT_MAX_ADDITIONS,
    REVIEW_MODEL,
    REVIEW_REASONING_EFFORT,
    REVIEW_RUNTIME_ADAPTER,
)
from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, IssuesReview, LineRange
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, ChunksList, FileInfo
from products.review_hog.backend.temporal.activities import (
    LoadedPerspectiveDTO,
    ReviewChunkInput,
    SandboxStageInput,
    review_chunk_activity,
    split_chunks_activity,
)

_MODULE = "products.review_hog.backend.temporal.activities"


def _review_input(**overrides: object) -> ReviewChunkInput:
    kwargs: dict = {
        "team_id": 1,
        "user_id": 2,
        "report_id": "rep-1",
        "head_sha": "sha1",
        "repository": "o/r",
        "branch": "feat",
        "run_index": 1,
        "chunk_id": 3,
        "pass_number": 1,
        "skill_name": "s-logic",
        "skill_version": 1,
    }
    kwargs.update(overrides)
    return ReviewChunkInput(**kwargs)


def _wave_issue(title: str) -> Issue:
    return Issue(
        id="1-0-1",
        title=title,
        file="a.py",
        lines=[LineRange(start=1)],
        issue="the wave problem",
        suggestion="the wave fix",
        priority=IssuePriority.SHOULD_FIX,
    )


def _snapshot(pr_files: list[PRFile] | None = None) -> PRSnapshotArtefact:
    return PRSnapshotArtefact(
        head_sha="sha1",
        pr_metadata=PRMetadata(
            number=1,
            title="t",
            state="open",
            draft=False,
            created_at="c",
            updated_at="u",
            author="octocat",
            base_branch="main",
            head_branch="feat",
            commits=1,
            additions=1,
            deletions=0,
            changed_files=1,
        ),
        pr_comments=[],
        pr_files=pr_files or [],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "additions,expects_oneshot",
    [
        (CHUNKING_ONESHOT_MAX_ADDITIONS, True),
        (CHUNKING_ONESHOT_MAX_ADDITIONS + 1, False),
    ],
)
async def test_split_chunks_activity_routes_llm_chunking_by_oneshot_gate(additions: int, expects_oneshot: bool) -> None:
    # The one-shot gate is inclusive on reviewable added lines: within it the semantic chunker runs
    # as a direct gateway call, above it the sandbox path is kept. Both cases sit over the
    # single-chunk gate so the LLM chunker (not the deterministic plan) is what routes.
    plan = ChunksList(chunks=[Chunk(chunk_id=1, files=[FileInfo(filename="a.py")])])
    mock_oneshot = AsyncMock(return_value=plan)
    mock_sandbox = AsyncMock(return_value=plan)
    with (
        patch(f"{_MODULE}.Heartbeater"),
        patch(f"{_MODULE}.load_chunk_set", return_value=None),
        patch(
            f"{_MODULE}.load_pr_snapshot",
            return_value=_snapshot(
                pr_files=[PRFile(filename="a.py", status="modified", additions=additions, deletions=0)]
            ),
        ),
        patch(f"{_MODULE}.persist_chunk_set"),
        patch(f"{_MODULE}.run_oneshot_review", mock_oneshot),
        patch(f"{_MODULE}.run_sandbox_review", mock_sandbox),
    ):
        chunk_ids = await split_chunks_activity(
            SandboxStageInput(
                team_id=1,
                user_id=2,
                report_id="rep-1",
                head_sha="sha1",
                repository="o/r",
                branch="feat",
                run_index=1,
            )
        )

    assert chunk_ids == [1]
    assert mock_oneshot.called is expects_oneshot
    assert mock_sandbox.called is not expects_oneshot


@pytest.mark.asyncio
async def test_review_chunk_activity_pins_the_review_model_for_the_perspective_review() -> None:
    # The change's core contract: the perspective-review sandbox turn runs on the pinned REVIEW_* model.
    # The pin kwargs default to None, so dropping them at this one call site would silently fall back to
    # the sandbox default with every plumbing-level test still passing — this activity is the only guard.
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


@pytest.mark.asyncio
async def test_blind_spot_unit_scopes_wave_findings_to_its_chunk_and_steps_as_blind_spots() -> None:
    # A broken (pass, chunk) filter feeds the sweep another chunk's findings or nothing at all.
    # Also pins the blind-spots step name and the lens-list threading.
    done = {
        (1, 3): IssuesReview(issues=[_wave_issue("same-chunk wave finding")]),
        (1, 4): IssuesReview(issues=[_wave_issue("other-chunk wave finding")]),
    }
    mock_review = AsyncMock(return_value=IssuesReview(issues=[]))
    with (
        patch(f"{_MODULE}.Heartbeater"),
        patch(f"{_MODULE}.load_perspective_results", return_value=done),
        patch(f"{_MODULE}.load_pr_snapshot", return_value=_snapshot()),
        patch(
            f"{_MODULE}.load_chunk_set",
            return_value=ChunksList(chunks=[Chunk(chunk_id=3, files=[FileInfo(filename="a.py")])]),
        ),
        patch(f"{_MODULE}.load_prior_findings", return_value=[]),
        patch(f"{_MODULE}.persist_perspective_results"),
        patch(f"{_MODULE}.run_sandbox_review", mock_review),
    ):
        assert (
            await review_chunk_activity(
                _review_input(
                    pass_number=2,
                    skill_name="review-hog-blind-spots-general",
                    blind_spot_check=True,
                    wave_perspectives=[
                        LoadedPerspectiveDTO(
                            pass_number=1,
                            skill_name="review-hog-perspective-logic",
                            version=1,
                            description="logic lens",
                        )
                    ],
                )
            )
            is True
        )

    kwargs = mock_review.call_args.kwargs
    assert kwargs["step_name"] == "blind-spots-c3"
    assert "same-chunk wave finding" in kwargs["prompt"]
    assert "other-chunk wave finding" not in kwargs["prompt"]
    assert "logic lens" in kwargs["prompt"]
