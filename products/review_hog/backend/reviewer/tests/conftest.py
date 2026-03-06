"""Pytest configuration and shared fixtures for tests."""

import json
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import AsyncMock

from products.review_hog.backend.reviewer.models.chunk_analysis import ChunkAnalysis, ChunkMeta
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, IssuesReview, LineRange
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.tools.github_meta import PRComment, PRFile, PRMetadata


@pytest.fixture
def pr_metadata() -> PRMetadata:
    """Load PR metadata from fixture file."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    with (fixtures_dir / "pr_meta.json").open() as f:
        return PRMetadata.model_validate_json(f.read())


@pytest.fixture
def pr_files() -> list[PRFile]:
    """Load PR files from fixture file."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    files = []
    with (fixtures_dir / "pr_files.jsonl").open() as f:
        for line in f:
            if line.strip():
                files.append(PRFile.model_validate_json(line))
    return files


@pytest.fixture
def pr_comments() -> list[PRComment]:
    """Load PR comments from fixture file."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    comments = []
    with (fixtures_dir / "pr_comments.jsonl").open() as f:
        for line in f:
            if line.strip():
                comments.append(PRComment.model_validate_json(line))
    return comments


@pytest.fixture
def expected_chunks() -> ChunksList:
    """Load expected chunks output from fixture file."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    with (fixtures_dir / "expected_chunks.json").open() as f:
        return ChunksList.model_validate_json(f.read())


@pytest.fixture
def mock_run_claude_code_failure() -> AsyncMock:
    """Create a mock for run_code that simulates a failure."""

    async def mock_func(
        **_kwargs: Any,
    ) -> bool:
        """Mock implementation that returns failure."""
        return False

    return AsyncMock(side_effect=mock_func)


@pytest.fixture
def temp_review_dir(tmp_path: Path) -> Path:
    """Create a temporary review directory."""
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    return review_dir


@pytest.fixture
def temp_project_dir(tmp_path: Path) -> Path:
    """Create a temporary project directory."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    return project_dir


@pytest.fixture
def mock_prepare_code_context() -> str:
    """Mock return value for prepare_code_context."""
    return "@src/core/config.py#L10-20\n@src/core/__init__.py"


@pytest.fixture
def sample_issue() -> Issue:
    """Create a sample Issue for testing."""
    return Issue(
        id="1-1",
        title="Potential IndexError in summary access",
        file="src/analyzer.py",
        lines=[LineRange(start=45, end=47)],
        issue="The code accesses summary[0] without checking if the list is empty",
        suggestion="Add length check before accessing: if summary and len(summary) > 0:",
        priority=IssuePriority.MUST_FIX,
    )


@pytest.fixture
def sample_chunk_analysis_simple() -> ChunkAnalysis:
    """Create a simple ChunkAnalysis for testing."""
    return ChunkAnalysis(
        goal="This chunk implements the core authentication logic for the application.",
        chunk_meta=ChunkMeta(
            chunk_id=1,
            files_in_this_chunk=["src/auth/login.py", "src/auth/validate.py"],
        ),
    )


@pytest.fixture
def sample_chunk_analysis_complex(
    sample_chunk_analysis_simple: ChunkAnalysis,
) -> ChunkAnalysis:
    """Create a complex ChunkAnalysis for testing.

    Extends the simple version with additional files.
    """
    # Create a copy to avoid modifying the original
    import copy

    complex_analysis = copy.deepcopy(sample_chunk_analysis_simple)

    # Update for complex test cases
    complex_analysis.goal = "Fix authentication logic and improve security architecture"
    complex_analysis.chunk_meta.chunk_id = 1
    complex_analysis.chunk_meta.files_in_this_chunk.extend(["src/config.py", "src/analyzer.py"])

    # Update other fields
    return complex_analysis


@pytest.fixture
def sample_issues_review_simple() -> IssuesReview:
    """Create a simple IssuesReview for testing."""
    return IssuesReview(
        issues=[
            Issue(
                id="1-1",
                title="SQL Injection vulnerability",
                file="src/auth/login.py",
                lines=[LineRange(start=45, end=50)],
                issue="Direct string concatenation in SQL query",
                suggestion="Use parameterized queries",
                priority=IssuePriority.MUST_FIX,
            )
        ],
    )


@pytest.fixture
def sample_issues_review_complex(sample_issue: Issue) -> IssuesReview:
    """Create a complex IssuesReview with multiple issues for testing."""
    return IssuesReview(
        issues=[
            sample_issue,
            Issue(
                id="1-2",
                title="Missing error handling",
                file="src/auth.py",
                lines=[LineRange(start=23, end=25)],
                issue="No try-catch around database call",
                suggestion="Wrap in try-except block",
                priority=IssuePriority.SHOULD_FIX,
            ),
            Issue(
                id="1-3",
                title="Use constant for magic number",
                file="src/config.py",
                lines=[LineRange(start=10, end=None)],
                issue="Magic number 3600 should be a constant",
                suggestion="Define TOKEN_EXPIRY_SECONDS = 3600",
                priority=IssuePriority.CONSIDER,
            ),
        ],
    )


def create_mock_run_code(
    model_instance: Any,
) -> Callable[[Any], Coroutine[Any, Any, bool]]:
    """Create a mock for CodeExecutor.run_code that returns a specific model instance.

    Args:
        model_instance: The pydantic model instance to return

    Returns:
        Async function that writes the model to output when called
    """

    async def mock_func(self: Any) -> bool:
        """Mock implementation that writes model to output."""
        # Access output_path from the CodeExecutor instance
        output_path = self.output_path
        model_json = json.dumps(model_instance.model_dump(mode="json"), indent=2)
        with Path(output_path).open("w") as f:
            f.write(model_json)
        return True

    # Return the function directly, not wrapped in AsyncMock
    return mock_func


@pytest.fixture
def sample_validation() -> IssueValidation:
    """Create a sample valid IssueValidation for testing."""
    return IssueValidation(
        is_valid=True,
        argumentation="The issue correctly identifies a potential bug.",
        category="bug",
    )


@pytest.fixture
def sample_invalid_validation() -> IssueValidation:
    """Create a sample invalid IssueValidation for testing."""
    return IssueValidation(
        is_valid=False,
        argumentation="This is not a real issue, the check already exists.",
        category="code_quality",
    )
