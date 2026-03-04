import re
from dataclasses import dataclass

from django.db import transaction

from temporalio import activity

from posthog.temporal.common.logger import get_logger

logger = get_logger(__name__)


def _markdown_to_slack_mrkdwn(text: str) -> str:
    """Convert markdown to Slack mrkdwn format.

    Handles the most common differences while preserving code blocks.
    """
    # Preserve code blocks from transformation
    code_blocks: list[str] = []

    def _stash_code_block(match: re.Match) -> str:
        code_blocks.append(match.group(0))
        return f"\x00CODE{len(code_blocks) - 1}\x00"

    text = re.sub(r"```[\s\S]*?```", _stash_code_block, text)
    text = re.sub(r"`[^`]+`", _stash_code_block, text)

    # Markdown tables → plain text columns
    text = _convert_tables(text)

    # Headers → bold (### Header → *Header*)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)

    # Bold: **text** → *text* (but not inside already-converted bold)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)

    # Strikethrough: ~~text~~ → ~text~
    text = re.sub(r"~~(.+?)~~", r"~\1~", text)

    # Images before links since ![...] is more specific than [...]
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"<\2|\1>", text)

    # Links: [text](url) → <url|text>
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<\2|\1>", text)

    # Restore code blocks
    for i, block in enumerate(code_blocks):
        text = text.replace(f"\x00CODE{i}\x00", block)

    return text


def _convert_tables(text: str) -> str:
    """Convert markdown tables to aligned plain-text columns."""
    lines = text.split("\n")
    result: list[str] = []
    table_lines: list[str] = []

    def _flush_table() -> None:
        if not table_lines:
            return
        rows: list[list[str]] = []
        for line in table_lines:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            # Skip separator rows (----, :---:, etc.)
            if all(re.match(r"^:?-+:?$", c) for c in cells):
                continue
            rows.append(cells)
        if not rows:
            table_lines.clear()
            return
        # Calculate column widths
        col_count = max(len(r) for r in rows)
        widths = [0] * col_count
        for row in rows:
            for i, cell in enumerate(row):
                if i < col_count:
                    widths[i] = max(widths[i], len(cell))
        for row in rows:
            padded = []
            for i in range(col_count):
                cell = row[i] if i < len(row) else ""
                padded.append(cell.ljust(widths[i]))
            result.append("  ".join(padded).rstrip())
        table_lines.clear()

    for line in lines:
        stripped = line.strip()
        if re.match(r"^\|.*\|$", stripped):
            table_lines.append(stripped)
        else:
            _flush_table()
            result.append(line)
    _flush_table()

    return "\n".join(result)


@dataclass
class RelaySlackMessageInput:
    run_id: str
    relay_id: str
    text: str
    user_message_ts: str | None = None
    delete_progress: bool = True
    reaction_emoji: str = "white_check_mark"


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
    handler.update_reaction(input.reaction_emoji)

    with transaction.atomic():
        locked_task_run = TaskRun.objects.select_for_update().get(id=input.run_id)
        locked_state = locked_task_run.state or {}
        sent_relay_ids = locked_state.get("slack_sent_relay_ids") or []
        if input.relay_id in sent_relay_ids:
            return

        sent_relay_ids.append(input.relay_id)
        # Keep a rolling window to bound state size while preserving idempotency for recent relays.
        locked_state["slack_sent_relay_ids"] = sent_relay_ids[-30:]
        locked_task_run.state = locked_state
        locked_task_run.save(update_fields=["state", "updated_at"])
