"""Render the PR-facing review body (stored as `ReviewReport.report_markdown` and posted to GitHub).

Assembles the per-chunk report tree from in-process pipeline objects (chunks, the canonical issues
and their validations), keeping only validated issues, then renders the high-level summary body. The
detailed per-issue findings are published as inline comments by `publish_review` (read from the
durable finding/verdict rows), so the body stays a summary.
"""

import logging

from products.review_hog.backend.reviewer.constants import effective_priority
from products.review_hog.backend.reviewer.diff_position import (
    build_diff_line_map,
    find_diff_position,
    format_line_ranges,
)
from products.review_hog.backend.reviewer.models.github_meta import PRFile
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority
from products.review_hog.backend.reviewer.models.prepare_validation_markdown import (
    ValidationMarkdownReport,
    ValidationMarkdownReportChunk,
    ValidationMarkdownReportIssue,
)
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList

logger = logging.getLogger(__name__)


def build_review_body(
    *,
    chunks_data: ChunksList,
    issues: list[Issue],
    validations: dict[str, IssueValidation],
    pr_files: list[PRFile],
    published_priorities: set[IssuePriority],
) -> str:
    """Render the PR-facing review body from this turn's in-process pipeline objects.

    `validations` is keyed by the live issue id (`{pass}-{chunk}-{issue}`); only issues the
    validator ruled valid appear in the report. `pr_files` (this turn's reviewed diff) decides which
    valid findings can't be anchored to an inline comment — those are surfaced in an "Other findings"
    section instead of being silently dropped at publish. `published_priorities` is the acting user's
    urgency-threshold set (`published_priorities_for`), shared with the publisher so counts and
    comments agree.
    """
    report = _assemble_report(chunks_data, issues, validations)
    off_diff = _off_diff_publishable_findings(issues, validations, pr_files, published_priorities)
    return _render_review_body(report, off_diff, published_priorities)


def _assemble_report(
    chunks_data: ChunksList,
    issues: list[Issue],
    validations: dict[str, IssueValidation],
) -> ValidationMarkdownReport:
    """Group validated issues under their chunk (keyed via the issue id `{pass}-{chunk}-{issue}`)."""
    issues_by_chunk: dict[int, list[Issue]] = {}
    for issue in issues:
        parts = issue.id.split("-")
        if len(parts) != 3:
            logger.warning(f"Invalid issue ID format: {issue.id}")
            continue
        try:
            chunk_id = int(parts[1])
        except ValueError:
            logger.warning(f"Invalid issue ID format: {issue.id}")
            continue
        issues_by_chunk.setdefault(chunk_id, []).append(issue)

    report_chunks: list[ValidationMarkdownReportChunk] = []
    for chunk in chunks_data.chunks:
        validated_issues = [
            ValidationMarkdownReportIssue(
                issue=issue, effective_priority=effective_priority(issue.priority, v.adjusted_priority)
            )
            for issue in issues_by_chunk.get(chunk.chunk_id, [])
            if (v := validations.get(issue.id)) is not None and v.is_valid
        ]
        # A chunk with no validated finding has nothing to show — skip it so the body stays a list of
        # findings and doesn't balloon on a large multi-chunk PR.
        if not validated_issues:
            continue
        report_chunks.append(ValidationMarkdownReportChunk(chunk=chunk, validated_issues=validated_issues))
    return ValidationMarkdownReport(chunks=report_chunks)


def _off_diff_publishable_findings(
    issues: list[Issue],
    validations: dict[str, IssueValidation],
    pr_files: list[PRFile],
    published_priorities: set[IssuePriority],
) -> list[tuple[Issue, IssueValidation]]:
    """Valid publishable findings whose line isn't on the diff, so they get no inline comment.

    GitHub only takes inline comments on changed lines, so a valid finding on a changed file but an
    unchanged line would otherwise vanish at publish. The body surfaces these instead of dropping them.
    """
    diff_lines = build_diff_line_map(pr_files)
    out: list[tuple[Issue, IssueValidation]] = []
    for issue in issues:
        validation = validations.get(issue.id)
        if validation is None or not validation.is_valid:
            continue
        if effective_priority(issue.priority, validation.adjusted_priority) not in published_priorities:
            continue
        if find_diff_position(issue.file, issue.lines, diff_lines) is not None:
            continue  # has an inline anchor → posted inline, not here
        out.append((issue, validation))
    return out


def _render_review_body(
    report: ValidationMarkdownReport,
    off_diff_findings: list[tuple[Issue, IssueValidation]],
    published_priorities: set[IssuePriority],
) -> str:
    """Render the top-level review body: the per-chunk overview plus any off-diff findings section."""
    lines = [
        "# ReviewHog Report",
        "",
    ]

    for chunk_report in report.chunks:
        chunk = chunk_report.chunk
        issue_count = sum(1 for vi in chunk_report.validated_issues if vi.effective_priority in published_priorities)

        chunk_type = chunk.chunk_type.replace("_", " ").capitalize() if chunk.chunk_type else "Changes"
        lines.extend([f"## {chunk_type}", ""])

        if chunk.files:
            file_list = ", ".join(f"`{f.filename}`" for f in chunk.files)
            lines.extend([f"**Files:** {file_list}", ""])

        if issue_count > 0:
            issues_label = "issue" if issue_count == 1 else "issues"
            lines.extend([f"**Issues:** {issue_count} {issues_label}", ""])

        if chunk.key_changes:
            lines.extend(["<details>", "<summary>What were the main changes</summary>", "<br>", ""])
            for change in chunk.key_changes:
                lines.append(f"- {change}")
            lines.extend(["", "</details>", ""])

    lines.extend(_render_off_diff_section(off_diff_findings))
    return "\n".join(lines)


def _render_off_diff_section(findings: list[tuple[Issue, IssueValidation]]) -> list[str]:
    """Render valid findings with no inline position as a body section (empty when there are none)."""
    if not findings:
        return []
    lines = [
        "## Other findings (outside the changed lines)",
        "",
        "_Valid issues on this PR's files that sit on lines GitHub won't let us comment on inline._",
        "",
    ]
    for issue, validation in findings:
        priority = effective_priority(issue.priority, validation.adjusted_priority)
        meta = [f"**Priority:** {priority.value}", f"**File:** `{issue.file}:{format_line_ranges(issue.lines)}`"]
        if validation.category:
            meta.append(f"**Category:** {validation.category}")
        lines.extend(
            [
                f"### {issue.title}",
                "",
                " | ".join(meta),
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
                "<summary><strong>Why we think it's a valid issue</strong></summary>",
                "<br>",
                "",
                validation.argumentation,
                "",
                "</details>",
                "",
            ]
        )
    return lines
