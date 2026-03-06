import json
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from products.review_hog.backend.reviewer.llm.code import CodeExecutor
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRMetadata
from products.review_hog.backend.reviewer.models.issue_combination import IssueCombination
from products.review_hog.backend.reviewer.models.issue_deduplicator import IssueDeduplication

logger = logging.getLogger(__name__)


def load_previous_issues(review_dir: Path) -> list[PRComment]:
    """Load and filter PR comments for previous issues from greptile-apps[bot].

    Args:
        review_dir: The review directory containing pr_comments.jsonl

    Returns:
        List of PR comments from greptile-apps[bot]
    """
    previous_issues = []
    pr_comments_file = review_dir / "pr_comments.jsonl"

    if pr_comments_file.exists():
        with pr_comments_file.open() as f:
            for line in f:
                if line.strip():
                    comment = PRComment.model_validate_json(line)
                    if comment.user == "greptile-apps[bot]":
                        previous_issues.append(comment)
        logger.info(f"Found {len(previous_issues)} previous issues from greptile-apps[bot]")
    else:
        logger.info("No pr_comments.jsonl file found, proceeding without previous issues")

    return previous_issues


async def deduplicate_issues(
    pr_metadata: PRMetadata,
    review_dir: Path,
    project_dir: str,
) -> None:
    """Deduplicate issues found across all passes."""
    # Load issues from cleaning step (was combination step)
    issues_cleaned_file = review_dir / "issues_cleaned.json"
    if not issues_cleaned_file.exists():
        logger.error("No issues_cleaned.json file found. Run issue cleaning first.")
        raise FileNotFoundError(f"Cleaned issues file not found: {issues_cleaned_file}")

    with issues_cleaned_file.open() as f:
        issues_found = IssueCombination.model_validate_json(f.read())

    if not issues_found.issues:
        logger.info("No issues found to deduplicate.")
        # Create empty deduplication result
        empty_deduplication = IssueDeduplication(duplicates=[])
        with (review_dir / "deduplicator.json").open("w") as f:
            f.write(empty_deduplication.model_dump_json(indent=2))

        # Create empty final issues file as IssueCombination
        empty_issue_combination = IssueCombination(issues=[])
        with (review_dir / "issues_found.json").open("w") as f:
            f.write(empty_issue_combination.model_dump_json(indent=2))
        return

    # Load the deduplication schema
    prompts_dir = Path(__file__).parent.parent / "prompts" / "issue_deduplicator"
    with (prompts_dir / "schema.json").open() as f:
        schema = f.read()

    # Setup Jinja environment
    env = Environment(loader=FileSystemLoader(prompts_dir), autoescape=select_autoescape())
    template = env.get_template("prompt.jinja")

    # Check if deduplication already exists
    deduplicator_file = review_dir / "deduplicator.json"
    final_issues_file = review_dir / "issues_found.json"

    if deduplicator_file.exists() and final_issues_file.exists():
        logger.info("Issue deduplication already completed, skipping...")
        return

    # Load previous issues from PR comments
    previous_issues = load_previous_issues(review_dir)

    logger.info(f"Starting deduplication of {len(issues_found.issues)} issues...")

    # Prepare issues data for the prompt
    issues_json = json.dumps([issue.model_dump(mode="json") for issue in issues_found.issues], indent=2)

    # Prepare previous issues for the prompt
    previous_issues_json = json.dumps([comment.model_dump(mode="json") for comment in previous_issues], indent=2)

    # Render the template
    prompt = template.render(
        CLAUDE_CODE_CONTEXT="",  # No specific code context needed for deduplication
        PR_CONTEXT=json.dumps(pr_metadata.model_dump(mode="json"), indent=2),
        PREVIOUS_ISSUES_JSON=previous_issues_json,
        ISSUES_JSON=issues_json,
        DEDUPLICATION_SCHEMA=schema.strip(),
    )

    # Store the generated prompt for inspection
    deduplication_prompt_file = review_dir / "deduplication_prompt.md"
    with deduplication_prompt_file.open("w") as f:
        f.write(prompt)
    logger.info(f"Deduplication prompt saved to: {deduplication_prompt_file}")

    # Run deduplication using Claude Code
    success = await run_deduplication(
        prompt=prompt,
        output_path=str(deduplicator_file),
        project_dir=project_dir,
    )

    if not success:
        logger.error("Failed to run issue deduplication")
        raise RuntimeError("Issue deduplication failed")

    # Load the deduplication result and apply it
    with deduplicator_file.open() as f:
        deduplication_result = IssueDeduplication.model_validate_json(f.read())

    # Create the list of duplicates
    duplicate_ids = [dup.id for dup in deduplication_result.duplicates]
    deduplicated_issues = [issue for issue in issues_found.issues if issue.id not in duplicate_ids]

    # Save final issues as IssueCombination (replaces the original issues_found.json)
    final_issue_combination = IssueCombination(issues=deduplicated_issues)
    with final_issues_file.open("w") as f:
        f.write(final_issue_combination.model_dump_json(indent=2))

    # Calculate actual number of issues removed
    num_removed = len(issues_found.issues) - len(deduplicated_issues)
    logger.info(
        f"Deduplication completed: {len(issues_found.issues)} -> {len(deduplicated_issues)} issues "
        f"({num_removed} issues removed)"
    )


async def run_deduplication(
    prompt: str,
    output_path: str,
    project_dir: str,
) -> bool:
    """Run deduplication for issues using Claude Code SDK."""
    try:
        # System prompt for issue deduplication
        system_prompt = """You are a senior code reviewer analyzing duplicate issues in a pull request.
Your task is to:
1. Identify issues that are duplicates based on file location, line ranges, and problem description
2. Select the best representative issue to keep from each group of duplicates
3. Be conservative - only mark issues as duplicates if you're confident they address the same problem

IMPORTANT: Return ONLY valid JSON output that conforms to the provided schema."""

        code_executor = CodeExecutor(
            prompt=prompt,
            system_prompt=system_prompt,
            project_dir=project_dir,
            output_path=output_path,
            model_to_validate=IssueDeduplication,
        )
        success = await code_executor.run_code()
        if not success:
            logger.error("Failed to run issue deduplication")
            return False

        return True
    except Exception as e:
        logger.error(f"Error running issue deduplication: {e}")
        return False
