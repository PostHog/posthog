import json

from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.issues_review import Issue
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk
from products.review_hog.backend.reviewer.sandbox.code_context import prepare_code_context
from products.review_hog.backend.reviewer.tools.prompt_helpers import load_template_and_schema

VALIDATION_SYSTEM_PROMPT = """You are a senior code reviewer validating suggested issues in a pull request.
Your task is to:
1. Analyze the suggested issue in the context of the codebase
2. Determine if the issue is valid and should be addressed
3. Provide clear reasoning for your decision
4. Identify the category and potential risks if applicable

IMPORTANT: Return ONLY valid JSON output that conforms to the provided schema."""


def build_validation_prompt(
    *,
    issue: Issue,
    chunk: Chunk,
    skill_name: str,
    skill_version: int,
    pr_metadata: PRMetadata,
    pr_files: list[PRFile],
) -> str:
    """Render the validation prompt for one issue against the live codebase.

    The keep/drop criteria aren't spliced in — the prompt instructs the agent to `skill-get` them
    over MCP — so we pass the validation skill's name and pinned version, not its body. `pr_files`
    is already narrowed to the issue's own file by the caller.
    """
    claude_code_context = prepare_code_context([issue.file], pr_files) if issue.file else ""
    template, schema = load_template_and_schema("issue_validation")
    return template.render(
        CLAUDE_CODE_CONTEXT=claude_code_context,
        PR_CONTEXT=json.dumps(pr_metadata.model_dump(mode="json"), indent=2),
        CHUNK_CONTEXT=json.dumps(chunk.model_dump(), indent=2),
        ISSUE=issue.model_dump_json(indent=2),
        VALIDATION_SCHEMA=schema.strip(),
        VALIDATION_SKILL_NAME=skill_name,
        VALIDATION_SKILL_VERSION=skill_version,
    )
