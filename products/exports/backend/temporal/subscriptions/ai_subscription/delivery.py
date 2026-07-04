import uuid
from datetime import datetime
from urllib.parse import urlencode

import structlog

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
from products.exports.backend.temporal.subscriptions.delivery_common import (
    build_markdown_slack_message,
    render_markdown_email_html,
)

from ee.tasks.subscriptions.slack_subscriptions import (
    UTM_TAGS_BASE,
    SlackDeliveryResult,
    SlackMessageData,
    deliver_slack_message_data,
)

logger = structlog.get_logger(__name__)


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
        window_days=subscription.report_window_days,
        trace_correlation_id=subscription.id,
    )


def _build_feedback_url(subscription_url: str, delivery_id: uuid.UUID, feedback: str, source: str) -> str:
    # Lands on the authenticated subscription page; the frontend reads these exact params
    # (feedback_delivery, feedback, feedback_source) and captures an `ai_report_feedback` event.
    params = urlencode({"feedback_delivery": str(delivery_id), "feedback": feedback, "feedback_source": source})
    return f"{subscription_url}?{params}"


def send_email_ai_subscription_report(
    *,
    email: str,
    subscription: Subscription,
    markdown: str,
    delivery_run_id: str,
    delivery_id: uuid.UUID,
) -> None:
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=email"
    html = render_markdown_email_html(markdown)
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


def _build_ai_slack_message(
    subscription: Subscription,
    markdown: str,
    *,
    delivery_id: uuid.UUID,
    integration: Integration | None = None,
) -> SlackMessageData:
    subscription_url = subscription.url or absolute_uri(
        f"/project/{subscription.team_id}/subscriptions/{subscription.id}"
    )
    feedback_positive_url = _build_feedback_url(subscription_url, delivery_id, "positive", "slack")
    feedback_negative_url = _build_feedback_url(subscription_url, delivery_id, "negative", "slack")
    feedback_block = {
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": (f"Was this report useful? <{feedback_positive_url}|👍 Yes> · <{feedback_negative_url}|👎 No>"),
            }
        ],
    }
    return build_markdown_slack_message(
        subscription,
        markdown,
        default_title="Your PostHog AI report",
        button_label="Manage subscription",
        button_url=subscription_url,
        extra_blocks=[feedback_block],
        integration=integration,
    )


async def send_slack_ai_subscription_report(
    *,
    subscription: Subscription,
    markdown: str,
    integration: Integration,
    delivery_id: uuid.UUID,
) -> SlackDeliveryResult:
    message_data = _build_ai_slack_message(subscription, markdown, delivery_id=delivery_id, integration=integration)
    return await deliver_slack_message_data(integration, subscription, message_data)


__all__ = [
    "build_ai_subscription_report",
    "send_email_ai_subscription_report",
    "send_slack_ai_subscription_report",
]
