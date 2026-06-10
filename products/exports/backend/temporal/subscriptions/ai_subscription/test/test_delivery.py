import pytest
from unittest.mock import MagicMock

from products.exports.backend.temporal.subscriptions.ai_subscription.delivery import (
    SLACK_MRKDWN_SECTION_LIMIT,
    _build_ai_slack_message,
    _split_text_into_chunks,
    render_ai_email_html,
)

_PARA = "a" * (SLACK_MRKDWN_SECTION_LIMIT - 100)


class TestSplitTextIntoChunks:
    @pytest.mark.parametrize(
        "name,text,expected",
        [
            ("short_text_single_chunk", "short report", ["short report"]),
            ("empty_text_no_chunks", "", []),
            ("breaks_on_paragraph_boundary", f"{_PARA}\n\n{_PARA}", [_PARA, _PARA]),
        ],
    )
    def test_exact_chunking(self, name: str, text: str, expected: list[str]) -> None:
        assert _split_text_into_chunks(text) == expected

    @pytest.mark.parametrize("prefix", ["\n\n", "\n", "  \n\n  "])
    def test_leading_blank_lines_do_not_emit_empty_chunk(self, prefix: str) -> None:
        # regression: a body starting on a paragraph boundary used to carve off an empty first chunk
        chunks = _split_text_into_chunks(prefix + ("a" * (SLACK_MRKDWN_SECTION_LIMIT + 100)))
        assert chunks
        assert all(chunk.strip() for chunk in chunks)

    def test_no_newlines_falls_back_to_hard_cut(self) -> None:
        text = "x" * (SLACK_MRKDWN_SECTION_LIMIT * 2 + 50)
        chunks = _split_text_into_chunks(text)
        assert len(chunks) >= 3
        assert all(len(c) <= SLACK_MRKDWN_SECTION_LIMIT for c in chunks)
        assert "".join(chunks) == text


class TestRenderAIEmailHtml:
    def test_neutralizes_raw_html_but_keeps_tables(self) -> None:
        html = render_ai_email_html("## Heading\n\n<script>alert(1)</script>\n\n| a | b |\n|---|---|\n| 1 | 2 |")
        # Raw HTML in the markdown source is escaped to inert text (html=False), never a live tag.
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        # Legitimate markdown structure (headings, tables) still renders.
        assert "<table>" in html
        assert "<h2>" in html

    def test_renders_basic_markdown(self) -> None:
        html = render_ai_email_html("**bold** and *italic*")
        assert "<strong>bold</strong>" in html
        assert "<em>italic</em>" in html


