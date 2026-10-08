import re
import json
import math
import logging
import posixpath

from posthog.dataclasses import frozen

from products.review_hog.backend.reviewer.constants import (
    CHUNK_SOFT_MAX_ADDITIONS,
    CHUNK_TARGET_ADDITIONS,
    FLASH_LENS_CHUNK_MAX_LINES,
    FLASH_LENS_MAX_CHUNKS,
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


# `tools/` matches only at the repository root, because nested `tools/` directories hold product code.
_NOT_REVIEWABLE_PATH = re.compile(
    "|".join(
        [
            r"(^|/)(tests?|__tests__|__snapshots__|fixtures|snapshots|generated|docs)/",
            r"(^|/)test_[^/]*$",
            r"_test\.(py|go|rs)$",
            r"\.(test|spec|stories)\.[jt]sx?$",
            r"\.(md|mdx|txt|snap|svg|png|jpg|lock|csv|json)$",
            r"(^|/)pnpm-lock\.yaml$",
            r"^(tools|\.github|\.depot)/",
        ]
    )
)


def is_reviewable_path(path: str) -> bool:
    """Whether a changed file counts toward the size of a lens part."""
    return _NOT_REVIEWABLE_PATH.search(path) is None


def _changed_lines(pr_file: PRFile) -> int:
    return pr_file.additions + pr_file.deletions


@frozen
class LensChunkPlan:
    """The file lists the Flash lens sessions review: one session per lens and list."""

    chunks: list[list[str]]
    # The PR needed more than FLASH_LENS_MAX_CHUNKS parts at the normal size, so each part is larger.
    capped: bool


def _pack_by_directory(pr_files: list[PRFile], line_budget: int) -> list[list[str]]:
    """Pack files in path order into parts of at most `line_budget` changed lines.

    A directory's files stay in one part when they fit. A larger directory is packed file by file. A
    file is never split, so one file over the budget makes a part larger than the budget.
    """
    groups: dict[str, list[PRFile]] = {}
    for pr_file in sorted(pr_files, key=lambda f: f.filename):
        groups.setdefault(posixpath.dirname(pr_file.filename), []).append(pr_file)
    chunks: list[list[str]] = []
    current: list[str] = []
    current_lines = 0
    for group in groups.values():
        group_lines = sum(_changed_lines(f) for f in group)
        if current and current_lines + group_lines > line_budget:
            chunks.append(current)
            current, current_lines = [], 0
        if group_lines <= line_budget:
            current.extend(f.filename for f in group)
            current_lines += group_lines
            continue
        for pr_file in group:
            if current and current_lines + _changed_lines(pr_file) > line_budget:
                chunks.append(current)
                current, current_lines = [], 0
            current.append(pr_file.filename)
            current_lines += _changed_lines(pr_file)
    if current:
        chunks.append(current)
    return chunks


def plan_lens_chunks(pr_files: list[PRFile]) -> LensChunkPlan:
    """Split the PR into the parts the lens sessions review, without an LLM call.

    A PR whose reviewable lines fit one part is one part with every file, like the main session sees it.
    A larger PR splits over its reviewable files only. Above FLASH_LENS_MAX_CHUNKS parts, the line budget
    grows to the smallest value that packs the PR into that many parts, so the parts come out about equal.
    The plan is recomputed from the PR snapshot wherever it is needed and never persisted, because
    `split_chunks_activity` reuses any chunk set persisted for the same head.
    """
    reviewable = [f for f in pr_files if is_reviewable_path(f.filename)]
    reviewable_lines = sum(_changed_lines(f) for f in reviewable)
    if reviewable_lines <= FLASH_LENS_CHUNK_MAX_LINES:
        whole_pr = [f.filename for f in pr_files]
        return LensChunkPlan(chunks=[whole_pr] if whole_pr else [], capped=False)
    chunks = _pack_by_directory(reviewable, FLASH_LENS_CHUNK_MAX_LINES)
    if len(chunks) <= FLASH_LENS_MAX_CHUNKS:
        return LensChunkPlan(chunks=chunks, capped=False)
    # Binary search: the whole PR in one part always fits, so `high` always packs into few enough parts.
    low = max(FLASH_LENS_CHUNK_MAX_LINES, math.ceil(reviewable_lines / FLASH_LENS_MAX_CHUNKS))
    high = reviewable_lines
    while low < high:
        middle = (low + high) // 2
        if len(_pack_by_directory(reviewable, middle)) <= FLASH_LENS_MAX_CHUNKS:
            high = middle
        else:
            low = middle + 1
    return LensChunkPlan(chunks=_pack_by_directory(reviewable, high), capped=True)


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
