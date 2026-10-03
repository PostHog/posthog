import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration, SlackIntegration
from posthog.slack.markdown import SLACK_MARKDOWN_TEXT_MAX_LEN, slack_markdown_block

from products.slack_app.backend.feature_flags import is_slack_app_forking_enabled
from products.slack_app.backend.services.slack_messages import (
    RunFooter,
    app_home_url,
    context_block,
    fork_menu_actions_block,
    fork_menu_element,
    leading_mention_prefix,
    load_run_footer,
    normalize_labeled_mentions_to_bare,
    personal_integrations_url,
    post_slack_thread_reply,
    project_web_url,
    reply_footer_block,
    run_context_block,
    slack_message_exists,
    turn_feedback_block,
)

if TYPE_CHECKING:
    from products.slack_app.backend.models import SlackThreadTaskMapping

logger = structlog.get_logger(__name__)

PROGRESS_MESSAGE_MARKER = "Working on task..."
UPSTREAM_PROVIDER_FAILURE_MESSAGE = (
    "The upstream AI provider failed to process the request. Please retry the task in a few minutes."
)
UPSTREAM_PROVIDER_ERROR_STATUS_PATTERN = re.compile(r"\bapi error:\s*(?:429|5\d\d)\b", re.IGNORECASE)
SANDBOX_TASK_SPEND_LIMIT_MARKER = "this agent run reached its spend limit"
DEFAULT_FAILURE_RECOVERY_HINT = (
    "Reply in this thread with `retry` to try again from the latest checkpoint, "
    "or add the missing details and I'll re-plan before continuing."
)
_TASK_FIELD_LIMIT = 256
_MARKDOWN_CHUNK_LIMIT = 12000
_SECTION_TEXT_LIMIT = 3000

# Slack rejects the request outright for these, and repeating the same blocks cannot change the
# answer, so the reply is posted plainly instead. The same pair is what the scout delivery in
# signals treats as a block rejection.
_BLOCK_REJECTION_ERROR_CODES = frozenset({"invalid_blocks", "invalid_blocks_format"})
# Slack closed the stream, so every later append and the stop call fail the same way.
_STREAM_ENDED_ERROR_CODE = "message_not_in_streaming_state"


def _split_markdown_text(text: str, limit: int = _MARKDOWN_CHUNK_LIMIT) -> list[str]:
    """≤limit pieces at paragraph/line boundaries. Slack stitches chunks server-side."""
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n\n", 0, limit)
        if cut <= 0:
            cut = remaining.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        pieces.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        pieces.append(remaining)
    return pieces


def _markdown_text_pieces(text: str) -> list[str]:
    """Prepare agent prose for `markdown_text` stream chunks.

    Object tags are already markdown by the time they reach here, because the activity that
    owns the text rewrites them into links and only it knows which project the cited objects
    live in. This is transport, so it takes the prose as given: labeled mentions become bare
    ones so an echoed ping notifies, then the result is split to fit a chunk.
    """
    text = normalize_labeled_mentions_to_bare(text)
    return _split_markdown_text(text) if text.strip() else []


def _task_update_chunk(
    task_id: str,
    title: str,
    status: str,
    details: str | None,
) -> dict[str, Any]:
    """task_update chunk with title/details truncated to Slack's 256-char cap."""
    chunk: dict[str, Any] = {
        "type": "task_update",
        "id": task_id,
        "title": title[:_TASK_FIELD_LIMIT],
        "status": status,
    }
    if details:
        chunk["details"] = details[:_TASK_FIELD_LIMIT]
    return chunk


def _plan_update_chunk(title: str) -> dict[str, Any]:
    return {"type": "plan_update", "title": title[:_TASK_FIELD_LIMIT]}


def _status_chunks(task_updates: list[dict[str, Any]] | None, markdown_text: str | None) -> list[dict[str, Any]]:
    """task_update chunks for the well-formed steps, then markdown_text chunks for the prose."""
    chunks: list[dict[str, Any]] = []
    for t in task_updates or []:
        task_id = t.get("id")
        title = t.get("title")
        status = t.get("status")
        if not task_id or not title or not status:
            continue
        chunks.append(_task_update_chunk(str(task_id), str(title), str(status), t.get("details")))
    if markdown_text:
        for piece in _markdown_text_pieces(markdown_text):
            chunks.append({"type": "markdown_text", "text": piece})
    return chunks


