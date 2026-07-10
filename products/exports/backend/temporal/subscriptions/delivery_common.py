import uuid
from collections.abc import Awaitable, Callable

import nh3
import temporalio.activity
from markdown_it import MarkdownIt
from markdown_to_mrkdwn import SlackMarkdownConverter
from slack_sdk.errors import SlackApiError
from structlog import get_logger
from temporalio.exceptions import ApplicationError

from posthog.exceptions_capture import capture_exception
from posthog.helpers.markdown_safety import strip_external_links_markdown
from posthog.helpers.slack_subscription_explore import build_explore_hint
from posthog.models.integration import Integration
from posthog.sync import database_sync_to_async

from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery
from products.exports.backend.temporal.subscriptions.types import (
    DeliverSubscriptionInputs,
    DeliverSubscriptionResult,
    RecipientResult,
)

from ee.tasks.subscriptions import SLACK_USER_CONFIG_ERRORS, _capture_delivery_failed_event
from ee.tasks.subscriptions.auto_disable import (
    SLACK_DISCONNECTED_DISABLE_REASON,
    SLACK_PERMISSION_REVOKED_DISABLE_REASON,
    DisableReason,
    disable_invalid_subscription,
)
from ee.tasks.subscriptions.slack_subscriptions import (
    UTM_TAGS_BASE,
    SlackDeliveryResult,
    SlackMessageData,
    get_slack_integration_for_team,
)

LOGGER = get_logger(__name__)

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


def render_markdown_email_html(markdown: str) -> str:
    rendered = _MARKDOWN_RENDERER.render(strip_external_links_markdown(markdown))
    return nh3.clean(rendered, tags=_ALLOWED_EMAIL_TAGS, attributes=_ALLOWED_EMAIL_ATTRS)


def split_text_into_slack_chunks(text: str, limit: int = SLACK_MRKDWN_SECTION_LIMIT) -> list[str]:
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


async def read_delivery_snapshot_value(delivery_id: uuid.UUID, key: str) -> str | None:
    @database_sync_to_async(thread_sensitive=False)
    def _read() -> str | None:
        # DoesNotExist is tolerated here (read side): a missing row just means "no content yet".
        try:
            snapshot = SubscriptionDelivery.objects.values_list("content_snapshot", flat=True).get(pk=delivery_id)
        except SubscriptionDelivery.DoesNotExist:
            return None
        if not isinstance(snapshot, dict):
            return None
        value = snapshot.get(key)
        return value if isinstance(value, str) and value else None

    return await _read()


# What content_snapshot values look like: markdown/id strings, or the AI diagnostics list.
SnapshotValue = str | list[dict[str, str | bool | None]]


async def write_delivery_snapshot_values(delivery_id: uuid.UUID, values: dict[str, SnapshotValue]) -> None:
    """Merge keys into a delivery's content_snapshot. Assumes single-writer execution: the
    activities for one delivery_id run sequentially within a single workflow, so this
    read-modify-write is never concurrent. Not safe to call from concurrent writers."""

    @database_sync_to_async(thread_sensitive=False)
    def _write() -> None:
        # No DoesNotExist guard: create_delivery_record always writes this row first,
        # so a missing row is a wiring bug — let it raise loudly.
        delivery = SubscriptionDelivery.objects.get(pk=delivery_id)
        delivery.content_snapshot = {**(delivery.content_snapshot or {}), **values}
        delivery.save(update_fields=["content_snapshot", "last_updated_at"])

    await _write()


def build_markdown_slack_message(
    subscription: Subscription,
    markdown: str,
    *,
    default_title: str,
    button_label: str,
    button_url: str,
    extra_blocks: list[dict] | None = None,
    integration: Integration | None = None,
) -> SlackMessageData:
    """Shared Slack layout for markdown-report subscriptions (AI reports, Pulse briefs):
    title, chunked body with thread overflow, one action button, caller-provided extra
    blocks (e.g. the AI feedback prompt), and the explore hint."""
    utm_tags = f"{UTM_TAGS_BASE}&utm_medium=slack"
    channel = subscription.target_value.split("|")[0]
    sections = split_text_into_slack_chunks(_SLACK_CONVERTER.convert(strip_external_links_markdown(markdown)))
    title = subscription.title or default_title
    first_section = sections[0] if sections else "_No report content was generated._"

    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": first_section}},
    ]
    if len(sections) > 1:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": "_See thread for the rest of the report._"}}
        )
    blocks.extend(
        [
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": button_label},
                        "url": f"{button_url}?{utm_tags}",
                    }
                ],
            },
        ]
    )
    blocks.extend(extra_blocks or [])
    # AI consent is enforced upstream before any markdown report is generated, so the hint always shows.
    if explore_hint := build_explore_hint(integration, utm_tags=utm_tags, ai_enabled=True):
        blocks.append(explore_hint)

    thread_messages = [
        {"blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": section}}]} for section in sections[1:]
    ]
    # unfurl=False: report content is LLM-generated; never let Slack auto-fetch a link it contains.
    return SlackMessageData(channel=channel, blocks=blocks, title=title, thread_messages=thread_messages, unfurl=False)


