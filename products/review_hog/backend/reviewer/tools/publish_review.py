import os
import logging
from pathlib import Path

from github import Github, GithubException
from github.PullRequest import ReviewComment

from products.review_hog.backend.reviewer.models.chunk_analysis import ChunkAnalysis
from products.review_hog.backend.reviewer.models.github_meta import PRFile
from products.review_hog.backend.reviewer.models.issue_combination import IssueCombination
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority, LineRange
from products.review_hog.backend.reviewer.models.prepare_validation_markdown import (
    ValidationMarkdownReport,
    ValidationMarkdownReportChunk,
    ValidationMarkdownReportIssue,
)
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList

logger = logging.getLogger(__name__)


def publish_review(
    owner: str,
    repo: str,
    pr_number: int,
    review_dir: Path,
) -> None:
    """Publish review results as a GitHub PR review with inline comments."""
    logger.info(f"Publishing review for {owner}/{repo}#{pr_number}")

    chunks_data = _load_chunks(review_dir)
    pr_files = _load_pr_files(review_dir)
    report = _build_validation_report(review_dir, chunks_data)

    diff_lines = _build_diff_line_map(pr_files)
    body = _build_review_body(report)
    comments = _build_inline_comments(report, diff_lines)

    if not comments:
        logger.info("No publishable issues found, skipping review")
        return

    logger.info(f"Review: {len(body)} chars body, {len(comments)} inline comments")

    _post_github_review(owner, repo, pr_number, body, comments)


def _load_chunks(review_dir: Path) -> ChunksList:
    path = review_dir / "chunks.json"
    with path.open() as f:
        return ChunksList.model_validate_json(f.read())


def _load_pr_files(review_dir: Path) -> list[PRFile]:
    path = review_dir / "pr_files.jsonl"
    with path.open() as f:
        return [PRFile.model_validate_json(line) for line in f.readlines() if line.strip()]


def _build_diff_line_map(
    pr_files: list[PRFile],
) -> dict[str, set[int]]:
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


def _build_validation_report(
    review_dir: Path,
    chunks_data: ChunksList,
) -> ValidationMarkdownReport:
    """Build validation report from JSON files."""
    chunk_analyses: dict[int, ChunkAnalysis] = {}
    for chunk in chunks_data.chunks:
        path = review_dir / f"chunk-{chunk.chunk_id}-analysis.json"
        if path.exists():
            with path.open() as f:
                chunk_analyses[chunk.chunk_id] = ChunkAnalysis.model_validate_json(f.read())
        else:
            logger.warning(f"Missing analysis for chunk {chunk.chunk_id}")

    issues_path = review_dir / "issues_found.json"
    with issues_path.open() as f:
        issues_data = IssueCombination.model_validate_json(f.read())

    # Group issues by chunk using ID format "{pass}-{chunk}-{issue_num}"
    issues_by_chunk: dict[int, list[tuple[Issue, int, int]]] = {}
    for issue in issues_data.issues:
        parts = issue.id.split("-")
        if len(parts) != 3:
            logger.warning(f"Invalid issue ID format: {issue.id}")
            continue
        try:
            pass_id = int(parts[0])
            chunk_id = int(parts[1])
            issue_number = int(parts[2])
        except ValueError:
            logger.warning(f"Invalid issue ID format: {issue.id}")
            continue
        if chunk_id not in issues_by_chunk:
            issues_by_chunk[chunk_id] = []
        issues_by_chunk[chunk_id].append((issue, pass_id, issue_number))

    report_chunks = []
    for chunk in chunks_data.chunks:
        chunk_id = chunk.chunk_id
        chunk_analysis = chunk_analyses.get(chunk_id)
        if not chunk_analysis:
            logger.warning(f"Skipping chunk {chunk_id} - no analysis")
            continue

        validated_issues: list[ValidationMarkdownReportIssue] = []
        if chunk_id in issues_by_chunk:
            for issue, pass_id, issue_num in issues_by_chunk[chunk_id]:
                validation_path = (
                    review_dir
                    / f"pass{pass_id}_results"
                    / "validation"
                    / "summaries"
                    / (f"chunk-{chunk_id}-issue-{issue_num}-validation-summary.json")
                )
                if not validation_path.exists():
                    logger.warning(f"Missing validation for issue {issue.id}")
                    continue

                with validation_path.open() as f:
                    try:
                        validation = IssueValidation.model_validate_json(f.read())
                    except Exception as e:
                        logger.exception(f"Error parsing validation for issue {issue.id}: {e}")
                        continue

                if validation.is_valid:
                    validated_issues.append(
                        ValidationMarkdownReportIssue(
                            issue=issue,
                            validation=validation,
                        )
                    )

        report_chunks.append(
            ValidationMarkdownReportChunk(
                chunk=chunk,
                chunk_analysis=chunk_analysis,
                validated_issues=validated_issues,
            )
        )

    return ValidationMarkdownReport(chunks=report_chunks)


