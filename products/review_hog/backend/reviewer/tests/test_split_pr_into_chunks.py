from pathlib import Path

import pytest
from pytest import MonkeyPatch
from unittest.mock import MagicMock, patch

from jinja2 import Environment

from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList
from products.review_hog.backend.reviewer.tests.conftest import create_mock_run_sandbox_review
from products.review_hog.backend.reviewer.tools.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.tools.split_pr_into_chunks import (
    generate_chunking_prompt,
    split_pr_into_chunks,
)

TEAM_ID = 1
REPORT_ID = "report-1"
HEAD_SHA = "abc123"


class TestGenerateChunkingPrompt:
    def test_generate_chunking_prompt_renders_schema_and_intent(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
    ) -> None:
        # The prompt carries the PR's intent (title + description) and the output schema the sandbox
        # parses against — not the full metadata dump, which the prompt deliberately omits.
        prompt = generate_chunking_prompt(
            pr_metadata=pr_metadata,
            pr_comments=pr_comments,
            pr_files=pr_files,
        )

        assert isinstance(prompt, str)
        assert pr_metadata.title in prompt
        assert pr_metadata.model_dump_json() not in prompt
        assert "<output_schema>" in prompt
        assert '"ChunksList"' in prompt
        assert '"Chunk"' in prompt

    def test_generate_chunking_prompt_missing_schema(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        monkeypatch: MonkeyPatch,
    ) -> None:
        def mock_exists(self: Path) -> bool:
            if "schema.json" in str(self):
                return False
            return self._old_exists()  # type: ignore

        with monkeypatch.context() as m:
            Path._old_exists = Path.exists  # type: ignore
            m.setattr(Path, "exists", mock_exists)

            with pytest.raises(FileNotFoundError, match="Schema file not found"):
                generate_chunking_prompt(
                    pr_metadata=pr_metadata,
                    pr_comments=pr_comments,
                    pr_files=pr_files,
                )

    def test_generate_chunking_prompt_missing_template(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        monkeypatch: MonkeyPatch,
    ) -> None:
        def mock_get_template(self: Environment, name: str) -> None:  # noqa: ARG001
            raise Exception("Template not found")

        with monkeypatch.context() as m:
            m.setattr(Environment, "get_template", mock_get_template)

            with pytest.raises(RuntimeError, match="Error loading prompt template"):
                generate_chunking_prompt(
                    pr_metadata=pr_metadata,
                    pr_comments=pr_comments,
                    pr_files=pr_files,
                )


class TestSplitPrIntoChunks:
    @pytest.mark.asyncio
    async def test_split_pr_into_chunks_success(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        expected_chunks: ChunksList,
    ) -> None:
        # No persisted chunk set => run the sandbox, return its chunks, and persist exactly once.
        mock_load = MagicMock(return_value=None)
        mock_persist = MagicMock()

        with (
            patch(
                "products.review_hog.backend.reviewer.tools.split_pr_into_chunks.load_chunk_set",
                mock_load,
            ),
            patch(
                "products.review_hog.backend.reviewer.tools.split_pr_into_chunks.persist_chunk_set",
                mock_persist,
            ),
            patch(
                "products.review_hog.backend.reviewer.tools.split_pr_into_chunks.run_sandbox_review",
                create_mock_run_sandbox_review(expected_chunks),
            ),
        ):
            result = await split_pr_into_chunks(
                team_id=TEAM_ID,
                report_id=REPORT_ID,
                head_sha=HEAD_SHA,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                branch="test-branch",
                repository="test/repo",
            )

        assert result is expected_chunks
        mock_persist.assert_called_once_with(
            team_id=TEAM_ID, report_id=REPORT_ID, head_sha=HEAD_SHA, chunks=expected_chunks
        )

    @pytest.mark.asyncio
    async def test_split_pr_into_chunks_resumes_from_persisted_set(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
        expected_chunks: ChunksList,
    ) -> None:
        # An existing chunk set for this turn short-circuits the sandbox and reuses the stored result.
        mock_load = MagicMock(return_value=expected_chunks)
        mock_persist = MagicMock()
        mock_run_sandbox = MagicMock()

        with (
            patch(
                "products.review_hog.backend.reviewer.tools.split_pr_into_chunks.load_chunk_set",
                mock_load,
            ),
            patch(
                "products.review_hog.backend.reviewer.tools.split_pr_into_chunks.persist_chunk_set",
                mock_persist,
            ),
            patch(
                "products.review_hog.backend.reviewer.tools.split_pr_into_chunks.run_sandbox_review",
                mock_run_sandbox,
            ),
        ):
            result = await split_pr_into_chunks(
                team_id=TEAM_ID,
                report_id=REPORT_ID,
                head_sha=HEAD_SHA,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                branch="test-branch",
                repository="test/repo",
            )

        assert result is expected_chunks
        mock_run_sandbox.assert_not_called()
        mock_persist.assert_not_called()

    @pytest.mark.asyncio
    async def test_split_pr_into_chunks_sandbox_failure_raises(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
    ) -> None:
        # Sandbox returning None means no chunks were produced — surface a hard failure, persist nothing.
        mock_persist = MagicMock()

        async def sandbox_returns_none(**kwargs: object) -> None:
            return None

        with (
            patch(
                "products.review_hog.backend.reviewer.tools.split_pr_into_chunks.load_chunk_set",
                MagicMock(return_value=None),
            ),
            patch(
                "products.review_hog.backend.reviewer.tools.split_pr_into_chunks.persist_chunk_set",
                mock_persist,
            ),
            patch(
                "products.review_hog.backend.reviewer.tools.split_pr_into_chunks.run_sandbox_review",
                sandbox_returns_none,
            ),
            pytest.raises(RuntimeError, match="Failed to generate chunks"),
        ):
            await split_pr_into_chunks(
                team_id=TEAM_ID,
                report_id=REPORT_ID,
                head_sha=HEAD_SHA,
                pr_metadata=pr_metadata,
                pr_comments=pr_comments,
                pr_files=pr_files,
                branch="test-branch",
                repository="test/repo",
            )

        mock_persist.assert_not_called()
