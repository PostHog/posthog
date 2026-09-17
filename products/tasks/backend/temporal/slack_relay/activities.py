import re
from collections.abc import Callable
from typing import Any

from temporalio import activity

from posthog.dataclasses import frozen
from posthog.helpers.slack_markdown import SLACK_MARKDOWN_TEXT_MAX_LEN, opens_with_line_anchored_markdown
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.logic.services.living_artifacts import (
    deliver_pending_slack_file_artifacts,
    has_pending_slack_file_artifacts,
    has_pending_slack_image_artifacts,
)

logger = get_logger(__name__)

_RE_DELIVERY_CLAIM = re.compile(r"\b(?:attached|uploaded|shared)\b", re.IGNORECASE)
_RE_DELIVERY_NEGATION = re.compile(
    r"\b(?:not|never|cannot|can't|could not|couldn't|unable to|no file was)\s+"
    r"(?:actually\s+)?(?:be\s+)?(?:attached|uploaded|shared)\b",
    re.IGNORECASE,
)
_RE_LOCAL_DELIVERABLE_REFERENCE = re.compile(
    r"(?:/tmp/workspace/|\b(?:report|pdf|spreadsheet|document|file)\b|\.(?:pdf|xlsx|csv|docx|txt|md|html)\b)",
    re.IGNORECASE,
)
_UNCONFIRMED_ATTACHMENT_NOTICE = "\n\n_Note: I can relay text here, but no file was attached to Slack for this run._"


class _RelayAlreadyRecorded(Exception):
    """Raised when a relay was already recorded while holding the row lock."""


def _append_unconfirmed_attachment_notice(
    text: str,
    *,
    origin_product: str | None,
) -> str:
    if origin_product != "slack":
        return text

    normalized = " ".join(text.split())
    if _RE_DELIVERY_NEGATION.search(normalized):
        return text
    if not _RE_DELIVERY_CLAIM.search(normalized):
        return text
    if not _RE_LOCAL_DELIVERABLE_REFERENCE.search(normalized):
        return text

    return f"{text.rstrip()}{_UNCONFIRMED_ATTACHMENT_NOTICE}"


_FENCED_CODE_RE = re.compile(r"```([^\n]*)\n([\s\S]*?)\n```")


