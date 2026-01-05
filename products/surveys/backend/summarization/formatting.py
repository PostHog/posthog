"""Formatting utilities for survey summaries."""

from .llm.schema import SurveySummaryResponse

FREQUENCY_LABELS = {
    "common": "Common",
    "moderate": "Moderate",
    "rare": "Rare",
}


def format_as_markdown(summary: SurveySummaryResponse) -> str:
    """Convert structured summary to markdown format for display."""
    lines = [summary.overview, ""]

    if summary.themes:
        lines.append("**Key Themes:**")
        for theme in summary.themes:
            frequency_label = FREQUENCY_LABELS.get(theme.frequency, "")
            frequency_suffix = f" ({frequency_label})" if frequency_label else ""
            lines.append(f"- **{theme.theme}**{frequency_suffix}: {theme.description}")
        lines.append("")

    if summary.key_insight:
        lines.append(f"**Key Insight:** {summary.key_insight}")

    return "\n".join(lines)
