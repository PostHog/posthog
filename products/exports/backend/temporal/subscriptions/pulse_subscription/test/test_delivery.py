from products.exports.backend.temporal.subscriptions.pulse_subscription.delivery import (
    pulse_page_url,
    render_brief_markdown,
)
from products.pulse.backend.models import ProductBrief


class TestRenderBriefMarkdown:
    def test_renders_titles_bodies_and_citation_links(self) -> None:
        brief = ProductBrief(
            team_id=42,
            sections=[
                {
                    "kind": "movement",
                    "title": "What happened",
                    "markdown": "Signup conversion dropped 12%.",
                    "citations": ["insight:abc123", "flag:7"],
                    "confidence": 0.9,
                },
                {
                    "kind": "opportunity",
                    "title": "What to build next",
                    "markdown": "Fix mobile Safari.",
                    "citations": [],
                },
            ],
        )

        markdown = render_brief_markdown(brief)
        url = pulse_page_url(42)

        assert "## What happened" in markdown
        assert "Signup conversion dropped 12%." in markdown
        assert f"[insight:abc123]({url})" in markdown
        assert f"[flag:7]({url})" in markdown
        assert "## What to build next" in markdown
        assert f"[View this brief in PostHog Pulse]({url})" in markdown

    def test_skips_malformed_sections_without_crashing(self) -> None:
        brief = ProductBrief(
            team_id=42,
            sections=["not-a-dict", {"citations": [None, 3]}, {"title": "", "markdown": ""}],
        )

        markdown = render_brief_markdown(brief)

        # Only the footer link survives; malformed entries neither crash nor emit content.
        assert markdown == f"[View this brief in PostHog Pulse]({pulse_page_url(42)})"
