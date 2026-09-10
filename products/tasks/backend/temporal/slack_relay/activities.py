import re
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
from products.tasks.backend.temporal.slack_relay.object_tags import rewrite_object_tags_for_slack

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
    markdown document. A hard char break inside an inline span like ``**bold**``
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
        project_web_url,
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
    # composed actually notify their targets. Done before splitting/conversion: the bare form
    # is shorter (never enlarges a chunk) and the mrkdwn converter passes it through untouched.
    text = normalize_labeled_mentions_to_bare(text)

    # Object tags (``<insight id="…">``, ``<hogql display="block">``) are what the desktop renders
    # as chips and chart cards; Slack would show them as escaped XML. Rewritten to links and
    # fenced SQL before splitting so chunk sizes account for the markdown they become.
    text = rewrite_object_tags_for_slack(text, project_url=project_web_url(task_run.team_id))

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

    # Pending chart images compose into a single Slack message together with the answer text.
    compose_with_charts = has_pending_slack_files and has_pending_slack_image_artifacts(task_run)

    # One `markdown` block per message whether or not charts compose into it, so composing
    # costs the answer nothing. The mention rides on the first chunk, so it comes out of the
    # same budget: without that the chunk it lands on overflows the block and posts as
    # Markdown source. A `markdown` block takes the agent's Markdown as written, so the
    # chunks go out unconverted.
    chunks = _split_markdown_for_slack(text, limit=SLACK_MARKDOWN_TEXT_MAX_LEN - len(mention_prefix))

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
        answer_posted = deliver_pending_slack_file_artifacts(
            task_run, answer_sections=sections, answer_is_markdown=True
        ).answer_posted
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
