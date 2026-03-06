import logging
from pathlib import Path
from typing import Any

from products.review_hog.backend.reviewer.models.chunk_analysis import ChunkAnalysis
from products.review_hog.backend.reviewer.models.issue_combination import IssueCombination
from products.review_hog.backend.reviewer.models.issue_validation import IssueValidation
from products.review_hog.backend.reviewer.models.issues_review import Issue
from products.review_hog.backend.reviewer.models.prepare_validation_markdown import (
    ValidationMarkdownReport,
    ValidationMarkdownReportChunk,
    ValidationMarkdownReportIssue,
)
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import ChunksList

logger = logging.getLogger(__name__)


async def prepare_validation_markdown(
    chunks_data: ChunksList,
    review_dir: Path,
    pr_metadata: dict,
) -> None:
    """
    Generate a markdown report combining chunk analyses, issues, and validation results.

    Args:
        chunks_data: Data about all chunks
        review_dir: Directory containing review files
        pr_metadata: PR metadata
    """
    logger.info("Starting validation markdown preparation")

    # Load chunk analyses
    chunk_analyses = {}
    for chunk in chunks_data.chunks:
        analysis_path = review_dir / f"chunk-{chunk.chunk_id}-analysis.json"
        if analysis_path.exists():
            with analysis_path.open() as f:
                chunk_analyses[chunk.chunk_id] = ChunkAnalysis.model_validate_json(f.read())
        else:
            logger.warning(f"Missing chunk analysis for chunk {chunk.chunk_id}")

    # Load issues
    issues_path = review_dir / "issues_found.json"
    if not issues_path.exists():
        raise FileNotFoundError(f"Issues file not found: {issues_path}")

    with issues_path.open() as f:
        issues_data = IssueCombination.model_validate_json(f.read())

    # Group issues by chunk
    issues_by_chunk: dict[int, list[tuple[Issue, int, int]]] = {}
    for issue in issues_data.issues:
        # Parse issue ID: "{pass-id}-{chunk-id}-{issue-number}"
        parts = issue.id.split("-")
        if len(parts) != 3:
            logger.warning(f"Invalid issue ID format: {issue.id}")
            continue

        try:
            pass_id, chunk_id, issue_number = (
                int(parts[0]),
                int(parts[1]),
                int(parts[2]),
            )
        except ValueError:
            logger.warning(f"Invalid issue ID format: {issue.id}")
            continue

        if chunk_id not in issues_by_chunk:
            issues_by_chunk[chunk_id] = []
        issues_by_chunk[chunk_id].append((issue, pass_id, issue_number))

    # Build report structure
    report_chunks = []
    for chunk in chunks_data.chunks:
        chunk_id = chunk.chunk_id

        # Get chunk analysis
        chunk_analysis = chunk_analyses.get(chunk_id)
        if not chunk_analysis:
            logger.warning(f"Skipping chunk {chunk_id} - no analysis found")
            continue

        # Get validated issues for this chunk
        validated_issues = []
        if chunk_id in issues_by_chunk:
            for issue, pass_id, issue_number in issues_by_chunk[chunk_id]:
                # # TODO: Remove after the fix
                # # Find position of the issue in the issues list
                # for iw, wakawaka in enumerate(issues_data.issues):
                #     if wakawaka.id == issue.id:
                #         issue_number = iw + 1

                # Load validation result
                # Issue number is 1-based in ID but 0-based in filename
                validation_filename = f"chunk-{chunk_id}-issue-{issue_number}-validation-summary.json"
                validation_path = (
                    review_dir / f"pass{pass_id}_results" / "validation" / "summaries" / validation_filename
                )

                if not validation_path.exists():
                    raise FileNotFoundError(f"Validation file not found: {validation_path}")

                with validation_path.open() as f:
                    issue_raw = f.read()
                    try:
                        validation = IssueValidation.model_validate_json(issue_raw)
                    except Exception as e:
                        logger.error(f"Error validating issue {issue.id} ({e}) ({validation_path}): {issue_raw}")
                        raise

                # Only include issues where validation is_valid is true
                if validation.is_valid:
                    validated_issues.append(ValidationMarkdownReportIssue(issue=issue, validation=validation))

        report_chunks.append(
            ValidationMarkdownReportChunk(
                chunk=chunk,
                chunk_analysis=chunk_analysis,
                validated_issues=validated_issues,
            )
        )

    # Create final report
    report = ValidationMarkdownReport(chunks=report_chunks)

    # Generate markdown
    markdown_content = _generate_markdown_report(report, pr_metadata)

    # Save report
    output_path = review_dir / "review_report.md"
    with output_path.open("w") as f:
        f.write(markdown_content)

    logger.info(f"Validation markdown report generated: {output_path}")


