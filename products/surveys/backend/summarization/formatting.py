"""Formatting utilities for survey summaries."""

from .llm.schema import SurveySummaryResponse

FREQUENCY_INDICATORS = {
    "common": "🔥",
    "moderate": "📊",
    "rare": "💡",
}


def format_as_markdown(summary: SurveySummaryResponse) -> str:
    """Convert structured summary to markdown format for display."""
    lines = [summary.overview, ""]

    if summary.themes:
        lines.append("**Key Themes:**")
        for theme in summary.themes:
            indicator = FREQUENCY_INDICATORS.get(theme.frequency, "•")
            lines.append(f"- {indicator} **{theme.theme}**: {theme.description}")
        lines.append("")

    if summary.key_insight:
        lines.append(f"**💡 Key Insight:** {summary.key_insight}")

    return "\n".join(lines)
