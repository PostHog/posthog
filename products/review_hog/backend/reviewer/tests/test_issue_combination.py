import json
from pathlib import Path

import pytest

from products.review_hog.backend.reviewer.models.issue_combination import IssueCombination
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, IssuesReview, LineRange
from products.review_hog.backend.reviewer.tools.issue_combination import combine_issues


class TestCombineIssues:
    """Test combine_issues function."""

    def test_combine_issues_single_pass(self, temp_review_dir: Path) -> None:
        """Test combining issues from a single pass."""
        # Create pass1 results
        pass1_dir = temp_review_dir / "pass1_results"
        pass1_dir.mkdir(parents=True)

        # Create chunk summaries with issues
        chunk1_issues = IssuesReview(
            issues=[
                Issue(
                    id="1-1",
                    title="SQL Injection vulnerability",
                    file="src/auth.py",
                    lines=[LineRange(start=45, end=50)],
                    issue="Direct string concatenation in SQL query",
                    suggestion="Use parameterized queries",
                    priority=IssuePriority.MUST_FIX,
                )
            ],
        )

        chunk2_issues = IssuesReview(
            issues=[
                Issue(
                    id="1-2",
                    title="Missing error handling",
                    file="src/config.py",
                    lines=[LineRange(start=23, end=25)],
                    issue="No try-catch around database call",
                    suggestion="Wrap in try-except block",
                    priority=IssuePriority.SHOULD_FIX,
                )
            ],
        )

        # Save chunk summaries
        (pass1_dir / "chunk-1-issues-review.json").write_text(chunk1_issues.model_dump_json())
        (pass1_dir / "chunk-2-issues-review.json").write_text(chunk2_issues.model_dump_json())

        # Run combine_issues
        combine_issues(temp_review_dir)

        # Verify combined results
        issues_found_file = temp_review_dir / "issues_found_raw.json"
        assert issues_found_file.exists()

        with issues_found_file.open() as f:
            combined_data = json.load(f)

        # Validate the structure
        assert len(combined_data["issues"]) == 2
        assert combined_data["issues"][0]["id"] == "1-1"
        assert combined_data["issues"][1]["id"] == "1-2"
        assert combined_data["issues"][0]["title"] == "SQL Injection vulnerability"
        assert combined_data["issues"][1]["title"] == "Missing error handling"

    def test_combine_issues_multiple_passes(self, temp_review_dir: Path) -> None:
        """Test combining issues from multiple passes."""
        # Create multiple pass directories with issues
        for pass_num in range(1, 4):
            pass_dir = temp_review_dir / f"pass{pass_num}_results"
            pass_dir.mkdir(parents=True)

            # Create issues for each pass
            for chunk_num in range(1, 3):
                issues = IssuesReview(
                    issues=[
                        Issue(
                            id=f"{pass_num}-{chunk_num}",
                            title=f"Issue from pass {pass_num} chunk {chunk_num}",
                            file=f"src/file{chunk_num}.py",
                            lines=[LineRange(start=10, end=20)],
                            issue=f"Problem in pass {pass_num}",
                            suggestion=f"Fix for pass {pass_num}",
                            priority=IssuePriority.MUST_FIX if pass_num == 1 else IssuePriority.SHOULD_FIX,
                        )
                    ],
                )

                chunk_file = pass_dir / f"chunk-{chunk_num}-issues-review.json"
                chunk_file.write_text(issues.model_dump_json())

        # Run combine_issues
        combine_issues(temp_review_dir)

        # Verify combined results
        issues_found_file = temp_review_dir / "issues_found_raw.json"
        assert issues_found_file.exists()

        with issues_found_file.open() as f:
            combined_data = json.load(f)

        # Should have 6 issues total (3 passes * 2 chunks * 1 issue each)
        assert len(combined_data["issues"]) == 6

        # Verify we have issues from all passes (by checking IDs contain pass numbers)
        pass_numbers = {int(issue["id"].split("-")[0]) for issue in combined_data["issues"]}
        assert pass_numbers == {1, 2, 3}

        # Verify issue IDs are correct
        expected_ids = {f"{p}-{c}" for p in range(1, 4) for c in range(1, 3)}
        actual_ids = {issue["id"] for issue in combined_data["issues"]}
        assert actual_ids == expected_ids

    def test_combine_issues_no_issues(self, temp_review_dir: Path) -> None:
        """Test combining when there are no issues."""
        # Create empty pass directories
        for pass_num in range(1, 4):
            pass_dir = temp_review_dir / f"pass{pass_num}_results"
            pass_dir.mkdir(parents=True)

        # Run combine_issues
        combine_issues(temp_review_dir)

        # Verify empty results
        issues_found_file = temp_review_dir / "issues_found_raw.json"
        assert issues_found_file.exists()

        with issues_found_file.open() as f:
            combined_data = json.load(f)

        assert combined_data["issues"] == []

    def test_combine_issues_some_empty_passes(self, temp_review_dir: Path) -> None:
        """Test combining when some passes have no issues."""
        # Create pass1 with issues
        pass1_dir = temp_review_dir / "pass1_results"
        pass1_dir.mkdir(parents=True)

        issues = IssuesReview(
            issues=[
                Issue(
                    id="1-1",
                    title="Critical issue",
                    file="src/main.py",
                    lines=[LineRange(start=50, end=55)],
                    issue="Security vulnerability",
                    suggestion="Apply security fix",
                    priority=IssuePriority.MUST_FIX,
                )
            ],
        )

        (pass1_dir / "chunk-1-issues-review.json").write_text(issues.model_dump_json())

        # Create empty pass2 and pass3 directories
        (temp_review_dir / "pass2_results").mkdir(parents=True)
        (temp_review_dir / "pass3_results").mkdir(parents=True)

        # Run combine_issues
        combine_issues(temp_review_dir)

        # Verify results
        issues_found_file = temp_review_dir / "issues_found_raw.json"
        assert issues_found_file.exists()

        with issues_found_file.open() as f:
            combined_data = json.load(f)

        assert len(combined_data["issues"]) == 1
        assert combined_data["issues"][0]["id"] == "1-1"
        assert combined_data["issues"][0]["title"] == "Critical issue"

    def test_combine_issues_empty_issues_list(self, temp_review_dir: Path) -> None:
        """Test combining when chunk files exist but have empty issues lists."""
        # Create pass1 with chunk files containing empty issues
        pass1_dir = temp_review_dir / "pass1_results"
        pass1_dir.mkdir(parents=True)

        empty_issues = IssuesReview(
            issues=[],
        )

        (pass1_dir / "chunk-1-issues-review.json").write_text(empty_issues.model_dump_json())
        (pass1_dir / "chunk-2-issues-review.json").write_text(empty_issues.model_dump_json())

        # Run combine_issues
        combine_issues(temp_review_dir)

        # Verify empty results
        issues_found_file = temp_review_dir / "issues_found_raw.json"
        assert issues_found_file.exists()

        with issues_found_file.open() as f:
            combined_data = json.load(f)

        assert combined_data["issues"] == []

    def test_combine_issues_mixed_chunk_patterns(self, temp_review_dir: Path) -> None:
        """Test combining with different chunk file naming patterns."""
        pass1_dir = temp_review_dir / "pass1_results"
        pass1_dir.mkdir(parents=True)

        # Create chunk files with different numbers
        for chunk_id in [1, 3, 5]:  # Non-consecutive chunk IDs
            issues = IssuesReview(
                issues=[
                    Issue(
                        id=f"1-{chunk_id}",
                        title=f"Issue in chunk {chunk_id}",
                        file=f"src/chunk{chunk_id}.py",
                        lines=[LineRange(start=1, end=10)],
                        issue=f"Problem in chunk {chunk_id}",
                        suggestion="Fix it",
                        priority=IssuePriority.CONSIDER,
                    )
                ],
            )

            chunk_file = pass1_dir / f"chunk-{chunk_id}-issues-review.json"
            chunk_file.write_text(issues.model_dump_json())

        # Run combine_issues
        combine_issues(temp_review_dir)

        # Verify results
        issues_found_file = temp_review_dir / "issues_found_raw.json"
        assert issues_found_file.exists()

        with issues_found_file.open() as f:
            combined_data = json.load(f)

        assert len(combined_data["issues"]) == 3
        chunk_ids = {issue["id"] for issue in combined_data["issues"]}
        assert chunk_ids == {"1-1", "1-3", "1-5"}

    def test_combine_issues_invalid_json_file(self, temp_review_dir: Path) -> None:
        """Test error handling when a chunk file contains invalid JSON."""
        pass1_dir = temp_review_dir / "pass1_results"
        pass1_dir.mkdir(parents=True)

        # Create a valid chunk file
        valid_issues = IssuesReview(
            issues=[
                Issue(
                    id="1-1",
                    title="Valid issue",
                    file="src/valid.py",
                    lines=[LineRange(start=1, end=5)],
                    issue="A valid problem",
                    suggestion="Fix it properly",
                    priority=IssuePriority.MUST_FIX,
                )
            ],
        )

        (pass1_dir / "chunk-1-issues-review.json").write_text(valid_issues.model_dump_json())

        # Create an invalid JSON file
        (pass1_dir / "chunk-2-issues-review.json").write_text('{"invalid": "json", "missing": "closing_brace"')

        # Should raise an exception
        with pytest.raises(Exception) as exc_info:
            combine_issues(temp_review_dir)

        assert "Failed to load issues review" in str(exc_info.value)

    def test_combine_issues_validates_as_issue_combination(self, temp_review_dir: Path) -> None:
        """Test that the combined issues can be validated as IssueCombination model."""
        # Create test data
        pass1_dir = temp_review_dir / "pass1_results"
        pass1_dir.mkdir(parents=True)

        issues = IssuesReview(
            issues=[
                Issue(
                    id="1-1",
                    title="Test issue",
                    file="src/test.py",
                    lines=[LineRange(start=1, end=5)],
                    issue="Test problem",
                    suggestion="Test fix",
                    priority=IssuePriority.MUST_FIX,
                )
            ],
        )

        (pass1_dir / "chunk-1-issues-review.json").write_text(issues.model_dump_json())

        # Run combine_issues
        combine_issues(temp_review_dir)

        # Verify the output can be loaded as IssueCombination
        issues_found_file = temp_review_dir / "issues_found_raw.json"
        with issues_found_file.open() as f:
            raw_data = json.load(f)

        # Validate that raw_data can be loaded as IssueCombination model
        issue_combination = IssueCombination.model_validate(raw_data)

        assert len(issue_combination.issues) == 1
        assert issue_combination.issues[0].id == "1-1"
        assert issue_combination.issues[0].title == "Test issue"