def _format_task_error(error: str) -> str:
    error = error.strip()
    if not error:
        return "Unknown error"

    if SANDBOX_TASK_SPEND_LIMIT_MARKER in error.lower():
        return error

    if UPSTREAM_PROVIDER_ERROR_STATUS_PATTERN.search(error):
        return UPSTREAM_PROVIDER_FAILURE_MESSAGE

    return error


@dataclass(frozen=False)
class SlackThreadContext:
    """Context for posting messages to a Slack thread."""

    integration_id: int
    channel: str
    thread_ts: str
    user_message_ts: str | None = None
    mentioning_slack_user_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "integration_id": self.integration_id,
            "channel": self.channel,
            "thread_ts": self.thread_ts,
        }
        if self.user_message_ts is not None:
            d["user_message_ts"] = self.user_message_ts
        if self.mentioning_slack_user_id is not None:
            d["mentioning_slack_user_id"] = self.mentioning_slack_user_id
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SlackThreadContext":
        return cls(
            integration_id=data["integration_id"],
            channel=data["channel"],
            thread_ts=data["thread_ts"],
            user_message_ts=data.get("user_message_ts"),
            mentioning_slack_user_id=data.get("mentioning_slack_user_id"),
        )

    @classmethod
    def from_mapping(
        cls, mapping: "SlackThreadTaskMapping", user_message_ts: str | None = None
    ) -> "SlackThreadContext":
        return cls(
            integration_id=mapping.integration_id,
            channel=mapping.channel,
            thread_ts=mapping.thread_ts,
            user_message_ts=user_message_ts,
            mentioning_slack_user_id=mapping.mentioning_slack_user_id,
        )


def _pr_buttons(pr_url: str, task_url: str | None) -> list[dict[str, Any]]:
    buttons: list[dict[str, Any]] = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "View PR", "emoji": True},
            "url": pr_url,
        },
    ]
    if task_url:
        buttons.append(
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Open in PostHog", "emoji": True},
                "url": task_url,
            }
        )
    return buttons


