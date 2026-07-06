import re
from dataclasses import dataclass
from typing import Any

from markdown_to_mrkdwn import SlackMarkdownConverter
from temporalio import activity

from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import close_db_connections

logger = get_logger(__name__)

_CONVERTER = SlackMarkdownConverter()

_RE_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_RE_TABLE_SEPARATOR_CELL = re.compile(r"^:?-{2,}:?$")
_RE_FENCE = re.compile(r"^\s*(```|~~~)")
_RE_INLINE_MARKDOWN_MARKERS = re.compile(r"\*\*|__|\*|_|~~|`")
_RE_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

# Repair pattern: bold/italic markers placed *inside* the close of a Slack-style
# angle-bracket link, e.g. ``**<https://example.com**>`` instead of
# ``**<https://example.com>**``. The agent hand-rolls Slack mrkdwn occasionally
# and types the closing marker before ``>``; the standard converter has no way
# to recover, so the asterisks end up adjacent to ``>`` in the final output and
# Slack renders neither the bold nor the link. The flanking lookbehind/lookahead
# require the opening and closing marker runs to be balanced — they refuse to
# half-match a longer asterisk run, so unbalanced edge cases like ``**<url*>``
# are left alone rather than silently rewritten into a different broken shape.
_RE_LINK_TRAILING_MARKER = re.compile(r"(?<![*_~])(\*+|_+|~+)<([^<>]+?)\1>(?![*_~])")

# Repair pattern: a bare ``http(s)`` URL wrapped directly in emphasis markers,
# e.g. ``**https://example.com**``. The converter halves the markers in place
# and emits ``*https://example.com*``; Slack then auto-links the URL but
# renders the surrounding ``*`` as literal text because there is no whitespace
# flanking the markers. Pre-wrapping the URL in ``<>`` lets the converter emit
# the well-formed ``*<https://example.com>*`` — a clean bolded clickable link.
# The URL group excludes whitespace and angle brackets so already well-formed
# links (``**<url>**``) and bracketed markdown links (``**[text](url)**``) are
# left alone.
_RE_BARE_URL_IN_EMPHASIS = re.compile(r"(?<![*_~])(\*+|_+|~+)(https?://[^\s<>]+?)\1(?![*_~])")


class _RelayAlreadyRecorded(Exception):
    """Raised when a relay was already recorded while holding the row lock."""


def _markdown_to_slack_mrkdwn(text: str) -> str:
    """Convert markdown to Slack ``mrkdwn`` via ``markdown_to_mrkdwn``.

    Tables are pre-converted to fenced code blocks before the library runs because
    Slack ``mrkdwn`` is rendered in a proportional font — pipe-separated rows do
    not line up. A fenced code block forces monospace and the columns align.

    Misplaced link markers (e.g. ``**<url**>``) and bare URLs wrapped in
    emphasis (e.g. ``**https://example.com**``) are normalized first so the
    converter sees well-formed input.
    """
    if not text:
        return text
    repaired = _wrap_bare_urls_in_emphasis(_repair_link_trailing_markers(text))
    return _CONVERTER.convert(_tables_to_fenced_code_blocks(repaired))


def _repair_link_trailing_markers(text: str) -> str:
    """Move emphasis markers from inside a Slack-style link close to outside.

    Handles ``**<url**>``/``*<url*>``/``_<url_>`` (and the ``<url|label>``
    variants) by relocating the closing marker after ``>``. The negated
    character class stops the match at the next ``<`` or ``>``, so adjacent
    links don't cross-contaminate.
    """
    return _RE_LINK_TRAILING_MARKER.sub(r"\1<\2>\1", text)


def _wrap_bare_urls_in_emphasis(text: str) -> str:
    """Wrap bare ``http(s)`` URLs adjacent to emphasis markers with angle brackets.

    ``**https://example.com**`` becomes ``**<https://example.com>**`` so the
    downstream converter produces a properly formatted Slack link. Already
    bracketed URLs (``**<url>**``) and markdown links (``**[label](url)**``)
    are left untouched because the URL group rejects ``<`` and ``[``.
    """
    return _RE_BARE_URL_IN_EMPHASIS.sub(r"\1<\2>\1", text)


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
@close_db_connections
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

    target = mapping.latest_actor_slack_user_id or mapping.mentioning_slack_user_id
    mention_prefix = f"<@{target}> " if target else ""
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