class _SlackChunkPacker:
    """Packs markdown into chunks of at most ``limit`` characters."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._chunks: list[str] = []
        self._current = ""

    def _try_append(self, atom: str, joiner: str) -> bool:
        """Add ``atom`` to the open chunk, or report that it does not fit."""
        if len(self._current) + len(joiner) + len(atom) > self._limit:
            return False
        self._current = self._current + joiner + atom
        return True

    def _flush(self) -> None:
        stripped = self._current.rstrip()
        if stripped:
            self._chunks.append(stripped)
        self._current = ""

    def _append_atom(self, atom: str, separator: str) -> None:
        """Append ``atom``, starting a new chunk first if it would overflow the open one."""
        if self._try_append(atom, separator if self._current else ""):
            return
        self._flush()
        self._current = atom

    def _split_long_line(self, line: str) -> None:
        """Hard-split a single line that is itself longer than the limit."""
        remaining = line
        while len(remaining) > self._limit:
            self._flush()
            self._chunks.append(remaining[: self._limit])
            remaining = remaining[self._limit :]
        if remaining:
            self._append_atom(remaining, "\n")

    def _pack(self, body: str, separator: str, overflow: Callable[[str], None]) -> None:
        """Pack the parts of ``body``, sending a part that alone overflows to ``overflow``."""
        # The joiner rule here differs from _append_atom's: on a part after the first it
        # keeps the separator even when the open chunk is empty, where _append_atom drops
        # it. The two are not interchangeable, because merging them changes which
        # characters start a chunk.
        for index, atom in enumerate(body.split(separator)):
            joiner = separator if index > 0 or self._current else ""
            if self._try_append(atom, joiner):
                continue
            if len(atom) <= self._limit:
                self._append_atom(atom, separator)
            else:
                overflow(atom)

    def _pack_lines(self, paragraph: str) -> None:
        self._pack(paragraph, "\n", self._split_long_line)

    def _add_text(self, body: str) -> None:
        self._pack(body, "\n\n", self._pack_lines)

    def _add_fenced_chunks(self, body: str, *, fence_open: str, fence_close: str) -> None:
        """Spread a code body too long for one chunk over several, each one fully fenced.

        Every chunk repeats the fence pair, so it comes out of that chunk's own budget.
        A break lands on a line boundary when one falls inside the remaining room.
        """
        room = max(1, self._limit - len(fence_open) - len(fence_close))
        cursor = 0
        while cursor < len(body):
            end = min(cursor + room, len(body))
            if end < len(body):
                newline = body.rfind("\n", cursor, end)
                if newline > cursor:
                    end = newline
            self._chunks.append(f"{fence_open}{body[cursor:end]}{fence_close}")
            cursor = end + 1 if end < len(body) and body[end] == "\n" else end

    def _add_code_block(self, language: str, body: str) -> None:
        fence_open = f"```{language}\n" if language else "```\n"
        fence_close = "\n```"
        if len(fence_open) + len(body) + len(fence_close) <= self._limit:
            self._append_atom(f"{fence_open}{body}{fence_close}", "\n\n")
            return
        self._flush()
        self._add_fenced_chunks(body, fence_open=fence_open, fence_close=fence_close)

    def add_markdown(self, text: str) -> None:
        """Pack ``text``, keeping every fenced code block apart from the prose around it."""
        pos = 0
        for match in _FENCED_CODE_RE.finditer(text):
            if match.start() > pos:
                self._add_text(text[pos : match.start()])
            self._add_code_block(match.group(1), match.group(2))
            pos = match.end()
        if pos < len(text):
            self._add_text(text[pos:])

    def finish(self) -> list[str]:
        self._flush()
        return self._chunks


def _split_markdown_for_slack(text: str, limit: int) -> list[str]:
    """Split raw markdown into Slack-sized chunks at safe structural boundaries.

    Splits prefer paragraph (``\\n\\n``) and line (``\\n``) boundaries, then a hard
    character break as a last resort. Fenced code blocks that cross a chunk
    boundary are closed at the end of one chunk and reopened (with the same
    language hint) at the start of the next so each chunk is a self-contained
    markdown document.
    """
    if len(text) <= limit:
        return [text]

    packer = _SlackChunkPacker(limit)
    packer.add_markdown(text)
    return packer.finish()


@frozen
class RelaySlackMessageInput:
    run_id: str
    relay_id: str
    text: str
    user_message_ts: str | None = None
    delete_progress: bool = True
    reaction_emoji: str | None = None
    # Id of the user message this relay answers (agent-server echo), used to
    # tag the exact sender; None falls back to the run-state/mapping actors.
    message_id: str | None = None
    # Gateway trace id of the turn that produced this answer. Trailing and defaulted so a
    # relay enqueued before this field existed still decodes.
    trace_id: str | None = None


@activity.defn
@close_db_connections
def relay_slack_message(input: RelaySlackMessageInput) -> None:
    from products.slack_app.backend.models import SlackThreadTaskMapping
    from products.slack_app.backend.services.slack_messages import (
        load_run_footer,
        normalize_labeled_mentions_to_bare,
        strip_object_tags,
    )
    from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler
    from products.tasks.backend.models import TaskRun
    from products.tasks.backend.temporal.process_task.utils import get_message_actor

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

    # Rewrite echoed ``<@U…|name>`` tokens to the bare ``<@U…>`` so the mentions the agent
    # composed actually notify their targets. Done before splitting: the bare form is shorter,
    # so it never enlarges a chunk.
    text = normalize_labeled_mentions_to_bare(strip_object_tags(text)).strip()

    # Living-artifacts gating lives in the service: has_pending_slack_file_artifacts
    # (and deliver_pending_slack_file_artifacts below) return falsy when the
    # workspace's living-artifacts flag is off. Run-manifest artifacts are internal
    # and must never surface here — Slack delivery goes through living artifacts only.
    has_pending_slack_files = has_pending_slack_file_artifacts(task_run)
    if not has_pending_slack_files:
        text = _append_unconfirmed_attachment_notice(
            text,
            origin_product=mapping.task.origin_product,
        )

    context = SlackThreadContext(
        integration_id=mapping.integration_id,
        channel=mapping.channel,
        thread_ts=mapping.thread_ts,
        user_message_ts=input.user_message_ts,
        mentioning_slack_user_id=mapping.mentioning_slack_user_id,
    )
    # Mention resolution, most precise first: the echoed message's recorded
    # sender, then the live/mapping actors for pre-rollout runs. Resolved before the
    # handler so the footer's links are gated on whoever this reply is actually for.
    mention_from_message = get_message_actor(input.run_id, input.message_id) if input.message_id else None
    target = (
        mention_from_message
        or state.get("slack_actor_slack_user_id")
        or mapping.latest_actor_slack_user_id
        or mapping.mentioning_slack_user_id
    )

    handler = SlackThreadHandler(context, actor_slack_user_id=target, turn_trace_id=input.trace_id)
    handler.run_footer = load_run_footer(task_run.id)

    # The mention opens the answer, in the same line, so the reply reads as one message. An answer
    # that opens with a heading, a list, a quote, a table, or a fence is the exception: Markdown
    # reads those only at the start of a line, so a mention in front of one would turn it into
    # literal text. Those answers take the mention on a line of its own, which keeps the construct
    # intact and still notifies.
    mention_separator = "\n\n" if opens_with_line_anchored_markdown(text) else " "
    mention_prefix = f"<@{target}>{mention_separator}" if target else ""

    compose_with_charts = has_pending_slack_files and has_pending_slack_image_artifacts(task_run)

    # The mention rides on the first chunk, so it comes out of the same budget: without that
    # allowance the chunk it lands on overflows the block and posts as Markdown source.
    chunks = _split_markdown_for_slack(text, limit=SLACK_MARKDOWN_TEXT_MAX_LEN - len(mention_prefix)) if text else []

    def _record_sent_relay(state: dict[str, Any]) -> None:
        sent_relay_ids = state.get("slack_sent_relay_ids") or []
        if input.relay_id in sent_relay_ids:
            raise _RelayAlreadyRecorded

        sent_relay_ids.append(input.relay_id)
        # Keep a rolling window to bound state size while preserving idempotency for recent relays.
        state["slack_sent_relay_ids"] = sent_relay_ids[-30:]

    # Claim the relay before the first Slack call. The Slack posts below swallow their own
    # errors, so this write is the only step that can fail after a message is already in the
    # thread, and a retry would then post it again. Claiming first means a failed write retries
    # before anything is sent, and a retry after the claim skips instead of duplicating.
    try:
        TaskRun.mutate_state_atomic(input.run_id, _record_sent_relay)
    except _RelayAlreadyRecorded:
        logger.info("slack_relay_duplicate_skipped", run_id=input.run_id, relay_id=input.relay_id)
        return

    if input.delete_progress:
        handler.delete_progress()

    answer_posted = False
    if compose_with_charts:
        sections = list(chunks)
        if sections:
            sections[0] = f"{mention_prefix}{sections[0]}"
        answer_posted = deliver_pending_slack_file_artifacts(task_run, answer_sections=sections).answer_posted
        if answer_posted:
            # The answer went out inside the composed message, whose blocks are the text
            # sections and the chart cards, so the footer follows it as its own message.
            handler.post_footer()

    if not answer_posted:
        for index, chunk in enumerate(chunks):
            prefix = mention_prefix if index == 0 else ""
            # This relay carries one agent answer, split only to fit Slack's length cap, so
            # the last chunk is where the turn ends and the footer belongs.
            handler.post_thread_message(f"{prefix}{chunk}", with_footer=index == len(chunks) - 1, markdown=True)
        if has_pending_slack_files and not compose_with_charts:
            deliver_pending_slack_file_artifacts(task_run)

    if input.reaction_emoji is not None:
        handler.update_reaction(input.reaction_emoji)