def _generate_header_section(pr_metadata: dict[str, Any], num_chunks: int) -> list[str]:
    """Generate the header section of the markdown report."""
    return [
        "# PR Review Report",
        "",
        f"**PR:** #{pr_metadata['number']} - {pr_metadata['title']}",
        f"**Author:** {pr_metadata['author']}",
        f"**State:** {pr_metadata['state']}",
        f"**Base Branch:** {pr_metadata['base_branch']}",
        f"**Head Branch:** {pr_metadata['head_branch']}",
        "",
        "## Summary",
        "",
        f"This report contains detailed analysis of {num_chunks} chunks with their associated issues and validation results.",
        "",
    ]


def _generate_toc_section(report: ValidationMarkdownReport) -> list[str]:
    """Generate the table of contents section."""
    lines = [
        "## Table of Contents",
        "",
    ]

    for chunk_report in report.chunks:
        chunk_id = chunk_report.chunk.chunk_id
        lines.append(f"- [Chunk {chunk_id}](#chunk-{chunk_id})")

    lines.append("")
    return lines


def _generate_issues_section(
    validated_issues: list[ValidationMarkdownReportIssue],
) -> list[str]:
    """Generate the issues and validations section."""
    lines = []

    if validated_issues:
        lines.extend(
            [
                "### Issues and Validations",
                "",
            ]
        )

        for validated_issue in validated_issues:
            issue = validated_issue.issue
            validation = validated_issue.validation

            # Issue header
            status_emoji = "✅" if validation.is_valid else "❌"
            lines.extend(
                [
                    f"#### {status_emoji} Issue {issue.id}: {issue.title}",
                    "",
                    f"**Priority:** {issue.priority.value}",
                    "",
                    f"**File:** `{issue.file}` (lines {issue.lines})",
                    "",
                    f"**Issue:** {issue.issue}",
                    "",
                    f"**Suggestion:** {issue.suggestion}",
                    "",
                ]
            )

            # Validation results
            lines.extend(
                [
                    f"**Validation Result:** {'Valid' if validation.is_valid else 'Invalid'}",
                    "",
                    f"**Argumentation:** {validation.argumentation}",
                    "",
                ]
            )

            if validation.category:
                lines.extend(
                    [
                        f"**Category:** {validation.category}",
                        "",
                    ]
                )

            lines.append("---")
            lines.append("")
    else:
        lines.extend(
            [
                "### Issues and Validations",
                "",
                "No issues found for this chunk.",
                "",
            ]
        )

    return lines


def _generate_markdown_report(report: ValidationMarkdownReport, pr_metadata: dict[str, Any]) -> str:
    """Generate markdown content from the validation report."""
    lines = []

    # Header
    lines.extend(_generate_header_section(pr_metadata, len(report.chunks)))

    # Table of contents
    lines.extend(_generate_toc_section(report))

    # Chunk details
    for chunk_report in report.chunks:
        chunk = chunk_report.chunk
        analysis = chunk_report.chunk_analysis

        lines.extend(
            [
                f"## Chunk {chunk.chunk_id}",
                "",
                "### Overview",
                "",
                f"**Type:** {chunk.chunk_type or 'N/A'}",
                "",
            ]
        )

        # Files
        if chunk.files:
            lines.extend(
                [
                    "**Files:**",
                    "",
                ]
            )
            for file_info in chunk.files:
                lines.append(f"- `{file_info.filename}`")
            lines.append("")

        # Key changes
        if chunk.key_changes:
            lines.extend(
                [
                    "**Key Changes:**",
                    "",
                ]
            )
            for change in chunk.key_changes:
                lines.append(f"- {change}")
            lines.append("")

        # Analysis
        lines.extend(
            [
                "### Analysis",
                "",
                f"**Goal:** {analysis.goal}",
                "",
            ]
        )

        # Issues and validations
        lines.extend(_generate_issues_section(chunk_report.validated_issues))

    return "\n".join(lines)