class TestExternalUrlExfilGuard:
    """A prompt-injected synthesis could embed a link to attacker.example; Slack auto-unfurls
    outbound links server-side, which is an exfil channel. External URLs and markdown images
    must be stripped from delivered output regardless of how the LLM was steered."""

    def test_email_strips_external_link_href_keeps_text(self) -> None:
        html = render_ai_email_html("See [here](https://attacker.example/exfil?p=secret) for details.")
        assert "attacker.example" not in html
        assert "here" in html

    def test_email_keeps_posthog_links(self) -> None:
        html = render_ai_email_html("Open [the dashboard](https://app.posthog.com/insights/abc).")
        assert "app.posthog.com/insights/abc" in html

    @pytest.mark.parametrize(
        "raw",
        [
            "https://attacker.example\\@posthog.com/exfil",  # literal backslash authority bypass
            "https://attacker.example%5C@posthog.com/exfil",  # percent-encoded backslash
            "https://posthog.com@attacker.example/exfil",  # plain userinfo confusion
        ],
    )
    def test_email_rejects_authority_confusion_bypass(self, raw: str) -> None:
        # urlparse may read the host as posthog.com, but browsers navigate to attacker.example —
        # the allowlist must not be fooled into preserving any of these as a live link.
        html = render_ai_email_html(f"Click [here]({raw}).")
        assert "attacker.example" not in html, raw
        assert "here" in html

    def test_email_strips_markdown_images(self) -> None:
        html = render_ai_email_html("Pixel: ![tracker](https://attacker.example/track.gif)")
        assert "attacker.example" not in html
        assert "<img" not in html

    def test_slack_strips_external_link(self) -> None:
        message = _build_ai_slack_message(
            _mock_subscription(), "See [details](https://attacker.example/exfil?p=secret)"
        )
        all_text = " ".join(b["text"]["text"] for b in message.blocks if b["type"] == "section")
        assert "attacker.example" not in all_text
        assert "details" in all_text

    def test_slack_keeps_posthog_link(self) -> None:
        message = _build_ai_slack_message(
            _mock_subscription(), "Open [dashboard](https://app.posthog.com/insights/abc)"
        )
        all_text = " ".join(b["text"]["text"] for b in message.blocks if b["type"] == "section")
        assert "app.posthog.com/insights/abc" in all_text

    def test_slack_defangs_bare_external_url(self) -> None:
        # a bare (non-markdown) URL still gets linkified/unfurled by Slack — must be defanged
        message = _build_ai_slack_message(_mock_subscription(), "Visit https://attacker.example/exfil?p=secret now")
        all_text = " ".join(b["text"]["text"] for b in message.blocks if b["type"] == "section")
        assert "`https://attacker.example/exfil?p=secret`" in all_text

    def test_slack_defangs_autolink(self) -> None:
        message = _build_ai_slack_message(_mock_subscription(), "See <https://attacker.example/exfil> here")
        all_text = " ".join(b["text"]["text"] for b in message.blocks if b["type"] == "section")
        assert "`https://attacker.example/exfil`" in all_text

    def test_slack_keeps_bare_posthog_url(self) -> None:
        message = _build_ai_slack_message(_mock_subscription(), "Open https://app.posthog.com/insights/abc now")
        all_text = " ".join(b["text"]["text"] for b in message.blocks if b["type"] == "section")
        assert "https://app.posthog.com/insights/abc" in all_text
        assert "`https://app.posthog.com" not in all_text  # PostHog hosts stay live, not defanged

    def test_slack_defangs_scheme_less_www_url(self) -> None:
        # Slack also linkifies scheme-less www. URLs — those must be defanged too
        message = _build_ai_slack_message(_mock_subscription(), "Visit www.attacker.example/exfil now")
        all_text = " ".join(b["text"]["text"] for b in message.blocks if b["type"] == "section")
        assert "`www.attacker.example/exfil`" in all_text

    def test_slack_keeps_www_posthog_url(self) -> None:
        message = _build_ai_slack_message(_mock_subscription(), "Docs at www.posthog.com/docs here")
        all_text = " ".join(b["text"]["text"] for b in message.blocks if b["type"] == "section")
        assert "www.posthog.com/docs" in all_text
        assert "`www.posthog.com" not in all_text

    def test_slack_does_not_mangle_email_addresses(self) -> None:
        message = _build_ai_slack_message(_mock_subscription(), "Reach me@www.example.com for access")
        all_text = " ".join(b["text"]["text"] for b in message.blocks if b["type"] == "section")
        assert "me@www.example.com" in all_text
        assert "`www.example.com" not in all_text

    def test_slack_defangs_parenthetical_external_url(self) -> None:
        # a URL inside plain parentheses is preceded by `(` but is not a markdown link — still defang it
        message = _build_ai_slack_message(_mock_subscription(), "Revenue event (https://attacker.example/track) spiked")
        all_text = " ".join(b["text"]["text"] for b in message.blocks if b["type"] == "section")
        assert "`https://attacker.example/track`" in all_text

    def test_slack_defangs_uppercase_scheme_autolink(self) -> None:
        # URL schemes are case-insensitive — an uppercase scheme must not slip past the matcher
        message = _build_ai_slack_message(_mock_subscription(), "See <HTTPS://attacker.example/exfil> now")
        all_text = " ".join(b["text"]["text"] for b in message.blocks if b["type"] == "section")
        assert "`HTTPS://attacker.example/exfil`" in all_text

    def test_email_defangs_uppercase_autolink(self) -> None:
        html = render_ai_email_html("See <HTTPS://attacker.example/exfil> now")
        assert "href=" not in html.lower()  # never a live link, regardless of scheme case
        assert "<code>" in html
        assert "attacker.example" in html

    def test_email_defangs_bare_external_url(self) -> None:
        html = render_ai_email_html("Visit https://attacker.example/exfil now")
        assert 'href="https://attacker.example' not in html  # never a live link
        assert "<code>" in html  # rendered as inert code, still visible
        assert "attacker.example" in html

    def test_disables_slack_unfurl(self) -> None:
        # belt-and-suspenders to the content stripping: Slack must not auto-fetch any link in the report
        message = _build_ai_slack_message(_mock_subscription(), "A short report.")
        assert message.unfurl is False


def _mock_subscription() -> MagicMock:
    sub = MagicMock()
    sub.target_value = "C123|#general"
    sub.title = "Weekly report"
    sub.url = "https://app.posthog.com/project/1/subscriptions/2"
    sub.team_id = 1
    sub.id = 2
    return sub


class TestBuildAISlackMessage:
    def test_single_section_report_has_no_thread_messages(self) -> None:
        message = _build_ai_slack_message(_mock_subscription(), "A short report.")
        assert message.channel == "C123"
        assert message.thread_messages == []
        section_texts = [b["text"]["text"] for b in message.blocks if b["type"] == "section"]
        assert all(text.strip() for text in section_texts), "no empty section text allowed"

    def test_long_report_overflows_into_thread(self) -> None:
        long_markdown = ("para\n\n" * 1).join("x" * (SLACK_MRKDWN_SECTION_LIMIT - 50) for _ in range(3))
        message = _build_ai_slack_message(_mock_subscription(), long_markdown)
        assert len(message.thread_messages) >= 1
        for thread_msg in message.thread_messages:
            for block in thread_msg["blocks"]:
                assert block["text"]["text"].strip(), "thread section text must be non-empty"
