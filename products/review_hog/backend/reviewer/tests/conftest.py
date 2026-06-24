"""Pytest configuration and shared fixtures for tests."""

from pathlib import Path

import pytest

from pydantic import BaseModel

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


def create_mock_run_sandbox_review(model_instance: BaseModel):
    """Mock for `run_sandbox_review` that returns the given validated model.

    Matches the seam's new contract — the executor returns the parsed model (or None on failure)
    rather than writing a file.
    """

    async def mock_func(**kwargs: object) -> BaseModel:
        return model_instance

    return mock_func


@pytest.fixture
def sample_validation() -> IssueValidation:
    """Create a sample valid IssueValidation for testing."""
    return IssueValidation(
        is_valid=True,
        argumentation="The issue correctly identifies a potential bug.",
        category="bug",
    )
