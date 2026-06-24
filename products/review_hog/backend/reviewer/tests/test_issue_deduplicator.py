from pathlib import Path
from typing import Any

import pytest
from unittest.mock import patch

from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRMetadata
from products.review_hog.backend.reviewer.models.issue_combination import IssueCombination
from products.review_hog.backend.reviewer.models.issue_deduplicator import DuplicateIssue, IssueDeduplication
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.tests.conftest import create_mock_run_sandbox_review
from products.review_hog.backend.reviewer.tools.issue_deduplicator import (
    _comment_line,
    _select_dedup_candidates,
    deduplicate_issues,
)


def _issue(issue_id: str, file: str, start: int, end: int) -> Issue:
    return Issue(
        id=issue_id,
        title=f"Issue {issue_id}",
        file=file,
        lines=[LineRange(start=start, end=end)],
        issue="problem",
        suggestion="fix",
        priority=IssuePriority.SHOULD_FIX,
    )


class TestIssueDeduplicator:
    """Test issue deduplication functionality."""

    @pytest.fixture
    def sample_issues(self) -> list[Issue]:
        """Create sample issues with some duplicates."""
        return [
            Issue(
                id="1-1",
                title="SQL Injection vulnerability",
                file="src/auth.py",
                lines=[LineRange(start=45, end=50)],
                issue="Direct string concatenation in SQL query",
                suggestion="Use parameterized queries",
                priority=IssuePriority.MUST_FIX,
            ),
            Issue(
                id="2-1",
                title="SQL injection risk in authentication",
                file="src/auth.py",
                lines=[LineRange(start=45, end=50)],
                issue="String concatenation creates SQL injection vulnerability",
                suggestion="Use parameterized queries instead",
                priority=IssuePriority.MUST_FIX,
            ),
            Issue(
                id="1-2",
                title="Missing error handling",
                file="src/config.py",
                lines=[LineRange(start=23, end=25)],
                issue="No try-catch around database call",
                suggestion="Wrap in try-except block",
                priority=IssuePriority.SHOULD_FIX,
            ),
            Issue(
                id="3-1",
                title="Performance issue in loop",
                file="src/utils.py",
                lines=[LineRange(start=100, end=110)],
                issue="Inefficient list comprehension",
                suggestion="Use generator expression",
                priority=IssuePriority.CONSIDER,
            ),
        ]

    @pytest.fixture
    def mock_deduplication_result(self) -> IssueDeduplication:
        """Mock deduplication result that identifies 2-1 as duplicate of 1-1."""
        return IssueDeduplication(
            duplicates=[
                DuplicateIssue(
                    id="2-1",
                )
            ],
        )

    @pytest.mark.asyncio
    async def test_deduplicate_issues_success(
        self,
        tmp_path: Path,
        pr_metadata: PRMetadata,
        sample_issues: list[Issue],
        mock_deduplication_result: IssueDeduplication,
    ) -> None:
        """Test successful issue deduplication."""
        # Setup test data
        review_dir = tmp_path / "review"
        review_dir.mkdir()

        # Create issues_cleaned.json (now used instead of issues_found_raw.json)
        issue_combination = IssueCombination(issues=sample_issues)
        with (review_dir / "issues_cleaned.json").open("w") as f:
            f.write(issue_combination.model_dump_json())

        # Mock the sandbox review call
        with patch(
            "products.review_hog.backend.reviewer.tools.issue_deduplicator.run_sandbox_review",
            create_mock_run_sandbox_review(mock_deduplication_result),
        ):
            # Run deduplication
            await deduplicate_issues(
                pr_metadata=pr_metadata,
                review_dir=review_dir,
                branch="test-branch",
                repository="test/repo",
            )

        # Verify deduplicator.json was created
        deduplicator_file = review_dir / "deduplicator.json"
        assert deduplicator_file.exists()

        with deduplicator_file.open() as f:
            result = IssueDeduplication.model_validate_json(f.read())

        assert len(result.duplicates) == 1
        assert result.duplicates[0].id == "2-1"

        # Verify issues_found.json was created with deduplicated issues
        final_issues_file = review_dir / "issues_found.json"
        assert final_issues_file.exists()

        with final_issues_file.open() as f:
            final_combination = IssueCombination.model_validate_json(f.read())

        assert len(final_combination.issues) == 3
        kept_ids = {issue.id for issue in final_combination.issues}
        assert kept_ids == {"1-1", "1-2", "3-1"}

    @pytest.mark.asyncio
    async def test_deduplicate_issues_no_issues(
        self,
        tmp_path: Path,
        pr_metadata: PRMetadata,
    ) -> None:
        """Test deduplication when no issues exist."""
        review_dir = tmp_path / "review"
        review_dir.mkdir()

        # Create empty issues_cleaned.json
        empty_combination = IssueCombination(issues=[])
        with (review_dir / "issues_cleaned.json").open("w") as f:
            f.write(empty_combination.model_dump_json())

        # Run deduplication
        await deduplicate_issues(
            pr_metadata=pr_metadata,
            review_dir=review_dir,
            branch="test-branch",
            repository="test/repo",
        )

        # Verify empty results
        deduplicator_file = review_dir / "deduplicator.json"
        assert deduplicator_file.exists()

        with deduplicator_file.open() as f:
            result = IssueDeduplication.model_validate_json(f.read())

        assert result.duplicates == []

        # Verify empty final issues
        final_issues_file = review_dir / "issues_found.json"
        assert final_issues_file.exists()

        with final_issues_file.open() as f:
            final_combination = IssueCombination.model_validate_json(f.read())

        assert final_combination.issues == []

    @pytest.mark.asyncio
    async def test_deduplicate_issues_already_exists(
        self,
        tmp_path: Path,
        pr_metadata: PRMetadata,
        sample_issues: list[Issue],
    ) -> None:
        """Test that deduplication is skipped if output already exists."""
        review_dir = tmp_path / "review"
        review_dir.mkdir()

        # Create issues_cleaned.json (now used instead of issues_found_raw.json)
        issue_combination = IssueCombination(issues=sample_issues)
        with (review_dir / "issues_cleaned.json").open("w") as f:
            f.write(issue_combination.model_dump_json())

        # Create existing output files
        existing_result = IssueDeduplication(duplicates=[])
        with (review_dir / "deduplicator.json").open("w") as f:
            f.write(existing_result.model_dump_json())

        existing_empty_combination = IssueCombination(issues=[])
        with (review_dir / "issues_found.json").open("w") as f:
            f.write(existing_empty_combination.model_dump_json())

        # Mock sandbox review (should not be called)
        with patch("products.review_hog.backend.reviewer.tools.issue_deduplicator.run_sandbox_review") as mock_sandbox:
            # Run deduplication
            await deduplicate_issues(
                pr_metadata=pr_metadata,
                review_dir=review_dir,
                branch="test-branch",
                repository="test/repo",
            )

            # Verify sandbox was not called
            mock_sandbox.assert_not_called()

    @pytest.mark.asyncio
    async def test_deduplicate_issues_missing_input_file(
        self,
        tmp_path: Path,
        pr_metadata: PRMetadata,
    ) -> None:
        """Test error handling when issues_cleaned.json is missing."""
        review_dir = tmp_path / "review"
        review_dir.mkdir()

        # Run deduplication without creating issues_cleaned.json
        with pytest.raises(FileNotFoundError, match="Cleaned issues file not found"):
            await deduplicate_issues(
                pr_metadata=pr_metadata,
                review_dir=review_dir,
                branch="test-branch",
                repository="test/repo",
            )

    @pytest.mark.asyncio
    async def test_deduplicate_issues_claude_failure(
        self,
        tmp_path: Path,
        pr_metadata: PRMetadata,
        sample_issues: list[Issue],
    ) -> None:
        """Test error handling when Claude Code fails."""
        review_dir = tmp_path / "review"
        review_dir.mkdir()

        # Create issues_cleaned.json (now used instead of issues_found_raw.json)
        issue_combination = IssueCombination(issues=sample_issues)
        with (review_dir / "issues_cleaned.json").open("w") as f:
            f.write(issue_combination.model_dump_json())

        # Mock sandbox review failure
        async def mock_failure(**kwargs: Any) -> bool:
            return False

        with (
            patch("products.review_hog.backend.reviewer.tools.issue_deduplicator.run_sandbox_review", mock_failure),
            pytest.raises(RuntimeError, match="Issue deduplication failed"),
        ):
            await deduplicate_issues(
                pr_metadata=pr_metadata,
                review_dir=review_dir,
                branch="test-branch",
                repository="test/repo",
            )

    def test_duplicate_issue_model(self) -> None:
        """Test DuplicateIssue model validation."""
        duplicate = DuplicateIssue(id="2-1")

        assert duplicate.id == "2-1"

    def test_issue_deduplication_model(self) -> None:
        """Test IssueDeduplication model validation."""
        deduplication = IssueDeduplication(
            duplicates=[
                DuplicateIssue(id="2-1"),
                DuplicateIssue(id="3-1"),
            ],
        )

        assert len(deduplication.duplicates) == 2
        assert deduplication.duplicates[0].id == "2-1"

    @pytest.mark.asyncio
    async def test_deduplication_e2e_integration(
        self,
        tmp_path: Path,
        pr_metadata: PRMetadata,
        sample_issues: list[Issue],
    ) -> None:
        """End-to-end test of deduplication process with realistic data."""
        review_dir = tmp_path / "review"
        review_dir.mkdir()

        # Create issues_cleaned.json with duplicates
        issue_combination = IssueCombination(issues=sample_issues)
        with (review_dir / "issues_cleaned.json").open("w") as f:
            f.write(issue_combination.model_dump_json())

        # Create a realistic deduplication result
        realistic_result = IssueDeduplication(
            duplicates=[
                DuplicateIssue(
                    id="2-1",
                )
            ],
        )

        with patch(
            "products.review_hog.backend.reviewer.tools.issue_deduplicator.run_sandbox_review",
            create_mock_run_sandbox_review(realistic_result),
        ):
            # Run the full deduplication process
            await deduplicate_issues(
                pr_metadata=pr_metadata,
                review_dir=review_dir,
                branch="test-branch",
                repository="test/repo",
            )

        # Verify the complete workflow
        # 1. Deduplication decision is saved
        deduplicator_file = review_dir / "deduplicator.json"
        assert deduplicator_file.exists()

        # 2. Final issues are saved
        final_issues_file = review_dir / "issues_found.json"
        assert final_issues_file.exists()

        with final_issues_file.open() as f:
            final_combination = IssueCombination.model_validate_json(f.read())

        # 3. Only non-duplicate issues remain
        assert len(final_combination.issues) == 3
        final_ids = {issue.id for issue in final_combination.issues}
        assert final_ids == {"1-1", "1-2", "3-1"}

        # 4. Duplicate issue (2-1) is removed
        assert "2-1" not in final_ids

    @pytest.mark.asyncio
    async def test_deduplication_prompt_with_previous_issues(
        self,
        tmp_path: Path,
        pr_metadata: PRMetadata,
        sample_issues: list[Issue],
        pr_comments: list[PRComment],
    ) -> None:
        """Test that previous issues from Greptile are included in the prompt."""
        review_dir = tmp_path / "review"
        review_dir.mkdir()

        # Create issues_cleaned.json
        issue_combination = IssueCombination(issues=sample_issues)
        with (review_dir / "issues_cleaned.json").open("w") as f:
            f.write(issue_combination.model_dump_json())

        # Create pr_comments.jsonl with Greptile comments
        with (review_dir / "pr_comments.jsonl").open("w") as f:
            for comment in pr_comments:
                f.write(comment.model_dump_json() + "\n")

        # Mock the sandbox review call to capture the prompt
        captured_prompt = None

        async def capture_prompt(**kwargs: Any) -> bool:
            nonlocal captured_prompt
            captured_prompt = kwargs["prompt"]
            # Create a valid result file
            output_path = Path(kwargs["output_path"])
            result = IssueDeduplication(duplicates=[])
            with output_path.open("w") as f:
                f.write(result.model_dump_json())
            return True

        with patch("products.review_hog.backend.reviewer.tools.issue_deduplicator.run_sandbox_review", capture_prompt):
            # Run deduplication
            await deduplicate_issues(
                pr_metadata=pr_metadata,
                review_dir=review_dir,
                branch="test-branch",
                repository="test/repo",
            )

        # Verify the prompt includes previous issues
        assert captured_prompt is not None
        assert "<previous_issues>" in captured_prompt

        # Check that Greptile comments are in the prompt
        assert "greptile-apps[bot]" in captured_prompt
        assert "SQL Injection vulnerability" in captured_prompt
        assert "Performance issue" in captured_prompt

        # Check that non-Greptile comments are NOT in the prompt
        assert "regular-user" not in captured_prompt
        assert "Configuration looks good" not in captured_prompt

    @pytest.mark.asyncio
    async def test_deduplication_prompt_without_previous_issues(
        self,
        tmp_path: Path,
        pr_metadata: PRMetadata,
        sample_issues: list[Issue],
    ) -> None:
        """Test that prompt handles missing pr_comments.jsonl gracefully."""
        review_dir = tmp_path / "review"
        review_dir.mkdir()

        # Create issues_cleaned.json
        issue_combination = IssueCombination(issues=sample_issues)
        with (review_dir / "issues_cleaned.json").open("w") as f:
            f.write(issue_combination.model_dump_json())

        # Do NOT create pr_comments.jsonl

        # Mock the sandbox review call to capture the prompt
        captured_prompt = None

        async def capture_prompt(**kwargs: Any) -> bool:
            nonlocal captured_prompt
            captured_prompt = kwargs["prompt"]
            # Create a valid result file
            output_path = Path(kwargs["output_path"])
            result = IssueDeduplication(duplicates=[])
            with output_path.open("w") as f:
                f.write(result.model_dump_json())
            return True

        with patch("products.review_hog.backend.reviewer.tools.issue_deduplicator.run_sandbox_review", capture_prompt):
            # Run deduplication
            await deduplicate_issues(
                pr_metadata=pr_metadata,
                review_dir=review_dir,
                branch="test-branch",
                repository="test/repo",
            )

        # Verify the prompt has empty previous issues
        assert captured_prompt is not None
        assert "<previous_issues>" in captured_prompt
        assert "<previous_issues>\n[]" in captured_prompt

    @pytest.mark.asyncio
    async def test_deduplicate_skips_llm_when_no_positional_collision(
        self,
        tmp_path: Path,
        pr_metadata: PRMetadata,
    ) -> None:
        """When no two issues share a file + overlapping lines, the LLM dedupe is skipped entirely."""
        review_dir = tmp_path / "review"
        review_dir.mkdir()

        # Three issues, all in different files/lines — nothing collides
        isolated_issues = [
            _issue("1-1", "src/a.py", 10, 20),
            _issue("1-2", "src/b.py", 30, 40),
            _issue("1-3", "src/c.py", 50, 60),
        ]
        with (review_dir / "issues_cleaned.json").open("w") as f:
            f.write(IssueCombination(issues=isolated_issues).model_dump_json())

        with patch("products.review_hog.backend.reviewer.tools.issue_deduplicator.run_sandbox_review") as mock_sandbox:
            await deduplicate_issues(
                pr_metadata=pr_metadata,
                review_dir=review_dir,
                branch="test-branch",
                repository="test/repo",
            )

            # No candidates -> the LLM dedupe is never invoked
            mock_sandbox.assert_not_called()

        # deduplicator.json records no duplicates
        with (review_dir / "deduplicator.json").open() as f:
            result = IssueDeduplication.model_validate_json(f.read())
        assert result.duplicates == []

        # All issues are kept
        with (review_dir / "issues_found.json").open() as f:
            final = IssueCombination.model_validate_json(f.read())
        assert {issue.id for issue in final.issues} == {"1-1", "1-2", "1-3"}

    @pytest.mark.asyncio
    async def test_deduplicate_keeps_isolated_issue_alongside_llm_dedupe(
        self,
        tmp_path: Path,
        pr_metadata: PRMetadata,
    ) -> None:
        """Positionally-isolated issues survive even though only colliding candidates reach the LLM."""
        review_dir = tmp_path / "review"
        review_dir.mkdir()

        # 1-1 and 2-1 collide (same file + lines); 1-2 is isolated
        issues = [
            _issue("1-1", "src/auth.py", 45, 50),
            _issue("2-1", "src/auth.py", 45, 50),
            _issue("1-2", "src/other.py", 10, 12),
        ]
        with (review_dir / "issues_cleaned.json").open("w") as f:
            f.write(IssueCombination(issues=issues).model_dump_json())

        captured_prompt: str | None = None

        async def capture_and_mark_dup(**kwargs: Any) -> bool:
            nonlocal captured_prompt
            captured_prompt = kwargs["prompt"]
            Path(kwargs["output_path"]).write_text(
                IssueDeduplication(duplicates=[DuplicateIssue(id="2-1")]).model_dump_json()
            )
            return True

        with patch(
            "products.review_hog.backend.reviewer.tools.issue_deduplicator.run_sandbox_review",
            capture_and_mark_dup,
        ):
            await deduplicate_issues(
                pr_metadata=pr_metadata,
                review_dir=review_dir,
                branch="test-branch",
                repository="test/repo",
            )

        # Only the colliding candidates were sent to the LLM, not the isolated issue
        assert captured_prompt is not None
        assert '"id": "1-1"' in captured_prompt
        assert '"id": "2-1"' in captured_prompt
        assert '"id": "1-2"' not in captured_prompt

        # Survivors: the isolated issue plus the kept candidate; the duplicate is gone
        with (review_dir / "issues_found.json").open() as f:
            final = IssueCombination.model_validate_json(f.read())
        assert {issue.id for issue in final.issues} == {"1-1", "1-2"}

    def test_select_dedup_candidates_partitions_by_position(self) -> None:
        issues = [
            _issue("1-1", "src/auth.py", 45, 50),  # collides with 2-1
            _issue("2-1", "src/auth.py", 48, 55),  # overlaps 1-1
            _issue("1-2", "src/config.py", 23, 25),  # isolated
        ]

        candidates, unique = _select_dedup_candidates(issues, prior_comment_lines=[])

        assert {c.id for c in candidates} == {"1-1", "2-1"}
        assert {u.id for u in unique} == {"1-2"}

    def test_select_dedup_candidates_collision_with_prior_comment(self) -> None:
        # The lone issue collides with a prior review comment sitting inside its line range
        issues = [_issue("1-1", "src/auth.py", 45, 50)]

        candidates, unique = _select_dedup_candidates(issues, prior_comment_lines=[("src/auth.py", 47)])

        assert {c.id for c in candidates} == {"1-1"}
        assert unique == []

    def test_comment_line_resolves_position_or_none(self) -> None:
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
        # Falls back to start_line when line is absent (must only read fields PRComment actually has)
        assert _comment_line(_comment(line=None, start_line=42)) == ("src/auth.py", 42)
        assert _comment_line(_comment(line=None, start_line=None)) is None
