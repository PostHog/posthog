import json

from products.review_hog.backend.reviewer.models.chunk_analysis import ChunkAnalysis
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk
from products.review_hog.backend.reviewer.tools.prompt_helpers import (
    build_chunk_prompt_context,
    load_template_and_schema,
)

REVIEW_SYSTEM_PROMPT = (
    "You are a senior code reviewer focused on identifying and documenting issues in a GitHub PR chunk.\n"
    "Focus on:\n"
    "- Identifying real issues that impact code quality, security, or performance\n"
    "- Providing specific, actionable suggestions for each issue\n"
    "- Categorizing issues by priority (must_fix, should_fix, consider)\n"
    "- Following the specific output format requirements for IssuesReview\n"
    "IMPORTANT: Return ONLY valid JSON output without any markdown formatting or explanatory text."
)


def build_review_prompt(
    *,
    skill_name: str,
    skill_version: int,
    chunk: Chunk,
    analysis: ChunkAnalysis | None,
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
) -> str:
    """Render one (perspective, chunk) review prompt, injecting the chunk's analysis as context.

    Each (perspective × chunk) review is independent — no cross-perspective context; overlap between
    perspectives is resolved downstream by deduplication. The perspective's focus isn't spliced in —
    the prompt instructs the agent to `skill-get` it over MCP — so we pass the perspective's skill
    name and pinned version, not its body.
    """
    main_template, output_schema = load_template_and_schema("issues_review")
    chunk_analysis_context = json.dumps(analysis.model_dump(mode="json"), indent=2) if analysis is not None else None
    return main_template.render(
        **build_chunk_prompt_context(chunk, pr_metadata, pr_comments, pr_files),
        CHUNK_ANALYSIS_CONTEXT=chunk_analysis_context,
        OUTPUT_SCHEMA=output_schema,
        PERSPECTIVE_SKILL_NAME=skill_name,
        PERSPECTIVE_SKILL_VERSION=skill_version,
    )
