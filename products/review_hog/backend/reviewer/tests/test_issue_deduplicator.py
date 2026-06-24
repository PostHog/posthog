from typing import Any

import pytest
from unittest.mock import patch

from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRMetadata
from products.review_hog.backend.reviewer.models.issue_deduplicator import DuplicateIssue, IssueDeduplication
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.tests.conftest import create_mock_run_sandbox_review
from products.review_hog.backend.reviewer.tools.issue_deduplicator import (
    _comment_line,
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


def _bot_comment(path: str, line: int) -> PRComment:
    # A prior inline comment from the competing reviewer bot we dedupe against.
    return PRComment(
        path=path,
        line=line,
        body="x",
        diff_hunk="",
        user="greptile-apps[bot]",
        created_at="2024-01-01",
    )


# --- Pure pre-filter functions (Pattern A) -----------------------------------


def test_select_dedup_candidates_partitions_by_position() -> None:
    issues = [
        _issue("1-1", "src/auth.py", 45, 50),  # collides with 2-1
        _issue("2-1", "src/auth.py", 48, 55),  # overlaps 1-1
        _issue("1-2", "src/config.py", 23, 25),  # isolated
    ]

    candidates, unique = _select_dedup_candidates(issues, prior_comment_lines=[])

    assert {c.id for c in candidates} == {"1-1", "2-1"}
    assert {u.id for u in unique} == {"1-2"}


def test_select_dedup_candidates_collision_with_prior_comment() -> None:
    # A lone issue becomes a candidate when a prior bot comment sits inside its line range.
    issues = [_issue("1-1", "src/auth.py", 45, 50)]

    candidates, unique = _select_dedup_candidates(issues, prior_comment_lines=[("src/auth.py", 47)])

    assert {c.id for c in candidates} == {"1-1"}
    assert unique == []


def test_select_dedup_candidates_prior_comment_in_other_file_does_not_collide() -> None:
    # A prior comment on a different file (or outside the range) must not pull the issue in.
    issues = [_issue("1-1", "src/auth.py", 45, 50)]

    candidates, unique = _select_dedup_candidates(
        issues, prior_comment_lines=[("src/other.py", 47), ("src/auth.py", 99)]
    )

    assert candidates == []
    assert {u.id for u in unique} == {"1-1"}


def test_comment_line_resolves_position_or_none() -> None:
    def _comment(line: int | None, start_line: int | None) -> PRComment:
        return PRComment(
            path="src/auth.py",
            line=line,
            start_line=start_line,
            body="x",
            diff_hunk="",
            user="greptile-apps[bot]",
            created_at="2024-01-01",
        )

    assert _comment_line(_comment(line=47, start_line=None)) == ("src/auth.py", 47)
    # Falls back to start_line when line is absent.
    assert _comment_line(_comment(line=None, start_line=42)) == ("src/auth.py", 42)
    assert _comment_line(_comment(line=None, start_line=None)) is None


# --- deduplicate_issues orchestration (Pattern B: only the sandbox seam is mocked) ---


@pytest.mark.asyncio
async def test_deduplicate_empty_issues_returns_empty_without_sandbox(pr_metadata: PRMetadata) -> None:
    with patch(f"{_MODULE}.run_sandbox_review") as mock_sandbox:
        result = await deduplicate_issues(
            issues=[],
            pr_metadata=pr_metadata,
            pr_comments=[],
            branch="test-branch",
            repository="test/repo",
        )

    assert result == []
    mock_sandbox.assert_not_called()


@pytest.mark.asyncio
async def test_deduplicate_no_positional_collision_keeps_all_without_sandbox(pr_metadata: PRMetadata) -> None:
    # Distinct files/lines and no prior bot comments -> nothing collides -> LLM dedupe skipped.
    issues = [
        _issue("1-1", "src/a.py", 10, 20),
        _issue("1-2", "src/b.py", 30, 40),
        _issue("1-3", "src/c.py", 50, 60),
    ]

    with patch(f"{_MODULE}.run_sandbox_review") as mock_sandbox:
        result = await deduplicate_issues(
            issues=issues,
            pr_metadata=pr_metadata,
            pr_comments=[],
            branch="test-branch",
            repository="test/repo",
        )

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

    with patch(f"{_MODULE}.run_sandbox_review", create_mock_run_sandbox_review(dedup)):
        result = await deduplicate_issues(
            issues=issues,
            pr_metadata=pr_metadata,
            pr_comments=[],
            branch="test-branch",
            repository="test/repo",
        )

    # The flagged duplicate is dropped; the kept candidate and the isolated issue survive.
    assert {i.id for i in result} == {"1-1", "1-2"}


@pytest.mark.asyncio
async def test_deduplicate_prior_bot_comment_makes_issue_a_candidate(pr_metadata: PRMetadata) -> None:
    # A single issue colliding with a prior greptile comment reaches the LLM, which drops it.
    issues = [_issue("1-1", "src/auth.py", 45, 50)]
    comments = [_bot_comment("src/auth.py", 47)]
    dedup = IssueDeduplication(duplicates=[DuplicateIssue(id="1-1")])

    with patch(f"{_MODULE}.run_sandbox_review", create_mock_run_sandbox_review(dedup)):
        result = await deduplicate_issues(
            issues=issues,
            pr_metadata=pr_metadata,
            pr_comments=comments,
            branch="test-branch",
            repository="test/repo",
        )

    assert result == []


@pytest.mark.asyncio
async def test_deduplicate_raises_when_sandbox_returns_none(pr_metadata: PRMetadata) -> None:
    issues = [
        _issue("1-1", "src/auth.py", 45, 50),
        _issue("2-1", "src/auth.py", 45, 50),
    ]

    async def mock_failure(**kwargs: Any) -> None:
        return None

    with (
        patch(f"{_MODULE}.run_sandbox_review", mock_failure),
        pytest.raises(RuntimeError, match="Issue deduplication failed"),
    ):
        await deduplicate_issues(
            issues=issues,
            pr_metadata=pr_metadata,
            pr_comments=[],
            branch="test-branch",
            repository="test/repo",
        )
