import os
import logging

from github import Github, GithubException
from github.PullRequest import ReviewComment

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding, ValidationVerdict
from products.review_hog.backend.reviewer.models.github_meta import PRFile
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority, LineRange
from products.review_hog.backend.reviewer.persistence import load_valid_findings

logger = logging.getLogger(__name__)

# Only these priorities are published as inline comments (CONSIDER is body-only context).
_PUBLISHED_PRIORITIES = {IssuePriority.MUST_FIX, IssuePriority.SHOULD_FIX}


def publish_review(
    *, owner: str, repo: str, pr_number: int, team_id: int, report_id: str, pr_files: list[PRFile]
) -> None:
    """Publish the review to GitHub: the stored body plus inline comments from the durable rows.

    The body is `ReviewReport.report_markdown` (rendered this turn); the inline comments are rebuilt
    from the current valid finding/verdict rows, positioned against the PR's diff. Reads the DB, so
    callers run it off the event loop (e.g. via `sync_to_async`).
    """
    logger.info(f"Publishing review for {owner}/{repo}#{pr_number}")

    report = ReviewReport.objects.for_team(team_id).get(id=report_id)
    body = report.report_markdown
    valid_findings = load_valid_findings(team_id=team_id, report_id=report_id)

    diff_lines = _build_diff_line_map(pr_files)
    comments = _build_inline_comments(valid_findings, diff_lines)

    if not comments:
        logger.info("No publishable issues found, skipping review")
        return

    logger.info(f"Review: {len(body)} chars body, {len(comments)} inline comments")
    _post_github_review(owner, repo, pr_number, body, comments)


def _build_diff_line_map(pr_files: list[PRFile]) -> dict[str, set[int]]:
    """Map each filename to the set of new-file line numbers present in the diff."""
    diff_lines: dict[str, set[int]] = {}
    for pr_file in pr_files:
        valid_lines: set[int] = set()
        for change in pr_file.changes:
            if change.type == "deletion":
                continue
            start = change.new_start_line
            if start is not None:
                end = change.new_end_line or start
                valid_lines.update(range(start, end + 1))
        diff_lines[pr_file.filename] = valid_lines
    return diff_lines


def _format_line_ranges(line_ranges: list[LineRange]) -> str:
    """Format line ranges as a readable string."""
    parts = []
    for lr in line_ranges:
        if lr.end is None or lr.end == lr.start:
            parts.append(str(lr.start))
        else:
            parts.append(f"{lr.start}-{lr.end}")
    return ", ".join(parts)


def _format_issue_comment(finding: ReviewIssueFinding, verdict: ValidationVerdict) -> str:
    """Format a finding + its verdict as an inline comment body."""
    formatted_lines = _format_line_ranges(finding.lines)

    meta_parts = [f"**Priority:** {finding.priority.value}"]
    if verdict.category:
        meta_parts.append(f"**Category:** {verdict.category}")
    meta_parts.append(f"**Lines:** {formatted_lines}")

    lines = [
        f"### {finding.title}",
        "",
        " | ".join(meta_parts),
        "",
        "---",
        "",
        finding.body,
        "",
        "<details>",
        "<summary><strong>Suggested fix</strong></summary>",
        "<br>",
        "",
        finding.suggestion,
        "",
        "</details>",
        "",
        "<details>",
        ("<summary><strong>Why we think it's a valid issue</strong></summary>"),
        "<br>",
        "",
        verdict.argumentation,
        "",
        "</details>",
        "",
        "<details>",
        ("<summary><strong>Prompt to fix with AI (copy-paste)</strong></summary>"),
        "<br>",
        "",
        "```",
        "## Context",
    ]

    for lr in finding.lines:
        if lr.end is None or lr.end == lr.start:
            lines.append(f"@{finding.file}#L{lr.start}")
        else:
            lines.append(f"@{finding.file}#L{lr.start}-{lr.end}")

    lines.extend(
        [
            "",
            "<issue_description>",
            finding.body,
            "</issue_description>",
            "",
            "<issue_validation>",
            verdict.argumentation,
            "</issue_validation>",
            "",
            "## Task",
            "Investigate the issue and solve it",
            "",
            "<potential_solution>",
            finding.suggestion,
            "</potential_solution>",
            "```",
            "",
            "</details>",
            "",
        ]
    )

    return "\n".join(lines)


def _find_valid_comment_position(
    file: str,
    line_ranges: list[LineRange],
    diff_lines: dict[str, set[int]],
) -> tuple[int, int | None] | None:
    """Find the first valid line position for an inline comment.

    Tries each line range in order. Returns (start_line, end_line) for the first range whose start
    line is in the diff. end_line is None for single-line comments. Returns None if no valid
    position is found.
    """
    valid_lines = diff_lines.get(file)
    if valid_lines is None:
        return None

    for lr in line_ranges:
        if lr.start in valid_lines:
            end = lr.end if lr.end is not None and lr.end in valid_lines else None
            return (lr.start, end)
    return None


def _build_inline_comments(
    valid_findings: list[tuple[ReviewIssueFinding, ValidationVerdict]],
    diff_lines: dict[str, set[int]],
) -> list[ReviewComment]:
    """Build inline comment dicts for the GitHub PR review API from valid finding/verdict rows."""
    comments: list[ReviewComment] = []

    for finding, verdict in valid_findings:
        if finding.priority not in _PUBLISHED_PRIORITIES:
            continue

        position = _find_valid_comment_position(finding.file, finding.lines, diff_lines)
        if position is None:
            logger.warning(f"No valid diff position for finding in {finding.file}, skipping")
            continue

        start_line, end_line = position
        comment = ReviewComment(
            path=finding.file,
            body=_format_issue_comment(finding, verdict),
            side="RIGHT",
        )

        if end_line is not None and end_line != start_line:
            comment["start_line"] = start_line
            comment["start_side"] = "RIGHT"
            comment["line"] = end_line
        else:
            comment["line"] = start_line

        comments.append(comment)

    return comments


def _post_github_review(
    owner: str,
    repo: str,
    pr_number: int,
    body: str,
    comments: list[ReviewComment],
) -> None:
    """Post the review to GitHub as a PR review."""
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        raise ValueError("GITHUB_TOKEN environment variable not set.")

    g = Github(github_token)
    repo_obj = g.get_repo(f"{owner}/{repo}")
    pr = repo_obj.get_pull(pr_number)

    pr.create_issue_comment(
        "ReviewHog Alpha \U0001f994 "
        "If you find any issues helpful - "
        'please reply "valid", "invalid", etc., '
        "for evaluation purposes \U0001f64f"
    )

    if comments:
        try:
            pr.create_review(
                body=body,
                event="COMMENT",
                comments=comments,
            )
            logger.info(f"Review posted with {len(comments)} inline comments")
            return
        except GithubException as e:
            logger.warning(f"Failed to post review with inline comments: {e}. Posting review body only.")

    pr.create_review(body=body, event="COMMENT")
    logger.info("Review posted (body only)")
