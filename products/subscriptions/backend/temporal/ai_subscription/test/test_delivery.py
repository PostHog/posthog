import uuid
from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.template.loader import render_to_string

from markdown_it import MarkdownIt
from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from products.slack_app.backend.facade.testing import REQUIRED_SLACK_SCOPES
from products.subscriptions.backend.facade.contracts import SubscriptionTriggerType
from products.subscriptions.backend.logic.slack_subscriptions import SlackMessage
from products.subscriptions.backend.logic.teams_subscriptions import TEAMS_CARD_TEXT_BUDGET
from products.subscriptions.backend.models.subscription import AIQueryPlanStatus, Subscription, SubscriptionDelivery
from products.subscriptions.backend.temporal.ai_subscription.activities import _deliver_ai_subscription
from products.subscriptions.backend.temporal.ai_subscription.delivery import (
    CHART_IMAGE_URL_TTL,
    SLACK_MARKDOWN_MESSAGE_LIMIT,
    SLACK_MRKDWN_SECTION_LIMIT,
    SLACK_TABLE_CHARACTER_LIMIT,
    TEAMS_REPORT_BLOCK_COUNT,
    TEAMS_TEXT_BLOCK_LIMIT,
    _build_ai_slack_message,
    _last_scheduled_report_cutoff,
    _persist_ai_query_plan,
    _split_text_into_chunks,
    build_ai_subscription_report,
    build_ai_teams_card,
    build_chart_image_urls,
    render_ai_email_html,
    send_email_ai_subscription_report,
    send_slack_ai_subscription_report,
)
from products.subscriptions.backend.temporal.ai_subscription.report_pipeline import AiReportResult
from products.subscriptions.backend.temporal.ai_subscription.spec_generator import ReportWindow
from products.subscriptions.backend.temporal.types import (
    AI_REPORT_CHARTS_KEY,
    AI_REPORT_SNAPSHOT_KEY,
    AI_REPORT_WINDOW_END_KEY,
    DeliverSubscriptionInputs,
    DeliverSubscriptionResult,
)

_DELIVERY = "products.subscriptions.backend.temporal.ai_subscription.delivery"
_ACTIVITIES = "products.subscriptions.backend.temporal.ai_subscription.activities"

_PARA = "a" * (SLACK_MRKDWN_SECTION_LIMIT - 100)
_DELIVERY_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
_SUBSCRIPTION_URL = "https://app.posthog.com/project/1/subscriptions/2"


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
        html = render_ai_email_html("- **bold** and *italic*")
        assert "<ul>" in html
        assert "<li>" in html
        assert "<strong>bold</strong>" in html
        assert "<em>italic</em>" in html

    def test_chart_title_only_appears_in_the_image_alt_text(self) -> None:
        html = render_to_string(
            "email/ai_subscription_report.html",
            {"title": "Report", "rendered_html": "", "charts": [_CHART]},
        )

        assert html.count(_CHART["title"]) == 1


