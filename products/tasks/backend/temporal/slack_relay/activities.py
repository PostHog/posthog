import re
from dataclasses import dataclass
from typing import Any

from markdown_to_mrkdwn import SlackMarkdownConverter
from temporalio import activity

from posthog.temporal.common.logger import get_logger

logger = get_logger(__name__)

_CONVERTER = SlackMarkdownConverter()

_RE_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_RE_TABLE_SEPARATOR_CELL = re.compile(r"^:?-{2,}:?$")
_RE_FENCE = re.compile(r"^\s*(```|~~~)")
_RE_INLINE_MARKDOWN_MARKERS = re.compile(r"\*\*|__|\*|_|~~|`")
_RE_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


class _RelayAlreadyRecorded(Exception):
    """Raised when a relay was already recorded while holding the row lock."""


def _markdown_to_slack_mrkdwn(text: str) -> str:
    """Convert markdown to Slack ``mrkdwn`` via ``markdown_to_mrkdwn``.

    Tables are pre-converted to fenced code blocks before the library runs because
    Slack ``mrkdwn`` is rendered in a proportional font — pipe-separated rows do
    not line up. A fenced code block forces monospace and the columns align.
    """
    if not text:
        return text
    return _CONVERTER.convert(_tables_to_fenced_code_blocks(text))


def _tables_to_fenced_code_blocks(text: str) -> str:
    """Replace pipe-syntax markdown tables with fenced code blocks of padded columns.

    A run of consecutive ``|…|`` lines surrounding a ``---`` separator row is
    treated as a table; runs without a separator are left untouched. Lines inside
    an existing fenced code block are skipped entirely so we don't mis-detect a
    pipe-shaped line of source code as a table.
    """
    lines = text.split("\n")
    out: list[str] = []
    run: list[str] = []
    in_fence = False

    def _flush() -> None:
        if not run:
            return
        rendered = _render_table(run)
        out.extend(run if rendered is None else [rendered])
        run.clear()

    for line in lines:
        if _RE_FENCE.match(line):
            _flush()
            in_fence = not in_fence
            out.append(line)
            continue
        if not in_fence and _RE_TABLE_ROW.match(line):
            run.append(line)
        else:
            _flush()
            out.append(line)
    _flush()

    return "\n".join(out)


def _render_table(rows_raw: list[str]) -> str | None:
    """Render a candidate table block to a fenced code block, or ``None`` if invalid.

    A separator row of all-dashes cells (``---``, ``:---:``) is required — without
    it the pipes are likely incidental rather than a table.
    """
    parsed: list[list[str]] = []
    has_separator = False
    for line in rows_raw:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and all(_RE_TABLE_SEPARATOR_CELL.match(c) for c in cells):
            has_separator = True
            continue
        parsed.append([_strip_inline_markdown(c) for c in cells])

    if not has_separator or not parsed:
        return None

    col_count = max(len(r) for r in parsed)
    widths = [0] * col_count
    for row in parsed:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    body_lines = [
        "  ".join((row[i] if i < len(row) else "").ljust(widths[i]) for i in range(col_count)).rstrip()
        for row in parsed
    ]
    return "```\n" + "\n".join(body_lines) + "\n```"


def _strip_inline_markdown(cell: str) -> str:
    """Strip emphasis markers and unwrap links inside a cell.

    The cell ends up inside a fenced code block where ``*bold*`` and ``[text](url)``
    are not interpreted, so leaving the markers in just shifts column widths and
    adds visual noise.
    """
    cell = _RE_MD_LINK.sub(r"\1", cell)
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
