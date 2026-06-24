import json
import asyncio
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, Template, select_autoescape

from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, ChunksList
from products.review_hog.backend.reviewer.sandbox.code_context import prepare_code_context
from products.review_hog.backend.reviewer.sandbox.executor import run_sandbox_review

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a senior code reviewer validating suggested issues in a pull request.
Your task is to:
1. Analyze the suggested issue in the context of the codebase
2. Determine if the issue is valid and should be addressed
3. Provide clear reasoning for your decision
4. Identify the category and potential risks if applicable

IMPORTANT: Return ONLY valid JSON output that conforms to the provided schema."""


async def validate_issues(
    *,
    chunks_data: ChunksList,
    pr_metadata: PRMetadata,
    pr_files: list[PRFile],
    issues: list[Issue],
    branch: str,
    repository: str,
) -> dict[str, IssueValidation]:
    """Validate each canonical issue against the live codebase, keyed by issue id.

    All issues are validated concurrently under the global sandbox semaphore (no artificial
    batching — the semaphore is the only bound). An issue whose chunk can't be resolved or whose
    sandbox call fails is dropped from the result.
    """
    chunks_map = {chunk.chunk_id: chunk for chunk in chunks_data.chunks}
    template, schema = _load_template_and_schema()

    issue_ids: list[str] = []
    tasks = []
    for issue in issues:
        parts = issue.id.split("-")
        if len(parts) != 3:
            logger.warning(f"Skipping validation for issue with malformed id: {issue.id}")
            continue
        chunk = chunks_map.get(int(parts[1]))
        if chunk is None:
            logger.warning(f"Skipping validation for issue {issue.id}: chunk {parts[1]} not found")
            continue
        issue_ids.append(issue.id)
        tasks.append(
            _validate_one(
                issue=issue,
                chunk=chunk,
                template=template,
                schema=schema,
                pr_metadata=pr_metadata,
                pr_files=pr_files,
                branch=branch,
                repository=repository,
            )
        )

    if not tasks:
        logger.info("No issues to validate")
        return {}

    logger.info(f"Validating {len(tasks)} issue(s)")
    results = await asyncio.gather(*tasks)
    validations = {issue_id: result for issue_id, result in zip(issue_ids, results) if result is not None}
    if len(validations) != len(tasks):
        logger.error(f"Failed to validate {len(tasks) - len(validations)} issue(s)")
    return validations


def _load_template_and_schema() -> tuple[Template, str]:
    """Load the issue-validation Jinja template and its output schema (static package assets)."""
    prompts_dir = Path(__file__).parent.parent / "prompts" / "issue_validation"
    env = Environment(loader=FileSystemLoader(prompts_dir), autoescape=select_autoescape())
    template = env.get_template("prompt.jinja")
    with (prompts_dir / "schema.json").open() as f:
        return template, f.read()


async def _validate_one(
    *,
    issue: Issue,
    chunk: Chunk,
    template: Template,
    schema: str,
    pr_metadata: PRMetadata,
    pr_files: list[PRFile],
    branch: str,
    repository: str,
) -> IssueValidation | None:
    """Validate a single issue through a sandbox agent; None on failure."""
    claude_code_context = prepare_code_context([issue.file], pr_files) if issue.file else ""
    prompt = template.render(
        CLAUDE_CODE_CONTEXT=claude_code_context,
        PR_CONTEXT=json.dumps(pr_metadata.model_dump(mode="json"), indent=2),
        CHUNK_CONTEXT=json.dumps(chunk.model_dump(), indent=2),
        ISSUE=issue.model_dump_json(indent=2),
        VALIDATION_SCHEMA=schema.strip(),
    )
    validation = await run_sandbox_review(
        prompt=prompt,
        system_prompt=_SYSTEM_PROMPT,
        branch=branch,
        repository=repository,
        model_to_validate=IssueValidation,
        step_name=f"validation-{issue.id}",
    )
    if validation is None:
        logger.error(f"Failed to validate issue {issue.id}")
        return None
    return validation
