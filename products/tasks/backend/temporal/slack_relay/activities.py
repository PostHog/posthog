from dataclasses import dataclass
from typing import Any

from markdown_to_mrkdwn import SlackMarkdownConverter
from temporalio import activity

from posthog.temporal.common.logger import get_logger

logger = get_logger(__name__)

_CONVERTER = SlackMarkdownConverter()


class _RelayAlreadyRecorded(Exception):
    """Raised when a relay was already recorded while holding the row lock."""


def _markdown_to_slack_mrkdwn(text: str) -> str:
    return _CONVERTER.convert(text) if text else text


@dataclass
class RelaySlackMessageInput:
    run_id: str
    relay_id: str
    text: str
    user_message_ts: str | None = None
    delete_progress: bool = True
    reaction_emoji: str | None = None


@activity.defn
def relay_slack_message(input: RelaySlackMessageInput) -> None:
    from products.slack_app.backend.models import SlackThreadTaskMapping
    from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler
    from products.tasks.backend.models import TaskRun

    try:
        task_run = TaskRun.objects.get(id=input.run_id)
    except TaskRun.DoesNotExist:
        logger.warning("slack_relay_run_not_found", run_id=input.run_id, relay_id=input.relay_id)
        return

    state = task_run.state or {}
    sent_relay_ids = state.get("slack_sent_relay_ids") or []
    if input.relay_id in sent_relay_ids:
        logger.info("slack_relay_duplicate_skipped", run_id=input.run_id, relay_id=input.relay_id)
        return

    mapping = SlackThreadTaskMapping.objects.filter(task_run=task_run).first()
    if mapping is None:
        logger.info("slack_relay_mapping_not_found", run_id=input.run_id, relay_id=input.relay_id)
        return

    text = (input.text or "").strip()
    if not text:
        logger.info("slack_relay_empty_text", run_id=input.run_id, relay_id=input.relay_id)
        return

    text = _markdown_to_slack_mrkdwn(text)

    SLACK_MESSAGE_TEXT_LIMIT = 3900
    if len(text) > SLACK_MESSAGE_TEXT_LIMIT:
        text = f"{text[: SLACK_MESSAGE_TEXT_LIMIT - 3]}..."

    context = SlackThreadContext(
        integration_id=mapping.integration_id,
        channel=mapping.channel,
        thread_ts=mapping.thread_ts,
        user_message_ts=input.user_message_ts,
        mentioning_slack_user_id=mapping.mentioning_slack_user_id,
    )
    handler = SlackThreadHandler(context)

    mention_prefix = f"<@{mapping.mentioning_slack_user_id}> " if mapping.mentioning_slack_user_id else ""
    if input.delete_progress:
        handler.delete_progress()
    handler.post_thread_message(f"{mention_prefix}{text}")
    if input.reaction_emoji is not None:
        handler.update_reaction(input.reaction_emoji)

    def _record_sent_relay(state: dict[str, Any]) -> None:
        sent_relay_ids = state.get("slack_sent_relay_ids") or []
        if input.relay_id in sent_relay_ids:
            raise _RelayAlreadyRecorded

        sent_relay_ids.append(input.relay_id)
        # Keep a rolling window to bound state size while preserving idempotency for recent relays.
        state["slack_sent_relay_ids"] = sent_relay_ids[-30:]

    try:
        TaskRun.mutate_state_atomic(input.run_id, _record_sent_relay)
    except _RelayAlreadyRecorded:
        logger.info("slack_relay_duplicate_skipped", run_id=input.run_id, relay_id=input.relay_id)
