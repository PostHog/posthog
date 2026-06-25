from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk
from products.review_hog.backend.reviewer.tools.prompt_helpers import (
    build_chunk_prompt_context,
    load_template_and_schema,
)

ANALYSIS_SYSTEM_PROMPT = """You are a senior software engineer analyzing a chunk of code changes in a GitHub PR.
Focus on:
- Understanding the purpose and goal of the changes
- Analyzing the architecture and design patterns
- Identifying dependencies and integration points
- Providing technical insights about the implementation
IMPORTANT: Return ONLY valid JSON output without any markdown formatting or explanatory text."""


def build_analysis_prompt(
    *,
    chunk: Chunk,
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
) -> str:
    """Render the analysis prompt for one chunk (code context + the chunk's files/comments/intent)."""
    template, output_schema = load_template_and_schema("chunk_analysis")
    return template.render(
        **build_chunk_prompt_context(chunk, pr_metadata, pr_comments, pr_files),
        OUTPUT_SCHEMA=output_schema,
    )
