"""Generation and delivery of the weekly AI visibility report, a report the AEO product computes.

It runs in ProcessAISubscriptionWorkflow: generation stores the report on the delivery row, and
delivery reads it back and renders it for email or Slack. No language model is involved.
"""

import uuid
import datetime as dt
from typing import Any

import structlog
import temporalio.activity
from temporalio.exceptions import ApplicationError

from posthog.email import EmailMessage, raise_if_delivery_rejected
from posthog.integrations import IntegrationRecord
from posthog.models.utils import strip_null_bytes
from posthog.slack.formatting import channel_id_from_target, escape_slack_mrkdwn
from posthog.sync import database_sync_to_async
from posthog.utils import absolute_uri

from products.aeo.backend.facade.api import get_weekly_report, weekly_report_from_json, weekly_report_to_json
from products.aeo.backend.facade.contracts import (
    WeeklyReport,
    WeeklyReportAction,
    WeeklyReportPage,
    WeeklyReportPageRole,
    WeeklyReportTopic,
)
from products.subscriptions.backend.logic.slack_subscriptions import (
    SlackDeliveryResult,
    SlackMessage,
    deliver_slack_message_data,
)
from products.subscriptions.backend.logic.subscription_utils import UTM_TAGS_BASE
from products.subscriptions.backend.models.subscription import (
    AI_VISIBILITY_REPORT_DEFAULT_TITLE,
    Subscription,
    SubscriptionDelivery,
    get_unsubscribe_token,
)
from products.subscriptions.backend.temporal.delivery_common import deliver_email, deliver_slack
from products.subscriptions.backend.temporal.types import (
    AI_VISIBILITY_REPORT_SNAPSHOT_KEY,
    DeliverSubscriptionInputs,
    DeliverSubscriptionResult,
    GenerateAIReportResult,
    RecipientResult,
)

LOGGER = structlog.get_logger(__name__)

NO_ANSWERS_SKIP_TYPE = "NoAIVisibilityAnswers"
NO_ANSWERS_SKIP_MESSAGE = (
    "No AI answers were recorded for non-branded prompts in the report week, so there was nothing to send."
)
# Topics past this are summarized in one line, so a large prompt set can't fill the message.
MAX_LISTED_TOPICS = 10
SLACK_HEADER_LIMIT = 150

PAGE_ROLE_LABELS = {
    WeeklyReportPageRole.OWNED_GAINED: "Your page that gained most",
    WeeklyReportPageRole.OWNED_LOST: "Your page that lost most",
    WeeklyReportPageRole.COMPETITOR_GAINED: "Competitor page that gained most",
}


async def generate_ai_visibility_report(subscription: Subscription, delivery_id: uuid.UUID) -> GenerateAIReportResult:
    @database_sync_to_async(thread_sensitive=False)
    def _generate() -> GenerateAIReportResult:
        delivery = SubscriptionDelivery.objects.get(pk=delivery_id)
        snapshot = delivery.content_snapshot if isinstance(delivery.content_snapshot, dict) else {}
        # A retried activity keeps the report it already stored, so the delivery sends the numbers it recorded.
        if AI_VISIBILITY_REPORT_SNAPSHOT_KEY not in snapshot:
            report = get_weekly_report(subscription.team_id, timezone_name=subscription.team.timezone)
            if not report.has_answers:
                return GenerateAIReportResult(
                    skipped=True,
                    target_type=subscription.target_type,
                    skip_error={"message": NO_ANSWERS_SKIP_MESSAGE, "type": NO_ANSWERS_SKIP_TYPE},
                )
            delivery.content_snapshot = {
                **snapshot,
                AI_VISIBILITY_REPORT_SNAPSHOT_KEY: strip_null_bytes(weekly_report_to_json(report)),
            }
            delivery.save(update_fields=["content_snapshot", "last_updated_at"])
        return GenerateAIReportResult(aborted=False, target_type=subscription.target_type)

    return await _generate()


async def _load_report(delivery_id: uuid.UUID) -> WeeklyReport:
    @database_sync_to_async(thread_sensitive=False)
    def _read() -> Any:
        snapshot = SubscriptionDelivery.objects.values_list("content_snapshot", flat=True).get(pk=delivery_id)
        return snapshot.get(AI_VISIBILITY_REPORT_SNAPSHOT_KEY) if isinstance(snapshot, dict) else None

    data = await _read()
    try:
        return weekly_report_from_json(data)
    except (KeyError, TypeError, ValueError) as error:
        # Generation stores the report before delivery runs, and a retry can't regenerate it here.
        raise ApplicationError(
            f"AI visibility report missing for delivery {delivery_id}", non_retryable=True
        ) from error


