import json
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRMetadata
from products.review_hog.backend.reviewer.models.issue_deduplicator import IssueDeduplication
from products.review_hog.backend.reviewer.models.issues_review import Issue, LineRange
from products.review_hog.backend.reviewer.sandbox.executor import run_sandbox_review

logger = logging.getLogger(__name__)

# A competing reviewer whose prior inline comments we dedupe against, so ReviewHog doesn't re-raise
# issues another bot already flagged on the PR.
_PRIOR_REVIEWER_BOT = "greptile-apps[bot]"


def _previous_bot_issues(pr_comments: list[PRComment]) -> list[PRComment]:
    """The prior-reviewer bot's inline comments, to dedupe ReviewHog's findings against."""
    previous = [c for c in pr_comments if c.user == _PRIOR_REVIEWER_BOT]
    logger.info(f"Found {len(previous)} previous issues from {_PRIOR_REVIEWER_BOT}")
    return previous


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


_SYSTEM_PROMPT = """You are a senior code reviewer analyzing duplicate issues in a pull request.
Your task is to:
1. Identify issues that are duplicates based on file location, line ranges, and problem description
2. Select the best representative issue to keep from each group of duplicates
3. Be conservative - only mark issues as duplicates if you're confident they address the same problem

IMPORTANT: Return ONLY valid JSON output that conforms to the provided schema."""


async def deduplicate_issues(
    *,
    issues: list[Issue],
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    branch: str,
    repository: str,
) -> list[Issue]:
    """Deduplicate the in-scope issues and return the survivors (the canonical post-dedup set).

    A deterministic positional pre-filter keeps positionally-isolated findings without an LLM call;
    only file+line colliders (vs another issue or a prior bot comment) reach the single sandbox
    dedupe call, which also drops issues already raised by a competing bot's prior comments.
    """
    if not issues:
        logger.info("No issues found to deduplicate.")
        return []

    previous_issues = _previous_bot_issues(pr_comments)
    prior_comment_lines = [pos for c in previous_issues if (pos := _comment_line(c)) is not None]
    candidates, unique = _select_dedup_candidates(issues, prior_comment_lines)
    logger.info(
        f"Deduplication: {len(candidates)} positional candidate(s); "
        f"{len(unique)} issue(s) kept without an LLM call (no positional overlap)"
    )
    if not candidates:
        logger.info("No positional duplicate candidates; kept all issues")
        return issues

    prompts_dir = Path(__file__).parent.parent / "prompts" / "issue_deduplicator"
    with (prompts_dir / "schema.json").open() as f:
        schema = f.read()
    env = Environment(loader=FileSystemLoader(prompts_dir), autoescape=select_autoescape())
    template = env.get_template("prompt.jinja")
    prompt = template.render(
        CLAUDE_CODE_CONTEXT="",  # No specific code context needed for deduplication
        PR_CONTEXT=json.dumps(pr_metadata.model_dump(mode="json"), indent=2),
        PREVIOUS_ISSUES_JSON=json.dumps([c.model_dump(mode="json") for c in previous_issues], indent=2),
        ISSUES_JSON=json.dumps([issue.model_dump(mode="json") for issue in candidates], indent=2),
        DEDUPLICATION_SCHEMA=schema.strip(),
    )

    deduplication_result = await run_sandbox_review(
        prompt=prompt,
        system_prompt=_SYSTEM_PROMPT,
        branch=branch,
        repository=repository,
        model_to_validate=IssueDeduplication,
        step_name="dedup",
    )
    if deduplication_result is None:
        logger.error("Failed to run issue deduplication")
        raise RuntimeError("Issue deduplication failed")

    # `unique` issues always survive; only positional candidates can be dropped by the LLM.
    duplicate_ids = {dup.id for dup in deduplication_result.duplicates}
    deduplicated_issues = unique + [issue for issue in candidates if issue.id not in duplicate_ids]
    logger.info(
        f"Deduplication completed: {len(issues)} -> {len(deduplicated_issues)} issues "
        f"({len(issues) - len(deduplicated_issues)} issues removed)"
    )
    return deduplicated_issues
