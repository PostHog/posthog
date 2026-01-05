"""Formatting utilities for survey summaries."""

from .llm.schema import SurveySummaryResponse


def format_as_markdown(summary: SurveySummaryResponse) -> str:
    """Convert structured summary to markdown format for display."""
    lines = [summary.overview, ""]

    if summary.themes:
        lines.append("**Key Themes:**")
        for theme in summary.themes:
            # frequency is already a percentage string like ">50%", "25-50%", etc.
            lines.append(f"- **{theme.theme}** ({theme.frequency}): {theme.description}")
        lines.append("")

    if summary.key_insight:
        lines.append(f"**Key Insight:** {summary.key_insight}")

    return "\n".join(lines)