class TestExternalUrlExfilGuard:
    """A prompt-injected synthesis could embed a link to attacker.example; Slack auto-unfurls
    outbound links server-side, which is an exfil channel. External URLs and markdown images
    must be stripped from delivered output regardless of how the LLM was steered."""

    @pytest.mark.parametrize(
        "definitions,expected",
        [
            ("[source]: h&#116;tps://example.com/report", set()),
            ("[source]: h&#116;tps://example.com/one\n  [source]: h&#116;tps://example.com/two", set()),
            (
                "[source]: https://posthog.com/docs?section=reports#slack",
                {"https://posthog.com/docs?section=reports#slack"},
            ),
            (
                "[source]: https://reports.example.com/report?view=weekly#traffic",
                {"https://reports.example.com/report?view=weekly#traffic"},
            ),
        ],
    )
    @pytest.mark.parametrize("padding", ["", "\n\n" + "Supporting detail. " * 800 + "\n\n"])
    async def test_slack_reference_destinations_follow_url_policy(
        self, definitions: str, expected: set[str], padding: str
    ) -> None:
        markdown = f"## Highlights\n\n- [Open report][source]\n\n{padding}{definitions}\n"
        with (
            patch(f"{_DELIVERY}.absolute_uri", return_value="https://reports.example.com/"),
            patch(f"{_DELIVERY}.deliver_slack_message_data", new_callable=AsyncMock) as send,
        ):
            await send_slack_ai_subscription_report(
                subscription=_mock_subscription(), markdown=markdown, integration=MagicMock(), delivery_id=_DELIVERY_ID
            )
        message = send.call_args.args[2]
        links = {
            item["url"]
            for block in message.blocks
            if block["type"] == "container"
            for child in block["child_blocks"]
            for section in child["elements"]
            for bullet in section.get("elements", [])
            for item in bullet.get("elements", [])
            if item["type"] == "link" and item["text"] == "Open report"
        }
        assert links == expected

    @pytest.mark.parametrize("kind", ["inline", "list_fence", "limit"])
    def test_slack_split_sections_keep_external_links_inert(self, kind: str) -> None:
        link = "[Report](h&#116;tps://example.com/report)"
        padding = "x" * SLACK_MARKDOWN_MESSAGE_LIMIT
        markdown = f"`{padding} {link}`"
        if kind == "list_fence":
            markdown = f"- Item\n\n  ```\n  {padding}\n  {link}\n  ```"
        elif kind == "limit":
            markdown = "`" + padding + " " + link + "y" * (SLACK_MARKDOWN_MESSAGE_LIMIT - len(link) - 1) + "`"
        message = _build_message(markdown)
        messages = [message.blocks, *(reply["blocks"] for reply in message.thread_messages)]
        assert message.thread_messages
        for blocks in messages:
            for block in blocks:
                if block["type"] != "markdown":
                    continue
                assert len(block["text"]) <= SLACK_MARKDOWN_MESSAGE_LIMIT
                tokens = MarkdownIt("commonmark").parse(block["text"])
                assert not any(child.type == "link_open" for token in tokens for child in token.children or [])
        assert "Report" in str(messages)

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
        message = _build_message("See [details](https://attacker.example/exfil?p=secret)")
        all_text = " ".join(b["text"] for b in message.blocks if b["type"] == "markdown")
        assert "attacker.example" not in all_text
        assert "details" in all_text

    def test_slack_keeps_posthog_link(self) -> None:
        message = _build_message("Open [dashboard](https://app.posthog.com/insights/abc)")
        all_text = " ".join(b["text"] for b in message.blocks if b["type"] == "markdown")
        assert "app.posthog.com/insights/abc" in all_text

    def test_slack_defangs_bare_external_url(self) -> None:
        # a bare (non-markdown) URL still gets linkified/unfurled by Slack — must be defanged
        message = _build_message("Visit https://attacker.example/exfil?p=secret now")
        all_text = " ".join(b["text"] for b in message.blocks if b["type"] == "markdown")
        assert "`https://attacker.example/exfil?p=secret`" in all_text

    def test_slack_defangs_autolink(self) -> None:
        message = _build_message("See <https://attacker.example/exfil> here")
        all_text = " ".join(b["text"] for b in message.blocks if b["type"] == "markdown")
        assert "`https://attacker.example/exfil`" in all_text

    def test_slack_keeps_bare_posthog_url(self) -> None:
        message = _build_message("Open https://app.posthog.com/insights/abc now")
        all_text = " ".join(b["text"] for b in message.blocks if b["type"] == "markdown")
        assert "https://app.posthog.com/insights/abc" in all_text
        assert "`https://app.posthog.com" not in all_text  # PostHog hosts stay live, not defanged

    def test_slack_defangs_scheme_less_www_url(self) -> None:
        # Slack also linkifies scheme-less www. URLs — those must be defanged too
        message = _build_message("Visit www.attacker.example/exfil now")
        all_text = " ".join(b["text"] for b in message.blocks if b["type"] == "markdown")
        assert "`www.attacker.example/exfil`" in all_text

    def test_slack_keeps_www_posthog_url(self) -> None:
        message = _build_message("Docs at www.posthog.com/docs here")
        all_text = " ".join(b["text"] for b in message.blocks if b["type"] == "markdown")
        assert "www.posthog.com/docs" in all_text
        assert "`www.posthog.com" not in all_text

    def test_slack_does_not_mangle_email_addresses(self) -> None:
        message = _build_message("Reach me@www.example.com for access")
        all_text = " ".join(b["text"] for b in message.blocks if b["type"] == "markdown")
        assert "me@www.example.com" in all_text
        assert "`www.example.com" not in all_text

    def test_slack_defangs_parenthetical_external_url(self) -> None:
        # a URL inside plain parentheses is preceded by `(` but is not a markdown link — still defang it
        message = _build_message("Revenue event (https://attacker.example/track) spiked")
        all_text = " ".join(b["text"] for b in message.blocks if b["type"] == "markdown")
        assert "`https://attacker.example/track`" in all_text

    def test_slack_defangs_uppercase_scheme_autolink(self) -> None:
        # URL schemes are case-insensitive — an uppercase scheme must not slip past the matcher
        message = _build_message("See <HTTPS://attacker.example/exfil> now")
        all_text = " ".join(b["text"] for b in message.blocks if b["type"] == "markdown")
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
        message = _build_message("A short report.")
        assert message.unfurl is False


def _mock_subscription() -> MagicMock:
    sub = MagicMock()
    sub.target_value = "C123|#general"
    sub.title = "Weekly report"
    sub.summary = "sent every week on Monday"
    sub.url = _SUBSCRIPTION_URL
    sub.team_id = 1
    sub.id = 2
    sub.delivery_config = {}
    sub.includes_delivery_part.side_effect = lambda option: Subscription._delivery_config_includes(
        sub.delivery_config, option
    )
    return sub


def _build_message(markdown: str) -> SlackMessage:
    return _build_ai_slack_message(_mock_subscription(), markdown, delivery_id=_DELIVERY_ID)


_CHART = {"title": "signups by day", "image_url": "https://ph.test/img.png"}


