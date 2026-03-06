"""Tests for the issue cleaner tool."""

from pathlib import Path

import pytest

from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRFileUpdate
from products.review_hog.backend.reviewer.models.issue_combination import IssueCombination
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.tools.issue_cleaner import clean_issues


@pytest.fixture
def temp_review_dir(tmp_path: Path) -> Path:
    """Create a temporary review directory."""
    review_dir = tmp_path / "test_review"
    review_dir.mkdir()
    return review_dir


def test_clean_issues_filters_by_file(temp_review_dir: Path) -> None:
    """Test that issues are filtered based on file presence in PR."""
    # Create test issues
    issues = [
        Issue(
            id="1-1-1",
            title="Issue in modified file",
            file="app/main.py",
            lines=[LineRange(start=16, end=19)],
            issue="Test issue",
            suggestion="Fix it",
            priority=IssuePriority.SHOULD_FIX,
        ),
        Issue(
            id="1-1-2",
            title="Issue in unmodified file",
            file="app/other.py",
            lines=[LineRange(start=5, end=15)],
            issue="Test issue",
            suggestion="Fix it",
            priority=IssuePriority.SHOULD_FIX,
        ),
    ]

    # Save raw issues
    raw_issues = IssueCombination(issues=issues)
    with (temp_review_dir / "issues_found_raw.json").open("w") as f:
        f.write(raw_issues.model_dump_json())

    # Create PR files with only main.py modified
    pr_file = PRFile(
        filename="app/main.py",
        status="modified",
        additions=5,
        deletions=2,
        changes=[
            PRFileUpdate(
                type="addition",
                new_start_line=15,
                new_end_line=20,
                code="new code",
            )
        ],
    )

    with (temp_review_dir / "pr_files.jsonl").open("w") as f:
        f.write(pr_file.model_dump_json() + "\n")

    # Run the cleaner
    clean_issues(temp_review_dir)

    # Check cleaned issues (in scope)
    with (temp_review_dir / "issues_cleaned.json").open() as f:
        cleaned = IssueCombination.model_validate_json(f.read())
    assert len(cleaned.issues) == 1
    assert cleaned.issues[0].id == "1-1-1"

    # Check out-of-scope issues
    with (temp_review_dir / "issues_outside_scope.json").open() as f:
        outside = IssueCombination.model_validate_json(f.read())
    assert len(outside.issues) == 1
    assert outside.issues[0].id == "1-1-2"


def test_clean_issues_filters_by_line_range(temp_review_dir: Path) -> None:
    """Test that issues are filtered based on line range overlap."""
    # Create test issues
    issues = [
        Issue(
            id="1-1-1",
            title="Issue completely in modified lines",
            file="app/main.py",
            lines=[LineRange(start=15, end=18)],
            issue="Test issue",
            suggestion="Fix it",
            priority=IssuePriority.SHOULD_FIX,
        ),
        Issue(
            id="1-1-2",
            title="Issue outside modified lines",
            file="app/main.py",
            lines=[LineRange(start=50, end=60)],
            issue="Test issue",
            suggestion="Fix it",
            priority=IssuePriority.SHOULD_FIX,
        ),
        Issue(
            id="1-1-3",
            title="Issue partially overlapping",
            file="app/main.py",
            lines=[LineRange(start=18, end=25)],
            issue="Test issue",
            suggestion="Fix it",
            priority=IssuePriority.SHOULD_FIX,
        ),
    ]

    # Save raw issues
    raw_issues = IssueCombination(issues=issues)
    with (temp_review_dir / "issues_found_raw.json").open("w") as f:
        f.write(raw_issues.model_dump_json())

    # Create PR files with specific line ranges
    pr_file = PRFile(
        filename="app/main.py",
        status="modified",
        additions=5,
        deletions=2,
        changes=[
            PRFileUpdate(
                type="addition",
                new_start_line=10,
                new_end_line=20,
                code="new code",
            )
        ],
    )

    with (temp_review_dir / "pr_files.jsonl").open("w") as f:
        f.write(pr_file.model_dump_json() + "\n")

    # Run the cleaner
    clean_issues(temp_review_dir)

    # Check cleaned issues (in scope)
    with (temp_review_dir / "issues_cleaned.json").open() as f:
        cleaned = IssueCombination.model_validate_json(f.read())
    # With overlap logic, both fully contained and partially overlapping issues should be in scope
    assert len(cleaned.issues) == 2
    issue_ids = {issue.id for issue in cleaned.issues}
    assert issue_ids == {"1-1-1", "1-1-3"}

    # Check out-of-scope issues
    with (temp_review_dir / "issues_outside_scope.json").open() as f:
        outside = IssueCombination.model_validate_json(f.read())
    assert len(outside.issues) == 1
    issue_ids = {issue.id for issue in outside.issues}
    assert issue_ids == {"1-1-2"}


