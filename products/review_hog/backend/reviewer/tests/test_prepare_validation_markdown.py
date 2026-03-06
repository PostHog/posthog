import tempfile
from pathlib import Path
from typing import Any

import pytest

from products.review_hog.backend.reviewer.models.chunk_analysis import ChunkAnalysis, ChunkMeta
from products.review_hog.backend.reviewer.models.issue_combination import IssueCombination
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, ChunksList, FileInfo
from products.review_hog.backend.reviewer.tools.prepare_validation_markdown import prepare_validation_markdown


@pytest.fixture
def sample_chunks_data() -> ChunksList:
    """Create sample chunks data."""
    return ChunksList(
        chunks=[
            Chunk(
                chunk_id=1,
                files=[
                    FileInfo(
                        filename="ee/hogai/notebook/notebook_serializer.py",
                    )
                ],
                chunk_type="infrastructure",
                key_changes=["Add MarkdownTokenizer", "Add NotebookSerializer"],
            ),
            Chunk(
                chunk_id=2,
                files=[
                    FileInfo(
                        filename="frontend/src/notebook.tsx",
                    )
                ],
                chunk_type="frontend",
            ),
        ]
    )


@pytest.fixture
def sample_chunk_analysis() -> ChunkAnalysis:
    """Create sample chunk analysis."""
    return ChunkAnalysis(
        goal="Implement core serialization infrastructure for notebook streaming",
        chunk_meta=ChunkMeta(
            chunk_id=1,
            files_in_this_chunk=["ee/hogai/notebook/notebook_serializer.py"],
        ),
    )


@pytest.fixture
def sample_issues() -> IssueCombination:
    """Create sample issues."""
    return IssueCombination(
        issues=[
            Issue(
                id="1-1-1",
                title="Blockquote parser doesn't handle lines starting with '>' (no space)",
                file="ee/hogai/notebook/notebook_serializer.py",
                lines=[LineRange(start=99, end=108)],
                issue="The blockquote parser only matches lines starting with '> '",
                suggestion="Modify the blockquote parser to handle both patterns",
                priority=IssuePriority.SHOULD_FIX,
            ),
            Issue(
                id="1-1-2",
                title="Greedy regex in bold pattern may cause incorrect parsing",
                file="ee/hogai/notebook/notebook_serializer.py",
                lines=[LineRange(start=401, end=None)],
                issue="The bold pattern uses .+? which could match incorrectly",
                suggestion="Use more restrictive pattern",
                priority=IssuePriority.CONSIDER,
            ),
        ]
    )


@pytest.fixture
def sample_validations() -> list[IssueValidation]:
    """Create sample validation results."""
    return [
        IssueValidation(
            is_valid=True,
            argumentation="The issue correctly identifies a CommonMark compliance problem",
            category="compatibility",
        ),
        IssueValidation(
            is_valid=False,
            argumentation="The current pattern works correctly with sequential processing",
            category=None,
        ),
    ]


@pytest.fixture
def sample_pr_metadata() -> dict[str, Any]:
    """Create sample PR metadata."""
    return {
        "number": 35962,
        "title": "Add notebook serialization infrastructure",
        "html_url": "https://github.com/PostHog/posthog/pull/35962",
        "author": "testuser",
        "state": "open",
        "base_branch": "main",
        "head_branch": "feature/notebook-serialization",
    }


@pytest.mark.asyncio
async def test_prepare_validation_markdown_success(
    sample_chunks_data: ChunksList,
    sample_chunk_analysis: ChunkAnalysis,
    sample_issues: IssueCombination,
    sample_validations: list[IssueValidation],
    sample_pr_metadata: dict[str, Any],
) -> None:
    """Test successful markdown report generation."""
    with tempfile.TemporaryDirectory() as temp_dir:
        review_dir = Path(temp_dir)

        # Create chunk analysis file
        analysis_path = review_dir / "chunk-1-analysis.json"
        with analysis_path.open("w") as f:
            f.write(sample_chunk_analysis.model_dump_json())

        # Create missing analysis for chunk 2 to test warning
        # Don't create this file to test missing analysis handling

        # Create issues file
        issues_path = review_dir / "issues_found.json"
        with issues_path.open("w") as f:
            f.write(sample_issues.model_dump_json())

        # Create validation directories and files
        pass1_val_dir = review_dir / "pass1_results" / "validation" / "summaries"
        pass1_val_dir.mkdir(parents=True)

        # Create validation files with proper naming based on issue IDs
        # Issue 1-1-1 -> issue number 1, Issue 1-1-2 -> issue number 2
        for issue, validation in zip(sample_issues.issues, sample_validations, strict=False):
            # Extract issue number from the issue ID (third part)
            issue_number = int(issue.id.split("-")[2])
            val_path = pass1_val_dir / f"chunk-1-issue-{issue_number}-validation-summary.json"
            with val_path.open("w") as f:
                f.write(validation.model_dump_json())

        # Run the function
        await prepare_validation_markdown(
            chunks_data=sample_chunks_data,
            review_dir=review_dir,
            pr_metadata=sample_pr_metadata,
        )

        # Check output file was created
        output_path = review_dir / "review_report.md"
        assert output_path.exists()

        # Read and verify content
        content = output_path.read_text()

        # Check header content
        assert "# PR Review Report" in content
        assert "**PR:** #35962" in content
        assert "**Author:** testuser" in content

        # Check chunk content
        assert "## Chunk 1" in content
        assert "**Type:** infrastructure" in content

        # Check analysis content
        assert "**Goal:** Implement core serialization infrastructure" in content

        # Check issues content - only valid issues should be present
        assert "Issue 1-1-1" in content
        assert "Issue 1-1-2" not in content  # Invalid issue should not be present
        assert "Blockquote parser doesn't handle" in content

        # Check validation content - only valid issue validation should be present
        assert "**Validation Result:** Valid" in content
        assert "**Validation Result:** Invalid" not in content  # Invalid validation should not be shown
        assert "CommonMark compliance problem" in content

        # Check priority is included
        assert "**Priority:** should_fix" in content
