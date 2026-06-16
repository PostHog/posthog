import re
import uuid
from datetime import datetime
from urllib.parse import urlencode, urlparse

import nh3
import structlog
from markdown_it import MarkdownIt
from markdown_to_mrkdwn import SlackMarkdownConverter

from posthog.api.utils import hostname_in_allowed_url_list
from posthog.email import EmailMessage
from posthog.models import Team, User
from posthog.models.integration import Integration
from posthog.sync import database_sync_to_async
from posthog.utils import absolute_uri

from products.exports.backend.models.subscription import Subscription, get_unsubscribe_token
from products.exports.backend.temporal.subscriptions.ai_subscription.report_pipeline import (
    AiReportResult,
    generate_ai_report,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.spec_generator import PromptRejectedError

from ee.tasks.subscriptions.slack_subscriptions import (
    UTM_TAGS_BASE,
    SlackDeliveryResult,
    SlackMessageData,
    deliver_slack_message_data,
)

logger = structlog.get_logger(__name__)


_MARKDOWN_RENDERER = MarkdownIt("commonmark", {"breaks": True, "html": False}).enable("table")
_SLACK_CONVERTER = SlackMarkdownConverter()

# defense-in-depth on top of html=False: allow only the tags commonmark emits
_ALLOWED_EMAIL_TAGS = {
    "a",
    "p",
    "br",
    "hr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "strong",
    "em",
    "b",
    "i",
    "code",
    "pre",
    "blockquote",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
}
_ALLOWED_EMAIL_ATTRS = {"a": {"href", "title"}}

# Slack's hard limit is 3000 chars per section block; keep margin for safety.
SLACK_MRKDWN_SECTION_LIMIT = 2900

# Only PostHog hosts are allowed in delivered report links. Any other host is stripped from
# the LLM output before rendering — Slack auto-unfurls outbound links server-side, which is
# an exfil channel an injected synthesis prompt could otherwise drive. Wildcard entries cover
# the `<region>.posthog.com` subdomains via `hostname_in_allowed_url_list`'s regex matching.
_ALLOWED_LINK_URLS = ["https://posthog.com", "https://*.posthog.com"]
# URL group supports one level of balanced parens so e.g. wikipedia /Foo_(bar) doesn't truncate
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\(((?:[^()\s]+|\([^)]*\))+)(?:\s+\"[^\"]*\")?\)")
_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
# `<scheme://…>` autolinks and bare `scheme://…` / `www.…` URLs — the forms Slack still linkifies and
# unfurls after the markdown-link pass above. Case-insensitive so an uppercase scheme can't slip
# through. The bare matcher skips only the `](url)` markdown-link context, `<` autolinks, backtick code
# spans, and email local-parts (`@`); a URL in plain parentheses is still defanged.
_AUTOLINK_RE = re.compile(r"<(https?://[^\s>]+)>", re.IGNORECASE)
_BARE_URL_RE = re.compile(r"(?<!\]\()(?<![<`@])((?:https?://|www\.)[^\s<>)\]`]+)", re.IGNORECASE)


def _is_allowed_link_url(url: str) -> bool:
    # Reject authority-confusion vectors *before* trusting urlparse's hostname. urlparse and a
    # browser disagree on the host whenever the authority contains a backslash, control/whitespace
    # char, or embedded userinfo (`@`): urlparse reads `evil.example\@posthog.com`,
    # `evil.example%5C@posthog.com`, or `posthog.com@evil.example` as one host, while the browser
    # navigates somewhere else. A legitimate PostHog link never has userinfo, so any `@` in the
    # authority — however encoded — is disqualifying. Also require an http(s) scheme.
    if "\\" in url or any(c.isspace() or ord(c) < 0x20 for c in url):
        return False
    try:
        parsed = urlparse(url)
        if parsed.username is not None or parsed.password is not None:
            return False
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    if parsed.scheme.lower() not in ("http", "https"):
        return False
    return hostname_in_allowed_url_list(_ALLOWED_LINK_URLS, host)


def _neutralize_url(url: str, keep_as: str | None = None) -> str:
    # Keep PostHog links live (rendered as `keep_as` when given — e.g. an autolink's `<url>` wrapper —
    # otherwise the bare URL); defang anything else into an inert code span so neither Slack (auto-
    # unfurl / linkify) nor email can turn an injected URL into a live request or a one-click link. The
    # URL stays visible so a reader can see what the report tried to embed. Scheme-less `www.` URLs get
    # a scheme prepended only for the host check, never in the output.
    check_url = url if url.lower().startswith(("http://", "https://")) else f"https://{url}"
    if _is_allowed_link_url(check_url):
        return keep_as if keep_as is not None else url
    return f"`{url}`"


def _strip_external_links_markdown(markdown: str) -> str:
    """Neutralize externally-hosted URLs in LLM-generated report content. Markdown images are
    dropped; `[text](url)`, `<url>` autolinks, and bare `http(s)://` / `www.` URLs keep PostHog hosts
    live and defang any other host. Defends against an injected synthesis prompt embedding an
    exfil/phishing URL that a delivery channel would auto-unfurl or linkify."""
    md = _MARKDOWN_IMAGE_RE.sub(lambda m: m.group(1) or "", markdown)
    md = _MARKDOWN_LINK_RE.sub(
        lambda m: m.group(0) if _is_allowed_link_url(m.group(2)) else m.group(1),
        md,
    )
    md = _AUTOLINK_RE.sub(lambda m: _neutralize_url(m.group(1), keep_as=m.group(0)), md)
    md = _BARE_URL_RE.sub(lambda m: _neutralize_url(m.group(1)), md)
    return md


def _split_text_into_chunks(text: str, limit: int = SLACK_MRKDWN_SECTION_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text] if text else []

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        # prefer a paragraph break, then any newline, else a hard cut; cut <= 0 guards against
        # carving an empty leading chunk and never progressing
        cut = remaining.rfind("\n\n", 0, limit)
        if cut <= 0:
            cut = remaining.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunk = remaining[:cut].rstrip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _resolve_subscription_actors(subscription: Subscription) -> tuple[Team, User | None]:
    # team/created_by are FK relations; reading them may hit the DB, so this runs off the event loop
    return subscription.team, subscription.created_by


async def build_ai_subscription_report(subscription: Subscription) -> AiReportResult:
    team, user = await database_sync_to_async(_resolve_subscription_actors, thread_sensitive=False)(subscription)
    # created_by is FK SET_NULL; the pipeline requires a non-None user
    if user is None:
        raise PromptRejectedError("AI subscription has no creator (created_by deleted); cannot deliver.")

    return await generate_ai_report(
        team=team,
        user=user,
        prompt=subscription.prompt,
        window_days=subscription.ai_report_window_days,
        trace_correlation_id=subscription.id,
    )


def _build_feedback_url(subscription_url: str, delivery_id: uuid.UUID, feedback: str, source: str) -> str:
    # Lands on the authenticated subscription page; the frontend reads these exact params
    # (feedback_delivery, feedback, feedback_source) and captures an `ai_report_feedback` event.
    params = urlencode({"feedback_delivery": str(delivery_id), "feedback": feedback, "feedback_source": source})
    return f"{subscription_url}?{params}"


def render_ai_email_html(markdown: str) -> str:
    rendered = _MARKDOWN_RENDERER.render(_strip_external_links_markdown(markdown))
    return nh3.clean(rendered, tags=_ALLOWED_EMAIL_TAGS, attributes=_ALLOWED_EMAIL_ATTRS)


def send_email_ai_subscription_report(
    *,
    email: str,
    subscription: Subscription,
    markdown: str,
    delivery_run_id: str,
    delivery_id: uuid.UUID,
) -> None:
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=email"
    html = render_ai_email_html(markdown)
    title = subscription.title or "Your PostHog AI report"
    subscription_url = subscription.url or absolute_uri(
        f"/project/{subscription.team_id}/subscriptions/{subscription.id}"
    )
    unsubscribe_url = absolute_uri(f"/unsubscribe?token={get_unsubscribe_token(subscription, email)}&{utm_tags}")

    campaign_key = f"ai_subscription_report_{subscription.id}_{delivery_run_id}"

    message = EmailMessage(
        campaign_key=campaign_key,
        subject=f"PostHog AI report - {title}",
        template_name="ai_subscription_report",
        template_context={
            "title": title,
            "rendered_html": html,
            "subscription_url": f"{subscription_url}?{utm_tags}",
            "unsubscribe_url": unsubscribe_url,
            "feedback_positive_url": _build_feedback_url(subscription_url, delivery_id, "positive", "email"),
            "feedback_negative_url": _build_feedback_url(subscription_url, delivery_id, "negative", "email"),
        },
    )
    message.add_recipient(email=email)
    message.send(send_async=False)


def send_email_ai_subscription_credit_limited(
    *,
    email: str,
    subscription: Subscription,
    resume_date: datetime,
    billing_period_key: str,
) -> None:
    """Notify the owner that a scheduled AI report was skipped for lack of AI credits.
    `billing_period_key` keys the campaign so MessagingRecord dedups to one notice per
    credit-reset cycle even if the skip path runs more than once."""
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=email"
    title = subscription.title or "Your PostHog AI report"
    subscription_url = subscription.url or absolute_uri(
        f"/project/{subscription.team_id}/subscriptions/{subscription.id}"
    )
    billing_url = absolute_uri("/organization/billing")

    message = EmailMessage(
        campaign_key=f"ai_subscription_credit_limited_{subscription.id}_{billing_period_key}",
        subject=f"PostHog AI report skipped - {title}",
        template_name="ai_subscription_credit_limited",
        template_context={
            "title": title,
            "resume_date": resume_date,
            "subscription_url": f"{subscription_url}?{utm_tags}",
            "billing_url": f"{billing_url}?{utm_tags}",
        },
    )
    message.add_recipient(email=email)
    message.send(send_async=False)


def _build_ai_slack_message(subscription: Subscription, markdown: str, *, delivery_id: uuid.UUID) -> SlackMessageData:
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=slack"
    channel = subscription.target_value.split("|")[0]
    sections = _split_text_into_chunks(_SLACK_CONVERTER.convert(_strip_external_links_markdown(markdown)))
    title = subscription.title or "Your PostHog AI report"
    first_section = sections[0] if sections else "_No report content was generated._"

    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": first_section}},
    ]
    if len(sections) > 1:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": "_See thread for the rest of the report._"}}
        )

    subscription_url = subscription.url or absolute_uri(
        f"/project/{subscription.team_id}/subscriptions/{subscription.id}"
    )
    feedback_positive_url = _build_feedback_url(subscription_url, delivery_id, "positive", "slack")
    feedback_negative_url = _build_feedback_url(subscription_url, delivery_id, "negative", "slack")
    blocks.extend(
        [
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Manage subscription"},
                        "url": f"{subscription_url}?{utm_tags}",
                    }
                ],
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            "Was this report useful? "
                            f"<{feedback_positive_url}|👍 Yes> · <{feedback_negative_url}|👎 No>"
                        ),
                    }
                ],
            },
        ]
    )

    thread_messages = [
        {"blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": section}}]} for section in sections[1:]
    ]
    # unfurl=False: report content is LLM-generated; never let Slack auto-fetch a link it contains.
    return SlackMessageData(channel=channel, blocks=blocks, title=title, thread_messages=thread_messages, unfurl=False)


async def send_slack_ai_subscription_report(
    *,
    subscription: Subscription,
    markdown: str,
    integration: Integration,
    delivery_id: uuid.UUID,
) -> SlackDeliveryResult:
    message_data = _build_ai_slack_message(subscription, markdown, delivery_id=delivery_id)
    return await deliver_slack_message_data(integration, subscription, message_data)


__all__ = [
    "build_ai_subscription_report",
    "render_ai_email_html",
    "send_email_ai_subscription_report",
    "send_slack_ai_subscription_report",
]