class TestSlackMarkdownContinuation:
    @pytest.mark.parametrize("row_count,cell_size,columns", [(110, 1, 2), (80, 140, 2), (1, 10010, 2), (1, 1, 21)])
    def test_tables_respect_row_and_character_limits(self, row_count: int, cell_size: int, columns: int) -> None:
        header = "| " + " | ".join(["Metric", *(["Value"] * (columns - 1))]) + " |\n" + "|---" * columns + "|\n"
        markdown = header + "".join(
            "| " + " | ".join([f"Row {index}", *(["x" * cell_size] * (columns - 1))]) + " |\n"
            for index in range(row_count)
        )
        message = _build_message(markdown)
        messages = [message.blocks, *(reply["blocks"] for reply in message.thread_messages)]
        parser = MarkdownIt("commonmark").enable("table")
        for blocks in messages:
            characters = 0
            for block in blocks:
                if block["type"] != "markdown":
                    continue
                tokens = parser.parse(block["text"])
                assert sum(token.type == "th_open" for token in tokens) <= 20
                rows = 0
                for token in tokens:
                    if token.type == "table_open":
                        rows = 0
                    elif token.type == "tr_open":
                        rows += 1
                        assert rows <= 100
                    elif token.type == "inline":
                        characters += len(token.content)
                assert characters <= 10000
        rendered = str(messages)
        assert all(f"Row {index}" in rendered for index in range(row_count))

    @pytest.mark.parametrize("underline_every_paragraph", [False, True])
    def test_formatted_report_respects_message_block_limit(self, underline_every_paragraph: bool) -> None:
        paragraphs = [f"## Topic {index}\n\nFinding {index}." for index in range(80)]
        if underline_every_paragraph:
            paragraphs = [paragraph + " <u>Important</u>" for paragraph in paragraphs]
        message = _build_message("<u>Overview</u>\n\n" + "\n\n".join(paragraphs))
        messages = [message.blocks, *(reply["blocks"] for reply in message.thread_messages)]
        assert all(len(blocks) <= 50 for blocks in messages)
        rendered = str(messages)
        assert all(f"Finding {index}." in rendered for index in range(80))
        if underline_every_paragraph:
            assert message.thread_messages
        else:
            assert not message.thread_messages

    @pytest.mark.parametrize("kind", ["table", "wide_row", "backticks", "tildes"])
    @pytest.mark.parametrize("overflow", [0, 1])
    def test_markdown_keeps_its_structure_at_the_message_limit(self, kind: str, overflow: int) -> None:
        limit = SLACK_MARKDOWN_MESSAGE_LIMIT
        if kind in {"table", "wide_row"}:
            limit = min(limit, SLACK_TABLE_CHARACTER_LIMIT)
            header = "| Metric | Value |\n|---|---|\n"
            first_row = "| First | " + "a" * (limit - len(header) - len("| First |  |\n")) + " |\n"
            report = header + first_row
            if overflow:
                if kind == "wide_row":
                    report = header + first_row.replace("First", "Firstx")
                else:
                    report += "| Second | 2 |\n"
        else:
            fence = "```"
            if kind == "tildes":
                fence = "~~~"
            opening = fence + "sql\n"
            closing = "\n" + fence
            content = "    SELECT " + "a" * (limit - len(opening) - len(closing) - len("    SELECT "))
            report = opening + content + closing
            if overflow:
                report = opening + content + "\n    SELECT 2;" + closing

        message = _build_message(report)
        blocks = [*message.blocks, *(block for reply in message.thread_messages for block in reply["blocks"])]
        chunks = [block["text"] for block in blocks if block["type"] == "markdown"]
        assert all(len(chunk) <= SLACK_MARKDOWN_MESSAGE_LIMIT for chunk in chunks)
        if not overflow:
            assert chunks == [report]
            return

        if kind != "wide_row":
            assert len(chunks) > 1
        parser = MarkdownIt("commonmark").enable("table")
        tokens = [parser.parse(chunk) for chunk in chunks]
        if kind == "table":
            assert all(chunk.startswith(header) for chunk in chunks)
            assert all(any(token.type == "table_open" for token in parsed) for parsed in tokens)
            assert sum(chunk.count("| First |") for chunk in chunks) == 1
            assert sum(chunk.count("| Second |") for chunk in chunks) == 1
        elif kind == "wide_row":
            assert all(parsed[0].type == "fence" for parsed in tokens)
            assert sum(chunk.count("| Firstx |") for chunk in chunks) == 1
        else:
            assert all(chunk.startswith(opening) and chunk.rstrip().endswith(fence) for chunk in chunks)
            assert all(parsed[0].type == "fence" for parsed in tokens)
            assert "    SELECT 2;" in chunks[-1]


class TestBuildChartImageUrls:
    def test_a_chart_gets_a_url_minted_at_the_asset_ttl(self) -> None:
        with patch(f"{_DELIVERY}.get_delivery_image_url", return_value="https://ph.test/img.png") as mint:
            urls = build_chart_image_urls([{"export_asset_id": 7, "title": "signups by day"}], team_id=1)

        assert urls == [_CHART]
        assert mint.call_args.kwargs["expiry_delta"] == CHART_IMAGE_URL_TTL

    @parameterized.expand(
        [
            ("expired_asset", [{"export_asset_id": 7, "title": "t"}], None),
            ("missing_id", [{"title": "no id"}], "https://ph.test/img.png"),
            ("not_a_dict", ["junk"], "https://ph.test/img.png"),
            ("not_a_list", "nonsense", "https://ph.test/img.png"),
            ("none", None, "https://ph.test/img.png"),
        ]
    )
    def test_unusable_entries_yield_nothing(self, _name, charts, minted) -> None:
        with patch(f"{_DELIVERY}.get_delivery_image_url", return_value=minted):
            assert build_chart_image_urls(charts, team_id=1) == []


