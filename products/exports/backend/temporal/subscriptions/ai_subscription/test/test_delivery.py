import uuid
from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.helpers.slack_scopes import REQUIRED_SLACK_SCOPES

from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery
from products.exports.backend.temporal.subscriptions.ai_subscription.delivery import (
    SLACK_MRKDWN_SECTION_LIMIT,
    _build_ai_slack_message,
    _last_scheduled_report_cutoff,
    _split_text_into_chunks,
    render_ai_email_html,
    send_email_ai_subscription_report,
)
from products.exports.backend.temporal.subscriptions.types import AI_REPORT_WINDOW_END_KEY, SubscriptionTriggerType

from ee.tasks.subscriptions.slack_subscriptions import SlackMessageData

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
        message = _build_message("See [details](https://attacker.example/exfil?p=secret)")
        all_text = " ".join(b["text"]["text"] for b in message.blocks if b["type"] == "section")
        assert "attacker.example" not in all_text
        assert "details" in all_text

    def test_slack_keeps_posthog_link(self) -> None:
        message = _build_message("Open [dashboard](https://app.posthog.com/insights/abc)")
        all_text = " ".join(b["text"]["text"] for b in message.blocks if b["type"] == "section")
        assert "app.posthog.com/insights/abc" in all_text

    def test_slack_defangs_bare_external_url(self) -> None:
        # a bare (non-markdown) URL still gets linkified/unfurled by Slack — must be defanged
        message = _build_message("Visit https://attacker.example/exfil?p=secret now")
        all_text = " ".join(b["text"]["text"] for b in message.blocks if b["type"] == "section")
        assert "`https://attacker.example/exfil?p=secret`" in all_text

    def test_slack_defangs_autolink(self) -> None:
        message = _build_message("See <https://attacker.example/exfil> here")
        all_text = " ".join(b["text"]["text"] for b in message.blocks if b["type"] == "section")
        assert "`https://attacker.example/exfil`" in all_text

    def test_slack_keeps_bare_posthog_url(self) -> None:
        message = _build_message("Open https://app.posthog.com/insights/abc now")
        all_text = " ".join(b["text"]["text"] for b in message.blocks if b["type"] == "section")
        assert "https://app.posthog.com/insights/abc" in all_text
        assert "`https://app.posthog.com" not in all_text  # PostHog hosts stay live, not defanged

    def test_slack_defangs_scheme_less_www_url(self) -> None:
        # Slack also linkifies scheme-less www. URLs — those must be defanged too
        message = _build_message("Visit www.attacker.example/exfil now")
        all_text = " ".join(b["text"]["text"] for b in message.blocks if b["type"] == "section")
        assert "`www.attacker.example/exfil`" in all_text

    def test_slack_keeps_www_posthog_url(self) -> None:
        message = _build_message("Docs at www.posthog.com/docs here")
        all_text = " ".join(b["text"]["text"] for b in message.blocks if b["type"] == "section")
        assert "www.posthog.com/docs" in all_text
        assert "`www.posthog.com" not in all_text

    def test_slack_does_not_mangle_email_addresses(self) -> None:
        message = _build_message("Reach me@www.example.com for access")
        all_text = " ".join(b["text"]["text"] for b in message.blocks if b["type"] == "section")
        assert "me@www.example.com" in all_text
        assert "`www.example.com" not in all_text

    def test_slack_defangs_parenthetical_external_url(self) -> None:
        # a URL inside plain parentheses is preceded by `(` but is not a markdown link — still defang it
        message = _build_message("Revenue event (https://attacker.example/track) spiked")
        all_text = " ".join(b["text"]["text"] for b in message.blocks if b["type"] == "section")
        assert "`https://attacker.example/track`" in all_text

    def test_slack_defangs_uppercase_scheme_autolink(self) -> None:
        # URL schemes are case-insensitive — an uppercase scheme must not slip past the matcher
        message = _build_message("See <HTTPS://attacker.example/exfil> now")
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
        message = _build_message("A short report.")
        assert message.unfurl is False


def _mock_subscription() -> MagicMock:
    sub = MagicMock()
    sub.target_value = "C123|#general"
    sub.title = "Weekly report"
    sub.url = _SUBSCRIPTION_URL
    sub.team_id = 1
    sub.id = 2
    return sub


def _build_message(markdown: str) -> SlackMessageData:
    return _build_ai_slack_message(_mock_subscription(), markdown, delivery_id=_DELIVERY_ID)


class TestBuildAISlackMessage:
    def test_single_section_report_has_no_thread_messages(self) -> None:
        message = _build_message("A short report.")
        assert message.channel == "C123"
        assert message.thread_messages == []
        section_texts = [b["text"]["text"] for b in message.blocks if b["type"] == "section"]
        assert all(text.strip() for text in section_texts), "no empty section text allowed"

    def test_long_report_overflows_into_thread(self) -> None:
        long_markdown = ("para\n\n" * 1).join("x" * (SLACK_MRKDWN_SECTION_LIMIT - 50) for _ in range(3))
        message = _build_message(long_markdown)
        assert len(message.thread_messages) >= 1
        for thread_msg in message.thread_messages:
            for block in thread_msg["blocks"]:
                assert block["text"]["text"].strip(), "thread section text must be non-empty"


def _mock_integration(scopes: frozenset[str]) -> MagicMock:
    integration = MagicMock()
    integration.kind = "slack"
    integration.id = 7
    integration.config = {"scope": ",".join(sorted(scopes))}
    integration.sensitive_config = {"access_token": "xoxb-test"}
    return integration


def _hint_texts(message: SlackMessageData) -> list[str]:
    return [el["text"] for block in message.blocks if block.get("type") == "context" for el in block["elements"]]


def _ai_message(*, integration: MagicMock | None = None) -> SlackMessageData:
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
        context_blocks = [b for b in message.blocks if b["type"] == "context"]
        assert len(context_blocks) == 1
        text = context_blocks[0]["elements"][0]["text"]
        assert "Was this report useful?" in text
        assert f"<{_feedback_url(feedback, 'slack')}|{label}>" in text

    @pytest.mark.parametrize("feedback", ["positive", "negative"])
    def test_email_context_carries_feedback_urls(self, feedback: str) -> None:
        with (
            patch(
                "products.exports.backend.temporal.subscriptions.ai_subscription.delivery.EmailMessage"
            ) as email_message,
            patch(
                "products.exports.backend.temporal.subscriptions.ai_subscription.delivery.get_unsubscribe_token",
                return_value="tok",
            ),
        ):
            send_email_ai_subscription_report(
                email="a@b.com",
                subscription=_mock_subscription(),
                markdown="Report body",
                delivery_run_id="run-1",
                delivery_id=_DELIVERY_ID,
            )
        context = email_message.call_args.kwargs["template_context"]
        assert context[f"feedback_{feedback}_url"] == _feedback_url(feedback, "email")


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
            SubscriptionTriggerType.TARGET_CHANGE,
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
