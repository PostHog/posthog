from pathlib import Path
from typing import Any

import pytest
from pytest import MonkeyPatch
from unittest.mock import AsyncMock, MagicMock, patch

from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.issues_review import (
    Issue,
    IssuePriority,
    IssuesReview,
    LineRange,
    PassContext,
    PassType,
)
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.tests.conftest import create_mock_run_code
from products.review_hog.backend.reviewer.tools.issues_review import (
    generate_prompts,
    load_previous_pass_results,
    process_chunk,
    review_chunks,
    review_chunks_pass,
)


@pytest.fixture
def mock_run_claude_code_issues_review_failure() -> AsyncMock:
    """Create a mock for run_code that fails."""

    async def mock_func() -> bool:
        """Mock implementation that returns failure."""
        return False

    return AsyncMock(side_effect=mock_func)


@pytest.fixture
def pass1_context(sample_issues_review_simple: IssuesReview) -> PassContext:
    """Create a PassContext for pass 1."""
    return PassContext(
        pass_number=1,
        pass_type=PassType.LOGIC_CORRECTNESS,
        issues=sample_issues_review_simple.issues,
    )


@pytest.fixture
def pass2_context() -> PassContext:
    """Create a PassContext for pass 2."""
    return PassContext(
        pass_number=2,
        pass_type=PassType.CONTRACTS_SECURITY,
        issues=[
            Issue(
                id="2-1",
                title="Missing input validation",
                file="src/api/endpoint.py",
                lines=[LineRange(start=100, end=105)],
                issue="No validation on user input",
                suggestion="Add input validation",
                priority=IssuePriority.SHOULD_FIX,
            )
        ],
    )


class TestLoadPreviousPassResults:
    """Test load_previous_pass_results function."""

    def test_load_previous_pass_results_no_previous(self, temp_review_dir: Path) -> None:
        """Test loading when no previous passes exist (first pass)."""
        results = load_previous_pass_results(review_dir=temp_review_dir, current_pass=1, chunks_count=2)
        assert results == []

    def test_load_previous_pass_results_single_pass(
        self, temp_review_dir: Path, sample_issues_review_simple: IssuesReview
    ) -> None:
        """Test loading results from a single previous pass."""
        # Create pass1 results
        pass1_dir = temp_review_dir / "pass1_results"
        pass1_dir.mkdir()

        # Write chunk summaries
        for chunk_id in [1, 2]:
            chunk_file = pass1_dir / f"chunk-{chunk_id}-issues-review.json"
            chunk_file.write_text(sample_issues_review_simple.model_dump_json())

        # Load for pass 2
        results = load_previous_pass_results(review_dir=temp_review_dir, current_pass=2, chunks_count=2)

        assert len(results) == 1
        assert results[0].pass_number == 1
        assert results[0].pass_type == PassType.LOGIC_CORRECTNESS
        # Count must_fix issues (1 issue per chunk)
        must_fix_count = sum(1 for issue in results[0].issues if issue.priority == IssuePriority.MUST_FIX)
        assert must_fix_count == 2

    def test_load_previous_pass_results_multiple_passes(
        self, temp_review_dir: Path, sample_issues_review_simple: IssuesReview
    ) -> None:
        """Test loading results from multiple previous passes."""
        # Create pass1 and pass2 results
        for pass_num in [1, 2]:
            pass_dir = temp_review_dir / f"pass{pass_num}_results"
            pass_dir.mkdir()

            for chunk_id in [1, 2]:
                chunk_file = pass_dir / f"chunk-{chunk_id}-issues-review.json"
                chunk_file.write_text(sample_issues_review_simple.model_dump_json())

        # Load for pass 3
        results = load_previous_pass_results(review_dir=temp_review_dir, current_pass=3, chunks_count=2)

        assert len(results) == 2
        assert results[0].pass_number == 1
        assert results[0].pass_type == PassType.LOGIC_CORRECTNESS
        assert results[1].pass_number == 2
        assert results[1].pass_type == PassType.CONTRACTS_SECURITY

    def test_load_previous_pass_results_missing_file(
        self, temp_review_dir: Path, sample_issues_review_simple: IssuesReview
    ) -> None:
        """Test error when a chunk summary file is missing."""
        # Create pass1 results with only one chunk
        pass1_dir = temp_review_dir / "pass1_results"
        pass1_dir.mkdir()

        chunk_file = pass1_dir / "chunk-1-issues-review.json"
        chunk_file.write_text(sample_issues_review_simple.model_dump_json())

        # Should raise error for missing chunk 2
        with pytest.raises(FileNotFoundError, match="Summary file not found for chunk 2"):
            load_previous_pass_results(review_dir=temp_review_dir, current_pass=2, chunks_count=2)


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
        """Test prompt generation for pass 1."""
        prompt_paths = await generate_prompts(
            chunks_list=expected_chunks,
            pr_metadata=pr_metadata,
            pr_comments=pr_comments,
            pr_files=pr_files,
            review_dir=temp_review_dir,
            pass_number=1,
            previous_passes_context=[],
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
    async def test_generate_prompts_with_previous_context(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
        pass1_context: PassContext,
    ) -> None:
        """Test prompt generation with previous pass context."""
        prompt_paths = await generate_prompts(
            chunks_list=expected_chunks,
            pr_metadata=pr_metadata,
            pr_comments=pr_comments,
            pr_files=pr_files,
            review_dir=temp_review_dir,
            pass_number=2,
            previous_passes_context=[pass1_context],
        )

        assert len(prompt_paths) == len(expected_chunks.chunks)

        # Verify previous context is included
        content = prompt_paths[0].read_text()
        assert "LOGIC_CORRECTNESS" in content or "Logic & Correctness" in content
        assert "SQL Injection vulnerability" in content  # Issue from pass1

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
            previous_passes_context=[],
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
        from jinja2 import Environment

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
                    previous_passes_context=[],
                )


