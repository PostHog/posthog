import json
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRMetadata
from products.review_hog.backend.reviewer.models.issue_combination import IssueCombination
from products.review_hog.backend.reviewer.models.issue_deduplicator import IssueDeduplication
from products.review_hog.backend.reviewer.models.issues_review import Issue, LineRange
from products.review_hog.backend.reviewer.sandbox.executor import run_sandbox_review

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


def _ranges_overlap(a: list[LineRange], b: list[LineRange]) -> bool:
    """True if any line range in a overlaps any line range in b."""
    for ra in a:
        a_end = ra.end or ra.start
        for rb in b:
            b_end = rb.end or rb.start
            if ra.start <= b_end and rb.start <= a_end:
                return True
    return False


def _comment_line(comment: PRComment) -> tuple[str, int] | None:
    """The (file, line) a prior review comment sits on, or None if it has no resolvable line."""
    line = comment.line if comment.line is not None else comment.start_line
    return (comment.path, line) if line is not None else None


def _select_dedup_candidates(
    issues: list[Issue], prior_comment_lines: list[tuple[str, int]]
) -> tuple[list[Issue], list[Issue]]:
    """Split issues into (dedup candidates, definitely-unique) by deterministic position.

    Only an issue that shares a file and overlapping lines with another issue — or with a prior
    review comment — can be a duplicate, so the rest skip the LLM dedupe entirely. This keeps the
    single dedupe call small as the number of lenses grows, and never drops a positionally isolated
    finding. Whether two positionally-colliding issues are *actually* duplicates is still left to
    the content-aware LLM.
    """
    candidates: list[Issue] = []
    unique: list[Issue] = []
    for i, issue in enumerate(issues):
        collides_with_issue = any(
            i != j and issue.file == other.file and _ranges_overlap(issue.lines, other.lines)
            for j, other in enumerate(issues)
        )
        collides_with_comment = any(
            path == issue.file and any(r.start <= line <= (r.end or r.start) for r in issue.lines)
            for path, line in prior_comment_lines
        )
        (candidates if collides_with_issue or collides_with_comment else unique).append(issue)
    return candidates, unique


async def deduplicate_issues(
    pr_metadata: PRMetadata,
    review_dir: Path,
    branch: str,
    repository: str,
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

    # Deterministic pre-filter: only issues that positionally collide with another issue or a prior
    # comment can be duplicates — the rest survive without an LLM call, keeping the dedupe call small.
    prior_comment_lines = [pos for c in previous_issues if (pos := _comment_line(c)) is not None]
    candidates, unique = _select_dedup_candidates(issues_found.issues, prior_comment_lines)
    logger.info(
        f"Deduplication: {len(candidates)} positional candidate(s); "
        f"{len(unique)} issue(s) kept without an LLM call (no positional overlap)"
    )

    if not candidates:
        empty_deduplication = IssueDeduplication(duplicates=[])
        with deduplicator_file.open("w") as f:
            f.write(empty_deduplication.model_dump_json(indent=2))
        with final_issues_file.open("w") as f:
            f.write(IssueCombination(issues=issues_found.issues).model_dump_json(indent=2))
        logger.info("No positional duplicate candidates; kept all issues")
        return

    # Prepare issues data for the prompt (only the positional candidates)
    issues_json = json.dumps([issue.model_dump(mode="json") for issue in candidates], indent=2)

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

    # Run deduplication using sandbox
    success = await run_deduplication(
        prompt=prompt,
        output_path=str(deduplicator_file),
        branch=branch,
        repository=repository,
    )

    if not success:
        logger.error("Failed to run issue deduplication")
        raise RuntimeError("Issue deduplication failed")

    # Load the deduplication result and apply it
    with deduplicator_file.open() as f:
        deduplication_result = IssueDeduplication.model_validate_json(f.read())

    # `unique` issues always survive; only positional candidates can be dropped by the LLM.
    duplicate_ids = {dup.id for dup in deduplication_result.duplicates}
    deduplicated_issues = unique + [issue for issue in candidates if issue.id not in duplicate_ids]

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
    branch: str,
    repository: str,
) -> bool:
    """Run deduplication for issues using a sandbox agent."""
    try:
        system_prompt = """You are a senior code reviewer analyzing duplicate issues in a pull request.
Your task is to:
1. Identify issues that are duplicates based on file location, line ranges, and problem description
2. Select the best representative issue to keep from each group of duplicates
3. Be conservative - only mark issues as duplicates if you're confident they address the same problem

IMPORTANT: Return ONLY valid JSON output that conforms to the provided schema."""

        success = await run_sandbox_review(
            prompt=prompt,
            system_prompt=system_prompt,
            branch=branch,
            repository=repository,
            output_path=output_path,
            model_to_validate=IssueDeduplication,
            step_name="dedup",
        )
        if not success:
            logger.error("Failed to run issue deduplication")
            return False

        return True
    except Exception as e:
        logger.exception(f"Error running issue deduplication: {e}")
        return False