async def deliver_ai_visibility_report(
    subscription: Subscription,
    inputs: DeliverSubscriptionInputs,
    recipient_results: list[RecipientResult],
) -> DeliverSubscriptionResult:
    if inputs.delivery_id is None:
        raise ApplicationError(
            f"AI visibility report for subscription {subscription.id} has no delivery_id", non_retryable=True
        )
    delivery_id = inputs.delivery_id
    report = await _load_report(delivery_id)

    if subscription.target_type == Subscription.SubscriptionTarget.EMAIL:
        # Stable across this run's retries and unique per run, so MessagingRecord dedups retries only.
        workflow_run_id = temporalio.activity.info().workflow_run_id
        if workflow_run_id is None:
            raise ApplicationError("AI visibility report email requires a workflow run id", non_retryable=True)

        async def _send_email(email: str) -> None:
            await database_sync_to_async(send_email_ai_visibility_report, thread_sensitive=False)(
                email=email, subscription=subscription, report=report, delivery_run_id=workflow_run_id
            )

        return await deliver_email(subscription, inputs, recipient_results, _send_email)
    if subscription.target_type == Subscription.SubscriptionTarget.SLACK:
        return await deliver_slack(
            subscription,
            recipient_results,
            lambda integration: send_slack_ai_visibility_report(subscription, report, integration),
        )
    # The API accepts only email and Slack for this report, so another target is a row edited out of band.
    raise ApplicationError(
        f"AI visibility report reached an unsupported target {subscription.target_type!r}", non_retryable=True
    )


def _title(subscription: Subscription) -> str:
    return subscription.title or AI_VISIBILITY_REPORT_DEFAULT_TITLE


def format_rate(rate: float | None) -> str:
    if rate is None:
        return "no answers"
    return f"{rate * 100:.1f}".removesuffix(".0") + "%"


def format_change(change: float | None) -> str:
    if change is None:
        return "new this week"
    points = f"{abs(change) * 100:.1f}".removesuffix(".0")
    if points == "0":
        return "no change"
    unit = "pt" if points == "1" else "pts"
    return f"{'+' if change > 0 else '-'}{points} {unit}"


def answer_count(answers: int) -> str:
    return f"{answers:,} answer" if answers == 1 else f"{answers:,} answers"


def _format_day(day: dt.date) -> str:
    return f"{day:%b} {day.day}"


def report_period(report: WeeklyReport) -> str:
    return f"{_format_day(report.window_from)} to {_format_day(report.window_to)}"


def topic_name(topic: str) -> str:
    return topic or "No topic"