class TestChartsOnSlackMessages:
    def test_charts_follow_the_report_text(self) -> None:
        message = _build_ai_slack_message(
            _mock_subscription(), "A short report.", delivery_id=_DELIVERY_ID, charts=[_CHART]
        )

        assert [block["type"] for block in message.blocks[:5]] == [
            "divider",
            "header",
            "context",
            "markdown",
            "image",
        ]
        assert message.blocks[3]["text"] == "A short report."
        assert message.blocks[1]["text"]["text"] == "Your subscription to Weekly report is ready! 🎉"
        assert message.blocks[2]["elements"][0]["text"] == "🤖 AI prompt: Weekly report"
        assert message.blocks[4]["image_url"] == _CHART["image_url"]
        assert message.blocks[4]["alt_text"] == "signups by day"
        assert message.blocks[4]["title"] == {"type": "plain_text", "text": "signups by day"}

    def test_an_untitled_chart_posts_no_title_block(self) -> None:
        message = _build_ai_slack_message(
            _mock_subscription(),
            "A short report.",
            delivery_id=_DELIVERY_ID,
            charts=[{"title": "", "image_url": "https://ph.test/img.png"}],
        )

        assert "title" not in message.blocks[4]
        assert message.blocks[4]["alt_text"] == "Chart"

    def test_a_chartless_report_posts_no_image_blocks(self) -> None:
        message = _build_message("A short report.")

        assert all(block["type"] != "image" for block in message.blocks)

    async def test_a_chart_slack_rejects_costs_the_chart_not_the_report(self) -> None:
        sent: list[list[dict]] = []

        async def _deliver(_integration, _subscription, message_data):
            sent.append(message_data.blocks)
            if any(block["type"] == "image" for block in message_data.blocks):
                raise SlackApiError("bad blocks", response={"error": "invalid_blocks"})
            return MagicMock()

        with patch(f"{_DELIVERY}.deliver_slack_message_data", side_effect=_deliver):
            await send_slack_ai_subscription_report(
                subscription=_mock_subscription(),
                markdown="A short report.",
                integration=MagicMock(),
                delivery_id=_DELIVERY_ID,
                charts=[_CHART],
            )

        assert len(sent) == 2
        assert any(block["type"] == "image" for block in sent[0])
        assert all(block["type"] != "image" for block in sent[1])
        assert {"type": "markdown", "text": "A short report."} in sent[1]

    async def test_a_hidden_chart_does_not_trigger_the_resend(self) -> None:
        # A report that hides its charts already sends a payload with no image block, so the
        # retry would repeat an identical message and double the posts Slack rate-limits.
        subscription = _mock_subscription()
        subscription.delivery_config = {"include_images": False}
        sent: list[list[dict]] = []

        async def _deliver(_integration, _subscription, message_data):
            sent.append(message_data.blocks)
            raise SlackApiError("bad blocks", response={"error": "invalid_blocks"})

        with patch(f"{_DELIVERY}.deliver_slack_message_data", side_effect=_deliver):
            with pytest.raises(SlackApiError):
                await send_slack_ai_subscription_report(
                    subscription=subscription,
                    markdown="A short report.",
                    integration=MagicMock(),
                    delivery_id=_DELIVERY_ID,
                    charts=[_CHART],
                )

        assert len(sent) == 1
        assert all(block["type"] != "image" for block in sent[0])

    async def test_a_slack_error_that_is_not_about_blocks_still_raises(self) -> None:
        with patch(
            f"{_DELIVERY}.deliver_slack_message_data",
            side_effect=SlackApiError("nope", response={"error": "channel_not_found"}),
        ):
            with pytest.raises(SlackApiError):
                await send_slack_ai_subscription_report(
                    subscription=_mock_subscription(),
                    markdown="A short report.",
                    integration=MagicMock(),
                    delivery_id=_DELIVERY_ID,
                    charts=[_CHART],
                )

    async def test_the_slack_sender_never_touches_the_orm(self) -> None:
        with (
            patch(f"{_DELIVERY}.get_delivery_image_url") as mint,
            patch(f"{_DELIVERY}.deliver_slack_message_data", new_callable=AsyncMock),
        ):
            await send_slack_ai_subscription_report(
                subscription=_mock_subscription(),
                markdown="A short report.",
                integration=MagicMock(),
                delivery_id=_DELIVERY_ID,
                charts=[_CHART],
            )

        mint.assert_not_called()


class TestBuildAISlackMessage:
    def test_leading_callout_keeps_links_and_markdown_styles(self) -> None:
        message = _build_message(
            "## Main result\n\n- [**Check`out`**](https://us.posthog.com/project/2/dashboard/123) "
            "rose **20%** on *Monday*, replacing ~~retired~~ `legacy`."
        )
        callout = next(block for block in message.blocks if block["type"] == "container")
        elements = callout["child_blocks"][0]["elements"][0]["elements"][0]["elements"]
        assert {
            "type": "link",
            "url": "https://us.posthog.com/project/2/dashboard/123",
            "text": "Checkout",
            "style": {"bold": True},
        } in elements
        for text, style in [("20%", "bold"), ("Monday", "italic"), ("retired", "strike"), ("legacy", "code")]:
            assert {"type": "text", "text": text, "style": {style: True}} in elements

    @pytest.mark.parametrize(
        "content",
        [
            "- Parent\n  - Child",
            "- Finding\n\n  ```sql\n  SELECT 1\n  ```",
            "- <u>Parent</u>\n  - Child",
            "- <u>Finding</u>\n\n  ```sql\n  SELECT 1\n  ```",
        ],
    )
    def test_complex_findings_keep_native_markdown(self, content: str) -> None:
        markdown = f"## Main result\n\n{content}"
        message = _build_message(markdown)
        assert message.blocks[3] == {"type": "markdown", "text": markdown}

    def test_single_section_report_has_no_thread_messages(self) -> None:
        message = _build_message("A short report.")
        assert message.channel == "C123"
        assert message.thread_messages == []
        section_texts = [b["text"]["text"] for b in message.blocks if b["type"] == "section"]
        assert all(text.strip() for text in section_texts), "no empty section text allowed"

    @pytest.mark.parametrize(
        "markdown",
        [
            "## Weekly report\n\n| Day | Sessions |\n|---|---|\n| Monday | **42** |",
            "**Bold** and *italic* with [dashboard](https://app.posthog.com/insights/abc)",
            "```\n| Day | Sessions |\n| Monday | 42 |\n```",
            "x" * SLACK_MARKDOWN_MESSAGE_LIMIT,
            "",
        ],
    )
    def test_preserves_report_markdown(self, markdown: str) -> None:
        message = _build_message(markdown)
        assert message.blocks[3] == {"type": "markdown", "text": markdown or "_No report content was generated._"}
        assert message.thread_messages == []

    def test_long_report_overflows_into_thread(self) -> None:
        long_markdown = ("para\n\n" * 1).join("x" * (SLACK_MARKDOWN_MESSAGE_LIMIT - 50) for _ in range(3))
        message = _build_message(long_markdown)
        assert len(message.thread_messages) >= 1
        for thread_msg in message.thread_messages:
            for block in thread_msg["blocks"]:
                assert block["type"] == "markdown"
                assert block["text"].strip(), "thread text must be non-empty"
                assert len(block["text"]) <= SLACK_MARKDOWN_MESSAGE_LIMIT

    def test_minimal_delivery_keeps_only_the_title_and_report(self) -> None:
        subscription = _mock_subscription()
        subscription.delivery_config = {
            "include_images": False,
            "include_feedback": False,
            "include_manage_link": False,
            "include_posthog_hint": False,
        }

        message = _build_ai_slack_message(
            subscription,
            "A short report.",
            delivery_id=_DELIVERY_ID,
            integration=_mock_integration(REQUIRED_SLACK_SCOPES),
            charts=[_CHART],
        )

        assert [block["type"] for block in message.blocks] == ["divider", "header", "context", "markdown"]
        assert message.blocks[3]["text"] == "A short report."

    def test_with_images_delivery_keeps_charts_without_posthog_controls(self) -> None:
        subscription = _mock_subscription()
        subscription.delivery_config = {
            "include_images": True,
            "include_feedback": False,
            "include_manage_link": False,
            "include_posthog_hint": False,
        }

        message = _build_ai_slack_message(
            subscription,
            "A short report.",
            delivery_id=_DELIVERY_ID,
            integration=_mock_integration(REQUIRED_SLACK_SCOPES),
            charts=[_CHART],
        )

        assert [block["type"] for block in message.blocks] == [
            "divider",
            "header",
            "context",
            "markdown",
            "image",
        ]
        assert message.blocks[4]["image_url"] == _CHART["image_url"]


