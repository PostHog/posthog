import re
from dataclasses import dataclass
from typing import Any

from temporalio import activity

from posthog.temporal.common.logger import get_logger

logger = get_logger(__name__)


class _RelayAlreadyRecorded(Exception):
    """Raised when a relay was already recorded while holding the row lock."""


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


# Slack renders text above ~4000 characters as a "Show more" affordance and silently truncates;
# splitting at 3500 leaves comfortable headroom for the mention prefix and code-fence overhead.
SLACK_MESSAGE_TEXT_LIMIT = 3500

_FENCED_CODE_RE = re.compile(r"```([^\n]*)\n([\s\S]*?)\n```")


def _split_markdown_for_slack(text: str, limit: int = SLACK_MESSAGE_TEXT_LIMIT) -> list[str]:
    """Split raw markdown into Slack-sized chunks at safe structural boundaries.

    Splits prefer paragraph (``\\n\\n``) and line (``\\n``) boundaries, then a hard
    character break as a last resort. Fenced code blocks that cross a chunk
    boundary are closed at the end of one chunk and reopened (with the same
    language hint) at the start of the next so each chunk is a self-contained
    markdown document. Callers convert each chunk to Slack mrkdwn independently;
    that ordering means a hard char break inside an inline span like ``**bold**``
    or ``[text](url)`` leaves the broken halves as literal text rather than
    producing dangling unbalanced markers in the rendered output.
    """
    if len(text) <= limit:
        return [text]

    segments: list[tuple[str, str, str]] = []
    pos = 0
    for match in _FENCED_CODE_RE.finditer(text):
        if match.start() > pos:
            segments.append(("text", "", text[pos : match.start()]))
        segments.append(("code", match.group(1), match.group(2)))
        pos = match.end()
    if pos < len(text):
        segments.append(("text", "", text[pos:]))

    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        stripped = current.rstrip()
        if stripped:
            chunks.append(stripped)
        current = ""

    def append_atom(atom: str, separator: str = "") -> None:
        """Append ``atom`` to the current chunk, flushing first if it would overflow."""
        nonlocal current
        candidate = current + (separator if current else "") + atom
        if len(candidate) <= limit:
            current = candidate
            return
        flush()
        current = atom

    def split_long_line(line: str) -> None:
        """Hard-split a single line that is itself longer than the limit."""
        nonlocal current
        remaining = line
        while len(remaining) > limit:
            flush()
            chunks.append(remaining[:limit])
            remaining = remaining[limit:]
        if remaining:
            append_atom(remaining, separator="\n")

    for kind, lang, body in segments:
        if kind == "text":
            for paragraph_index, paragraph in enumerate(body.split("\n\n")):
                separator = "\n\n" if paragraph_index > 0 or current else ""
                if len(current) + len(separator) + len(paragraph) <= limit:
                    current = current + separator + paragraph
                    continue
                if len(paragraph) <= limit:
                    append_atom(paragraph, separator="\n\n")
                    continue
                # Paragraph alone overflows — fall back to per-line packing.
                for line_index, line in enumerate(paragraph.split("\n")):
                    sep = "\n" if line_index > 0 or current else ""
                    if len(current) + len(sep) + len(line) <= limit:
                        current = current + sep + line
                    elif len(line) <= limit:
                        append_atom(line, separator="\n")
                    else:
                        split_long_line(line)
            continue

        fence_open = f"```{lang}\n" if lang else "```\n"
        fence_close = "\n```"
        full_block = f"{fence_open}{body}{fence_close}"
        if len(full_block) <= limit:
            append_atom(full_block, separator="\n\n")
            continue
        # Block itself overflows — emit it across multiple fenced chunks, line-aligned.
        flush()
        overhead = len(fence_open) + len(fence_close)
        room = max(1, limit - overhead)
        cursor = 0
        while cursor < len(body):
            end = min(cursor + room, len(body))
            if end < len(body):
                newline = body.rfind("\n", cursor, end)
                if newline > cursor:
                    end = newline
            chunks.append(f"{fence_open}{body[cursor:end]}{fence_close}")
            cursor = end + 1 if end < len(body) and body[end] == "\n" else end

    flush()
    return chunks


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

    # Split the raw markdown first, then convert each chunk independently. Converting
    # per-chunk means an inline span broken by a hard char split (e.g. ``**bold**``
    # halved) stays literal in the output instead of leaving dangling Slack-mrkdwn
    # markers that would garble the rendering of surrounding text.
    chunks = [_markdown_to_slack_mrkdwn(chunk) for chunk in _split_markdown_for_slack(text)]

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
    for index, chunk in enumerate(chunks):
        prefix = mention_prefix if index == 0 else ""
        handler.post_thread_message(f"{prefix}{chunk}")
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