async def deliver_markdown_subscription(
    subscription: Subscription,
    inputs: DeliverSubscriptionInputs,
    recipient_results: list[RecipientResult],
    *,
    snapshot_key: str,
    kind_label: str,
    send_email: Callable[[str, str, str, uuid.UUID], Awaitable[None]],
    send_slack: Callable[[Integration, str, uuid.UUID], Awaitable[SlackDeliveryResult]],
) -> DeliverSubscriptionResult:
    """Ship a markdown report an earlier activity already persisted onto the delivery row
    (read back by `snapshot_key` — kept off the Temporal wire, ~2 MiB cap). Transient send
    errors retry; terminal Slack errors auto-disable. `send_email(email, markdown,
    delivery_run_id, delivery_id)` and `send_slack(integration, markdown, delivery_id)`
    carry the per-kind formatting."""
    if inputs.delivery_id is None:
        # The markdown workflows always create the delivery row and persist the report before
        # delivery, so a missing reference is a wiring bug, not a runtime state.
        raise ApplicationError(
            f"{kind_label} delivery for subscription {subscription.id} has no delivery_id", non_retryable=True
        )
    delivery_id = inputs.delivery_id

    markdown = await read_delivery_snapshot_value(delivery_id, snapshot_key)
    if markdown is None:
        # The report is persisted before delivery is scheduled; re-running *delivery* can't
        # regenerate it, so retrying just burns attempts — fail loud rather than ship empty.
        raise ApplicationError(
            f"{kind_label} report missing for subscription {subscription.id} (delivery {delivery_id})",
            non_retryable=True,
        )

    if subscription.target_type == Subscription.SubscriptionTarget.EMAIL:
        # Dedup key for MessagingRecord: stable across this run's retries, unique per run so a re-test re-sends.
        workflow_run_id = temporalio.activity.info().workflow_run_id
        if workflow_run_id is None:
            raise ApplicationError(f"{kind_label} email delivery requires a workflow run id", non_retryable=True)

        async def _send_one(email: str) -> None:
            await send_email(email, markdown, workflow_run_id, delivery_id)

        return await deliver_email(subscription, inputs, recipient_results, _send_one)
    if subscription.target_type == Subscription.SubscriptionTarget.SLACK:
        return await deliver_slack(
            subscription,
            recipient_results,
            lambda integration: send_slack(integration, markdown, delivery_id),
        )
    # `validate_subscription_for_delivery` auto-disables unsupported targets up front,
    # so reaching here means an invariant was violated.
    raise ApplicationError(
        f"{kind_label} delivery reached an unsupported target {subscription.target_type!r}", non_retryable=True
    )


async def auto_disable_and_return(
    subscription: Subscription,
    reason: DisableReason,
    recipient_results: list[RecipientResult],
) -> DeliverSubscriptionResult:
    """Permanent-failure exit path: record per-recipient failure, capture analytics,
    and auto-disable the subscription. Shared by the insight/dashboard and AI delivery paths."""
    recipient_results.append(
        RecipientResult(
            recipient=subscription.target_value,
            status="failed",
            error={"message": reason.description, "type": reason.key},
        )
    )
    # `_capture_delivery_failed_event` only reads `str(e)` and `type(e).__name__`,
    # so a plain Exception conveys the same info without implying retry semantics.
    _capture_delivery_failed_event(subscription, Exception(reason.description))
    await database_sync_to_async(disable_invalid_subscription, thread_sensitive=False)(subscription, reason)
    return DeliverSubscriptionResult(recipient_results=recipient_results)