class TestBuildAITeamsCard:
    def _body(self, markdown: str) -> list[dict]:
        card = build_ai_teams_card(_mock_subscription(), markdown, delivery_id=_DELIVERY_ID)
        return card["attachments"][0]["content"]["body"]

    def test_charts_follow_the_report_text(self) -> None:
        card = build_ai_teams_card(_mock_subscription(), "A short report.", delivery_id=_DELIVERY_ID, charts=[_CHART])
        body = card["attachments"][0]["content"]["body"]

        image_blocks = [block for block in body if block["type"] == "Image"]
        assert image_blocks == [
            {
                "type": "Image",
                "url": _CHART["image_url"],
                "size": "Stretch",
                "altText": _CHART["title"],
            }
        ]

    def test_hidden_charts_do_not_appear(self) -> None:
        subscription = _mock_subscription()
        subscription.delivery_config = {"include_images": False}

        card = build_ai_teams_card(subscription, "A short report.", delivery_id=_DELIVERY_ID, charts=[_CHART])
        body = card["attachments"][0]["content"]["body"]

        assert all(block["type"] != "Image" for block in body)

    @pytest.mark.asyncio
    async def test_delivery_includes_generated_chart_urls(self) -> None:
        subscription = _mock_subscription()
        subscription.target_type = Subscription.SubscriptionTarget.TEAMS

        with (
            patch(
                f"{_ACTIVITIES}._load_snapshot",
                new=AsyncMock(
                    return_value={
                        AI_REPORT_SNAPSHOT_KEY: "A short report.",
                        AI_REPORT_CHARTS_KEY: [{"export_asset_id": 99, "title": "signups by day"}],
                    }
                ),
            ),
            patch(f"{_ACTIVITIES}.build_chart_image_urls", return_value=[_CHART]),
            patch(
                f"{_ACTIVITIES}.deliver_teams_webhook",
                new=AsyncMock(return_value=DeliverSubscriptionResult()),
            ) as deliver_teams,
        ):
            await _deliver_ai_subscription(
                subscription,
                DeliverSubscriptionInputs(
                    subscription_id=subscription.id,
                    exported_asset_ids=[],
                    total_insight_count=0,
                    delivery_id=_DELIVERY_ID,
                ),
                [],
            )

        assert deliver_teams.await_args is not None
        body = deliver_teams.await_args.kwargs["body"]["attachments"][0]["content"]["body"]
        assert [block for block in body if block["type"] == "Image"] == [
            {
                "type": "Image",
                "url": _CHART["image_url"],
                "size": "Stretch",
                "altText": _CHART["title"],
            }
        ]

    def test_long_report_is_split_across_text_blocks(self) -> None:
        body = self._body("\n\n".join("x" * (TEAMS_TEXT_BLOCK_LIMIT - 50) for _ in range(3)))

        report_blocks = [b for b in body if set(b["text"]) == {"x"}]
        assert len(report_blocks) == 3
        assert all(len(b["text"]) <= TEAMS_TEXT_BLOCK_LIMIT for b in report_blocks)

    @pytest.mark.parametrize(
        "filler",
        [
            "x",
            # Three bytes per character, so a report that fits by character count is far over the
            # byte count Teams measures the payload in.
            "詳",
        ],
    )
    def test_report_over_the_card_budget_is_shortened_with_a_link_out(self, filler: str) -> None:
        body = self._body("\n\n".join(filler * (TEAMS_TEXT_BLOCK_LIMIT - 50) for _ in range(20)))

        assert sum(len(b["text"].encode("utf-8")) for b in body) <= TEAMS_CARD_TEXT_BUDGET
        assert len([b for b in body if set(b["text"]) == {filler}]) <= TEAMS_REPORT_BLOCK_COUNT
        assert "This report was shortened to fit." in body[-2]["text"]

    def test_external_links_in_the_report_are_stripped(self) -> None:
        body = self._body("See [the docs](https://evil.example.com/x) for more.")

        assert "evil.example.com" not in str(body)

    def test_external_links_in_the_subscription_title_are_stripped(self) -> None:
        subscription = _mock_subscription()
        subscription.title = "[Open report](https://attacker.example/login)"

        card = build_ai_teams_card(subscription, "A short report.", delivery_id=_DELIVERY_ID)
        body = card["attachments"][0]["content"]["body"]

        assert body[0]["text"] == "**Open report**"

    def test_minimal_delivery_removes_feedback_and_manage_action(self) -> None:
        subscription = _mock_subscription()
        subscription.delivery_config = {
            "include_images": False,
            "include_feedback": False,
            "include_manage_link": False,
            "include_posthog_hint": False,
        }

        card = build_ai_teams_card(subscription, "A short report.", delivery_id=_DELIVERY_ID)
        content = card["attachments"][0]["content"]

        assert "Was this report useful?" not in str(content["body"])
        assert content["actions"] == []

    def test_minimal_delivery_shortening_notice_has_no_posthog_link(self) -> None:
        subscription = _mock_subscription()
        subscription.delivery_config = {
            "include_images": False,
            "include_feedback": False,
            "include_manage_link": False,
            "include_posthog_hint": False,
        }

        card = build_ai_teams_card(
            subscription,
            "\n\n".join("x" * (TEAMS_TEXT_BLOCK_LIMIT - 50) for _ in range(20)),
            delivery_id=_DELIVERY_ID,
        )
        content = card["attachments"][0]["content"]

        assert "This report was shortened to fit." in str(content["body"])
        assert "Read all of it in PostHog" not in str(content["body"])