def test_clean_issues_handles_single_line_issues(temp_review_dir: Path) -> None:
    """Test that single-line issues are handled correctly."""
    # Create test issues with single line numbers
    issues = [
        Issue(
            id="1-1-1",
            title="Single line issue in range",
            file="app/main.py",
            lines=[LineRange(start=15, end=None)],
            issue="Test issue",
            suggestion="Fix it",
            priority=IssuePriority.SHOULD_FIX,
        ),
        Issue(
            id="1-1-2",
            title="Single line issue outside range",
            file="app/main.py",
            lines=[LineRange(start=100, end=None)],
            issue="Test issue",
            suggestion="Fix it",
            priority=IssuePriority.SHOULD_FIX,
        ),
    ]

    # Save raw issues
    raw_issues = IssueCombination(issues=issues)
    with (temp_review_dir / "issues_found_raw.json").open("w") as f:
        f.write(raw_issues.model_dump_json())

    # Create PR files
    pr_file = PRFile(
        filename="app/main.py",
        status="modified",
        additions=5,
        deletions=2,
        changes=[
            PRFileUpdate(
                type="addition",
                new_start_line=10,
                new_end_line=20,
                code="new code",
            )
        ],
    )

    with (temp_review_dir / "pr_files.jsonl").open("w") as f:
        f.write(pr_file.model_dump_json() + "\n")

    # Run the cleaner
    clean_issues(temp_review_dir)

    # Check results
    with (temp_review_dir / "issues_cleaned.json").open() as f:
        cleaned = IssueCombination.model_validate_json(f.read())
    assert len(cleaned.issues) == 1
    assert cleaned.issues[0].id == "1-1-1"


def test_clean_issues_handles_empty_line_ranges(temp_review_dir: Path) -> None:
    """Test that issues with empty line ranges are handled gracefully."""
    # Create test issues with various line formats
    issues = [
        Issue(
            id="1-1-1",
            title="Empty line ranges",
            file="app/main.py",
            lines=[],
            issue="Test issue",
            suggestion="Fix it",
            priority=IssuePriority.SHOULD_FIX,
        ),
        Issue(
            id="1-1-2",
            title="Valid line format",
            file="app/main.py",
            lines=[LineRange(start=15, end=18)],
            issue="Test issue",
            suggestion="Fix it",
            priority=IssuePriority.SHOULD_FIX,
        ),
    ]

    # Save raw issues
    raw_issues = IssueCombination(issues=issues)
    with (temp_review_dir / "issues_found_raw.json").open("w") as f:
        f.write(raw_issues.model_dump_json())

    # Create PR files
    pr_file = PRFile(
        filename="app/main.py",
        status="modified",
        additions=5,
        deletions=2,
        changes=[
            PRFileUpdate(
                type="addition",
                new_start_line=10,
                new_end_line=20,
                code="new code",
            )
        ],
    )

    with (temp_review_dir / "pr_files.jsonl").open("w") as f:
        f.write(pr_file.model_dump_json() + "\n")

    # Run the cleaner - should not crash
    clean_issues(temp_review_dir)

    # Check that valid issue is in scope, empty lines issue is also in scope
    # (when lines are empty, the issue is considered in-scope if file matches)
    with (temp_review_dir / "issues_cleaned.json").open() as f:
        cleaned = IssueCombination.model_validate_json(f.read())
    assert len(cleaned.issues) == 2


