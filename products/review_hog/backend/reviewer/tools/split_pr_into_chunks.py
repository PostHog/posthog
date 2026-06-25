from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRFile, PRMetadata
from products.review_hog.backend.reviewer.tools.prompt_helpers import format_pr_intent, load_template_and_schema

CHUNKING_SYSTEM_PROMPT = """You are a code review assistant analyzing GitHub PRs and organizing them into logical chunks.
Focus on:
- Understanding file relationships and dependencies
- Grouping related files based on functionality
- Creating coherent, independently reviewable chunks
- Following the specific output format requirements

IMPORTANT: Return ONLY valid JSON output without any markdown formatting or explanatory text."""


def generate_chunking_prompt(
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    pr_files: list[PRFile],
) -> str:
    """Render the chunking prompt for the sandbox agent."""
    prompt_template, output_schema = load_template_and_schema("chunking")
    return prompt_template.render(
        PR_INTENT=format_pr_intent(pr_metadata),
        PR_COMMENTS=[x.model_dump_json(exclude={"id", "created_at"}) for x in pr_comments],
        PR_FILES=[x.model_dump_json() for x in pr_files],
        OUTPUT_SCHEMA=output_schema,
    )
