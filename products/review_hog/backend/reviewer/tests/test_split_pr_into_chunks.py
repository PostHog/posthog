import re
import json
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from jinja2 import Environment

from products.review_hog.backend.reviewer.constants import (
    CHUNK_SOFT_MAX_ADDITIONS,
    CHUNK_TARGET_ADDITIONS,
    SINGLE_CHUNK_GATE_ADDITIONS,
)
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, ChunksList, FileInfo
from products.review_hog.backend.reviewer.tools.split_pr_into_chunks import (
    generate_chunking_prompt,
    plan_deterministic_chunks,
)


def _file(filename: str, additions: int, deletions: int = 0) -> PRFile:
    return PRFile(filename=filename, status="modified", additions=additions, deletions=deletions)


class TestGenerateChunkingPrompt:
    def test_generate_chunking_prompt_renders_schema_and_intent(
        self,
        pr_metadata: PRMetadata,
        pr_comments: list[PRComment],
        pr_files: list[PRFile],
    ) -> None:
        # The prompt carries the PR's intent (title + description), the size budget the chunker uses,
        # and the output schema the sandbox parses — not the full metadata dump it omits.
        prompt = generate_chunking_prompt(
            pr_metadata=pr_metadata,
            pr_comments=pr_comments,
            pr_files=pr_files,
        )

        assert isinstance(prompt, str)
        assert pr_metadata.title in prompt
        assert pr_metadata.model_dump_json() not in prompt
        assert str(CHUNK_TARGET_ADDITIONS) in prompt
        assert str(CHUNK_SOFT_MAX_ADDITIONS) in prompt
        assert "<output_schema>" in prompt
        assert '"ChunksList"' in prompt
        assert '"Chunk"' in prompt

    @staticmethod
    def _fenced_block(prompt: str, heading: str) -> str:
        match = re.search(rf"## {heading}\n```\n(.*?)\n```", prompt, re.DOTALL)
        assert match, f"missing '{heading}' block"
        return match.group(1)

    def test_prompt_embeds_files_and_comments_as_json_arrays(self, pr_metadata: PRMetadata) -> None:
        # The chunker is told to size chunks from each file's `additions` field, so the file/comment
        # blocks must be one parseable JSON array — not Python's str(list) repr of pre-encoded strings.
        comments = [
            PRComment(id=7, path="a.py", line=3, body="prior note", diff_hunk="@@", user="hedgehog", created_at="c")
        ]
        files = [_file("a.py", additions=12, deletions=1), _file("b.py", additions=30)]

        prompt = generate_chunking_prompt(pr_metadata, comments, files)

        parsed_files = json.loads(self._fenced_block(prompt, "PR files"))
        assert [(f["filename"], f["additions"]) for f in parsed_files] == [("a.py", 12), ("b.py", 30)]
        parsed_comments = json.loads(self._fenced_block(prompt, "PR comments"))
        assert [c["body"] for c in parsed_comments] == ["prior note"]
        assert "id" not in parsed_comments[0]

    def test_chunks_list_rejects_duplicate_chunk_ids(self) -> None:
        # Fan-out and resume resolve chunks by id keeping the first match, so a duplicate id from the
        # chunking LLM silently drops a chunk from review — it must fail validation and be retried.
        def chunk(chunk_id: int, filename: str) -> Chunk:
            return Chunk(chunk_id=chunk_id, files=[FileInfo(filename=filename)])

        with pytest.raises(ValueError, match="chunk_id values must be unique"):
            ChunksList(chunks=[chunk(1, "a.py"), chunk(2, "b.py"), chunk(1, "c.py")])

        assert len(ChunksList(chunks=[chunk(1, "a.py"), chunk(2, "b.py")]).chunks) == 2


class TestPlanDeterministicChunks:
    @pytest.mark.parametrize(
        "additions,defers_to_llm",
        [
            (SINGLE_CHUNK_GATE_ADDITIONS - 1, False),
            (SINGLE_CHUNK_GATE_ADDITIONS, False),
            (SINGLE_CHUNK_GATE_ADDITIONS + 1, True),
        ],
    )
    def test_threshold_decides_single_chunk_vs_llm(self, additions: int, defers_to_llm: bool) -> None:
        # The cost fix: a PR within the gate stays one chunk (LLM skipped); only a larger PR defers
        # to the semantic chunker. The boundary is inclusive.
        planned = plan_deterministic_chunks([_file("a.py", additions)])

        if defers_to_llm:
            assert planned is None
        else:
            assert planned is not None
            assert len(planned.chunks) == 1

    def test_counts_additions_only_not_deletions(self) -> None:
        # Sizing is additions-only — a delete-heavy PR (few additions) is still one chunk, not split.
        planned = plan_deterministic_chunks([_file("a.py", additions=50, deletions=9999)])

        assert planned is not None
        assert len(planned.chunks) == 1

    def test_single_chunk_holds_all_files_with_neutral_metadata(self) -> None:
        # The deterministic chunk gathers every reviewable file under chunk_id 1 with no LLM-derived
        # type/key_changes, so the downstream body renderer falls back to its generic heading.
        planned = plan_deterministic_chunks([_file("a.py", 10), _file("b.py", 20)])

        assert planned is not None
        chunk = planned.chunks[0]
        assert chunk.chunk_id == 1
        assert [f.filename for f in chunk.files] == ["a.py", "b.py"]
        assert chunk.chunk_type is None
        assert chunk.key_changes == []

    def test_no_reviewable_files_yields_no_chunks(self) -> None:
        # A PR left with nothing reviewable (everything filtered upstream) produces zero chunks so the
        # run no-ops, rather than calling the LLM with an empty file set.
        planned = plan_deterministic_chunks([])

        assert planned is not None
        assert planned.chunks == []

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