class SlackThreadHandler:
    """Handler for posting updates to a Slack thread during task execution."""

    def __init__(
        self,
        context: SlackThreadContext,
        run_footer: RunFooter | None = None,
        actor_slack_user_id: str | None = None,
        turn_trace_id: str | None = None,
    ) -> None:
        self.context = context
        self.run_footer = run_footer or RunFooter()
        # Beside the footer rather than in it: a trace id belongs to one turn, and the
        # next turn in the same thread has its own.
        self.turn_trace_id = turn_trace_id
        # Who this reply is for, which can differ from the task creator because a thread
        # outlives its opener.
        self.actor_slack_user_id = actor_slack_user_id or context.mentioning_slack_user_id
        self._integration: Integration | None = None
        self._client: WebClient | None = None
        self._bot_user_id: str | None = None
        self._fork_flag: bool | None = None
        self.stream_ended = False

    @classmethod
    def for_run(
        cls,
        context: SlackThreadContext,
        run_id: str | UUID | None,
        *,
        actor_slack_user_id: str | None = None,
        turn_trace_id: str | None = None,
    ) -> "SlackThreadHandler":
        """A handler whose footer describes ``run_id``.

        The footer's project segment is judged against the install this context posts through,
        so the footer always loads with ``context.integration_id``.
        """
        return cls(
            context,
            load_run_footer(run_id, integration_id=context.integration_id),
            actor_slack_user_id=actor_slack_user_id,
            turn_trace_id=turn_trace_id,
        )

    def _get_integration(self) -> Integration:
        if self._integration is None:
            # nosemgrep: idor-lookup-without-team (internal context, ID from Slack event mapping)
            self._integration = Integration.objects.get(id=self.context.integration_id)
        return self._integration

    @property
    def project_url(self) -> str:
        """Base for links to the objects this thread's replies cite.

        Reuses the memoized integration, so asking for it costs nothing beyond the lookup
        posting already does.
        """
        return project_web_url(self._get_integration().team_id)

    def _get_client(self) -> WebClient:
        if self._client is None:
            integration = self._get_integration()
            self._client = SlackIntegration(integration).client
        return self._client

    def reader_task_url(self) -> str | None:
        """The task page behind this reply, or `None` when the run has no task. Shown to
        every reader; the page enforces access itself."""
        return self.run_footer.task_url

    def _footer_block(self, include_task_url: bool = True) -> dict[str, Any] | None:
        """This handler's footer, or `None` when there is nothing to describe."""
        if not self.run_footer.has_content():
            return None
        footer = self.run_footer
        if not include_task_url:
            footer = replace(footer, task_url=None)
        configure_url = app_home_url(self._get_integration())
        return reply_footer_block(footer, configure_url)

    def _fork_menu(self) -> dict[str, Any] | None:
        """The overflow menu for this reply, or `None` outside the rollout.

        Only ever asked for once a footer exists, which is what keeps a reply with
        nothing to describe off the integration lookup behind the flag — the same
        bargain `_footer_block` makes.
        """
        integration = self._get_integration()
        # Memoized like the sibling gates: a reply asks for this up to three times, and
        # the flag is evaluated remotely.
        if self._fork_flag is None:
            self._fork_flag = is_slack_app_forking_enabled(integration)
        if not self._fork_flag:
            return None
        return fork_menu_element(integration.id)

    def _feedback_block(self) -> dict[str, Any] | None:
        """The thumbs for this reply, or `None` when there is nothing to rate.

        A reply with no run behind it — a note, a card posted before the run existed —
        has nothing a rating could be attributed to.
        """
        run_id = self.run_footer.run_id
        if not run_id:
            return None
        return turn_feedback_block(self._get_integration().id, run_id, self.turn_trace_id)

    def _append_trailing_blocks(self, ts: str) -> None:
        """Add the fork menu and the thumbs to a streamed reply, which has no section to
        hang either on.

        One append per block, and both after the answer's: a request Slack rejects must
        cost that control alone, never the reply and never its sibling.
        """
        if self.stream_ended:
            return
        for block, failure in (
            (self._fork_menu_actions_block(), "slack_app_fork_menu_append_failed"),
            (self._feedback_block(), "slack_app_feedback_buttons_append_failed"),
        ):
            if not block:
                continue
            try:
                self._get_client().chat_appendStream(
                    channel=self.context.channel,
                    ts=ts,
                    chunks=[{"type": "blocks", "blocks": [block]}],
                )
            except Exception as e:
                logger.warning(failure, error=str(e))

    def _fork_menu_actions_block(self) -> dict[str, Any] | None:
        menu = self._fork_menu()
        return fork_menu_actions_block(menu) if menu else None

    def _get_bot_user_id(self) -> str | None:
        if self._bot_user_id is None:
            try:
                response = self._get_client().auth_test()
                self._bot_user_id = response.get("user_id")
            except Exception as e:
                logger.warning("slack_auth_test_failed", error=str(e))
        return self._bot_user_id

    def _post_in_thread(self, **kwargs: Any) -> Any:
        """Post in the run's thread, or nothing at all once the prompt it answers is gone.

        Every lifecycle card and relayed answer goes through here, so a user who deletes
        the prompt mid-run simply stops hearing from us.
        """
        return post_slack_thread_reply(
            self._get_client(),
            channel=self.context.channel,
            thread_ts=self.context.thread_ts,
            **kwargs,
        )

    def _find_progress_message_ts(self) -> str | None:
        """Find existing progress message in the thread."""
        try:
            client = self._get_client()
            bot_user_id = self._get_bot_user_id()
            if not bot_user_id:
                return None

            response = client.conversations_replies(
                channel=self.context.channel,
                ts=self.context.thread_ts,
                limit=50,
            )
            messages: list[dict[str, Any]] = response.get("messages", [])

            for msg in messages:
                if msg.get("user") == bot_user_id and PROGRESS_MESSAGE_MARKER in msg.get("text", ""):
                    return msg.get("ts")
        except Exception as e:
            logger.warning("slack_find_progress_message_failed", error=str(e))
        return None

    def update_reaction(self, emoji: str) -> None:
        """Swap the reaction on the user's mention message."""
        target_ts = self.context.user_message_ts or self.context.thread_ts
        try:
            client = self._get_client()
            try:
                client.reactions_remove(channel=self.context.channel, timestamp=target_ts, name="eyes")
            except Exception:
                pass
            client.reactions_add(
                channel=self.context.channel,
                timestamp=target_ts,
                name=emoji,
            )
        except Exception as e:
            logger.warning("slack_update_reaction_failed", error=str(e))

    def start_status_stream(
        self,
        task_updates: list[dict[str, Any]] | None = None,
        first_markdown_text: str | None = None,
        plan_title: str | None = None,
    ) -> str | None:
        """chat.startStream in plan-block mode. Seed with plan-block steps, a
        markdown_text chunk, or both. The plan block stays where its first step
        lands, and later task_update chunks change that block in place."""
        if not self.actor_slack_user_id:
            return None
        if first_markdown_text:
            first_markdown_text = self._with_leading_mention(first_markdown_text)
        chunks = _status_chunks(task_updates, first_markdown_text)
        if not chunks:
            return None
        if plan_title:
            chunks.insert(0, _plan_update_chunk(plan_title))
        try:
            client = self._get_client()
            if not slack_message_exists(client, self.context.channel, self.context.thread_ts):
                logger.warning("slack_app_status_stream_skipped_message_deleted", channel=self.context.channel)
                return None
            integration = self._get_integration()
            response = client.chat_startStream(
                channel=self.context.channel,
                thread_ts=self.context.thread_ts,
                recipient_user_id=self.actor_slack_user_id,
                recipient_team_id=integration.integration_id,
                task_display_mode="plan",
                chunks=chunks,
            )
            ts = response.get("ts") if isinstance(response, dict) else response["ts"]
            return ts if isinstance(ts, str) else None
        except Exception as e:
            logger.warning("slack_app_status_stream_start_failed", error=str(e))
            return None

    def append_status_chunks(
        self,
        ts: str,
        task_updates: list[dict[str, Any]] | None = None,
        markdown_text: str | None = None,
        plan_title: str | None = None,
    ) -> bool:
        """Append plan-block step transitions and/or markdown_text chunks. Returns whether the stream is still open."""
        chunks = _status_chunks(task_updates, markdown_text)
        if plan_title:
            chunks.insert(0, _plan_update_chunk(plan_title))
        self._append_chunks(ts, chunks, "slack_app_status_stream_append_failed")
        return not self.stream_ended

    def append_status_blocks(self, ts: str, blocks: list[dict[str, Any]]) -> bool:
        """Append Block Kit blocks, such as chart cards, to an open stream. Returns whether Slack took them."""
        if not blocks:
            return True
        return self._append_chunks(
            ts, [{"type": "blocks", "blocks": blocks}], "slack_app_status_stream_blocks_append_failed"
        )

    def stop_status_stream(
        self,
        ts: str,
        complete_task_id: str | None = None,
        complete_task_title: str | None = None,
        final_markdown: str | None = None,
        plan_title: str | None = None,
        append_attachments: Callable[[], None] | None = None,
        mention_sent: bool = False,
    ) -> None:
        """Final flush: mark the last plan-block step complete, stream the answer, then chat.stopStream.

        The answer starts with the @-mention, so the one notification lands with it. With no
        answer to stream here, the mention closes the message instead, unless ``mention_sent``
        says the answer already carried it. ``append_attachments`` runs after the answer, so
        chart cards sit under the text that describes them. The provenance footer is a `blocks`
        chunk because a `context` block is the only way to get muted text.

        When Slack already closed the stream, the answer goes out as a plain thread reply,
        and nothing else is sent to the closed stream."""
        answer_chunks: list[dict[str, Any]] = []
        if plan_title:
            answer_chunks.append(_plan_update_chunk(plan_title))
        if complete_task_id and complete_task_title:
            answer_chunks.append(_task_update_chunk(complete_task_id, complete_task_title, "complete", None))
        if final_markdown:
            for piece in _markdown_text_pieces(self._with_leading_mention(final_markdown)):
                answer_chunks.append({"type": "markdown_text", "text": piece})
        self._append_chunks(ts, answer_chunks, "slack_app_status_stream_final_append_failed")
        if self.stream_ended:
            if final_markdown:
                self._post_answer_outside_stream(final_markdown)
            return
        if append_attachments is not None:
            try:
                append_attachments()
            except Exception as e:
                logger.warning("slack_app_status_stream_attachments_failed", error=str(e))

        final_chunks: list[dict[str, Any]] = []
        recipient = self.actor_slack_user_id
        if recipient and not final_markdown and not mention_sent:
            # Newlines keep the mention off the tail of the last streamed prose chunk.
            final_chunks.append({"type": "markdown_text", "text": f"\n\n<@{recipient}>"})
        footer = self._footer_block()
        if footer:
            final_chunks.append({"type": "blocks", "blocks": [footer]})
        self._append_chunks(ts, final_chunks, "slack_app_status_stream_final_append_failed")
        if footer:
            self._append_trailing_blocks(ts)
        self._stop_stream(ts)

    def _stop_stream(self, ts: str) -> None:
        if self.stream_ended:
            return
        try:
            self._get_client().chat_stopStream(
                channel=self.context.channel,
                ts=ts,
            )
        except Exception as e:
            logger.warning("slack_app_status_stream_stop_failed", error=str(e))

    def _post_answer_outside_stream(self, final_markdown: str) -> None:
        pieces = _markdown_text_pieces(self._with_leading_mention(final_markdown))
        for index, piece in enumerate(pieces):
            self.post_thread_message(piece, with_footer=index == len(pieces) - 1, markdown=True)

    def _with_leading_mention(self, markdown: str) -> str:
        return leading_mention_prefix(markdown, self.actor_slack_user_id) + markdown

    def attach_files(self, ts: str, file_ids: list[str]) -> bool:
        """Attach uploaded files to a message whose stream has closed, keeping its blocks and text.

        A streaming message cannot hold a file, and chat.update is the only way to add one later."""
        try:
            self._get_client().chat_update(channel=self.context.channel, ts=ts, file_ids=file_ids)
        except Exception as e:
            logger.warning("slack_app_status_stream_attach_files_failed", error=str(e))
            return False
        return True

    def _append_chunks(self, ts: str, chunks: list[dict[str, Any]], failure_event: str) -> bool:
        if not chunks:
            return True
        if self.stream_ended:
            return False
        try:
            self._get_client().chat_appendStream(channel=self.context.channel, ts=ts, chunks=chunks)
        except SlackApiError as e:
            if e.response.get("error") == _STREAM_ENDED_ERROR_CODE:
                self.stream_ended = True
                logger.info("slack_app_status_stream_ended_by_slack", channel=self.context.channel)
            else:
                logger.warning(failure_event, error=str(e))
            return False
        except Exception as e:
            logger.warning(failure_event, error=str(e))
            return False
        return True

    def post_or_update_progress(self, stage: str, task_url: str | None = None) -> None:
        """Post a new progress message or update the existing one.

        The project and model ride along as a context line rather than their own
        message: what a task is running on and against is a property of the task, and
        the thread already has one place that describes it while it works.
        """
        text = f"*{PROGRESS_MESSAGE_MARKER}* :hourglass_flowing_sand:\nStage: {stage}"
        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        ]

        run_context = run_context_block(self.run_footer)
        if run_context:
            blocks.append(run_context)

        if task_url:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "View agent logs",
                                "emoji": True,
                            },
                            "url": task_url,
                        }
                    ],
                }
            )

        try:
            client = self._get_client()
            progress_ts = self._find_progress_message_ts()

            if progress_ts:
                client.chat_update(
                    channel=self.context.channel,
                    ts=progress_ts,
                    text=text,
                    blocks=blocks,
                )
            else:
                self._post_in_thread(text=text, blocks=blocks)
        except Exception as e:
            logger.exception("slack_progress_update_failed", error=str(e))

    def post_pr_opened(
        self,
        pr_url: str,
        task_url: str | None,
        reply_target_slack_user_id: str | None = None,
        bot_authored: bool = False,
    ) -> None:
        """Post the single per-run "PR opened" card.

        Used at every lifecycle moment a run surfaces a PR for the first
        time — mid-run announcement, post-sandbox cleanup, terminal
        completion. The activity-level dedupe in
        ``_post_pr_opened_notification_once`` ensures this fires once per
        ``pr_url`` per run regardless of which moment got there first.

        ``reply_target_slack_user_id`` is the resolved actor — typically the
        most recent thread participant. ``None`` produces an untagged message.

        ``bot_authored`` means the run fell back to the team GitHub installation
        because the actor had no usable personal one, so the pull request carries
        the bot's identity rather than theirs. This card is the first place that
        becomes visible, and it is the only surface guaranteed to reach someone
        who only ever talks to @PostHog from Slack.
        """
        mention_prefix = f"<@{reply_target_slack_user_id}> " if reply_target_slack_user_id else ""
        header = f"{mention_prefix}*Pull request opened* :rocket:"

        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
            {"type": "actions", "elements": _pr_buttons(pr_url, task_url)},
        ]
        if bot_authored:
            blocks.append(context_block(self._personal_github_hint()))

        self._delete_progress_and_post(header, blocks)

    def post_pr_closed(
        self,
        pr_url: str,
        task_url: str | None,
        reply_target_slack_user_id: str | None = None,
        merged: bool = False,
    ) -> bool:
        """Post that the pull request ``post_pr_opened`` announced was merged or closed.

        Without this card the thread keeps reading as if the work still waits for review.
        It leaves any progress message alone, because the run can still be working.
        Returns whether the card went out. A Slack failure is logged, never raised.
        """
        mention_prefix = f"<@{reply_target_slack_user_id}> " if reply_target_slack_user_id else ""
        outcome = "*Pull request merged* :tada:" if merged else "*Pull request closed without merging*"
        header = f"{mention_prefix}{outcome}"
        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
            {"type": "actions", "elements": _pr_buttons(pr_url, task_url)},
        ]
        if not merged:
            blocks.append(context_block("Reply in this thread to try a different approach."))
        try:
            return self._post_in_thread(text=header, blocks=blocks) is not None
        except Exception as e:
            logger.exception("slack_pr_closed_post_failed", error=str(e))
            return False

    def _personal_github_hint(self) -> str:
        """One muted line telling the reader why the pull request isn't theirs.

        Written for the next run rather than this one: authorship is fixed when a run is
        created, so connecting now changes who the following pull requests belong to, and
        the commits this thread pushes once someone replies here.
        """
        url = personal_integrations_url(self._get_integration().team_id)
        return f"Opened by the PostHog bot. <{url}|Connect your GitHub> so pull requests are opened as you."

    def post_footer(self) -> None:
        """Post the footer alone, for an answer with no message of its own to close.

        Only the composed chart delivery needs this: the answer rode along in the message
        carrying the chart cards, whose blocks are built during delivery, so the footer
        has nothing to attach to.
        """
        footer = self._footer_block()
        if not footer:
            return
        blocks = [footer]
        menu = self._fork_menu()
        if menu:
            blocks.append(fork_menu_actions_block(menu))
        feedback = self._feedback_block()
        if feedback:
            blocks.append(feedback)
        try:
            self._post_in_thread(text=footer["elements"][0]["text"], blocks=blocks)
        except Exception as e:
            logger.warning("slack_app_post_footer_failed", error=str(e))

    def _answer_blocks(
        self, text: str, footer: dict[str, Any] | None, *, markdown: bool
    ) -> list[dict[str, Any]] | None:
        """The blocks carrying one answer, or `None` to post it as plain text instead.

        Under `mrkdwn` a footerless answer needs no blocks, because a plain-text message renders
        `mrkdwn` on its own, so an ordinary message stays the plain-text post it has always been.
        A `markdown` block has no such equivalent: without it Slack shows the Markdown source, so
        the answer always carries one.

        The menu and the thumbs are only asked for once a footer exists, which keeps a reply with
        nothing to describe off the integration lookup behind their gates.
        """
        if markdown:
            blocks = [slack_markdown_block(text)]
        elif footer:
            # `expand` keeps the answer fully visible: a section collapses behind "Show more",
            # which plain text never did.
            blocks = [{"type": "section", "expand": True, "text": {"type": "mrkdwn", "text": text}}]
        else:
            return None
        if not footer:
            return blocks
        menu = self._fork_menu()
        if markdown:
            # A `markdown` block takes no accessory, so the menu follows the answer in an
            # `actions` block of its own, which is where the streamed replies already put it.
            blocks.append(footer)
            if menu:
                blocks.append(fork_menu_actions_block(menu))
        else:
            # The menu hangs off the answer, not the footer: a `context` block rejects
            # interactive elements, and moving the footer to a `section` to hold one
            # would cost it the muted styling that makes it read as a footer.
            if menu:
                blocks[0]["accessory"] = menu
            blocks.append(footer)
        # The thumbs close the message, below the footer, where a reader of any other
        # AI app already looks for them.
        feedback = self._feedback_block()
        if feedback:
            blocks.append(feedback)
        return blocks

    def post_thread_message(self, text: str, with_footer: bool = False, *, markdown: bool = False) -> None:
        """Post a plain message in the existing thread.

        ``with_footer`` closes the message with the provenance footer, for the last
        chunk of a non-streamed answer — the streamed path appends its own instead.
        `_answer_blocks` decides what the answer is carried in.

        ``markdown`` says the text is the agent's Markdown, which the relay passes on as
        written. It defaults off for a message of our own wording, which is already Slack
        ``mrkdwn`` and carries no Markdown worth rendering.
        """
        # Text past the block's character cap can only be posted as plain text, which carries
        # no blocks at all. Dropping the footer there costs a line of provenance, while keeping
        # it would cost the whole message. The menu and the thumbs go with it.
        markdown = markdown and len(text) <= SLACK_MARKDOWN_TEXT_MAX_LEN
        fits_in_a_block = markdown or len(text) <= _SECTION_TEXT_LIMIT
        footer = self._footer_block() if with_footer and fits_in_a_block else None
        blocks = self._answer_blocks(text, footer, markdown=markdown)
        try:
            self._post_in_thread(text=text, blocks=blocks)
        except SlackApiError as e:
            # Slack rejects a request whose blocks are invalid outright — the `text`
            # fallback does not rescue it — so the answer would go down with its footer.
            # Describing a run must never cost the reader the run's answer. Posting plainly
            # rather than retrying through this method drops every block at once, so a
            # rejection Slack repeats cannot loop.
            if blocks and e.response.get("error") in _BLOCK_REJECTION_ERROR_CODES:
                logger.warning("slack_app_answer_blocks_rejected", error=str(e))
                try:
                    self._post_in_thread(text=text)
                except Exception as retry_error:
                    logger.warning("slack_post_thread_message_failed", error=str(retry_error))
                return
            logger.warning("slack_post_thread_message_failed", error=str(e))
        except Exception as e:
            logger.warning("slack_post_thread_message_failed", error=str(e))

    def post_completion(self, task_url: str | None) -> None:
        """Post the no-PR completion message.

        Runs that produce a PR surface it via ``post_pr_opened`` (routed
        through ``_post_pr_opened_notification_once`` for once-per-URL
        semantics). This card is the "task finished without opening a PR"
        terminal state.
        """
        header = "*Task Completed* :hedgehog:"

        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        ]
        if task_url:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Open in PostHog",
                                "emoji": True,
                            },
                            "url": task_url,
                        }
                    ],
                }
            )

        self._delete_progress_and_post(header, blocks)

    def post_error(
        self, error: str, task_url: str | None, recovery_hint: str | None = DEFAULT_FAILURE_RECOVERY_HINT
    ) -> None:
        """Post error message with link to PostHog for details."""
        header = "*Task Failed* :x:"
        error = _format_task_error(error)
        truncated_error = error[:200] if len(error) > 200 else error

        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
            {"type": "section", "text": {"type": "mrkdwn", "text": truncated_error}},
        ]
        if recovery_hint:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": recovery_hint}})
        if task_url:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "See details in PostHog",
                                "emoji": True,
                            },
                            "url": task_url,
                        },
                    ],
                }
            )

        self._delete_progress_and_post(f"{header}\n{truncated_error}", blocks)

    def post_note(self, text: str) -> None:
        """Post a plain one-line note to the thread, replacing any progress message."""
        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        ]
        self._delete_progress_and_post(text, blocks, with_footer=False)

    def delete_progress(self) -> None:
        """Delete the progress message if it exists."""
        try:
            client = self._get_client()
            progress_ts = self._find_progress_message_ts()
            if progress_ts:
                client.chat_delete(channel=self.context.channel, ts=progress_ts)
        except Exception as e:
            logger.warning("slack_delete_progress_failed", error=str(e))

    def _delete_progress_and_post(self, text: str, blocks: list[dict[str, Any]], with_footer: bool = True) -> None:
        """Delete any progress message and post the final one in its place.

        Terminal cards close with the provenance footer, minus the web link their own
        button already carries.
        """
        if with_footer:
            footer = self._footer_block(include_task_url=False)
            if footer:
                blocks = [*blocks, footer]
        try:
            self.delete_progress()
            self._post_in_thread(text=text, blocks=blocks)
        except Exception as e:
            logger.exception("slack_completion_post_failed", error=str(e))
