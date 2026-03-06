from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest import MonkeyPatch

from products.review_hog.backend.reviewer.models.chunk_analysis import ChunkAnalysis, ChunkMeta
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.tests.conftest import create_mock_run_code
from products.review_hog.backend.reviewer.tools.chunk_analysis import (
    analyze_chunks,
    generate_prompts,
    process_chunk,
)


@pytest.fixture
def mock_run_claude_code_chunk_analysis_failure() -> (
    Callable[[Any], Coroutine[Any, Any, bool]]
):
    """Create a mock for CodeExecutor.run_code that fails."""

    async def mock_func(_self: Any) -> bool:
        """Mock implementation that returns failure."""
        return False

    return mock_func


class TestGeneratePrompts:
    """Test generate_prompts function."""

    @pytest.mark.asyncio
    async def test_generate_prompts(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
    ) -> None:
        """Test prompt generation for chunk analysis."""
        prompt_paths = await generate_prompts(
            chunks_list=expected_chunks,
            pr_metadata=pr_metadata,
            pr_comments=pr_comments,
            pr_files=pr_files,
            review_dir=temp_review_dir,
        )

        assert len(prompt_paths) == len(expected_chunks.chunks)

        # Check prompts were created
        for i, path in enumerate(prompt_paths):
            assert path.exists()
            assert path.name == f"chunk-{i + 1}-prompt.md"

            # Verify prompt content
            content = path.read_text()
            assert '"ChunkAnalysis"' in content  # Schema included
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
        prompt_dir = temp_review_dir / "prompts"
        prompt_dir.mkdir()
        existing_prompt = prompt_dir / "chunk-1-prompt.md"
        existing_prompt.write_text("Existing prompt")

        prompt_paths = await generate_prompts(
            chunks_list=expected_chunks,
            pr_metadata=pr_metadata,
            pr_comments=pr_comments,
            pr_files=pr_files,
            review_dir=temp_review_dir,
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
            if "prompt.jinja" in name:
                raise Exception("Template not found")
            # Return a mock template for other cases
            return MagicMock(render=lambda **kwargs: "mock content")  # noqa: ARG005

        with monkeypatch.context() as m:
            m.setattr(Environment, "get_template", mock_get_template)

            with pytest.raises(FileNotFoundError, match="Could not load prompt.jinja"):
                await generate_prompts(
                    chunks_list=expected_chunks,
                    pr_metadata=pr_metadata,
                    pr_comments=pr_comments,
                    pr_files=pr_files,
                    review_dir=temp_review_dir,
                )


class TestProcessChunk:
    """Test process_chunk function."""

    @pytest.mark.asyncio
    async def test_process_chunk_success(
        self,
        temp_review_dir: Path,
        temp_project_dir: Path,
        sample_chunk_analysis_simple: ChunkAnalysis,
    ) -> None:
        """Test successful chunk processing."""
        # Create prompt file
        prompt_path = temp_review_dir / "chunk-1-prompt.md"
        prompt_path.write_text("Test prompt content")

        output_path = temp_review_dir / "chunk-1-analysis.json"

        with patch(
            "app.llm.code.CodeExecutor.run_code",
            create_mock_run_code(sample_chunk_analysis_simple),
        ):
            result = await process_chunk(
                chunk_id=1,
                prompt_path=prompt_path,
                output_path=output_path,
                project_dir=str(temp_project_dir),
            )

        assert result is True
        assert output_path.exists()

        # Verify output is valid ChunkAnalysis
        analysis = ChunkAnalysis.model_validate_json(output_path.read_text())
        assert analysis.goal is not None
        assert analysis.chunk_meta is not None

    @pytest.mark.asyncio
    async def test_process_chunk_missing_prompt(
        self, temp_review_dir: Path, temp_project_dir: Path
    ) -> None:
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
        mock_run_claude_code_chunk_analysis_failure: AsyncMock,
    ) -> None:
        """Test handling of LLM failure."""
        prompt_path = temp_review_dir / "chunk-1-prompt.md"
        prompt_path.write_text("Test prompt")

        output_path = temp_review_dir / "output.json"

        with patch(
            "app.llm.code.CodeExecutor.run_code",
            mock_run_claude_code_chunk_analysis_failure,
        ):
            result = await process_chunk(
                chunk_id=1,
                prompt_path=prompt_path,
                output_path=output_path,
                project_dir=str(temp_project_dir),
            )

        assert result is False


