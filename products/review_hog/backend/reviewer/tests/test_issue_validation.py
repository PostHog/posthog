import pytest
from unittest.mock import patch

from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.tests.conftest import create_mock_run_sandbox_review
from products.review_hog.backend.reviewer.tools.issue_validation import validate_issues

_MODULE = "products.review_hog.backend.reviewer.tools.issue_validation"


def _issue(issue_id: str, file: str = "src/core/config.py") -> Issue:
    # middle id segment is the chunk_id the issue must resolve against
    return Issue(
        id=issue_id,
        title="Potential IndexError",
        file=file,
        lines=[LineRange(start=10, end=20)],
        issue="Accesses list without bounds check",
        suggestion="Add a length guard",
        priority=IssuePriority.MUST_FIX,
    )


class TestValidateIssues:
    @pytest.mark.asyncio
    async def test_resolvable_issues_are_keyed_by_id(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_files: list[PRFile],
        sample_validation: IssueValidation,
    ) -> None:
        # chunk_ids 1 and 2 exist in expected_chunks -> both issues validate
        issues = [_issue("1-1-1"), _issue("1-2-1")]

        with patch(f"{_MODULE}.run_sandbox_review", create_mock_run_sandbox_review(sample_validation)):
            result = await validate_issues(
                chunks_data=expected_chunks,
                pr_metadata=pr_metadata,
                pr_files=pr_files,
                issues=issues,
                branch="test-branch",
                repository="test/repo",
            )

        assert set(result.keys()) == {"1-1-1", "1-2-1"}
        assert all(v is sample_validation for v in result.values())

    @pytest.mark.asyncio
    async def test_chunk_not_found_issue_is_skipped_without_sandbox_call(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_files: list[PRFile],
        sample_validation: IssueValidation,
    ) -> None:
        # chunk_id 99 is absent from expected_chunks -> the issue is dropped and never reaches the sandbox
        good = _issue("1-1-1")
        missing_chunk = _issue("1-99-1")

        called_step_names: list[str] = []

        async def recording_sandbox(**kwargs: object) -> IssueValidation:
            called_step_names.append(str(kwargs["step_name"]))
            return sample_validation

        with patch(f"{_MODULE}.run_sandbox_review", recording_sandbox):
            result = await validate_issues(
                chunks_data=expected_chunks,
                pr_metadata=pr_metadata,
                pr_files=pr_files,
                issues=[good, missing_chunk],
                branch="test-branch",
                repository="test/repo",
            )

        assert set(result.keys()) == {"1-1-1"}
        assert called_step_names == ["validation-1-1-1"]

    @pytest.mark.parametrize("bad_id", ["1-1", "1-1-1-1", "1"])
    @pytest.mark.asyncio
    async def test_malformed_id_is_skipped(
        self,
        bad_id: str,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_files: list[PRFile],
        sample_validation: IssueValidation,
    ) -> None:
        # ids that don't split into exactly 3 parts are dropped before chunk resolution
        with patch(f"{_MODULE}.run_sandbox_review", create_mock_run_sandbox_review(sample_validation)):
            result = await validate_issues(
                chunks_data=expected_chunks,
                pr_metadata=pr_metadata,
                pr_files=pr_files,
                issues=[_issue(bad_id)],
                branch="test-branch",
                repository="test/repo",
            )

        assert result == {}

    @pytest.mark.asyncio
    async def test_sandbox_failure_drops_issue_from_result(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_files: list[PRFile],
        sample_validation: IssueValidation,
    ) -> None:
        # one issue's sandbox call returns None; only the successful one survives in the dict
        async def selective_sandbox(**kwargs: object) -> IssueValidation | None:
            return None if kwargs["step_name"] == "validation-1-2-1" else sample_validation

        with patch(f"{_MODULE}.run_sandbox_review", selective_sandbox):
            result = await validate_issues(
                chunks_data=expected_chunks,
                pr_metadata=pr_metadata,
                pr_files=pr_files,
                issues=[_issue("1-1-1"), _issue("1-2-1")],
                branch="test-branch",
                repository="test/repo",
            )

        assert set(result.keys()) == {"1-1-1"}

    @pytest.mark.asyncio
    async def test_no_resolvable_issues_returns_empty_dict(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_files: list[PRFile],
        sample_validation: IssueValidation,
    ) -> None:
        # nothing resolvable -> empty dict and the sandbox seam is never invoked
        with patch(f"{_MODULE}.run_sandbox_review", create_mock_run_sandbox_review(sample_validation)) as _:
            result = await validate_issues(
                chunks_data=expected_chunks,
                pr_metadata=pr_metadata,
                pr_files=pr_files,
                issues=[],
                branch="test-branch",
                repository="test/repo",
            )

        assert result == {}