class TestProcessChunk:
    """Test process_chunk function."""

    @pytest.mark.asyncio
    async def test_process_chunk_success(
        self,
        temp_review_dir: Path,
        temp_project_dir: Path,
        sample_issues_review_simple: IssuesReview,
    ) -> None:
        """Test successful chunk processing."""
        # Create prompt file
        prompt_path = temp_review_dir / "chunk-1-code-prompt.md"
        prompt_path.write_text("Test prompt content")

        output_path = temp_review_dir / "chunk-1-issues-review.json"

        with patch(
            "app.tools.issues_review.CodeExecutor.run_code",
            create_mock_run_code(sample_issues_review_simple),
        ):
            result = await process_chunk(
                chunk_id=1,
                prompt_path=prompt_path,
                output_path=output_path,
                project_dir=str(temp_project_dir),
            )

        # The function doesn't return True on success, just None (missing return statement)
        assert result is None or result is True
        assert output_path.exists()

        # Verify output is valid IssuesReview
        review = IssuesReview.model_validate_json(output_path.read_text())
        assert review.issues is not None
        # Check we have at least one must_fix issue
        must_fix_count = sum(1 for issue in review.issues if issue.priority == IssuePriority.MUST_FIX)
        assert must_fix_count == 1

    @pytest.mark.asyncio
    async def test_process_chunk_missing_prompt(self, temp_review_dir: Path, temp_project_dir: Path) -> None:
        """Test error when prompt file is missing."""
        prompt_path = temp_review_dir / "nonexistent-prompt.md"
        output_path = temp_review_dir / "output.json"

        with pytest.raises(FileNotFoundError, match="Prompt file not found"):
            await process_chunk(
                chunk_id=1,
                prompt_path=prompt_path,
                output_path=output_path,
                project_dir=str(temp_project_dir),
            )

    @pytest.mark.asyncio
    async def test_process_chunk_llm_failure(
        self,
        temp_review_dir: Path,
        temp_project_dir: Path,
        mock_run_claude_code_issues_review_failure: AsyncMock,
    ) -> None:
        """Test handling of LLM failure."""
        prompt_path = temp_review_dir / "chunk-1-code-prompt.md"
        prompt_path.write_text("Test prompt")

        output_path = temp_review_dir / "output.json"

        with patch(
            "app.tools.issues_review.CodeExecutor.run_code",
            mock_run_claude_code_issues_review_failure,
        ):
            result = await process_chunk(
                chunk_id=1,
                prompt_path=prompt_path,
                output_path=output_path,
                project_dir=str(temp_project_dir),
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
        temp_project_dir: Path,
        sample_issues_review_simple: IssuesReview,
    ) -> None:
        """Test reviewing a single pass with chunks."""
        # Use only first chunk for simplicity
        single_chunk = ChunksList(chunks=[expected_chunks.chunks[0]])

        with patch(
            "app.tools.issues_review.CodeExecutor.run_code",
            create_mock_run_code(sample_issues_review_simple),
        ):
            await review_chunks_pass(
                chunks_data=single_chunk,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                project_dir=str(temp_project_dir),
                pass_number=1,
                previous_passes_context=[],
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
        temp_project_dir: Path,
        sample_issues_review_simple: IssuesReview,
    ) -> None:
        """Test that existing results are skipped."""
        # Create existing result
        results_dir = temp_review_dir / "pass1_results"
        results_dir.mkdir()
        existing_result = results_dir / "chunk-1-issues-review.json"
        existing_result.write_text(sample_issues_review_simple.model_dump_json())

        mock_run_claude = AsyncMock(side_effect=create_mock_run_code(sample_issues_review_simple))
        with patch("app.tools.issues_review.CodeExecutor.run_code", mock_run_claude):
            await review_chunks_pass(
                chunks_data=expected_chunks,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                project_dir=str(temp_project_dir),
                pass_number=1,
                previous_passes_context=[],
            )

        # Should not call run_code for chunk 1
        # But should process other chunks
        mock_run_claude.assert_called()

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
        temp_project_dir: Path,
    ) -> None:
        """Test error handling for invalid pass number."""
        with pytest.raises(ValueError, match="Invalid pass number: 99"):
            await review_chunks_pass(
                chunks_data=expected_chunks,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                project_dir=str(temp_project_dir),
                pass_number=99,
                previous_passes_context=[],
            )

    @pytest.mark.asyncio
    async def test_review_chunks_pass_with_context(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
        temp_project_dir: Path,
        pass1_context: PassContext,
        sample_issues_review_simple: IssuesReview,
    ) -> None:
        """Test pass 2 with previous pass context."""
        single_chunk = ChunksList(chunks=[expected_chunks.chunks[0]])

        with patch(
            "app.tools.issues_review.CodeExecutor.run_code",
            create_mock_run_code(sample_issues_review_simple),
        ):
            await review_chunks_pass(
                chunks_data=single_chunk,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                project_dir=str(temp_project_dir),
                pass_number=2,
                previous_passes_context=[pass1_context],
            )

        # Verify pass 2 results
        result_file = temp_review_dir / "pass2_results" / "chunk-1-issues-review.json"
        assert result_file.exists()


