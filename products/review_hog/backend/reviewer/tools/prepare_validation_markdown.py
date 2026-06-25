"""Render the PR-facing review body (stored as `ReviewReport.report_markdown` and posted to GitHub).

Assembles the per-chunk report tree from in-process pipeline objects (chunks, analyses, the
canonical issues and their validations), keeping only validated issues, then renders the
high-level summary body. The detailed per-issue findings are published as inline comments by
`publish_review` (read from the durable finding/verdict rows), so the body stays a summary.
"""

import logging

from products.review_hog.backend.reviewer.models.chunk_analysis import ChunkAnalysis, ChunkMeta
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue, IssuePriority
from products.review_hog.backend.reviewer.models.prepare_validation_markdown import (
    ValidationMarkdownReport,
    ValidationMarkdownReportChunk,
    ValidationMarkdownReportIssue,
)
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, ChunksList

logger = logging.getLogger(__name__)

# Priorities surfaced in the body's per-chunk issue count (and published as inline comments).
_PUBLISHED_PRIORITIES = {IssuePriority.MUST_FIX, IssuePriority.SHOULD_FIX}


def build_review_body(
    *,
    chunks_data: ChunksList,
    analyses: dict[int, ChunkAnalysis],
    issues: list[Issue],
    validations: dict[str, IssueValidation],
) -> str:
    """Render the PR-facing review body from this turn's in-process pipeline objects.

    `validations` is keyed by the live issue id (`{pass}-{chunk}-{issue}`); only issues the
    validator ruled valid appear in the report.
    """
    report = _assemble_report(chunks_data, analyses, issues, validations)
    return _render_review_body(report)


def _assemble_report(
    chunks_data: ChunksList,
    analyses: dict[int, ChunkAnalysis],
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
            ValidationMarkdownReportIssue(issue=issue, validation=validations[issue.id])
            for issue in issues_by_chunk.get(chunk.chunk_id, [])
            if (v := validations.get(issue.id)) is not None and v.is_valid
        ]
        analysis = analyses.get(chunk.chunk_id)
        if analysis is None:
            # Analysis is best-effort and can fail transiently. Dropping the chunk would hide a valid
            # finding that publish (DB-driven) still posts an inline comment for — so keep the chunk
            # (with a placeholder) when it has validated issues, and stay quiet otherwise.
            if not validated_issues:
                continue
            analysis = _placeholder_analysis(chunk)
        report_chunks.append(
            ValidationMarkdownReportChunk(chunk=chunk, chunk_analysis=analysis, validated_issues=validated_issues)
        )
    return ValidationMarkdownReport(chunks=report_chunks)


def _placeholder_analysis(chunk: Chunk) -> ChunkAnalysis:
    """A stand-in analysis for a chunk whose analysis sandbox failed but which has validated issues."""
    return ChunkAnalysis(
        goal="(analysis unavailable for this chunk)",
        chunk_meta=ChunkMeta(chunk_id=chunk.chunk_id, files_in_this_chunk=[f.filename for f in chunk.files]),
    )


def _render_review_body(report: ValidationMarkdownReport) -> str:
    """Render the top-level review body with the PR overview and all chunk summaries."""
    lines = [
        "# ReviewHog Report",
        "",
    ]

    for chunk_report in report.chunks:
        chunk = chunk_report.chunk
        analysis = chunk_report.chunk_analysis
        issue_count = sum(1 for vi in chunk_report.validated_issues if vi.issue.priority in _PUBLISHED_PRIORITIES)

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
