import json
from pathlib import Path
from typing import Any

import pytest
from pytest import MonkeyPatch
from unittest.mock import AsyncMock, patch

from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.tests.conftest import create_mock_run_code
from products.review_hog.backend.reviewer.tools.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.tools.split_pr_into_chunks import (
    generate_chunking_prompt,
    split_pr_into_chunks,
)


class TestGenerateChunkingPrompt:
    """Test generate_chunking_prompt function."""

    def test_generate_chunking_prompt_success(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
    ) -> None:
        """Test successful prompt generation using actual template files."""
        prompt: str = generate_chunking_prompt(
            pr_metadata=pr_metadata,
            pr_comments=pr_comments,
            pr_files=pr_files,
            review_dir=temp_review_dir,
        )

        assert isinstance(prompt, str)
        assert len(prompt) > 0

        prompt_file: Path = temp_review_dir / "chunking_prompt.md"
        assert prompt_file.exists()

        assert "## PR metadata" in prompt
        assert "## PR comments" in prompt
        assert "## PR files" in prompt
        assert "<output_schema>" in prompt
        assert pr_metadata.model_dump_json() in prompt
        assert '"ChunksList"' in prompt
        assert '"Chunk"' in prompt

    def test_generate_chunking_prompt_missing_schema(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test prompt generation fails when schema file is missing."""

        def mock_exists(self: Path) -> bool:
            if "schema.json" in str(self):
                return False
            return self._old_exists()  # type: ignore

        with monkeypatch.context() as m:
            from pathlib import Path as OrigPath

            OrigPath._old_exists = OrigPath.exists  # type: ignore
            m.setattr(Path, "exists", mock_exists)

            with pytest.raises(FileNotFoundError, match="Schema file not found"):
                generate_chunking_prompt(
                    pr_metadata=pr_metadata,
                    pr_comments=pr_comments,
                    pr_files=pr_files,
                    review_dir=temp_review_dir,
                )

    def test_generate_chunking_prompt_missing_template(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Test prompt generation fails when template is missing."""
        from jinja2 import Environment

        def mock_get_template(self: Environment, name: str) -> None:  # noqa: ARG001
            raise Exception("Template not found")

        with monkeypatch.context() as m:
            m.setattr(Environment, "get_template", mock_get_template)

            with pytest.raises(RuntimeError, match="Error loading prompt template"):
                generate_chunking_prompt(
                    pr_metadata=pr_metadata,
                    pr_comments=pr_comments,
                    pr_files=pr_files,
                    review_dir=temp_review_dir,
                )


class TestSplitPrIntoChunks:
    """Test split_pr_into_chunks function."""

    @pytest.mark.asyncio
    async def test_split_pr_into_chunks_success(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
        temp_project_dir: Path,
        expected_chunks: ChunksList,
    ) -> None:
        """Test successful PR chunking."""
        with patch("app.tools.split_pr_into_chunks.generate_chunking_prompt") as mock_prompt:
            mock_prompt.return_value = "Test prompt"

            with patch(
                "app.tools.split_pr_into_chunks.CodeExecutor.run_code",
                create_mock_run_code(expected_chunks),
            ):
                await split_pr_into_chunks(
                    pr_metadata=pr_metadata,
                    pr_comments=pr_comments,
                    pr_files=pr_files,
                    review_dir=temp_review_dir,
                    project_dir=str(temp_project_dir),
                )

                chunks_file: Path = temp_review_dir / "chunks.json"
                assert chunks_file.exists()

                with chunks_file.open() as f:
                    saved_chunks: ChunksList = ChunksList.model_validate_json(f.read())
                assert len(saved_chunks.chunks) == len(expected_chunks.chunks)
                assert saved_chunks.chunks[0].chunk_id == expected_chunks.chunks[0].chunk_id

    @pytest.mark.asyncio
    async def test_split_pr_into_chunks_existing_file(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
        temp_project_dir: Path,
    ) -> None:
        """Test that chunking is skipped when chunks.json already exists."""
        chunks_file: Path = temp_review_dir / "chunks.json"
        existing_content: dict[str, Any] = {"chunks": [{"chunk_id": 999, "description": "Existing"}]}
        with chunks_file.open("w") as f:
            json.dump(existing_content, f)

        with (
            patch("app.tools.split_pr_into_chunks.generate_chunking_prompt") as mock_prompt,
            patch(
                "app.tools.split_pr_into_chunks.CodeExecutor.run_code",
            ) as mock_run_code_executor,
        ):
            await split_pr_into_chunks(
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                project_dir=str(temp_project_dir),
            )

            mock_prompt.assert_not_called()
            mock_run_code_executor.assert_not_called()

            with chunks_file.open() as f:
                content: dict[str, Any] = json.load(f)
            assert content["chunks"][0]["chunk_id"] == 999

    @pytest.mark.asyncio
    async def test_split_pr_into_chunks_empty_existing_file(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
        temp_project_dir: Path,
        expected_chunks: ChunksList,
    ) -> None:
        """Test that chunking proceeds when chunks.json exists but is empty."""
        chunks_file: Path = temp_review_dir / "chunks.json"
        chunks_file.touch()

        with patch("app.tools.split_pr_into_chunks.generate_chunking_prompt") as mock_prompt:
            mock_prompt.return_value = "Test prompt"

            with patch(
                "app.tools.split_pr_into_chunks.CodeExecutor.run_code",
                create_mock_run_code(expected_chunks),
            ):
                await split_pr_into_chunks(
                    pr_metadata=pr_metadata,
                    pr_comments=pr_comments,
                    pr_files=pr_files,
                    review_dir=temp_review_dir,
                    project_dir=str(temp_project_dir),
                )

                mock_prompt.assert_called_once()

                with chunks_file.open() as f:
                    saved_chunks: ChunksList = ChunksList.model_validate_json(f.read())
                assert len(saved_chunks.chunks) > 0

    @pytest.mark.asyncio
    async def test_split_pr_into_chunks_llm_failure(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
        temp_project_dir: Path,
        mock_run_claude_code_failure: AsyncMock,
    ) -> None:
        """Test handling of LLM failure."""
        with patch("app.tools.split_pr_into_chunks.generate_chunking_prompt") as mock_prompt:
            mock_prompt.return_value = "Test prompt"

            with (
                patch(
                    "app.tools.split_pr_into_chunks.CodeExecutor.run_code",
                    mock_run_claude_code_failure,
                ),
                pytest.raises(RuntimeError, match="Failed to generate chunks using Claude Code"),
            ):
                await split_pr_into_chunks(
                    pr_metadata=pr_metadata,
                    pr_comments=pr_comments,
                    pr_files=pr_files,
                    review_dir=temp_review_dir,
                    project_dir=str(temp_project_dir),
                )

    @pytest.mark.asyncio
    async def test_split_pr_into_chunks_prompt_generation_error(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
        temp_project_dir: Path,
    ) -> None:
        """Test handling of prompt generation error."""
        with patch("app.tools.split_pr_into_chunks.generate_chunking_prompt") as mock_prompt:
            mock_prompt.side_effect = FileNotFoundError("Schema file not found")

            with pytest.raises(FileNotFoundError, match="Schema file not found"):
                await split_pr_into_chunks(
                    pr_metadata=pr_metadata,
                    pr_comments=pr_comments,
                    pr_files=pr_files,
                    review_dir=temp_review_dir,
                    project_dir=str(temp_project_dir),
                )


class TestSplitPrIntoChunksEndToEnd:
    """End-to-end test for the complete chunking flow."""

    @pytest.mark.asyncio
    async def test_split_pr_into_chunks_e2e(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        temp_review_dir: Path,
        temp_project_dir: Path,
        expected_chunks: ChunksList,
    ) -> None:
        """Test the complete flow from PR data to validated chunks output."""

        # Create a custom mock for e2e test that creates stream file
        async def mock_e2e_run_code(self: Any) -> bool:
            """Mock that creates both output and stream files."""
            output_path = self.output_path
            chunks_json = json.dumps(expected_chunks.model_dump(mode="json"), indent=2)

            # Write main output file
            with Path(output_path).open("w") as f:
                f.write(chunks_json)

            # Write stream file (simulating Claude Code SDK behavior)
            stream_output_path = str(output_path).replace(".json", "_stream.json")
            result_message = {
                "subtype": "result",
                "result": f"```json\n{chunks_json}\n```",
            }
            with Path(stream_output_path).open("w") as f:
                json.dump([result_message], f, indent=2)

            return True

        with patch(
            "app.tools.split_pr_into_chunks.CodeExecutor.run_code",
            mock_e2e_run_code,
        ):
            await split_pr_into_chunks(
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                review_dir=temp_review_dir,
                project_dir=str(temp_project_dir),
            )

            chunks_file: Path = temp_review_dir / "chunks.json"
            prompt_file: Path = temp_review_dir / "chunking_prompt.md"
            stream_file: Path = temp_review_dir / "chunks_stream.json"

            assert chunks_file.exists()
            assert prompt_file.exists()
            assert stream_file.exists()

            with chunks_file.open() as f:
                saved_chunks: ChunksList = ChunksList.model_validate_json(f.read())

            assert len(saved_chunks.chunks) == len(expected_chunks.chunks)

            first_chunk = saved_chunks.chunks[0]
            expected_first = expected_chunks.chunks[0]

            assert first_chunk.chunk_id == expected_first.chunk_id
            assert first_chunk.chunk_type == expected_first.chunk_type
            assert len(first_chunk.files) == len(expected_first.files)

            with prompt_file.open() as f:
                prompt_content: str = f.read()

            assert "## PR metadata" in prompt_content
            assert "## PR comments" in prompt_content
            assert "## PR files" in prompt_content
            assert "<output_schema>" in prompt_content
            assert '"$defs"' in prompt_content
            assert '"ChunksList"' in prompt_content
            assert '"Chunk"' in prompt_content
            assert str(pr_metadata.number) in prompt_content
            assert pr_metadata.title in prompt_content
