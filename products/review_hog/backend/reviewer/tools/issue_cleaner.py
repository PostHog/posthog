"""Tool for cleaning issues based on PR scope."""

import logging

from products.review_hog.backend.reviewer.models.github_meta import PRFile
from products.review_hog.backend.reviewer.models.issues_review import Issue

logger = logging.getLogger(__name__)


def clean_issues(issues: list[Issue], pr_files: list[PRFile]) -> list[Issue]:
    """Return only the issues whose file and lines overlap the PR's changed ranges.

    Filters out findings that don't relate to files/lines modified in the PR, so the review stays
    scoped to the diff.
    """
    modified_files = _build_modified_files_map(pr_files)
    logger.info(f"Found {len(modified_files)} modified files in PR")

    in_scope_issues = [issue for issue in issues if _is_issue_in_scope(issue, modified_files)]
    logger.info(
        f"Issue cleaning completed: {len(issues)} total issues -> "
        f"{len(in_scope_issues)} in scope, {len(issues) - len(in_scope_issues)} out of scope"
    )
    return in_scope_issues


def _build_modified_files_map(
    pr_files: list[PRFile],
) -> dict[str, list[tuple[int, int]]]:
    """Build a map of modified files and their changed line ranges."""
    modified_files: dict[str, list[tuple[int, int]]] = {}
    for pr_file in pr_files:
        # Status is deliberately ignored: renamed/copied files still carry real diffs, and files
        # without addition changes (pure renames, deletions) yield no line ranges and are skipped below.
        line_ranges = []
        for change in pr_file.changes:
            if change.type != "addition":
                continue
            # Use new_start_line and new_end_line for additions
            if change.new_start_line is not None and change.new_end_line is not None:
                line_ranges.append((change.new_start_line, change.new_end_line))
        if line_ranges:
            modified_files[pr_file.filename] = line_ranges
    return modified_files


def _parse_issue_lines(issue: Issue) -> list[tuple[int, int]]:
    """Parse issue line ranges. Returns list of (start, end) tuples."""
    line_ranges = []
    for line_range in issue.lines:
        if line_range.end is None:
            # Single line issue
            line_ranges.append((line_range.start, line_range.start))
        else:
            # Multi-line issue
            line_ranges.append((line_range.start, line_range.end))
    return line_ranges


def _is_issue_in_scope(issue: Issue, modified_files: dict[str, list[tuple[int, int]]]) -> bool:
    """Check if an issue is in scope based on modified files and lines."""
    # Check if the issue's file is in the PR scope
    if issue.file not in modified_files:
        logger.debug(f"Issue {issue.id} is out of scope: file {issue.file} not in PR")
        return False

    # Parse the issue's line ranges
    issue_line_ranges = _parse_issue_lines(issue)
    if not issue_line_ranges:
        # If no line ranges, consider it in scope since the file matches
        return True

    # Check if ANY of the issue's line ranges overlap with ANY modified line ranges
    for issue_start, issue_end in issue_line_ranges:
        for pr_start, pr_end in modified_files[issue.file]:
            # Check for ANY overlap between [issue_start, issue_end] and [pr_start, pr_end]
            # Two ranges overlap if: start1 <= end2 AND start2 <= end1
            if issue_start <= pr_end and pr_start <= issue_end:
                logger.debug(
                    f"Issue {issue.id} is in scope: lines [{issue_start}-{issue_end}]"
                    f" overlap with changes [{pr_start}, {pr_end}]"
                )
                return True

    logger.debug(f"Issue {issue.id} is out of scope: no line ranges overlap with changes")
    return False
