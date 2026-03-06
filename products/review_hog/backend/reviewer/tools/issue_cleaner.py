"""Tool for cleaning issues based on PR scope."""

import logging
from pathlib import Path

from products.review_hog.backend.reviewer.models.github_meta import PRFile
from products.review_hog.backend.reviewer.models.issue_combination import IssueCombination
from products.review_hog.backend.reviewer.models.issues_review import Issue

logger = logging.getLogger(__name__)


def clean_issues(review_dir: Path) -> None:
    """Clean issues by filtering out those outside the PR scope.

    This function reads the raw issues from the combination step and filters them
    based on whether they relate to files and lines modified in the PR.
    Issues that are in scope are saved to issues_cleaned.json.
    Issues that are out of scope are saved to issues_outside_scope.json.
    """
    # Load raw issues from combination step
    issues_found_raw_file = review_dir / "issues_found_raw.json"
    if not issues_found_raw_file.exists():
        logger.error("No issues_found_raw.json file found. Run issue combination first.")
        raise FileNotFoundError(f"Raw issues file not found: {issues_found_raw_file}")

    with issues_found_raw_file.open() as f:
        issues_found = IssueCombination.model_validate_json(f.read())

    # Load PR files to understand the scope
    pr_files_file = review_dir / "pr_files.jsonl"
    if not pr_files_file.exists():
        logger.error("No pr_files.jsonl file found.")
        raise FileNotFoundError(f"PR files not found: {pr_files_file}")

    # Parse PR files from JSONL format
    pr_files: list[PRFile] = []
    with pr_files_file.open() as f:
        for line in f:
            if line.strip():
                pr_files.append(PRFile.model_validate_json(line))

    # Build a map of modified files and their changed line ranges
    modified_files = _build_modified_files_map(pr_files)
    logger.info(f"Found {len(modified_files)} modified files in PR")

    # Filter issues based on scope
    in_scope_issues: list[Issue] = []
    out_of_scope_issues: list[Issue] = []

    for issue in issues_found.issues:
        # If fits within scope of the changed lines
        if _is_issue_in_scope(issue, modified_files):
            in_scope_issues.append(issue)
        else:
            out_of_scope_issues.append(issue)

    # Save the cleaned (in-scope) issues
    cleaned_issues = IssueCombination(issues=in_scope_issues)
    with (review_dir / "issues_cleaned.json").open("w") as f:
        f.write(cleaned_issues.model_dump_json(indent=2))

    # Save the out-of-scope issues
    outside_scope_issues = IssueCombination(issues=out_of_scope_issues)
    with (review_dir / "issues_outside_scope.json").open("w") as f:
        f.write(outside_scope_issues.model_dump_json(indent=2))

    logger.info(
        f"Issue cleaning completed: {len(issues_found.issues)} total issues -> "
        f"{len(in_scope_issues)} in scope, {len(out_of_scope_issues)} out of scope"
    )


def _build_modified_files_map(
    pr_files: list[PRFile],
) -> dict[str, list[tuple[int, int]]]:
    """Build a map of modified files and their changed line ranges."""
    modified_files: dict[str, list[tuple[int, int]]] = {}
    for pr_file in pr_files:
        if pr_file.status not in ["modified", "added"]:
            continue
        line_ranges = []
        for change in pr_file.changes:
            if change.type not in ["addition", "modification"]:
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