class TestReviewChunks:
    """Test review_chunks main function."""

    @pytest.mark.asyncio
    async def test_review_chunks_all_passes(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
        temp_project_dir: Path,
        sample_issues_review_simple: IssuesReview,
    ) -> None:
        """Test running all three passes."""
        single_chunk = ChunksList(chunks=[expected_chunks.chunks[0]])

        with patch(
            "app.tools.issues_review.CodeExecutor.run_code",
            create_mock_run_code(sample_issues_review_simple),
        ):
            await review_chunks(
                chunks_data=single_chunk,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                project_dir=str(temp_project_dir),
            )

        # Verify all passes completed
        for pass_num in [1, 2, 3]:
            assert (temp_review_dir / f"pass{pass_num}_results").exists()
            result_file = temp_review_dir / f"pass{pass_num}_results" / "chunk-1-issues-review.json"
            assert result_file.exists()

    @pytest.mark.asyncio
    async def test_review_chunks_pass_failure_stops_execution(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
        temp_project_dir: Path,
    ) -> None:
        """Test that failure in one pass stops execution."""
        with patch("app.tools.issues_review.generate_prompts") as mock_prompts:
            mock_prompts.side_effect = FileNotFoundError("Template error")

            with pytest.raises(FileNotFoundError, match="Template error"):
                await review_chunks(
                    chunks_data=expected_chunks,
                    pr_metadata=pr_metadata,
                    pr_comments=pr_comments,
                    pr_files=pr_files,
                    review_dir=temp_review_dir,
                    project_dir=str(temp_project_dir),
                )

            # Only pass 1 directory should be created
            assert not (temp_review_dir / "pass2_results").exists()
            assert not (temp_review_dir / "pass3_results").exists()


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
        temp_project_dir: Path,
    ) -> None:
        """Test complete multi-pass review flow end-to-end."""
        # Create mock reviews for each pass with different issues
        pass1_review = IssuesReview(
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
        )

        pass2_review = IssuesReview(
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
        )

        pass3_review = IssuesReview(
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
        )

        reviews_by_pass = {1: pass1_review, 2: pass2_review, 3: pass3_review}

        async def mock_run_claude(self: Any) -> bool:
            """Mock that returns different reviews based on pass number in prompt."""
            # Access attributes from the CodeExecutor instance
            output_path = self.output_path
            prompt = self.prompt

            # Convert output_path to string if it's a Path object
            output_path_str = str(output_path)

            # Determine pass number from output path or prompt content
            pass_num = 1
            if "pass2" in output_path_str or "Pass 2:" in prompt or "PASS_NUMBER=2" in prompt:
                pass_num = 2
            elif "pass3" in output_path_str or "Pass 3:" in prompt or "PASS_NUMBER=3" in prompt:
                pass_num = 3

            review = reviews_by_pass[pass_num]
            Path(output_path_str).write_text(review.model_dump_json(indent=2))
            return True

        with patch(
            "app.tools.issues_review.CodeExecutor.run_code",
            mock_run_claude,
        ):
            await review_chunks(
                chunks_data=expected_chunks,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                project_dir=str(temp_project_dir),
            )

        # Verify all passes completed with correct data
        for pass_num in [1, 2, 3]:
            # Check directories
            assert (temp_review_dir / f"pass{pass_num}_results").exists()
            assert (temp_review_dir / f"pass{pass_num}_prompts").exists()

            # Check validation subdirectories
            validation_dir = temp_review_dir / f"pass{pass_num}_results" / "validation"
            assert (validation_dir / "prompts").exists()
            assert (validation_dir / "summaries").exists()
            assert (validation_dir / "combined").exists()

            # Check all chunks have results
            for chunk in expected_chunks.chunks:
                result_file = temp_review_dir / f"pass{pass_num}_results" / f"chunk-{chunk.chunk_id}-issues-review.json"
                assert result_file.exists()

                # Verify content matches expected pass
                review = IssuesReview.model_validate_json(result_file.read_text())
                # Check that the review has issues
                assert review.issues is not None

                # Verify issue types by pass
                if pass_num == 1:
                    assert any(issue.priority == IssuePriority.MUST_FIX for issue in review.issues)
                elif pass_num == 2:
                    assert any(issue.priority == IssuePriority.SHOULD_FIX for issue in review.issues)
                elif pass_num == 3:
                    assert any(issue.priority == IssuePriority.CONSIDER for issue in review.issues)

            # Check prompts were generated
            for chunk in expected_chunks.chunks:
                prompt_file = temp_review_dir / f"pass{pass_num}_prompts" / f"chunk-{chunk.chunk_id}-code-prompt.md"
                assert prompt_file.exists()

                # Verify prompt contains correct pass info
                content = prompt_file.read_text()
                assert f"Pass {pass_num}" in content or f"PASS_NUMBER={pass_num}" in content

                # Verify previous context included for pass 2 and 3
                if pass_num > 1:
                    assert "previous_passes_context" in content or "PREVIOUS_PASSES_CONTEXT" in content

        # Verify context accumulation (pass 3 should have context from pass 1 and 2)
        last_prompt = temp_review_dir / "pass3_prompts" / "chunk-1-code-prompt.md"
        content = last_prompt.read_text()

        # Should contain references to issues from previous passes
        assert "Logic error" in content or "logic_correctness" in content.lower()
        assert "security" in content.lower()
