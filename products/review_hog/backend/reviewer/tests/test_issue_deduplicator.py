from typing import Any

import pytest
from unittest.mock import AsyncMock, patch

from products.review_hog.backend.reviewer.constants import (
    DEDUP_MODEL,
    DEDUP_ONESHOT_MAX_FINDINGS,
    DEDUP_REASONING_EFFORT,
    DEDUP_RUNTIME_ADAPTER,
)
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRMetadata
from products.review_hog.backend.reviewer.models.issue_deduplicator import DuplicateIssue, IssueDeduplication
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.tests.conftest import create_mock_run_sandbox_review
from products.review_hog.backend.reviewer.tools.issue_deduplicator import (
    _comment_range,
    _select_dedup_candidates,
    deduplicate_issues,
)

_MODULE = "products.review_hog.backend.reviewer.tools.issue_deduplicator"


def _issue(issue_id: str, file: str, start: int, end: int | None) -> Issue:
    return Issue(
        id=issue_id,
        title=f"Issue {issue_id}",
        file=file,
        lines=[LineRange(start=start, end=end)],
        issue="problem",
        suggestion="fix",
        priority=IssuePriority.SHOULD_FIX,
    )


def _prior_comment(path: str, line: int, user: str) -> PRComment:
    # A prior inline comment. The dedup never branches on the author — it's passed to the LLM as
    # context only.
    return PRComment(
        path=path,
        line=line,
        body="x",
        diff_hunk="",
        user=user,
        created_at="2024-01-01",
    )


# --- Pure pre-filter functions (Pattern A) -----------------------------------


def test_select_dedup_candidates_partitions_by_position() -> None:
    issues = [
        _issue("1-1", "src/auth.py", 45, 50),  # collides with 2-1
        _issue("2-1", "src/auth.py", 48, 55),  # overlaps 1-1
        _issue("1-2", "src/config.py", 23, 25),  # isolated
    ]

    candidates, unique = _select_dedup_candidates(issues, prior_comment_ranges=[])

    assert {c.id for c in candidates} == {"1-1", "2-1"}
    assert {u.id for u in unique} == {"1-2"}


def test_select_dedup_candidates_collision_with_prior_comment() -> None:
    # A lone issue becomes a candidate when a prior bot comment sits inside its line range.
    issues = [_issue("1-1", "src/auth.py", 45, 50)]

    candidates, unique = _select_dedup_candidates(
        issues, prior_comment_ranges=[("src/auth.py", LineRange(start=47, end=47))]
    )

    assert {c.id for c in candidates} == {"1-1"}
    assert unique == []


def test_select_dedup_candidates_prior_comment_in_other_file_does_not_collide() -> None:
    # A prior comment on a different file (or outside the range) must not pull the issue in.
    issues = [_issue("1-1", "src/auth.py", 45, 50)]

    candidates, unique = _select_dedup_candidates(
        issues,
        prior_comment_ranges=[
            ("src/other.py", LineRange(start=47, end=47)),
            ("src/auth.py", LineRange(start=99, end=99)),
        ],
    )

    assert candidates == []
    assert {u.id for u in unique} == {"1-1"}


def _ranged_comment(line: int | None, start_line: int | None) -> PRComment:
    return PRComment(
        path="src/auth.py",
        line=line,
        start_line=start_line,
        body="x",
        diff_hunk="",
        user="greptile-apps[bot]",
        created_at="2024-01-01",
    )


def test_comment_range_resolves_span_or_none() -> None:
    assert _comment_range(_ranged_comment(line=47, start_line=None)) == ("src/auth.py", LineRange(start=47, end=47))
    # A multi-line comment spans [start_line, line] — not just its end line.
    assert _comment_range(_ranged_comment(line=20, start_line=10)) == ("src/auth.py", LineRange(start=10, end=20))
    # Falls back to start_line when line is absent.
    assert _comment_range(_ranged_comment(line=None, start_line=42)) == ("src/auth.py", LineRange(start=42, end=42))
    assert _comment_range(_ranged_comment(line=None, start_line=None)) is None


def test_multiline_comment_collides_across_its_whole_range() -> None:
    # Collapsing a multi-line comment (10-20) to its end line let a finding on 12-14 skip the LLM
    # dedup entirely and re-post what a reviewer already raised; only end-line hits collided.
    rng = _comment_range(_ranged_comment(line=20, start_line=10))
    assert rng is not None
    inside = _issue("1-1", "src/auth.py", 12, 14)
    outside = _issue("1-2", "src/auth.py", 30, 31)

    candidates, unique = _select_dedup_candidates([inside, outside], prior_comment_ranges=[rng])

    assert {c.id for c in candidates} == {"1-1"}
    assert {u.id for u in unique} == {"1-2"}


# --- deduplicate_issues orchestration (Pattern B: only the LLM executor seams are mocked) ---
# Within the one-shot gate (every small set below) the LLM dedupe is `run_oneshot_review`; the
# sandbox seam only fires above DEDUP_ONESHOT_MAX_FINDINGS (covered by the routing test).


@pytest.mark.asyncio
async def test_deduplicate_empty_issues_returns_empty_without_llm(pr_metadata: PRMetadata) -> None:
    with (
        patch(f"{_MODULE}.run_oneshot_review") as mock_oneshot,
        patch(f"{_MODULE}.run_sandbox_review") as mock_sandbox,
    ):
        result = await deduplicate_issues(
            team_id=1,
            user_id=1,
            issues=[],
            pr_metadata=pr_metadata,
            pr_comments=[],
            branch="test-branch",
            repository="test/repo",
        )

    assert result == []
    mock_oneshot.assert_not_called()
    mock_sandbox.assert_not_called()


