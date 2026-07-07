import json
import logging

from products.review_hog.backend.reviewer.constants import DEDUP_ONESHOT_MAX_FINDINGS
from products.review_hog.backend.reviewer.models.github_meta import PRComment, PRMetadata
from products.review_hog.backend.reviewer.models.issue_deduplicator import IssueDeduplication
from products.review_hog.backend.reviewer.models.issues_review import Issue, LineRange
from products.review_hog.backend.reviewer.sandbox.direct_llm import run_oneshot_review
from products.review_hog.backend.reviewer.sandbox.executor import run_sandbox_review
from products.review_hog.backend.reviewer.tools.prompt_helpers import load_template_and_schema

logger = logging.getLogger(__name__)


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
    single dedupe call small as the number of perspectives grows, and never drops a positionally isolated
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


_SYSTEM_PROMPT = """You are a senior code reviewer removing duplicate findings from a pull-request review.
A finding is a duplicate only when it raises the same concrete problem as another finding or a prior
inline comment — not merely because it shares a file or line. Once findings address the same concrete
problem, collapse them aggressively and keep only the single most comprehensive one.

IMPORTANT: Return ONLY valid JSON output that conforms to the provided schema."""


async def deduplicate_issues(
    *,
    team_id: int,
    user_id: int,
    issues: list[Issue],
    pr_metadata: PRMetadata,
    pr_comments: list[PRComment],
    branch: str,
    repository: str,
    workflow_id_prefix: str | None = None,
) -> list[Issue]:
    """Deduplicate the in-scope issues and return the survivors (the canonical post-dedup set).

    A deterministic positional pre-filter keeps positionally-isolated findings without an LLM call;
    only file+line colliders (vs another finding or any prior inline comment) reach the single LLM
    dedupe call, which also drops findings a prior inline comment already raised — from any reviewer,
    bot or human, ReviewHog's own included. The dedupe prompt is pure text (no code context), so
    within the one-shot gate that call is a direct gateway call; only an over-limit finding set
    falls back to the sandbox.
    """
    if not issues:
        logger.info("No issues found to deduplicate.")
        return []

    prior_comment_lines = [pos for c in pr_comments if (pos := _comment_line(c)) is not None]
    if pr_comments:
        authors = sorted({c.user for c in pr_comments})
        logger.info(f"Deduping against {len(pr_comments)} prior inline comment(s) from authors: {authors}")
    candidates, unique = _select_dedup_candidates(issues, prior_comment_lines)
    logger.info(
        f"Deduplication: {len(candidates)} positional candidate(s); "
        f"{len(unique)} issue(s) kept without an LLM call (no positional overlap)"
    )
    if not candidates:
        logger.info("No positional duplicate candidates; kept all issues")
        return issues

    template, schema = load_template_and_schema("issue_deduplicator")
    prompt = template.render(
        CLAUDE_CODE_CONTEXT="",  # No specific code context needed for deduplication
        PR_CONTEXT=json.dumps(pr_metadata.model_dump(mode="json"), indent=2),
        PRIOR_COMMENTS_JSON=json.dumps([c.model_dump(mode="json") for c in pr_comments], indent=2),
        ISSUES_JSON=json.dumps([issue.model_dump(mode="json") for issue in candidates], indent=2),
        DEDUPLICATION_SCHEMA=schema.strip(),
    )

    if DEDUP_ONESHOT_MAX_FINDINGS and len(issues) <= DEDUP_ONESHOT_MAX_FINDINGS:
        deduplication_result = await run_oneshot_review(
            team_id=team_id,
            user_id=user_id,
            prompt=prompt,
            system_prompt=_SYSTEM_PROMPT,
            model_to_validate=IssueDeduplication,
            step_name="dedup",
        )
    else:
        deduplication_result = await run_sandbox_review(
            team_id=team_id,
            user_id=user_id,
            repository=repository,
            branch=branch,
            prompt=prompt,
            system_prompt=_SYSTEM_PROMPT,
            model_to_validate=IssueDeduplication,
            step_name="dedup",
            workflow_id_prefix=workflow_id_prefix,
        )
    # `unique` issues always survive; only positional candidates can be dropped by the LLM.
    duplicate_ids = {dup.id for dup in deduplication_result.duplicates}
    deduplicated_issues = unique + [issue for issue in candidates if issue.id not in duplicate_ids]
    logger.info(
        f"Deduplication completed: {len(issues)} -> {len(deduplicated_issues)} issues "
        f"({len(issues) - len(deduplicated_issues)} issues removed)"
    )
    return deduplicated_issues
