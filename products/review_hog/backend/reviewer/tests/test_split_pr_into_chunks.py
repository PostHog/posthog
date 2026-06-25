from pathlib import Path

import pytest
from pytest import MonkeyPatch

from jinja2 import Environment

from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.tools.split_pr_into_chunks import generate_chunking_prompt


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

            with pytest.raises(FileNotFoundError, match="Could not load prompt.jinja template"):
                generate_chunking_prompt(
                    pr_metadata=pr_metadata,
                    pr_comments=pr_comments,
                    pr_files=pr_files,
                )