async def deliver_email(
    subscription: Subscription,
    inputs: DeliverSubscriptionInputs,
    recipient_results: list[RecipientResult],
    send_one: Callable[[str], Awaitable[None]],
) -> DeliverSubscriptionResult:
    """Send to each recipient via `send_one`. Partial success is kept; only an all-failed run
    raises, so a Temporal retry won't re-send to recipients who already succeeded."""
    emails = list(dict.fromkeys(e.strip() for e in subscription.target_value.split(",") if e.strip()))
    if inputs.is_new_subscription_target and inputs.previous_value is not None:
        previous = {e.strip() for e in inputs.previous_value.split(",") if e.strip()}
        emails = [e for e in emails if e not in previous]

    await LOGGER.ainfo(
        "deliver_subscription.sending_email", subscription_id=subscription.id, recipient_count=len(emails)
    )

    success_count = 0
    last_error: Exception | None = None
    for email in emails:
        try:
            await send_one(email)
            recipient_results.append(RecipientResult(recipient=email, status="success", error=None))
            success_count += 1
        except Exception as exc:
            LOGGER.error(
                "deliver_subscription.email_failed",
                subscription_id=subscription.id,
                email=email,
                next_delivery_date=subscription.next_delivery_date,
                destination=subscription.target_type,
                exc_info=True,
            )
            capture_exception(exc)
            _capture_delivery_failed_event(subscription, exc)
            recipient_results.append(
                RecipientResult(
                    recipient=email, status="failed", error={"message": str(exc), "type": type(exc).__name__}
                )
            )
            last_error = exc

    await LOGGER.ainfo(
        "deliver_subscription.email_complete",
        subscription_id=subscription.id,
        success_count=success_count,
        total_count=len(emails),
    )

    if last_error is not None and success_count == 0:
        raise last_error
    return DeliverSubscriptionResult(recipient_results=recipient_results)


def _resolve_slack_integration(subscription: Subscription) -> Integration | None:
    integration = subscription.integration
    if integration is not None and integration.kind != "slack":
        LOGGER.warning(
            "deliver_subscription.invalid_integration_kind",
            subscription_id=subscription.id,
            integration_id=integration.id,
            kind=integration.kind,
        )
        integration = None
    if integration is None:
        integration = get_slack_integration_for_team(subscription.team_id)
    return integration


async def deliver_slack(
    subscription: Subscription,
    recipient_results: list[RecipientResult],
    send: Callable[[Integration], Awaitable[SlackDeliveryResult]],
) -> DeliverSubscriptionResult:
    """A missing integration or a permanent Slack config error auto-disables the subscription;
    transient Slack errors raise so Temporal retries."""
    integration = await database_sync_to_async(_resolve_slack_integration, thread_sensitive=False)(subscription)
    if integration is None:
        LOGGER.warning("deliver_subscription.no_slack_integration", subscription_id=subscription.id)
        return await auto_disable_and_return(subscription, SLACK_DISCONNECTED_DISABLE_REASON, recipient_results)

    LOGGER.info("deliver_subscription.sending_slack_message", subscription_id=subscription.id)
    try:
        result = await send(integration)
    except ApplicationError:
        raise
    except Exception as exc:
        slack_error_code = exc.response.get("error") if isinstance(exc, SlackApiError) else None
        _capture_delivery_failed_event(subscription, exc)
        LOGGER.error(
            "deliver_subscription.slack_failed",
            subscription_id=subscription.id,
            slack_error=slack_error_code,
            next_delivery_date=subscription.next_delivery_date,
            destination=subscription.target_type,
            exc_info=True,
        )
        capture_exception(exc)
        if slack_error_code in SLACK_USER_CONFIG_ERRORS:
            # Won't self-heal without user action — auto-disable so it stops re-firing.
            return await auto_disable_and_return(
                subscription, SLACK_PERMISSION_REVOKED_DISABLE_REASON, recipient_results
            )
        raise  # Transient Slack errors — let Temporal retry

    if result.is_complete_success:
        await LOGGER.ainfo("deliver_subscription.slack_sent", subscription_id=subscription.id)
        recipient_results.append(RecipientResult(recipient=subscription.target_value, status="success", error=None))
    elif result.is_partial_failure:
        await LOGGER.awarning(
            "deliver_subscription.slack_partial_failure",
            subscription_id=subscription.id,
            failed_thread_count=len(result.failed_thread_message_indices),
            total_thread_count=result.total_thread_messages,
        )
        recipient_results.append(
            RecipientResult(
                recipient=subscription.target_value,
                status="partial",
                error={
                    "message": f"{len(result.failed_thread_message_indices)} thread message(s) failed",
                    "type": "partial_thread_failure",
                },
            )
        )
    return DeliverSubscriptionResult(recipient_results=recipient_results)
