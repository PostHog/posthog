import uuid
from datetime import UTC, datetime
from urllib.parse import urlencode

import nh3
import structlog
from markdown_it import MarkdownIt
from markdown_to_mrkdwn import SlackMarkdownConverter

from posthog.email import EmailMessage
from posthog.exceptions_capture import capture_exception
from posthog.helpers.markdown_safety import strip_external_links_markdown
from posthog.helpers.slack_subscription_explore import build_explore_hint
from posthog.models import Team, User
from posthog.models.integration import Integration
from posthog.sync import database_sync_to_async
from posthog.utils import absolute_uri

from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery, get_unsubscribe_token
from products.exports.backend.temporal.subscriptions.ai_subscription.report_pipeline import (
    AiReportResult,
    generate_ai_report,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.spec_generator import (
    PromptRejectedError,
    ReportWindow,
    compute_report_window,
)
from products.exports.backend.temporal.subscriptions.types import AI_REPORT_WINDOW_END_KEY, SubscriptionTriggerType

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


def _last_scheduled_report_cutoff(subscription: Subscription) -> datetime | None:
    try:
        row = (
            SubscriptionDelivery.objects.filter(
                subscription_id=subscription.id,
                status=SubscriptionDelivery.Status.COMPLETED,
                # Only real scheduled sends move the anchor: a manual "Test delivery" (or an immediate
                # target-change confirmation) right before a run would otherwise shrink its window to
                # near-empty — a test is a preview, not a send.
                trigger_type=SubscriptionTriggerType.SCHEDULED,
                finished_at__isnull=False,
            )
            .order_by("-finished_at")
            .values_list("finished_at", "content_snapshot")
            .first()
        )
        if row is None:
            return None
        finished_at, snapshot = row
        # Prefer the run's persisted window end: anchoring on finished_at leaves the run's own
        # generation+send time uncovered. Rows written before the key existed fall back.
        window_end = (snapshot or {}).get(AI_REPORT_WINDOW_END_KEY)
        if isinstance(window_end, str):
            try:
                return datetime.fromisoformat(window_end)
            except ValueError:
                pass
        return finished_at
    except Exception as exc:
        # A transient DB error on this one lookup shouldn't fail the whole delivery — None falls
        # back to the cadence window (which may re-cover already-sent data, never drop any).
        logger.warning(
            "ai_report.last_delivery_lookup_failed",
            subscription_id=subscription.id,
            team_id=subscription.team_id,
            exc_info=True,
        )
        capture_exception(exc, {"subscription_id": subscription.id, "feature": "ai_subscription"})
        return None


def _resolve_subscription_context(
    subscription: Subscription,
) -> tuple[Team, User | None, ReportWindow, dict | None]:
    # team/created_by are FK relations and the last-delivery lookup hits the DB; resolving the window
    # here keeps all ORM access (and the timezone math) off the event loop in one sync hop. The frozen
    # plan (if any) is read here too so the generation path stays free of ORM access.
    team = subscription.team
    # Day-based window modes don't anchor to delivery history — skip the lookup for them.
    last_scheduled_cutoff = (
        _last_scheduled_report_cutoff(subscription)
        if subscription.ai_window_mode == Subscription.AIWindowMode.SINCE_LAST_SENT
        else None
    )
    window = compute_report_window(
        team=team,
        last_scheduled_cutoff=last_scheduled_cutoff,
        now=datetime.now(tz=UTC),
        window_days=subscription.ai_report_window_days,
        mode=subscription.ai_window_mode,
        start_days_ago=subscription.ai_window_start_days_ago,
        end_days_ago=subscription.ai_window_end_days_ago,
    )
    return team, subscription.created_by, window, subscription.ai_query_plan


def _persist_ai_query_plan(subscription_id: int, team_id: int, prompt: str | None, plan: dict) -> None:
    # Targeted update, never a full save() — that would re-emit the activity-log/analytics signals.
    # Filtering on the planning-time prompt closes a race: a prompt edited mid-generation clears the
    # plan via Subscription.save(), and this no-ops instead of re-freezing a plan for the old prompt.
    Subscription.objects.filter(id=subscription_id, team_id=team_id, prompt=prompt).update(ai_query_plan=plan)


async def build_ai_subscription_report(subscription: Subscription) -> AiReportResult:
    team, user, window, ai_query_plan = await database_sync_to_async(
        _resolve_subscription_context, thread_sensitive=False
    )(subscription)
    # created_by is FK SET_NULL; the pipeline requires a non-None user
    if user is None:
        raise PromptRejectedError("AI subscription has no creator (created_by deleted); cannot deliver.")

    result = await generate_ai_report(
        team=team,
        user=user,
        prompt=subscription.prompt,
        window=window,
        ai_query_plan=ai_query_plan,
        trace_correlation_id=subscription.id,
    )

    if result.plan_to_persist is not None:
        try:
            await database_sync_to_async(_persist_ai_query_plan, thread_sensitive=False)(
                subscription.id, subscription.team_id, subscription.prompt, result.plan_to_persist
            )
        except Exception as exc:
            # The frozen plan is an optimization — losing this write must not abort the delivery (the
            # report is already generated; failing here would burn the LLM run and retry from scratch).
            logger.warning(
                "ai_report.ai_query_plan_persist_failed",
                subscription_id=subscription.id,
                team_id=subscription.team_id,
                exc_info=True,
            )
            capture_exception(exc, {"subscription_id": subscription.id, "feature": "ai_subscription"})

    return result


async def preview_ai_subscription_report(subscription: Subscription) -> AiReportResult:
    """Run the AI report generation pipeline for a preview — no delivery, no persistence.

    Same generation path as `build_ai_subscription_report` but deliberately side-effect-free on the
    subscription: it never persists the freshly-planned `ai_query_plan` (the query_plan API field is
    the explicit write path) and the caller never invokes a send function. The returned report
    markdown + per-step diagnostics let an owner see what the subscription would produce — including
    the generated HogQL — without emailing/Slacking anyone.
    """
    team, user, window, ai_query_plan = await database_sync_to_async(
        _resolve_subscription_context, thread_sensitive=False
    )(subscription)
    if user is None:
        raise PromptRejectedError("AI subscription has no creator (created_by deleted); cannot preview.")

    return await generate_ai_report(
        team=team,
        user=user,
        prompt=subscription.prompt,
        window=window,
        ai_query_plan=ai_query_plan,
        trace_correlation_id=subscription.id,
    )


def _build_feedback_url(subscription_url: str, delivery_id: uuid.UUID, feedback: str, source: str) -> str:
    # Lands on the authenticated subscription page; the frontend reads these exact params
    # (feedback_delivery, feedback, feedback_source) and captures an `ai_report_feedback` event.
    params = urlencode({"feedback_delivery": str(delivery_id), "feedback": feedback, "feedback_source": source})
    return f"{subscription_url}?{params}"


def render_ai_email_html(markdown: str) -> str:
    rendered = _MARKDOWN_RENDERER.render(strip_external_links_markdown(markdown))
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


def _build_ai_slack_message(
    subscription: Subscription,
    markdown: str,
    *,
    delivery_id: uuid.UUID,
    integration: Integration | None = None,
) -> SlackMessageData:
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=slack"
    channel = subscription.target_value.split("|")[0]
    sections = _split_text_into_chunks(_SLACK_CONVERTER.convert(strip_external_links_markdown(markdown)))
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

    action_elements: list[dict] = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Manage subscription"},
            "url": f"{subscription_url}?{utm_tags}",
        }
    ]
    blocks.extend(
        [
            {"type": "divider"},
            {"type": "actions", "elements": action_elements},
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
    # AI consent is enforced upstream before this report is built, so the hint always shows here.
    if explore_hint := build_explore_hint(integration, utm_tags=utm_tags, ai_enabled=True):
        blocks.append(explore_hint)

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
    message_data = _build_ai_slack_message(subscription, markdown, delivery_id=delivery_id, integration=integration)
    return await deliver_slack_message_data(integration, subscription, message_data)


__all__ = [
    "build_ai_subscription_report",
    "preview_ai_subscription_report",
    "render_ai_email_html",
    "send_email_ai_subscription_report",
    "send_slack_ai_subscription_report",
]
