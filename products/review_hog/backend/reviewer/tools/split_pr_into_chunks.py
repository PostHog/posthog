import json
import logging

from products.review_hog.backend.reviewer.constants import (
    CHUNK_SOFT_MAX_ADDITIONS,
    CHUNK_TARGET_ADDITIONS,
    SINGLE_CHUNK_GATE_ADDITIONS,
)
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, ChunksList, FileInfo
from products.review_hog.backend.reviewer.tools.prompt_helpers import format_pr_intent, load_template_and_schema

logger = logging.getLogger(__name__)

CHUNKING_SYSTEM_PROMPT = """You are a code review assistant analyzing GitHub PRs and organizing them into logical chunks.
Focus on:
- Understanding file relationships and dependencies
- Grouping related files based on functionality
- Creating coherent, independently reviewable chunks
- Following the specific output format requirements

IMPORTANT: Return ONLY valid JSON output without any markdown formatting or explanatory text."""


def count_reviewable_additions(pr_files: list[PRFile]) -> int:
    """Added lines across the PR's reviewable files (lock/build/generated already filtered upstream)."""
    return sum(f.additions for f in pr_files)


def plan_deterministic_chunks(pr_files: list[PRFile]) -> ChunksList | None:
    """One all-files chunk for a small PR (caller skips the chunking LLM), or None to defer to it.

    Returns a single chunk when reviewable additions fit `SINGLE_CHUNK_GATE_ADDITIONS`, an empty set
    when nothing is reviewable (the run no-ops), or None for larger PRs so the caller runs the LLM chunker.
    """
    if count_reviewable_additions(pr_files) > SINGLE_CHUNK_GATE_ADDITIONS:
        return None
    files = [FileInfo(filename=f.filename) for f in pr_files]
    return ChunksList(chunks=[Chunk(chunk_id=1, files=files)] if files else [])


def reconcile_chunks(chunks: ChunksList, pr_files: list[PRFile]) -> ChunksList:
    """Deterministically force the chunker LLM's output to cover exactly the PR's reviewable files.

    The prompt instructs "every file in exactly one chunk — no omissions, no duplicates", but prose
    is not enforcement: an omitted file silently skips EVERY downstream pass (selection, perspectives,
    and the blind-spot sweep all iterate `chunk.files`), a hallucinated file wastes review attention,
    and a duplicate double-reviews. The LLM's grouping is kept untouched: duplicates keep their first
    (highest-priority) chunk, unknown files are removed (a chunk emptied by that is dropped), and
    omitted files are appended as one catch-all chunk at the end.
    """
    real = {f.filename for f in pr_files}
    seen: set[str] = set()
    kept_chunks: list[Chunk] = []
    for chunk in chunks.chunks:
        kept_files: list[FileInfo] = []
        for file in chunk.files:
            if file.filename not in real:
                logger.warning("Chunker invented file '%s' (not in the PR); removing it", file.filename)
                continue
            if file.filename in seen:
                logger.warning("Chunker repeated file '%s'; keeping only its first chunk", file.filename)
                continue
            seen.add(file.filename)
            kept_files.append(file)
        if kept_files:
            kept_chunks.append(chunk.model_copy(update={"files": kept_files}))
        else:
            logger.warning("Chunk %s is empty after reconciliation; dropping it", chunk.chunk_id)
    missing = [f.filename for f in pr_files if f.filename not in seen]
    if missing:
        logger.warning("Chunker omitted %d file(s); appending them as a catch-all chunk: %s", len(missing), missing)
        next_id = max((c.chunk_id for c in kept_chunks), default=0) + 1
        kept_chunks.append(Chunk(chunk_id=next_id, files=[FileInfo(filename=name) for name in missing]))
    return ChunksList(chunks=kept_chunks)


def generate_chunking_prompt(
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
) -> str:
    """Render the chunking prompt for the sandbox agent (only reached for PRs over the single-chunk size)."""
    prompt_template, output_schema = load_template_and_schema("chunking")
    return prompt_template.render(
        PR_INTENT=format_pr_intent(pr_metadata),
        PR_COMMENTS=json.dumps(
            [x.model_dump(mode="json", exclude={"id", "created_at"}) for x in pr_comments], indent=2
        ),
        PR_FILES=json.dumps([x.model_dump(mode="json") for x in pr_files], indent=2),
        CHUNK_TARGET=CHUNK_TARGET_ADDITIONS,
        CHUNK_SOFT_MAX=CHUNK_SOFT_MAX_ADDITIONS,
        OUTPUT_SCHEMA=output_schema,
    )
