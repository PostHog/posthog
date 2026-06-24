from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import pytest
from pytest import MonkeyPatch
from unittest.mock import AsyncMock, MagicMock, patch

from jinja2 import Environment

from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, IssuesReview, LineRange
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.tests.conftest import create_mock_run_sandbox_review
from products.review_hog.backend.reviewer.tools.issues_review import (
    generate_prompts,
    process_chunk,
    review_chunks,
    review_chunks_pass,
)


@pytest.fixture
def mock_run_claude_code_issues_review_failure() -> Callable[..., Coroutine[Any, Any, bool]]:
    """Create a mock for run_sandbox_review that fails."""

    async def mock_func(**kwargs: Any) -> bool:
        """Mock implementation that returns failure."""
        return False

    return mock_func


class TestGeneratePrompts:
    """Test generate_prompts function."""

    @pytest.mark.asyncio
    async def test_generate_prompts_pass1(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
    ) -> None:
        prompt_paths = await generate_prompts(
            chunks_list=expected_chunks,
            pr_metadata=pr_metadata,
            pr_comments=pr_comments,
            pr_files=pr_files,
            review_dir=temp_review_dir,
            pass_number=1,
        )

        assert len(prompt_paths) == len(expected_chunks.chunks)

        # Check prompts were created
        for i, path in enumerate(prompt_paths):
            assert path.exists()
            assert path.name == f"chunk-{i + 1}-code-prompt.md"

            # Verify prompt content
            content = path.read_text()
            assert "Pass 1: Logic & Correctness Focus" in content
            assert '"IssuesReview"' in content  # Schema included
            assert pr_metadata.title in content

    @pytest.mark.asyncio
    async def test_generate_prompts_skip_existing(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
    ) -> None:
        """Test that existing prompts are skipped."""
        # Create existing prompt
        prompt_dir = temp_review_dir / "pass1_prompts"
        prompt_dir.mkdir()
        existing_prompt = prompt_dir / "chunk-1-code-prompt.md"
        existing_prompt.write_text("Existing prompt")

        prompt_paths = await generate_prompts(
            chunks_list=expected_chunks,
            pr_metadata=pr_metadata,
            pr_comments=pr_comments,
            pr_files=pr_files,
            review_dir=temp_review_dir,
            pass_number=1,
        )

        # Should still return path but not overwrite
        assert len(prompt_paths) == len(expected_chunks.chunks)
        assert prompt_paths[0] == existing_prompt
        assert existing_prompt.read_text() == "Existing prompt"

    @pytest.mark.asyncio
    async def test_generate_prompts_missing_template(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test error handling when template is missing."""

        def mock_get_template(self: Environment, name: str) -> MagicMock:  # noqa: ARG001
            if "pass1_focus" in name:
                raise Exception("Template not found")
            # Return a mock template for other cases
            return MagicMock(render=lambda **kwargs: "mock content")  # noqa: ARG005

        with monkeypatch.context() as m:
            m.setattr(Environment, "get_template", mock_get_template)

            with pytest.raises(FileNotFoundError, match="Could not load pass1_focus.jinja"):
                await generate_prompts(
                    chunks_list=expected_chunks,
                    pr_metadata=pr_metadata,
                    pr_comments=pr_comments,
                    pr_files=pr_files,
                    review_dir=temp_review_dir,
                    pass_number=1,
                )


class TestProcessChunk:
    """Test process_chunk function."""

    @pytest.mark.asyncio
    async def test_process_chunk_success(
        self,
        temp_review_dir: Path,
        sample_issues_review_simple: IssuesReview,
    ) -> None:
        """Test successful chunk processing."""
        # Create prompt file
        prompt_path = temp_review_dir / "chunk-1-code-prompt.md"
        prompt_path.write_text("Test prompt content")

        output_path = temp_review_dir / "chunk-1-issues-review.json"

        with patch(
            "products.review_hog.backend.reviewer.tools.issues_review.run_sandbox_review",
            create_mock_run_sandbox_review(sample_issues_review_simple),
        ):
            result = await process_chunk(
                chunk_id=1,
                pass_number=1,
                prompt_path=prompt_path,
                output_path=output_path,
                branch="test-branch",
                repository="test/repo",
            )

        assert result is True
        assert output_path.exists()

        # Verify output is valid IssuesReview
        review = IssuesReview.model_validate_json(output_path.read_text())
        assert review.issues is not None
        # Check we have at least one must_fix issue
        must_fix_count = sum(1 for issue in review.issues if issue.priority == IssuePriority.MUST_FIX)
        assert must_fix_count == 1

    @pytest.mark.asyncio
    async def test_process_chunk_passes_step_name(
        self,
        temp_review_dir: Path,
        sample_issues_review_simple: IssuesReview,
    ) -> None:
        """The sandbox step name encodes both the pass and the chunk."""
        prompt_path = temp_review_dir / "chunk-7-code-prompt.md"
        prompt_path.write_text("Test prompt content")
        output_path = temp_review_dir / "chunk-7-issues-review.json"

        mock_sandbox = AsyncMock(side_effect=create_mock_run_sandbox_review(sample_issues_review_simple))
        with patch("products.review_hog.backend.reviewer.tools.issues_review.run_sandbox_review", mock_sandbox):
            await process_chunk(
                chunk_id=7,
                pass_number=2,
                prompt_path=prompt_path,
                output_path=output_path,
                branch="test-branch",
                repository="test/repo",
            )

        assert mock_sandbox.call_args.kwargs["step_name"] == "issues-review-p2-c7"

    @pytest.mark.asyncio
    async def test_process_chunk_missing_prompt(self, temp_review_dir: Path) -> None:
        """Test error when prompt file is missing."""
        prompt_path = temp_review_dir / "nonexistent-prompt.md"
        output_path = temp_review_dir / "output.json"

        with pytest.raises(FileNotFoundError, match="Prompt file not found"):
            await process_chunk(
                chunk_id=1,
                pass_number=1,
                prompt_path=prompt_path,
                output_path=output_path,
                branch="test-branch",
                repository="test/repo",
            )

    @pytest.mark.asyncio
    async def test_process_chunk_llm_failure(
        self,
        temp_review_dir: Path,
        mock_run_claude_code_issues_review_failure: Callable[..., Coroutine[Any, Any, bool]],
    ) -> None:
        """Test handling of LLM failure."""
        prompt_path = temp_review_dir / "chunk-1-code-prompt.md"
        prompt_path.write_text("Test prompt")

        output_path = temp_review_dir / "output.json"

        with patch(
            "products.review_hog.backend.reviewer.tools.issues_review.run_sandbox_review",
            mock_run_claude_code_issues_review_failure,
        ):
            result = await process_chunk(
                chunk_id=1,
                pass_number=1,
                prompt_path=prompt_path,
                output_path=output_path,
                branch="test-branch",
                repository="test/repo",
            )

        assert result is False


class TestReviewChunksPass:
    """Test review_chunks_pass function."""

    @pytest.mark.asyncio
    async def test_review_chunks_pass_single_chunk(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
        sample_issues_review_simple: IssuesReview,
    ) -> None:
        """Test reviewing a single pass with chunks."""
        # Use only first chunk for simplicity
        single_chunk = ChunksList(chunks=[expected_chunks.chunks[0]])

        with patch(
            "products.review_hog.backend.reviewer.tools.issues_review.run_sandbox_review",
            create_mock_run_sandbox_review(sample_issues_review_simple),
        ):
            await review_chunks_pass(
                chunks_data=single_chunk,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                branch="test-branch",
                repository="test/repo",
                pass_number=1,
            )

        # Verify directories created
        assert (temp_review_dir / "pass1_results").exists()
        assert (temp_review_dir / "pass1_prompts").exists()

        # Verify result file created
        result_file = temp_review_dir / "pass1_results" / "chunk-1-issues-review.json"
        assert result_file.exists()

        # Verify it's a valid IssuesReview
        review = IssuesReview.model_validate_json(result_file.read_text())
        assert review.issues is not None

    @pytest.mark.asyncio
    async def test_review_chunks_pass_skip_existing(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
        sample_issues_review_simple: IssuesReview,
    ) -> None:
        """Test that existing results are skipped."""
        # Create existing result
        results_dir = temp_review_dir / "pass1_results"
        results_dir.mkdir()
        existing_result = results_dir / "chunk-1-issues-review.json"
        existing_result.write_text(sample_issues_review_simple.model_dump_json())

        mock_run_sandbox = AsyncMock(side_effect=create_mock_run_sandbox_review(sample_issues_review_simple))
        with patch("products.review_hog.backend.reviewer.tools.issues_review.run_sandbox_review", mock_run_sandbox):
            await review_chunks_pass(
                chunks_data=expected_chunks,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                branch="test-branch",
                repository="test/repo",
                pass_number=1,
            )

        # Should not call run_sandbox_review for chunk 1
        # But should process other chunks
        mock_run_sandbox.assert_called()

        # Original file should be unchanged
        review = IssuesReview.model_validate_json(existing_result.read_text())
        # Check that it's a valid IssuesReview
        assert review.issues is not None

    @pytest.mark.asyncio
    async def test_review_chunks_pass_invalid_pass_number(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
    ) -> None:
        """Test error handling for invalid pass number."""
        with pytest.raises(ValueError, match="Invalid pass number: 99"):
            await review_chunks_pass(
                chunks_data=expected_chunks,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                branch="test-branch",
                repository="test/repo",
                pass_number=99,
            )


class TestReviewChunks:
    """Test review_chunks main function."""

    @pytest.mark.asyncio
    async def test_review_chunks_runs_all_lenses(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
        sample_issues_review_simple: IssuesReview,
    ) -> None:
        """All three lenses run (concurrently, order-independent) and each writes its results."""
        single_chunk = ChunksList(chunks=[expected_chunks.chunks[0]])

        with patch(
            "products.review_hog.backend.reviewer.tools.issues_review.run_sandbox_review",
            create_mock_run_sandbox_review(sample_issues_review_simple),
        ):
            await review_chunks(
                chunks_data=single_chunk,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                branch="test-branch",
                repository="test/repo",
            )

        # Every lens produced results — order is not guaranteed since they run concurrently
        for pass_num in [1, 2, 3]:
            assert (temp_review_dir / f"pass{pass_num}_results").exists()
            result_file = temp_review_dir / f"pass{pass_num}_results" / "chunk-1-issues-review.json"
            assert result_file.exists()

    @pytest.mark.asyncio
    async def test_review_chunks_invokes_each_pass_once(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
    ) -> None:
        """review_chunks fans out to exactly the three lenses, regardless of completion order."""
        single_chunk = ChunksList(chunks=[expected_chunks.chunks[0]])

        seen_passes: list[int] = []

        async def fake_pass(**kwargs: Any) -> None:
            seen_passes.append(kwargs["pass_number"])

        with patch(
            "products.review_hog.backend.reviewer.tools.issues_review.review_chunks_pass",
            side_effect=fake_pass,
        ) as mock_pass:
            await review_chunks(
                chunks_data=single_chunk,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                branch="test-branch",
                repository="test/repo",
            )

        assert mock_pass.call_count == 3
        assert sorted(seen_passes) == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_review_chunks_pass_failure_propagates(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
    ) -> None:
        """A failure in any lens surfaces from review_chunks."""
        with patch("products.review_hog.backend.reviewer.tools.issues_review.generate_prompts") as mock_prompts:
            mock_prompts.side_effect = FileNotFoundError("Template error")

            with pytest.raises(FileNotFoundError, match="Template error"):
                await review_chunks(
                    chunks_data=expected_chunks,
                    pr_metadata=pr_metadata,
                    pr_comments=pr_comments,
                    pr_files=pr_files,
                    review_dir=temp_review_dir,
                    branch="test-branch",
                    repository="test/repo",
                )


class TestEndToEnd:
    """End-to-end test for complete review flow."""

    @pytest.mark.asyncio
    async def test_review_chunks_e2e(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
    ) -> None:
        """Each lens runs against every chunk and writes a valid result, with its own prompts."""
        # Distinct priority per pass so we can assert the right lens wrote each file
        reviews_by_pass = {
            1: IssuesReview(
                issues=[
                    Issue(
                        id="1-1",
                        title="Logic error in config parsing",
                        file="src/core/config.py",
                        lines=[LineRange(start=10, end=15)],
                        issue="Incorrect parsing logic",
                        suggestion="Fix parsing algorithm",
                        priority=IssuePriority.MUST_FIX,
                    )
                ],
            ),
            2: IssuesReview(
                issues=[
                    Issue(
                        id="1-1",
                        title="Potential security issue",
                        file="src/core/config.py",
                        lines=[LineRange(start=20, end=25)],
                        issue="Sensitive data in logs",
                        suggestion="Sanitize log output",
                        priority=IssuePriority.SHOULD_FIX,
                    )
                ],
            ),
            3: IssuesReview(
                issues=[
                    Issue(
                        id="1-1",
                        title="Performance optimization",
                        file="src/core/config.py",
                        lines=[LineRange(start=30, end=35)],
                        issue="Inefficient config loading",
                        suggestion="Cache configuration",
                        priority=IssuePriority.CONSIDER,
                    )
                ],
            ),
        }

        async def mock_run_sandbox(**kwargs: Any) -> bool:
            """Return a different review per lens, keyed off the pass-tagged step name."""
            step_name = kwargs["step_name"]
            pass_num = 2 if "-p2-" in step_name else 3 if "-p3-" in step_name else 1
            review = reviews_by_pass[pass_num]
            Path(kwargs["output_path"]).write_text(review.model_dump_json(indent=2))
            return True

        with patch(
            "products.review_hog.backend.reviewer.tools.issues_review.run_sandbox_review",
            mock_run_sandbox,
        ):
            await review_chunks(
                chunks_data=expected_chunks,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                branch="test-branch",
                repository="test/repo",
            )

        priority_by_pass = {
            1: IssuePriority.MUST_FIX,
            2: IssuePriority.SHOULD_FIX,
            3: IssuePriority.CONSIDER,
        }
        for pass_num in [1, 2, 3]:
            # Check directories
            assert (temp_review_dir / f"pass{pass_num}_results").exists()
            assert (temp_review_dir / f"pass{pass_num}_prompts").exists()

            # Check validation subdirectories
            validation_dir = temp_review_dir / f"pass{pass_num}_results" / "validation"
            assert (validation_dir / "prompts").exists()
            assert (validation_dir / "summaries").exists()
            assert (validation_dir / "combined").exists()

            # Check all chunks have results and carry the priority that lens emits
            for chunk in expected_chunks.chunks:
                result_file = temp_review_dir / f"pass{pass_num}_results" / f"chunk-{chunk.chunk_id}-issues-review.json"
                assert result_file.exists()
                review = IssuesReview.model_validate_json(result_file.read_text())
                assert any(issue.priority == priority_by_pass[pass_num] for issue in review.issues)

            # Check prompts were generated for each chunk
            for chunk in expected_chunks.chunks:
                prompt_file = temp_review_dir / f"pass{pass_num}_prompts" / f"chunk-{chunk.chunk_id}-code-prompt.md"
                assert prompt_file.exists()
                content = prompt_file.read_text()
                assert f"Pass {pass_num}" in content or f"PASS_NUMBER={pass_num}" in content