def test_clean_issues_overlap_scenarios(temp_review_dir: Path) -> None:
    """Test specific overlap scenarios that were previously missed."""
    # Create test issues covering the specific scenarios mentioned
    issues = [
        Issue(
            id="1-1-1",
            title="Issue covering split changes (213-223 with changes at 213 and 217-223)",
            file="app/main.py",
            lines=[LineRange(start=213, end=223)],
            issue="Test issue",
            suggestion="Fix it",
            priority=IssuePriority.SHOULD_FIX,
        ),
        Issue(
            id="1-1-2",
            title="Issue larger than changes (205-226 with changes at 217-223)",
            file="app/main.py",
            lines=[LineRange(start=205, end=226)],
            issue="Test issue",
            suggestion="Fix it",
            priority=IssuePriority.SHOULD_FIX,
        ),
        Issue(
            id="1-1-3",
            title="Issue range with single line change (111-113 with change at 112)",
            file="app/main.py",
            lines=[LineRange(start=111, end=113)],
            issue="Test issue",
            suggestion="Fix it",
            priority=IssuePriority.SHOULD_FIX,
        ),
        Issue(
            id="1-1-4",
            title="Issue with no overlap",
            file="app/main.py",
            lines=[LineRange(start=300, end=310)],
            issue="Test issue",
            suggestion="Fix it",
            priority=IssuePriority.SHOULD_FIX,
        ),
    ]

    # Save raw issues
    raw_issues = IssueCombination(issues=issues)
    with (temp_review_dir / "issues_found_raw.json").open("w") as f:
        f.write(raw_issues.model_dump_json())

    # Create PR files with multiple change ranges
    pr_file = PRFile(
        filename="app/main.py",
        status="modified",
        additions=15,
        deletions=5,
        changes=[
            PRFileUpdate(
                type="addition",
                new_start_line=112,
                new_end_line=112,
                code="single line change",
            ),
            PRFileUpdate(
                type="addition",
                new_start_line=213,
                new_end_line=213,
                code="another single line",
            ),
            PRFileUpdate(
                type="modification",
                new_start_line=217,
                new_end_line=223,
                code="block of changes",
            ),
        ],
    )

    with (temp_review_dir / "pr_files.jsonl").open("w") as f:
        f.write(pr_file.model_dump_json() + "\n")

    # Run the cleaner
    clean_issues(temp_review_dir)

    # Check cleaned issues (in scope)
    with (temp_review_dir / "issues_cleaned.json").open() as f:
        cleaned = IssueCombination.model_validate_json(f.read())
    # All issues except 1-1-4 should be in scope
    assert len(cleaned.issues) == 3
    issue_ids = {issue.id for issue in cleaned.issues}
    assert issue_ids == {"1-1-1", "1-1-2", "1-1-3"}

    # Check out-of-scope issues
    with (temp_review_dir / "issues_outside_scope.json").open() as f:
        outside = IssueCombination.model_validate_json(f.read())
    assert len(outside.issues) == 1
    assert outside.issues[0].id == "1-1-4"


def test_clean_issues_handles_multiple_pr_files(temp_review_dir: Path) -> None:
    """Test that multiple PR files are handled correctly."""
    # Create test issues across multiple files
    issues = [
        Issue(
            id="1-1-1",
            title="Issue in first file",
            file="app/main.py",
            lines=[LineRange(start=15, end=18)],
            issue="Test issue",
            suggestion="Fix it",
            priority=IssuePriority.SHOULD_FIX,
        ),
        Issue(
            id="1-1-2",
            title="Issue in second file",
            file="app/utils.py",
            lines=[LineRange(start=25, end=30)],
            issue="Test issue",
            suggestion="Fix it",
            priority=IssuePriority.SHOULD_FIX,
        ),
        Issue(
            id="1-1-3",
            title="Issue in unmodified file",
            file="app/other.py",
            lines=[LineRange(start=10, end=20)],
            issue="Test issue",
            suggestion="Fix it",
            priority=IssuePriority.SHOULD_FIX,
        ),
    ]

    # Save raw issues
    raw_issues = IssueCombination(issues=issues)
    with (temp_review_dir / "issues_found_raw.json").open("w") as f:
        f.write(raw_issues.model_dump_json())

    # Create multiple PR files
    pr_files = [
        PRFile(
            filename="app/main.py",
            status="modified",
            additions=5,
            deletions=2,
            changes=[
                PRFileUpdate(
                    type="addition",
                    new_start_line=10,
                    new_end_line=20,
                    code="new code",
                )
            ],
        ),
        PRFile(
            filename="app/utils.py",
            status="modified",
            additions=3,
            deletions=1,
            changes=[
                PRFileUpdate(
                    type="addition",
                    new_start_line=20,
                    new_end_line=35,
                    code="new utils",
                )
            ],
        ),
    ]

    with (temp_review_dir / "pr_files.jsonl").open("w") as f:
        for pr_file in pr_files:
            f.write(pr_file.model_dump_json() + "\n")

    # Run the cleaner
    clean_issues(temp_review_dir)

    # Check cleaned issues
    with (temp_review_dir / "issues_cleaned.json").open() as f:
        cleaned = IssueCombination.model_validate_json(f.read())
    assert len(cleaned.issues) == 2
    issue_ids = {issue.id for issue in cleaned.issues}
    assert issue_ids == {"1-1-1", "1-1-2"}

    # Check out-of-scope issues
    with (temp_review_dir / "issues_outside_scope.json").open() as f:
        outside = IssueCombination.model_validate_json(f.read())
    assert len(outside.issues) == 1
    assert outside.issues[0].id == "1-1-3"