class TestAnalyzeChunks:
    """Test analyze_chunks main function."""

    @pytest.mark.asyncio
    async def test_analyze_chunks_single_chunk(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
        temp_project_dir: Path,
        sample_chunk_analysis_simple: ChunkAnalysis,
    ) -> None:
        """Test analyzing a single chunk."""
        # Use only first chunk for simplicity
        single_chunk = ChunksList(chunks=[expected_chunks.chunks[0]])

        with patch(
            "app.llm.code.CodeExecutor.run_code",
            create_mock_run_code(sample_chunk_analysis_simple),
        ):
            await analyze_chunks(
                chunks_data=single_chunk,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                project_dir=str(temp_project_dir),
            )

        # Verify directories created
        assert (temp_review_dir / "prompts").exists()

        # Verify result file created
        result_file = temp_review_dir / "chunk-1-analysis.json"
        assert result_file.exists()

        # Verify it's a valid ChunkAnalysis
        analysis = ChunkAnalysis.model_validate_json(result_file.read_text())
        assert analysis.goal is not None
        assert analysis.chunk_meta is not None

    @pytest.mark.asyncio
    async def test_analyze_chunks_skip_existing(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
        temp_project_dir: Path,
        sample_chunk_analysis_simple: ChunkAnalysis,
    ) -> None:
        """Test that existing results are skipped."""
        # Create existing result
        existing_result = temp_review_dir / "chunk-1-analysis.json"
        existing_result.write_text(sample_chunk_analysis_simple.model_dump_json())

        mock_run_claude = MagicMock(
            wraps=create_mock_run_code(sample_chunk_analysis_simple)
        )
        with patch("app.llm.code.CodeExecutor.run_code", mock_run_claude):
            await analyze_chunks(
                chunks_data=expected_chunks,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                project_dir=str(temp_project_dir),
            )

        # Should not call run_code for chunk 1
        # But should process other chunks
        mock_run_claude.assert_called()

        # Original file should be unchanged
        analysis = ChunkAnalysis.model_validate_json(existing_result.read_text())
        assert analysis.chunk_meta.chunk_id == 1

    @pytest.mark.asyncio
    async def test_analyze_chunks_all_chunks(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
        temp_project_dir: Path,
        sample_chunk_analysis_simple: ChunkAnalysis,
    ) -> None:
        """Test analyzing all chunks."""
        with patch(
            "app.llm.code.CodeExecutor.run_code",
            create_mock_run_code(sample_chunk_analysis_simple),
        ):
            await analyze_chunks(
                chunks_data=expected_chunks,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                project_dir=str(temp_project_dir),
            )

        # Verify all chunks have results
        for chunk in expected_chunks.chunks:
            result_file = temp_review_dir / f"chunk-{chunk.chunk_id}-analysis.json"
            assert result_file.exists()

            # Verify content is valid
            analysis = ChunkAnalysis.model_validate_json(result_file.read_text())
            assert analysis.goal is not None

        # Check prompts were generated
        for chunk in expected_chunks.chunks:
            prompt_file = (
                temp_review_dir / "prompts" / f"chunk-{chunk.chunk_id}-prompt.md"
            )
            assert prompt_file.exists()


class TestEndToEnd:
    """End-to-end test for complete analysis flow."""

    @pytest.mark.asyncio
    async def test_analyze_chunks_e2e(
        self,
        expected_chunks: ChunksList,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
        temp_project_dir: Path,
    ) -> None:
        """Test complete chunk analysis flow end-to-end."""
        # Create mock analyses for each chunk
        chunk_analyses = {}
        for chunk in expected_chunks.chunks:
            chunk_analyses[chunk.chunk_id] = ChunkAnalysis(
                goal=f"Analysis for chunk {chunk.chunk_id}",
                chunk_meta=ChunkMeta(
                    chunk_id=chunk.chunk_id,
                    files_in_this_chunk=[f.filename for f in chunk.files],
                ),
            )

        async def mock_run_claude(
            self: Any,
        ) -> bool:
            """Mock that returns different analyses based on chunk."""
            # Access output_path from the CodeExecutor instance
            output_path = self.output_path
            # Convert output_path to string if it's a Path object
            output_path_str = str(output_path)

            # Determine chunk number from output path
            import re

            match = re.search(r"chunk-(\d+)-analysis\.json", output_path_str)
            if match:
                chunk_id = int(match.group(1))
                analysis = chunk_analyses.get(chunk_id)
                if analysis:
                    Path(output_path_str).write_text(analysis.model_dump_json(indent=2))
                    return True
            return False

        with patch(
            "app.tools.chunk_analysis.CodeExecutor.run_code",
            mock_run_claude,
        ):
            await analyze_chunks(
                chunks_data=expected_chunks,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                project_dir=str(temp_project_dir),
            )

        # Verify all chunks have analysis results
        for chunk in expected_chunks.chunks:
            result_file = temp_review_dir / f"chunk-{chunk.chunk_id}-analysis.json"
            assert result_file.exists()

            # Verify content matches expected chunk
            analysis = ChunkAnalysis.model_validate_json(result_file.read_text())
            assert f"chunk {chunk.chunk_id}" in analysis.goal
            assert analysis.chunk_meta.chunk_id == chunk.chunk_id

            # Check prompts were generated
            prompt_file = (
                temp_review_dir / "prompts" / f"chunk-{chunk.chunk_id}-prompt.md"
            )
            assert prompt_file.exists()

            # Verify prompt contains necessary information
            content = prompt_file.read_text()
            assert "ChunkAnalysis" in content
            assert pr_metadata.title in content
