import re
from dataclasses import dataclass
from typing import Any

from markdown_to_mrkdwn import SlackMarkdownConverter
from temporalio import activity

from posthog.temporal.common.logger import get_logger

logger = get_logger(__name__)

_RE_FENCED_CODE = re.compile(r"(?:^|\n)(```[\s\S]*?\n```|~~~[\s\S]*?\n~~~)", re.MULTILINE)
_RE_INLINE_CODE = re.compile(r"`[^`\n]+`")
_RE_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_RE_TABLE_SEPARATOR_CELL = re.compile(r"^:?-{2,}:?$")
_RE_INLINE_MARKDOWN_MARKERS = re.compile(r"(\*\*|__|\*|_|~~|`)")
_RE_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_RE_STASH_PLACEHOLDER = re.compile(r"\x00CODE(\d+)\x00")

_CONVERTER = SlackMarkdownConverter()


class _RelayAlreadyRecorded(Exception):
    """Raised when a relay was already recorded while holding the row lock."""


def _markdown_to_slack_mrkdwn(text: str) -> str:
    """Convert standard markdown to Slack ``mrkdwn``.

    Strategy:

    1. Stash fenced and inline code blocks so nothing inside them is touched.
    2. Pre-convert pipe-syntax tables into fenced code blocks. Slack renders fenced
       code in monospace, which is the only way columns line up — proportional-font
       ``mrkdwn`` cannot align spaces.
    3. Delegate the rest (bold, italic, lists, headers, links, task lists, hr,
       blockquotes) to ``markdown_to_mrkdwn.SlackMarkdownConverter``.
    4. Restore the stashed code blocks verbatim.
    """
    if not text:
        return text

    stashed: list[str] = []

    def _stash(match: re.Match) -> str:
        prefix = "\n" if match.group(0).startswith("\n") else ""
        stashed.append(match.group(1) if match.lastindex else match.group(0))
        return f"{prefix}\x00CODE{len(stashed) - 1}\x00"

    text = _RE_FENCED_CODE.sub(_stash, text)
    text = _RE_INLINE_CODE.sub(_stash, text)

    text = _tables_to_fenced_code_blocks(text)

    text = _CONVERTER.convert(text)

    def _restore(match: re.Match) -> str:
        return stashed[int(match.group(1))]

    return _RE_STASH_PLACEHOLDER.sub(_restore, text)


def _tables_to_fenced_code_blocks(text: str) -> str:
    """Replace pipe-syntax markdown tables with fenced code blocks of padded columns.

    A run of consecutive ``|…|`` lines surrounding a separator row (``|---|---|``) is
    treated as a table. Inline markdown markers inside cells are stripped before
    width calculation so the rendered column widths reflect what readers see.
    """
    lines = text.split("\n")
    out: list[str] = []
    run: list[str] = []

    def _flush() -> None:
        if not run:
            return
        rendered = _render_table(run)
        if rendered is None:
            out.extend(run)
        else:
            out.append(rendered)
        run.clear()

    for line in lines:
        if _RE_TABLE_ROW.match(line):
            run.append(line)
        else:
            _flush()
            out.append(line)
    _flush()

    return "\n".join(out)


def _render_table(rows_raw: list[str]) -> str | None:
    """Render a candidate table block to a fenced code block, or ``None`` if invalid.

    A valid table needs at least one separator row whose cells are all dashes
    (``---``, ``:---:``, etc.). Without it we leave the rows alone — they are most
    likely incidental pipe characters, not a table.
    """
    parsed: list[list[str]] = []
    has_separator = False
    for line in rows_raw:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and all(_RE_TABLE_SEPARATOR_CELL.match(c) for c in cells):
            has_separator = True
            continue
        parsed.append(cells)

    if not has_separator or not parsed:
        return None

    rendered_cells = [[_strip_inline_markdown(c) for c in row] for row in parsed]

    col_count = max(len(r) for r in rendered_cells)
    widths = [0] * col_count
    for row in rendered_cells:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    lines: list[str] = []
    for row in rendered_cells:
        padded = [(row[i] if i < len(row) else "").ljust(widths[i]) for i in range(col_count)]
        lines.append("  ".join(padded).rstrip())

    return "```\n" + "\n".join(lines) + "\n```"


def _strip_inline_markdown(cell: str) -> str:
    """Strip markdown emphasis markers from a table cell and unwrap links to their label.

    Tables are rendered inside a fenced code block where ``*bold*``/``_italic_`` are
    not interpreted; leaving the markers in would shift column widths and make the
    output noisier than the source.
    """
    cell = _RE_LINK.sub(r"\1", cell)
    cell = _RE_INLINE_MARKDOWN_MARKERS.sub("", cell)
    return cell.strip()


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
