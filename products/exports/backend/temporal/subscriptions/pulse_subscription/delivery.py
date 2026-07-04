from posthog.email import EmailMessage
from posthog.helpers.markdown_safety import strip_external_links_markdown
from posthog.helpers.slack_subscription_explore import build_explore_hint
from posthog.models.integration import Integration
from posthog.utils import absolute_uri

from products.exports.backend.models.subscription import Subscription, get_unsubscribe_token
from products.exports.backend.temporal.subscriptions.ai_subscription.delivery import (
    _SLACK_CONVERTER,
    _split_text_into_chunks,
    render_ai_email_html,
)
from products.pulse.backend.models import ProductBrief

from ee.tasks.subscriptions.slack_subscriptions import (
    UTM_TAGS_BASE,
    SlackDeliveryResult,
    SlackMessageData,
    deliver_slack_message_data,
)

# Spec §7: a QUIET brief is delivered as this honest one-line note, never padded content.
QUIET_BRIEF_NOTE = (
    "It's a quiet period — Pulse found nothing confident enough to report, so there's no brief this time."
)

DEFAULT_BRIEF_TITLE = "Your PostHog product brief"


def pulse_page_url(team_id: int) -> str:
    return absolute_uri(f"/project/{team_id}/pulse")


def render_brief_markdown(brief: ProductBrief) -> str:
    """Flatten a READY brief's sections into one markdown document: per-section title,
    body, and citations rendered as absolute links to the Pulse page (where the brief
    lives with its full evidence trail)."""
    url = pulse_page_url(brief.team_id)
    parts: list[str] = []
    for section in brief.sections:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").strip()
        body = str(section.get("markdown") or "").strip()
        if title:
            parts.append(f"## {title}")
        if body:
            parts.append(body)
        citations = [c for c in (section.get("citations") or []) if isinstance(c, str) and c]
        if citations:
            links = " · ".join(f"[{citation}]({url})" for citation in citations)
            parts.append(f"Evidence: {links}")
    parts.append(f"[View this brief in PostHog Pulse]({url})")
    return "\n\n".join(parts)


def send_email_pulse_brief(
    *,
    email: str,
    subscription: Subscription,
    markdown: str,
    delivery_run_id: str,
) -> None:
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=email"
    html = render_ai_email_html(markdown)
    title = subscription.title or DEFAULT_BRIEF_TITLE
    brief_url = subscription.url or pulse_page_url(subscription.team_id)
    unsubscribe_url = absolute_uri(f"/unsubscribe?token={get_unsubscribe_token(subscription, email)}&{utm_tags}")

    message = EmailMessage(
        # Stable across this run's retries, unique per run so a re-test re-sends.
        campaign_key=f"pulse_brief_report_{subscription.id}_{delivery_run_id}",
        subject=f"PostHog Pulse brief - {title}",
        template_name="pulse_brief_report",
        template_context={
            "title": title,
            "rendered_html": html,
            "brief_url": f"{brief_url}?{utm_tags}",
            "unsubscribe_url": unsubscribe_url,
        },
    )
    message.add_recipient(email=email)
    message.send(send_async=False)


def _build_pulse_slack_message(
    subscription: Subscription,
    markdown: str,
    *,
    integration: Integration | None = None,
) -> SlackMessageData:
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=slack"
    channel = subscription.target_value.split("|")[0]
    sections = _split_text_into_chunks(_SLACK_CONVERTER.convert(strip_external_links_markdown(markdown)))
    title = subscription.title or DEFAULT_BRIEF_TITLE
    first_section = sections[0] if sections else "_No brief content was generated._"

    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": first_section}},
    ]
    if len(sections) > 1:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": "_See thread for the rest of the brief._"}}
        )

    brief_url = subscription.url or pulse_page_url(subscription.team_id)
    blocks.extend(
        [
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View in Pulse"},
                        "url": f"{brief_url}?{utm_tags}",
                    }
                ],
            },
        ]
    )
    # AI consent is enforced upstream before a brief is generated, so the hint always shows here.
    if explore_hint := build_explore_hint(integration, utm_tags=utm_tags, ai_enabled=True):
        blocks.append(explore_hint)

    thread_messages = [
        {"blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": section}}]} for section in sections[1:]
    ]
    # unfurl=False: brief content is LLM-generated; never let Slack auto-fetch a link it contains.
    return SlackMessageData(channel=channel, blocks=blocks, title=title, thread_messages=thread_messages, unfurl=False)


async def send_slack_pulse_brief(
    *,
    subscription: Subscription,
    markdown: str,
    integration: Integration,
) -> SlackDeliveryResult:
    message_data = _build_pulse_slack_message(subscription, markdown, integration=integration)
    return await deliver_slack_message_data(integration, subscription, message_data)
