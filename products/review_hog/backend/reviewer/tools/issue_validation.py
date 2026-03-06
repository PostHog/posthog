import asyncio
import json
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, Template, select_autoescape

from products.review_hog.backend.reviewer.llm.code import CodeExecutor, prepare_code_context
from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.issue_combination import IssueCombination
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList

logger = logging.getLogger(__name__)


async def validate_issues(
    chunks_data: ChunksList,
    pr_metadata: PRMetadata,
    pr_files: list[PRFile],
    review_dir: Path,
    project_dir: str,
) -> None:
    """Validate issues found in all passes."""
    # Create a mapping of chunk_id to chunk data for easy access
    chunks_map = {chunk.chunk_id: chunk for chunk in chunks_data.chunks}

    # Load the validation schema
    prompts_dir = Path(__file__).parent.parent / "prompts" / "issue_validation"
    with (prompts_dir / "schema.json").open() as f:
        schema = f.read()

    # Setup Jinja environment
    env = Environment(loader=FileSystemLoader(prompts_dir), autoescape=select_autoescape())
    template = env.get_template("prompt.jinja")

    # Collect all validation tasks from all passes
    all_validation_tasks = []
    total_issues = 0

    # Collect tasks
    with (review_dir / "issues_found.json").open() as f:
        issues_found = IssueCombination.model_validate_json(f.read())
    for issue in issues_found.issues:
        pass_number, chunk_index, issue_number = issue.id.split("-")
        # Directory paths for this pass
        pass_results_dir = review_dir / f"pass{pass_number}_results"
        validation_prompts_dir = pass_results_dir / "validation" / "prompts"
        validation_summaries_dir = pass_results_dir / "validation" / "summaries"
        # Get chunk data
        chunk_data = chunks_map[int(chunk_index)]
        # Process all issues
        task = create_validation_task(
            template=template,
            issue=issue,
            chunk_index=int(chunk_index),
            issue_index=int(issue_number),
            validation_prompts_dir=validation_prompts_dir,
            validation_summaries_dir=validation_summaries_dir,
            schema=schema,
            pr_metadata=pr_metadata,
            pr_files=pr_files,
            chunk_data=chunk_data.model_dump(),
            project_dir=project_dir,
        )
        if task:
            all_validation_tasks.append(task)
            total_issues += 1

    # Run all validations in batches of 10
    if all_validation_tasks:
        logger.info(f"Running {len(all_validation_tasks)} total validations across all passes in batches of 10...")
        # Process in batches of 10
        batch_size = 10
        for i in range(0, len(all_validation_tasks), batch_size):
            batch = all_validation_tasks[i : i + batch_size]
            batch_end = min(i + batch_size, len(all_validation_tasks))
            logger.info(
                f"Processing batch {i // batch_size + 1}: tasks {i + 1}-{batch_end} of {len(all_validation_tasks)}"
            )
            tasks_results = await asyncio.gather(*batch)
            if not all(tasks_results):
                logger.error(f"Failed to validate some issues in batch {[x for x in tasks_results if not x]}")
        logger.info(f"Completed all {len(all_validation_tasks)} validations across all passes")
    else:
        logger.info("No validation tasks found across all passes")


async def create_validation_task(
    template: Template,
    issue: Issue,
    chunk_index: int,
    issue_index: int,
    validation_prompts_dir: Path,
    validation_summaries_dir: Path,
    schema: str,
    pr_metadata: PRMetadata,
    chunk_data: dict,
    pr_files: list[PRFile],
    project_dir: str,
) -> bool | None:
    """Create a validation task for an issue."""
    # Generate the prompt first
    prompt_path = validation_prompts_dir / f"chunk-{chunk_index}-issue-{issue_index}-validation-prompt.md"
    output_path = validation_summaries_dir / f"chunk-{chunk_index}-issue-{issue_index}-validation-summary.json"

    # Ensure directories exist
    validation_prompts_dir.mkdir(parents=True, exist_ok=True)
    validation_summaries_dir.mkdir(parents=True, exist_ok=True)

    # Skip if already validated
    if output_path.exists() and output_path.stat().st_size > 0:
        logger.info(f"Validation already exists for chunk {chunk_index} issue {issue_index}, skipping...")
        return None

    # Generate Claude Code context with specific line ranges if file is available
    claude_code_context = ""
    if issue.file:
        # Use prepare_code_context to get optimized line ranges
        claude_code_context = prepare_code_context([issue.file], pr_files)

    # Render the template
    prompt = template.render(
        CLAUDE_CODE_CONTEXT=claude_code_context,
        PR_CONTEXT=json.dumps(pr_metadata.model_dump(mode="json"), indent=2),
        CHUNK_CONTEXT=json.dumps(chunk_data, indent=2),
        ISSUE=issue.model_dump_json(indent=2),
        VALIDATION_SCHEMA=schema.strip(),
    )

    # Save the prompt file
    with prompt_path.open("w") as f:
        f.write(prompt)

    # Return the async task
    return await run_validation(
        prompt=prompt,
        output_path=output_path,
        project_dir=project_dir,
        chunk_index=chunk_index,
        issue_index=issue_index,
    )


async def run_validation(
    prompt: str,
    output_path: Path,
    project_dir: str,
    chunk_index: int,
    issue_index: int,
) -> bool:
    """Run validation for a single issue using Claude Code SDK."""
    try:
        # System prompt for issue validation
        system_prompt = """You are a senior code reviewer validating suggested issues in a pull request.
Your task is to:
1. Analyze the suggested issue in the context of the codebase
2. Determine if the issue is valid and should be addressed
3. Provide clear reasoning for your decision
4. Identify the category and potential risks if applicable

IMPORTANT: Return ONLY valid JSON output that conforms to the provided schema."""

        code_executor = CodeExecutor(
            prompt=prompt,
            system_prompt=system_prompt,
            project_dir=project_dir,
            output_path=str(output_path),
            model_to_validate=IssueValidation,
        )
        success = await code_executor.run_code()
        if not success:
            logger.error(f"Failed to validate chunk {chunk_index} issue {issue_index}")
            return False
        return True
    except Exception as e:
        logger.error(f"Error validating chunk {chunk_index} issue {issue_index}: {e}")
        return False