def _mock_integration(scopes: frozenset[str]) -> MagicMock:
    integration = MagicMock()
    integration.kind = "slack"
    integration.id = 7
    integration.config = {"scope": ",".join(sorted(scopes))}
    integration.sensitive_config = {"access_token": "xoxb-test"}
    return integration


def _hint_texts(message: SlackMessage) -> list[str]:
    return [el["text"] for block in message.blocks if block.get("type") == "context" for el in block["elements"]]


def _ai_message(*, integration: MagicMock | None = None) -> SlackMessage:
    return _build_ai_slack_message(
        _mock_subscription(),
        "A short report.",
        delivery_id=_DELIVERY_ID,
        integration=integration,
    )


class TestAIExploreHint:
    def test_no_hint_without_integration(self) -> None:
        assert not any("@PostHog" in t for t in _hint_texts(_ai_message()))

    def test_bot_ready_hint_nudges_mention(self) -> None:
        message = _ai_message(integration=_mock_integration(REQUIRED_SLACK_SCOPES))
        assert any("@PostHog" in t and "docs/slack-app" not in t for t in _hint_texts(message))

    def test_bot_not_ready_hint_links_docs(self) -> None:
        texts = _hint_texts(_ai_message(integration=_mock_integration(frozenset({"chat:write"}))))
        assert any("docs/slack-app" in t for t in texts)
        assert not any("Reply in this thread" in t for t in texts)


def _feedback_url(feedback: str, source: str) -> str:
    return f"{_SUBSCRIPTION_URL}?feedback_delivery={_DELIVERY_ID}&feedback={feedback}&feedback_source={source}"


class TestFeedbackFooter:
    @pytest.mark.parametrize(
        "feedback,label",
        [("positive", "👍 Yes"), ("negative", "👎 No")],
    )
    def test_slack_footer_links_carry_feedback_params(self, feedback: str, label: str) -> None:
        message = _build_message("A short report.")
        context_blocks = [b for b in message.blocks if b["type"] == "context" and b["elements"][0]["type"] == "mrkdwn"]
        assert len(context_blocks) == 1
        text = context_blocks[0]["elements"][0]["text"]
        assert "Was this report useful?" in text
        assert f"<{_feedback_url(feedback, 'slack')}|{label}>" in text

    @staticmethod
    def _send_email_and_get_context() -> dict:
        with (
            patch("products.subscriptions.backend.temporal.ai_subscription.delivery.EmailMessage") as email_message,
            patch(
                "products.subscriptions.backend.temporal.ai_subscription.delivery.get_unsubscribe_token",
                return_value="tok",
            ),
            # Mocking EmailMessage means no real send + no MessagingRecord, so the
            # post-send acceptance check would hit the DB; delivery is covered separately.
            patch("products.subscriptions.backend.temporal.ai_subscription.delivery.raise_if_delivery_rejected"),
        ):
            send_email_ai_subscription_report(
                email="a@b.com",
                subscription=_mock_subscription(),
                markdown="Report body",
                delivery_run_id="run-1",
                delivery_id=_DELIVERY_ID,
            )
        return email_message.call_args.kwargs["template_context"]

    @pytest.mark.parametrize("feedback", ["positive", "negative"])
    def test_email_context_carries_feedback_urls(self, feedback: str) -> None:
        context = self._send_email_and_get_context()
        assert context[f"feedback_{feedback}_url"] == _feedback_url(feedback, "email")

    def test_email_cta_carries_delivery_id(self) -> None:
        # Dropping this param silently kills click attribution: the frontend captures
        # `ai_report_clicked` from it, the report-engagement signal.
        context = self._send_email_and_get_context()
        assert f"&delivery={_DELIVERY_ID}" in context["subscription_url"]

    def test_minimal_email_keeps_unsubscribe_without_images_or_posthog_controls(self) -> None:
        subscription = _mock_subscription()
        subscription.delivery_config = {
            "include_images": False,
            "include_feedback": False,
            "include_manage_link": False,
            "include_posthog_hint": False,
        }
        with (
            patch("products.subscriptions.backend.temporal.ai_subscription.delivery.EmailMessage") as email_message,
            patch(
                "products.subscriptions.backend.temporal.ai_subscription.delivery.get_unsubscribe_token",
                return_value="tok",
            ),
            patch("products.subscriptions.backend.temporal.ai_subscription.delivery.raise_if_delivery_rejected"),
        ):
            send_email_ai_subscription_report(
                email="a@b.com",
                subscription=subscription,
                markdown="Report body",
                delivery_run_id="run-1",
                delivery_id=_DELIVERY_ID,
                charts=[_CHART],
            )

        html = render_to_string("email/ai_subscription_report.html", email_message.call_args.kwargs["template_context"])

        assert "Report body" in html
        assert _CHART["image_url"] not in html
        assert "Manage subscription" not in html
        assert "Was this report useful?" not in html
        assert "Unsubscribe from this report" in html


