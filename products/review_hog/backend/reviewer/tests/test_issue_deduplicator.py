from pathlib import Path
from typing import Any

import pytest
from unittest.mock import patch

from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRMetadata
from products.review_hog.backend.reviewer.models.issue_combination import IssueCombination
from products.review_hog.backend.reviewer.models.issue_deduplicator import DuplicateIssue, IssueDeduplication
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.tests.conftest import create_mock_run_code
from products.review_hog.backend.reviewer.tools.issue_deduplicator import deduplicate_issues


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

        # Mock the Claude Code call
        with patch(
            "app.tools.issue_deduplicator.CodeExecutor.run_code",
            create_mock_run_code(mock_deduplication_result),
        ):
            # Run deduplication
            await deduplicate_issues(
                pr_metadata=pr_metadata,
                review_dir=review_dir,
                project_dir=str(tmp_path),
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
            project_dir=str(tmp_path),
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

        # Mock Claude Code (should not be called)
        with patch("app.tools.issue_deduplicator.CodeExecutor.run_code") as mock_claude:
            # Run deduplication
            await deduplicate_issues(
                pr_metadata=pr_metadata,
                review_dir=review_dir,
                project_dir=str(tmp_path),
            )

            # Verify Claude was not called
            mock_claude.assert_not_called()

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
                project_dir=str(tmp_path),
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

        # Mock Claude Code failure
        async def mock_failure(self: Any) -> bool:  # noqa: ARG001
            return False

        with (
            patch("app.tools.issue_deduplicator.CodeExecutor.run_code", mock_failure),
            pytest.raises(RuntimeError, match="Issue deduplication failed"),
        ):
            await deduplicate_issues(
                pr_metadata=pr_metadata,
                review_dir=review_dir,
                project_dir=str(tmp_path),
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
            "app.tools.issue_deduplicator.CodeExecutor.run_code",
            create_mock_run_code(realistic_result),
        ):
            # Run the full deduplication process
            await deduplicate_issues(
                pr_metadata=pr_metadata,
                review_dir=review_dir,
                project_dir=str(tmp_path),
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

        # Mock the Claude Code call to capture the prompt
        captured_prompt = None

        async def capture_prompt(self: Any) -> bool:
            nonlocal captured_prompt
            captured_prompt = self.prompt
            # Create a valid result file
            output_path = Path(self.output_path)
            result = IssueDeduplication(duplicates=[])
            with output_path.open("w") as f:
                f.write(result.model_dump_json())
            return True

        with patch("app.tools.issue_deduplicator.CodeExecutor.run_code", capture_prompt):
            # Run deduplication
            await deduplicate_issues(
                pr_metadata=pr_metadata,
                review_dir=review_dir,
                project_dir=str(tmp_path),
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

        # Mock the Claude Code call to capture the prompt
        captured_prompt = None

        async def capture_prompt(self: Any) -> bool:
            nonlocal captured_prompt
            captured_prompt = self.prompt
            # Create a valid result file
            output_path = Path(self.output_path)
            result = IssueDeduplication(duplicates=[])
            with output_path.open("w") as f:
                f.write(result.model_dump_json())
            return True

        with patch("app.tools.issue_deduplicator.CodeExecutor.run_code", capture_prompt):
            # Run deduplication
            await deduplicate_issues(
                pr_metadata=pr_metadata,
                review_dir=review_dir,
                project_dir=str(tmp_path),
            )

        # Verify the prompt has empty previous issues
        assert captured_prompt is not None
        assert "<previous_issues>" in captured_prompt
        assert "<previous_issues>\n[]" in captured_prompt