def _build_review_body(
    report: ValidationMarkdownReport,
) -> str:
    """Build the top-level review body with PR overview and all chunk summaries."""
    published_priorities = {
        IssuePriority.MUST_FIX,
        IssuePriority.SHOULD_FIX,
    }

    lines = [
        "# ReviewHog Report",
        "",
    ]

    for chunk_report in report.chunks:
        chunk = chunk_report.chunk
        analysis = chunk_report.chunk_analysis
        issue_count = sum(1 for vi in chunk_report.validated_issues if vi.issue.priority in published_priorities)

        chunk_type = chunk.chunk_type.replace("_", " ").capitalize() if chunk.chunk_type else "Changes"

        lines.extend([f"## {chunk_type}", ""])

        if chunk.files:
            file_list = ", ".join(f"`{f.filename}`" for f in chunk.files)
            lines.extend([f"**Files:** {file_list}", ""])

        if issue_count > 0:
            issues_label = "issue" if issue_count == 1 else "issues"
            lines.extend([f"**Issues:** {issue_count} {issues_label}", ""])

        if chunk.key_changes:
            lines.extend(
                [
                    "<details>",
                    "<summary>What were the main changes</summary>",
                    "<br>",
                    "",
                ]
            )
            for change in chunk.key_changes:
                lines.append(f"- {change}")
            lines.extend(["", "</details>", ""])

        lines.extend(
            [
                "<details>",
                "<summary>Full analysis</summary>",
                "<br>",
                "",
                analysis.goal,
                "",
                "</details>",
                "",
            ]
        )

    return "\n".join(lines)


def _format_line_ranges(line_ranges: list[LineRange]) -> str:
    """Format line ranges as a readable string."""
    parts = []
    for lr in line_ranges:
        if lr.end is None or lr.end == lr.start:
            parts.append(str(lr.start))
        else:
            parts.append(f"{lr.start}-{lr.end}")
    return ", ".join(parts)


def _format_issue_comment(
    issue: Issue,
    validation: IssueValidation,
) -> str:
    """Format an issue as a markdown comment body, matching the review report format."""
    formatted_lines = _format_line_ranges(issue.lines)

    meta_parts = [
        f"**Priority:** {issue.priority.value}",
    ]
    if validation.category:
        meta_parts.append(f"**Category:** {validation.category}")
    meta_parts.append(f"**Lines:** {formatted_lines}")

    lines = [
        f"### {issue.title}",
        "",
        " | ".join(meta_parts),
        "",
        "---",
        "",
        issue.issue,
        "",
        "<details>",
        "<summary><strong>Suggested fix</strong></summary>",
        "<br>",
        "",
        issue.suggestion,
        "",
        "</details>",
        "",
        "<details>",
        ("<summary><strong>Why we think it's a valid issue</strong></summary>"),
        "<br>",
        "",
        validation.argumentation,
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

    for lr in issue.lines:
        if lr.end is None or lr.end == lr.start:
            lines.append(f"@{issue.file}#L{lr.start}")
        else:
            lines.append(f"@{issue.file}#L{lr.start}-{lr.end}")

    lines.extend(
        [
            "",
            "<issue_description>",
            issue.issue,
            "</issue_description>",
            "",
            "<issue_validation>",
            validation.argumentation,
            "</issue_validation>",
            "",
            "## Task",
            "Investigate the issue and solve it",
            "",
            "<potential_solution>",
            issue.suggestion,
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

    Tries each line range in order. Returns (start_line, end_line) for the
    first range whose start line is in the diff. end_line is None for
    single-line comments. Returns None if no valid position is found.
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
    report: ValidationMarkdownReport,
    diff_lines: dict[str, set[int]],
) -> list[ReviewComment]:
    """Build inline comment dicts for the GitHub PR review API."""
    published_priorities = {
        IssuePriority.MUST_FIX,
        IssuePriority.SHOULD_FIX,
    }
    comments: list[ReviewComment] = []

    for chunk_report in report.chunks:
        for validated_issue in chunk_report.validated_issues:
            issue = validated_issue.issue
            validation = validated_issue.validation

            if issue.priority not in published_priorities:
                continue

            position = _find_valid_comment_position(issue.file, issue.lines, diff_lines)
            if position is None:
                logger.warning(f"No valid diff position for issue {issue.id} in {issue.file}, skipping")
                continue

            start_line, end_line = position
            body = _format_issue_comment(issue, validation)

            comment = ReviewComment(
                path=issue.file,
                body=body,
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