class TestPersistAiQueryPlan(APIBaseTest):
    @parameterized.expand(
        [
            ("unchanged_prompt_and_images_persist", "original prompt?", {"include_images": False}, False, True),
            ("changed_prompt_noops", "edited mid-generation?", {"include_images": False}, False, False),
            ("images_enabled_mid_generation_noops", "original prompt?", {"include_images": True}, False, False),
            ("images_disabled_mid_generation_noops", "original prompt?", {"include_images": False}, True, False),
            ("explicitly_enabled_images_persist", "original prompt?", {"include_images": True}, True, True),
            ("omitted_images_default_to_enabled", "original prompt?", {}, True, True),
        ]
    )
    def test_persist_is_conditional_on_generation_inputs(
        self,
        _name: str,
        current_prompt: str,
        current_delivery_config: dict,
        expected_include_images: bool,
        written: bool,
    ) -> None:
        sub = Subscription.objects.create(
            team=self.team,
            prompt=current_prompt,
            delivery_config=current_delivery_config,
            target_type="email",
            target_value="a@posthog.com",
            frequency="weekly",
            interval=1,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        plan = {"version": 1, "plan": {}}

        persisted = _persist_ai_query_plan(
            sub.id,
            self.team.id,
            "original prompt?",
            plan,
            expected_include_images=expected_include_images,
        )

        sub.refresh_from_db()
        assert persisted is written
        assert sub.ai_query_plan == (plan if written else None)


class TestLastSuccessfulDeliveryAnchor(APIBaseTest):
    def _delivery(
        self, trigger_type: str, status: str, finished_at: datetime | None, snapshot: dict | None = None
    ) -> None:
        SubscriptionDelivery.objects.create(
            subscription=self.subscription,
            team=self.team,
            temporal_workflow_id="wf",
            idempotency_key=str(uuid.uuid4()),
            trigger_type=trigger_type,
            target_type="email",
            target_value="a@posthog.com",
            status=status,
            finished_at=finished_at,
            content_snapshot=snapshot or {},
        )

    def setUp(self) -> None:
        super().setUp()
        self.subscription = Subscription.objects.create(
            team=self.team,
            prompt="p?",
            target_type="email",
            target_value="a@posthog.com",
            frequency="weekly",
            interval=1,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def test_non_scheduled_deliveries_do_not_move_the_anchor(self) -> None:
        # Only completed SCHEDULED sends move the anchor: a manual "Test delivery" or a target-change
        # confirmation right before a run must not shrink its window to near-empty.
        scheduled_at = datetime(2026, 6, 22, 12, 0, tzinfo=UTC)
        self._delivery(SubscriptionTriggerType.SCHEDULED, SubscriptionDelivery.Status.COMPLETED, scheduled_at)
        self._delivery(
            SubscriptionTriggerType.MANUAL, SubscriptionDelivery.Status.COMPLETED, scheduled_at + timedelta(days=1)
        )
        self._delivery(
            SubscriptionTriggerType.SUBSCRIPTION_CHANGE,
            SubscriptionDelivery.Status.COMPLETED,
            scheduled_at + timedelta(days=2),
        )

        assert _last_scheduled_report_cutoff(self.subscription) == scheduled_at

    def test_anchor_prefers_the_persisted_window_end(self) -> None:
        # finished_at trails the run's window end by the generation+send time; anchoring there leaves
        # that interval uncovered. The persisted window end closes the gap exactly.
        window_end = datetime(2026, 6, 22, 12, 0, tzinfo=UTC)
        finished_at = window_end + timedelta(minutes=3)
        self._delivery(
            SubscriptionTriggerType.SCHEDULED,
            SubscriptionDelivery.Status.COMPLETED,
            finished_at,
            snapshot={AI_REPORT_WINDOW_END_KEY: window_end.isoformat()},
        )

        assert _last_scheduled_report_cutoff(self.subscription) == window_end

    def test_anchor_falls_back_to_finished_at_without_window_end(self) -> None:
        # Rows written before the key existed (or with a garbled value) anchor on finished_at as before.
        finished_at = datetime(2026, 6, 22, 12, 3, tzinfo=UTC)
        self._delivery(
            SubscriptionTriggerType.SCHEDULED,
            SubscriptionDelivery.Status.COMPLETED,
            finished_at,
            snapshot={AI_REPORT_WINDOW_END_KEY: "not-a-date"},
        )

        assert _last_scheduled_report_cutoff(self.subscription) == finished_at

    def test_no_scheduled_delivery_yields_none(self) -> None:
        self._delivery(
            SubscriptionTriggerType.MANUAL, SubscriptionDelivery.Status.COMPLETED, datetime(2026, 6, 22, tzinfo=UTC)
        )

        assert _last_scheduled_report_cutoff(self.subscription) is None


class TestFreezePlanPersistence:
    """build_ai_subscription_report freezes a freshly-generated plan and skips persistence on reuse.
    These guard the freeze contract without touching the DB — the conditional persist write itself is
    exercised by the integration/activity suites."""

    def _subscription(self, ai_query_plan: dict | None) -> Subscription:
        return Subscription(
            id=42,
            team_id=7,
            prompt="how are exports doing?",
            ai_query_plan=ai_query_plan,
            delivery_config={},
            target_type="email",
            target_value="a@posthog.com",
            frequency="weekly",
            interval=1,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def _context(self, sub: Subscription) -> tuple[MagicMock, MagicMock, ReportWindow, dict | None]:
        end = datetime(2026, 6, 29, 16, 0, tzinfo=UTC)
        window = ReportWindow(start=end - timedelta(days=1), end=end)
        return MagicMock(), MagicMock(), window, sub.ai_query_plan

    @parameterized.expand(
        [
            ("legacy_config", {}, True),
            ("images_off", {"include_images": False}, False),
        ]
    )
    async def test_first_run_persists_freshly_generated_plan(
        self, _name: str, delivery_config: dict, expected_include_images: bool
    ) -> None:
        sub = self._subscription(ai_query_plan=None)
        sub.delivery_config = delivery_config
        fresh_plan = {
            "overall_intent": "i",
            "steps": [{"description": "d", "query_type": "hogql", "hogql": "SELECT 1"}],
        }
        with (
            patch(f"{_DELIVERY}._resolve_subscription_context", return_value=self._context(sub)),
            patch(
                f"{_DELIVERY}.generate_ai_report",
                new=AsyncMock(
                    return_value=AiReportResult(
                        markdown="# R",
                        diagnostics=(),
                        window_end_utc="2026-06-29T16:00:00+00:00",
                        plan_to_persist=fresh_plan,
                        query_plan_status=AIQueryPlanStatus.FROZEN,
                    )
                ),
            ),
            patch(f"{_DELIVERY}._persist_ai_query_plan", return_value=True) as mock_persist,
        ):
            returned = await build_ai_subscription_report(sub)

        # The plan generated on the first delivery is frozen onto the (id, team_id)-scoped subscription.
        mock_persist.assert_called_once_with(
            sub.id,
            sub.team_id,
            sub.prompt,
            fresh_plan,
            expected_include_images=expected_include_images,
        )
        assert returned.query_plan_status == AIQueryPlanStatus.FROZEN

    async def test_persist_failure_does_not_abort_the_delivery(self) -> None:
        # The report is already generated when the freeze write runs; a transient DB error must not
        # fail the delivery (which would discard the report and burn a full LLM re-run on retry).
        sub = self._subscription(ai_query_plan=None)
        result = AiReportResult(
            markdown="# R",
            diagnostics=(),
            window_end_utc="2026-06-29T16:00:00+00:00",
            plan_to_persist={"version": 1, "plan": {}},
            query_plan_status=AIQueryPlanStatus.FROZEN,
        )
        with (
            patch(f"{_DELIVERY}._resolve_subscription_context", return_value=self._context(sub)),
            patch(f"{_DELIVERY}.generate_ai_report", new=AsyncMock(return_value=result)),
            patch(f"{_DELIVERY}._persist_ai_query_plan", side_effect=Exception("db blip")),
            patch(f"{_DELIVERY}.capture_exception") as mock_capture,
        ):
            returned = await build_ai_subscription_report(sub)

        assert returned is not result
        assert returned.markdown == result.markdown
        assert returned.query_plan_status == AIQueryPlanStatus.NOT_FROZEN
        mock_capture.assert_called_once()

    async def test_prompt_edit_race_records_plan_as_not_frozen(self) -> None:
        sub = self._subscription(ai_query_plan=None)
        result = AiReportResult(
            markdown="# R",
            diagnostics=(),
            window_end_utc="2026-06-29T16:00:00+00:00",
            plan_to_persist={"version": 1, "plan": {}},
            query_plan_status=AIQueryPlanStatus.FROZEN,
        )
        with (
            patch(f"{_DELIVERY}._resolve_subscription_context", return_value=self._context(sub)),
            patch(f"{_DELIVERY}.generate_ai_report", new=AsyncMock(return_value=result)),
            patch(f"{_DELIVERY}._persist_ai_query_plan", return_value=False),
        ):
            returned = await build_ai_subscription_report(sub)

        assert returned.query_plan_status == AIQueryPlanStatus.NOT_FROZEN

    async def test_reused_run_does_not_persist(self) -> None:
        frozen = {"overall_intent": "i", "steps": [{"description": "d", "query_type": "hogql", "hogql": "SELECT 1"}]}
        sub = self._subscription(ai_query_plan=frozen)
        with (
            patch(f"{_DELIVERY}._resolve_subscription_context", return_value=self._context(sub)) as mock_ctx,
            patch(
                f"{_DELIVERY}.generate_ai_report",
                new=AsyncMock(
                    return_value=AiReportResult(
                        markdown="# R",
                        diagnostics=(),
                        window_end_utc="2026-06-29T16:00:00+00:00",
                        plan_to_persist=None,
                        query_plan_status=AIQueryPlanStatus.FROZEN,
                    )
                ),
            ) as mock_gen,
            patch(f"{_DELIVERY}._persist_ai_query_plan") as mock_persist,
        ):
            returned = await build_ai_subscription_report(sub)

        # Reuse path returns plan_to_persist=None, so there's no write; the frozen plan is forwarded
        # to generation so it can skip the planner.
        mock_persist.assert_not_called()
        assert mock_gen.await_args is not None
        assert mock_gen.await_args.kwargs["ai_query_plan"] == frozen
        mock_ctx.assert_called_once()
        assert returned.query_plan_status == AIQueryPlanStatus.FROZEN

    @parameterized.expand(
        [
            ("legacy_config", {}, True, True),
            ("images_on", {"include_images": True}, True, True),
            ("images_off", {"include_images": False}, False, True),
            ("manage_link_off", {"include_manage_link": False}, True, False),
        ]
    )
    async def test_forwards_the_display_options_to_generation(
        self, _name: str, delivery_config: dict, expected_charts: bool, expected_manage_link: bool
    ) -> None:
        # Generation renders the charts, so the option has to reach it — gating only the delivery
        # renderers would still run a headless PNG export per chart for a report that hides them.
        # Generation also writes the all-queries-failed notice, whose recovery sentence names the
        # manage control, so it has to know whether the delivery renderers ship one.
        sub = self._subscription(ai_query_plan=None)
        sub.delivery_config = delivery_config
        result = AiReportResult(
            markdown="# R", diagnostics=(), window_end_utc="2026-06-29T16:00:00+00:00", plan_to_persist=None
        )
        with (
            patch(f"{_DELIVERY}._resolve_subscription_context", return_value=self._context(sub)),
            patch(f"{_DELIVERY}.generate_ai_report", new=AsyncMock(return_value=result)) as mock_gen,
        ):
            await build_ai_subscription_report(sub)

        assert mock_gen.await_args is not None
        assert mock_gen.await_args.kwargs["include_charts"] is expected_charts
        assert mock_gen.await_args.kwargs["include_manage_link"] is expected_manage_link