def _with_utm(url: str, medium: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{UTM_TAGS_BASE}&utm_medium={medium}"


def _subscription_url(subscription: Subscription) -> str:
    return subscription.url or absolute_uri(f"/project/{subscription.team_id}/subscriptions/{subscription.id}")


def _slack_link(url: str, label: str) -> str:
    # A cited URL is third-party text: `|` and `>` would end the link early and `<` would start a new one.
    safe_url = url.replace("|", "%7C").replace("<", "%3C").replace(">", "%3E")
    return f"<{safe_url}|{escape_slack_mrkdwn(label)}>"


def _page_label(url: str) -> str:
    label = url.split("://", 1)[-1].split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return label or url


def _topic_line(topic: WeeklyReportTopic) -> str:
    return (
        f"{escape_slack_mrkdwn(topic_name(topic.topic))}: {format_rate(topic.visibility)} "
        f"({format_change(topic.visibility_change)}, {answer_count(topic.answers)})"
    )


def _page_line(page: WeeklyReportPage) -> str:
    return (
        f"{PAGE_ROLE_LABELS[page.role]}: {_slack_link(page.url, _page_label(page.url))} in "
        f"{escape_slack_mrkdwn(topic_name(page.topic))}, cited in {format_rate(page.citation_rate)} of answers "
        f"({format_change(page.change)})"
    )


def _action_line(index: int, action: WeeklyReportAction) -> str:
    return f"{index}. {escape_slack_mrkdwn(action.text)} {_slack_link(_with_utm(action.url, 'slack'), 'Open')}"


def _mrkdwn_section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def build_ai_visibility_slack_message(subscription: Subscription, report: WeeklyReport) -> SlackMessage:
    scorecard = report.scorecard
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": _title(subscription)[:SLACK_HEADER_LIMIT]}},
        _mrkdwn_section(
            f"Brand visibility in AI answers to non-branded prompts, {report_period(report)}, "
            f"compared with the week before. Based on {answer_count(scorecard.answers)}."
        ),
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Brand visibility*\n{format_rate(scorecard.visibility)} ({format_change(scorecard.visibility_change)})",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Citation rate*\n{format_rate(scorecard.citation_rate)} ({format_change(scorecard.citation_rate_change)})",
                },
            ],
        },
    ]
    if report.topics:
        lines = [_topic_line(topic) for topic in report.topics[:MAX_LISTED_TOPICS]]
        if len(report.topics) > MAX_LISTED_TOPICS:
            lines.append(f"_{len(report.topics) - MAX_LISTED_TOPICS} more topics in AI visibility._")
        blocks.append(_mrkdwn_section("*Topics*\n" + "\n".join(lines)))
    if report.pages:
        blocks.append(_mrkdwn_section("*Pages to watch*\n" + "\n".join(_page_line(page) for page in report.pages)))
    if report.actions:
        blocks.append(
            _mrkdwn_section(
                "*Suggested actions*\n"
                + "\n".join(_action_line(index, action) for index, action in enumerate(report.actions, start=1))
            )
        )
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open AI visibility"},
                    "url": _with_utm(report.app_url, "slack"),
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Manage subscription"},
                    "url": _with_utm(_subscription_url(subscription), "slack"),
                },
            ],
        }
    )
    return SlackMessage(
        channel=channel_id_from_target(subscription.target_value),
        blocks=blocks,
        title=f"{_title(subscription)}: {report_period(report)}",
        # Page URLs come from third-party answers, so Slack must not fetch them.
        unfurl=False,
    )


async def send_slack_ai_visibility_report(
    subscription: Subscription, report: WeeklyReport, integration: IntegrationRecord
) -> SlackDeliveryResult:
    return await deliver_slack_message_data(
        integration, subscription, build_ai_visibility_slack_message(subscription, report)
    )


def ai_visibility_email_context(subscription: Subscription, report: WeeklyReport, *, email: str) -> dict[str, Any]:
    scorecard = report.scorecard
    return {
        "title": _title(subscription),
        "period": report_period(report),
        "answers": answer_count(scorecard.answers),
        "visibility": format_rate(scorecard.visibility),
        "visibility_change": format_change(scorecard.visibility_change),
        "citation_rate": format_rate(scorecard.citation_rate),
        "citation_rate_change": format_change(scorecard.citation_rate_change),
        "topics": [
            {
                "name": topic_name(topic.topic),
                "visibility": format_rate(topic.visibility),
                "change": format_change(topic.visibility_change),
                "answers": answer_count(topic.answers),
            }
            for topic in report.topics[:MAX_LISTED_TOPICS]
        ],
        "more_topics": max(len(report.topics) - MAX_LISTED_TOPICS, 0),
        "pages": [
            {
                "role": PAGE_ROLE_LABELS[page.role],
                "url": page.url,
                "label": _page_label(page.url),
                "topic": topic_name(page.topic),
                "citation_rate": format_rate(page.citation_rate),
                "change": format_change(page.change),
            }
            for page in report.pages
        ],
        "actions": [{"text": action.text, "url": _with_utm(action.url, "email")} for action in report.actions],
        "app_url": _with_utm(report.app_url, "email"),
        "subscription_url": _with_utm(_subscription_url(subscription), "email"),
        "unsubscribe_url": absolute_uri(
            f"/unsubscribe?token={get_unsubscribe_token(subscription, email)}&{UTM_TAGS_BASE}&utm_medium=email"
        ),
    }


def send_email_ai_visibility_report(
    *, email: str, subscription: Subscription, report: WeeklyReport, delivery_run_id: str
) -> None:
    campaign_key = f"ai_visibility_report_{subscription.id}_{delivery_run_id}"
    message = EmailMessage(
        campaign_key=campaign_key,
        subject=f"{_title(subscription)}: {report_period(report)}",
        template_name="ai_visibility_report",
        template_context=ai_visibility_email_context(subscription, report, email=email),
    )
    message.add_recipient(email=email)
    message.send(send_async=False)
    raise_if_delivery_rejected(campaign_key, email)