@pytest.mark.asyncio
async def test_deduplicate_no_positional_collision_keeps_all_without_llm(pr_metadata: PRMetadata) -> None:
    # Distinct files/lines and no prior bot comments -> nothing collides -> LLM dedupe skipped.
    issues = [
        _issue("1-1", "src/a.py", 10, 20),
        _issue("1-2", "src/b.py", 30, 40),
        _issue("1-3", "src/c.py", 50, 60),
    ]

    with (
        patch(f"{_MODULE}.run_oneshot_review") as mock_oneshot,
        patch(f"{_MODULE}.run_sandbox_review") as mock_sandbox,
    ):
        result = await deduplicate_issues(
            team_id=1,
            user_id=1,
            issues=issues,
            pr_metadata=pr_metadata,
            pr_comments=[],
            branch="test-branch",
            repository="test/repo",
        )

    mock_oneshot.assert_not_called()
    mock_sandbox.assert_not_called()
    assert {i.id for i in result} == {"1-1", "1-2", "1-3"}


@pytest.mark.asyncio
async def test_deduplicate_drops_llm_flagged_duplicate_keeps_isolated(pr_metadata: PRMetadata) -> None:
    # 1-1 and 2-1 collide (same file + lines); 1-2 is isolated and must survive untouched.
    issues = [
        _issue("1-1", "src/auth.py", 45, 50),
        _issue("2-1", "src/auth.py", 45, 50),
        _issue("1-2", "src/other.py", 10, 12),
    ]
    dedup = IssueDeduplication(duplicates=[DuplicateIssue(id="2-1")])

    with patch(f"{_MODULE}.run_oneshot_review", create_mock_run_sandbox_review(dedup)):
        result = await deduplicate_issues(
            team_id=1,
            user_id=1,
            issues=issues,
            pr_metadata=pr_metadata,
            pr_comments=[],
            branch="test-branch",
            repository="test/repo",
        )

    # The flagged duplicate is dropped; the kept candidate and the isolated issue survive.
    assert {i.id for i in result} == {"1-1", "1-2"}


@pytest.mark.asyncio
async def test_deduplicate_prior_comment_makes_issue_a_candidate(pr_metadata: PRMetadata) -> None:
    # Any prior inline comment overlapping a finding sends it to the LLM, which drops it. The author
    # is a non-privileged handle on purpose: dedup no longer filters by author (it used to recognize
    # one hardcoded bot), and nothing in our code branches on who wrote the comment.
    issues = [_issue("1-1", "src/auth.py", 45, 50)]
    comments = [_prior_comment("src/auth.py", 47, user="some-reviewer[bot]")]
    dedup = IssueDeduplication(duplicates=[DuplicateIssue(id="1-1")])

    with patch(f"{_MODULE}.run_oneshot_review", create_mock_run_sandbox_review(dedup)):
        result = await deduplicate_issues(
            team_id=1,
            user_id=1,
            issues=issues,
            pr_metadata=pr_metadata,
            pr_comments=comments,
            branch="test-branch",
            repository="test/repo",
        )

    assert result == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "issue_count,expects_oneshot",
    [
        (DEDUP_ONESHOT_MAX_FINDINGS, True),
        (DEDUP_ONESHOT_MAX_FINDINGS + 1, False),
    ],
)
async def test_dedup_llm_call_routes_by_oneshot_gate(
    pr_metadata: PRMetadata, issue_count: int, expects_oneshot: bool
) -> None:
    # The gate counts issues entering dedup and is inclusive: within it the dedupe is a direct
    # one-shot gateway call; above it the previous sandbox path is kept. Every issue shares the same
    # file+lines so the positional pre-filter always produces candidates and the LLM call fires.
    issues = [_issue(f"1-{i}", "src/auth.py", 45, 50) for i in range(issue_count)]
    keep_all = IssueDeduplication(duplicates=[])

    with (
        patch(f"{_MODULE}.run_oneshot_review", new=AsyncMock(return_value=keep_all)) as mock_oneshot,
        patch(f"{_MODULE}.run_sandbox_review", new=AsyncMock(return_value=keep_all)) as mock_sandbox,
    ):
        result = await deduplicate_issues(
            team_id=1,
            user_id=1,
            issues=issues,
            pr_metadata=pr_metadata,
            pr_comments=[],
            branch="test-branch",
            repository="test/repo",
        )

    assert len(result) == issue_count
    assert mock_oneshot.called is expects_oneshot
    assert mock_sandbox.called is not expects_oneshot
    if not expects_oneshot:
        # The pin kwargs default to None, so dropping them at this call site would silently fall
        # back to the sandbox default model — same contract as the chunking and review pin tests.
        kwargs = mock_sandbox.call_args.kwargs
        assert (kwargs["runtime_adapter"], kwargs["model"], kwargs["reasoning_effort"]) == (
            DEDUP_RUNTIME_ADAPTER,
            DEDUP_MODEL,
            DEDUP_REASONING_EFFORT,
        )


@pytest.mark.asyncio
async def test_deduplicate_propagates_llm_failure(pr_metadata: PRMetadata) -> None:
    # The executor raises on failure (instead of returning None); deduplicate_issues lets it
    # propagate so the dedup activity fails, is retried, then fails the run loudly.
    issues = [
        _issue("1-1", "src/auth.py", 45, 50),
        _issue("2-1", "src/auth.py", 45, 50),
    ]

    async def mock_failure(**kwargs: Any) -> None:
        raise RuntimeError("llm call crashed")

    with (
        patch(f"{_MODULE}.run_oneshot_review", mock_failure),
        pytest.raises(RuntimeError, match="llm call crashed"),
    ):
        await deduplicate_issues(
            team_id=1,
            user_id=1,
            issues=issues,
            pr_metadata=pr_metadata,
            pr_comments=[],
            branch="test-branch",
            repository="test/repo",
        )
