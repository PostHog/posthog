import re
import json

import pytest

from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, ChunksList, FileInfo
from products.review_hog.backend.reviewer.tools.split_pr_into_chunks import generate_chunking_prompt


def _pr_metadata() -> PRMetadata:
    return PRMetadata(
        number=1,
        title="t",
        state="open",
        draft=False,
        created_at="c",
        updated_at="u",
        author="octocat",
        base_branch="main",
        head_branch="feat",
        commits=1,
        additions=12,
        deletions=0,
        changed_files=2,
    )


def _fenced_block(prompt: str, heading: str) -> str:
    match = re.search(rf"## {heading}\n```\n(.*?)\n```", prompt, re.DOTALL)
    assert match, f"missing '{heading}' block"
    return match.group(1)


# The chunker is told to size chunks from each file's `additions` field, so the file/comment
# blocks must be one parseable JSON array — not Python's str(list) repr of pre-encoded strings.
def test_chunking_prompt_embeds_files_and_comments_as_json_arrays() -> None:
    comments = [
        PRComment(id=7, path="a.py", line=3, body="prior note", diff_hunk="@@", user="hedgehog", created_at="c")
    ]
    files = [
        PRFile(filename="a.py", status="modified", additions=12, deletions=1),
        PRFile(filename="b.py", status="added", additions=30, deletions=0),
    ]
    prompt = generate_chunking_prompt(_pr_metadata(), comments, files)

    parsed_files = json.loads(_fenced_block(prompt, "PR files"))
    assert [(f["filename"], f["additions"]) for f in parsed_files] == [("a.py", 12), ("b.py", 30)]

    parsed_comments = json.loads(_fenced_block(prompt, "PR comments"))
    assert [c["body"] for c in parsed_comments] == ["prior note"]
    assert "id" not in parsed_comments[0]


def _chunk(chunk_id: int) -> Chunk:
    return Chunk(chunk_id=chunk_id, files=[FileInfo(filename=f"file_{chunk_id}.py")])


# Fan-out and resume resolve chunks by id keeping the first match, so a duplicate id from the
# chunking LLM silently drops a chunk from review — it must fail validation and be retried instead.
def test_chunks_list_rejects_duplicate_chunk_ids() -> None:
    with pytest.raises(ValueError, match="chunk_id values must be unique"):
        ChunksList(chunks=[_chunk(1), _chunk(2), Chunk(chunk_id=1, files=[FileInfo(filename="other.py")])])

    assert len(ChunksList(chunks=[_chunk(1), _chunk(2)]).chunks) == 2
