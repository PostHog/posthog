import re
from dataclasses import dataclass, replace
from typing import Any

import structlog
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration, SlackIntegration

from products.slack_app.backend.feature_flags import (
    is_slack_app_forking_enabled,
    is_slack_app_home_enabled,
    is_slack_app_model_classifier_enabled,
)
from products.slack_app.backend.services.model_catalogue import describe_run_model
from products.slack_app.backend.services.slack_messages import (
    RunFooter,
    app_home_url,
    context_block,
    fork_menu_actions_block,
    fork_menu_element,
    normalize_labeled_mentions_to_bare,
    personal_integrations_url,
    post_slack_thread_reply,
    reply_footer_block,
    slack_message_exists,
    viewer_has_code_access,
)

logger = structlog.get_logger(__name__)

PROGRESS_MESSAGE_MARKER = "Working on task..."
UPSTREAM_PROVIDER_FAILURE_MESSAGE = (
    "The upstream AI provider failed to process the request. Please retry the task in a few minutes."
)
UPSTREAM_PROVIDER_ERROR_STATUS_PATTERN = re.compile(r"\bapi error:\s*(?:429|5\d\d)\b", re.IGNORECASE)
DEFAULT_FAILURE_RECOVERY_HINT = (
    "Reply in this thread with `retry` to try again from the latest checkpoint, "
    "or add the missing details and I'll re-plan before continuing."
)
DEFAULT_CANCELLED_RECOVERY_HINT = (
    "Reply in this thread when you want to resume, and include any new direction I should follow."
)


_TASK_FIELD_LIMIT = 256
_MARKDOWN_CHUNK_LIMIT = 12000
_SECTION_TEXT_LIMIT = 3000


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


def _format_task_error(error: str) -> str:
    error = error.strip()
    if not error:
        return "Unknown error"

    if UPSTREAM_PROVIDER_ERROR_STATUS_PATTERN.search(error):
        return UPSTREAM_PROVIDER_FAILURE_MESSAGE

    return error


@dataclass
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


class SlackThreadHandler:
    """Handler for posting updates to a Slack thread during task execution."""

    def __init__(
        self,
        context: SlackThreadContext,
        run_footer: RunFooter | None = None,
        actor_slack_user_id: str | None = None,
    ) -> None:
        self.context = context
        self.run_footer = run_footer or RunFooter()
        # Who this reply is for. Links are gated on their access, not the task creator's:
        # a thread outlives its opener, and a link only helps the person looking at it.
        self.actor_slack_user_id = actor_slack_user_id or context.mentioning_slack_user_id
        self._integration: Integration | None = None
        self._client: WebClient | None = None
        self._bot_user_id: str | None = None
        self._footer_flag: bool | None = None
        self._fork_flag: bool | None = None
        self._code_access: bool | None = None

    def _get_integration(self) -> Integration:
        if self._integration is None:
            # nosemgrep: idor-lookup-without-team (internal context, ID from Slack event mapping)
            self._integration = Integration.objects.get(id=self.context.integration_id)
        return self._integration

    def _get_client(self) -> WebClient:
        if self._client is None:
            integration = self._get_integration()
            self._client = SlackIntegration(integration).client
        return self._client

    def footer_enabled(self) -> bool:
        """Whether this workspace shows run provenance.

        Shares the model-classifier flag: choosing a model in a mention and being told
        which model ran are two halves of one feature. Public so a caller can skip the
        work of describing a run nobody will be shown, and memoized because that caller
        and the footer builder both ask.
        """
        if self._footer_flag is None:
            self._footer_flag = is_slack_app_model_classifier_enabled(self._get_integration())
        return bool(self._footer_flag)

    def viewer_can_open_code_links(self) -> bool:
        """Whether this reply's reader can open a PostHog Code link. Memoized: the cards
        ask for their buttons and the footer asks again for its own links."""
        if self._code_access is None:
            self._code_access = viewer_has_code_access(self._get_integration(), self.actor_slack_user_id)
        return bool(self._code_access)

    def reader_footer(self) -> RunFooter:
        """`run_footer` as this reply's reader may see it, links withheld where they can't
        open them.

        The one place that answers this, so a card's buttons and the footer's links can't
        disagree about the same reader. A footer carrying no links asks nothing, which
        keeps a plain answer off the identity lookup behind the access check.
        """
        if not (self.run_footer.task_url or self.run_footer.desktop_url):
            return self.run_footer
        if self.viewer_can_open_code_links():
            return self.run_footer
        return replace(self.run_footer, task_url=None, desktop_url=None)

    def reader_task_url(self) -> str | None:
        """The task page this reply's reader may open, or `None` where they may not."""
        return self.reader_footer().task_url

    def _footer_block(self, include_task_url: bool = True) -> dict[str, Any] | None:
        """This handler's footer, or `None` when the workspace isn't in the rollout.

        "Configure" points at the Home tab, so it only appears where that tab exists — a
        workspace outside the Home rollout would land on an empty one. The Home flag is
        only consulted once there is actually something to gate.
        """
        # A handler with nothing to describe can't produce a footer, so it never pays for
        # the flag lookups.
        if not self.run_footer.has_content():
            return None
        if not self.footer_enabled():
            return None
        footer = self.reader_footer()
        if not include_task_url:
            footer = replace(footer, task_url=None)
        integration = self._get_integration()
        configure_url = app_home_url(integration)
        if configure_url and not is_slack_app_home_enabled(integration):
            configure_url = None
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

    def _append_fork_menu(self, ts: str) -> None:
        """Add the fork menu to a streamed reply, which has no section to hang it on.

        Its own call on purpose: Slack documents no block-type restriction on a streamed
        `blocks` chunk but does not confirm interactive blocks are allowed either, and
        the answer rides the append before this one — a rejected request must cost the
        menu, never the reply.
        """
        menu = self._fork_menu()
        if not menu:
            return
        try:
            self._get_client().chat_appendStream(
                channel=self.context.channel,
                ts=ts,
                chunks=[{"type": "blocks", "blocks": [fork_menu_actions_block(menu)]}],
            )
        except Exception as e:
            logger.warning("slack_app_fork_menu_append_failed", error=str(e))

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
        first_task_id: str | None = None,
        first_task_title: str | None = None,
        first_task_details: str | None = None,
        first_markdown_text: str | None = None,
    ) -> str | None:
        """chat.startStream in plan-block mode. Seed with EITHER a task_update
        (starts with a plan-block step) OR a markdown_text chunk (starts as
        prose; a plan block appears later when a task_update arrives)."""
        if not self.context.mentioning_slack_user_id:
            return None
        chunks: list[dict[str, Any]] = []
        if first_task_id and first_task_title:
            chunks.append(_task_update_chunk(first_task_id, first_task_title, "in_progress", first_task_details))
        if first_markdown_text:
            for piece in _split_markdown_text(normalize_labeled_mentions_to_bare(first_markdown_text)):
                chunks.append({"type": "markdown_text", "text": piece})
        if not chunks:
            return None
        try:
            client = self._get_client()
            if not slack_message_exists(client, self.context.channel, self.context.thread_ts):
                logger.warning("slack_app_status_stream_skipped_message_deleted", channel=self.context.channel)
                return None
            integration = self._get_integration()
            response = client.chat_startStream(
                channel=self.context.channel,
                thread_ts=self.context.thread_ts,
                recipient_user_id=self.context.mentioning_slack_user_id,
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
    ) -> None:
        """Append plan-block step transitions and/or markdown_text chunks."""
        chunks: list[dict[str, Any]] = []
        for t in task_updates or []:
            task_id = t.get("id")
            title = t.get("title")
            status = t.get("status")
            if not task_id or not title or not status:
                continue
            chunks.append(_task_update_chunk(str(task_id), str(title), str(status), t.get("details")))
        if markdown_text:
            for piece in _split_markdown_text(normalize_labeled_mentions_to_bare(markdown_text)):
                chunks.append({"type": "markdown_text", "text": piece})
        if not chunks:
            return
        try:
            self._get_client().chat_appendStream(
                channel=self.context.channel,
                ts=ts,
                chunks=chunks,
            )
        except Exception as e:
            logger.warning("slack_app_status_stream_append_failed", error=str(e))

    def stop_status_stream(
        self,
        ts: str,
        complete_task_id: str | None = None,
        complete_task_title: str | None = None,
        complete_task_details: str | None = None,
        final_markdown: str | None = None,
    ) -> None:
        """Final flush: mark the last plan-block step complete, stream the final
        answer as markdown_text chunks (this is what STAYS in the message body),
        append a trailing @-mention for one notification, then chat.stopStream.

        The provenance footer closes the message. It arrives as a `blocks` chunk
        because a `context` block is the only way to get muted text, and it goes
        after the mention so the ping stays adjacent to the prose it answers."""
        final_chunks: list[dict[str, Any]] = []
        if complete_task_id and complete_task_title:
            final_chunks.append(
                _task_update_chunk(complete_task_id, complete_task_title, "complete", complete_task_details)
            )
        if final_markdown:
            for piece in _split_markdown_text(normalize_labeled_mentions_to_bare(final_markdown)):
                final_chunks.append({"type": "markdown_text", "text": piece})
        if self.context.mentioning_slack_user_id:
            # Newlines keep the mention off the tail of the last streamed prose chunk.
            final_chunks.append({"type": "markdown_text", "text": f"\n\n<@{self.context.mentioning_slack_user_id}>"})
        footer = self._footer_block()
        if footer:
            final_chunks.append({"type": "blocks", "blocks": [footer]})
        if final_chunks:
            try:
                self._get_client().chat_appendStream(
                    channel=self.context.channel,
                    ts=ts,
                    chunks=final_chunks,
                )
            except Exception as e:
                logger.warning("slack_app_status_stream_final_append_failed", error=str(e))
        if footer:
            self._append_fork_menu(ts)
        try:
            self._get_client().chat_stopStream(
                channel=self.context.channel,
                ts=ts,
            )
        except Exception as e:
            logger.warning("slack_app_status_stream_stop_failed", error=str(e))

    def post_or_update_progress(self, stage: str, task_url: str | None = None) -> None:
        """Post a new progress message or update the existing one.

        The model rides along as a context line rather than its own message: which
        model is running is a property of the task, and the thread already has one
        place that describes the task while it works. Unlike the reply footer this
        is not gated — a running task says what it is running on either way.
        """
        text = f"*{PROGRESS_MESSAGE_MARKER}* :hourglass_flowing_sand:\nStage: {stage}"
        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        ]

        if self.run_footer.model:
            blocks.append(context_block(describe_run_model(self.run_footer.model, self.run_footer.reasoning_effort)))

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

        buttons: list[dict[str, Any]] = [
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "View PR",
                    "emoji": True,
                },
                "url": pr_url,
            },
        ]
        if task_url:
            buttons.append(
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Open in PostHog",
                        "emoji": True,
                    },
                    "url": task_url,
                }
            )

        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
            {"type": "actions", "elements": buttons},
        ]
        if bot_authored:
            blocks.append(context_block(self._personal_github_hint()))

        self._delete_progress_and_post(header, blocks)

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
        try:
            self._post_in_thread(text=footer["elements"][0]["text"], blocks=blocks)
        except Exception as e:
            logger.warning("slack_app_post_footer_failed", error=str(e))

    def post_thread_message(self, text: str, with_footer: bool = False) -> None:
        """Post a plain message in the existing thread.

        ``with_footer`` closes the message with the provenance footer, for the last
        chunk of a non-streamed answer — the streamed path appends its own instead.
        Passing it only adds blocks when there is actually a footer to show, so an
        ordinary message stays a plain-text post.
        """
        # A section block caps at 3000 characters; over that, dropping the footer costs a
        # line of provenance, while keeping it would cost the whole message.
        footer = self._footer_block() if with_footer and len(text) <= _SECTION_TEXT_LIMIT else None
        # No footer means no blocks at all, so an ordinary message stays the plain-text
        # post it has always been. `expand` keeps the answer fully visible: a section
        # collapses behind "Show more", which plain text never did.
        blocks: list[dict[str, Any]] | None = None
        if footer:
            answer: dict[str, Any] = {"type": "section", "expand": True, "text": {"type": "mrkdwn", "text": text}}
            # The menu hangs off the answer, not the footer: a `context` block rejects
            # interactive elements, and moving the footer to a `section` to hold one
            # would cost it the muted styling that makes it read as a footer.
            menu = self._fork_menu()
            if menu:
                answer["accessory"] = menu
            blocks = [answer, footer]
        try:
            self._post_in_thread(text=text, blocks=blocks)
        except SlackApiError as e:
            # Slack rejects a request whose blocks are invalid outright — the `text`
            # fallback does not rescue it — so the answer would go down with its footer.
            # Describing a run must never cost the reader the run's answer.
            if blocks and e.response.get("error") == "invalid_blocks":
                logger.warning("slack_app_footer_blocks_rejected", error=str(e))
                self.post_thread_message(text)
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

    def post_cancelled(self, task_url: str | None, recovery_hint: str | None = DEFAULT_CANCELLED_RECOVERY_HINT) -> None:
        """Post cancelled message with link to PostHog for details."""
        header = "*Sandbox stopped* :hedgehog:"

        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
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
                                "text": "Open in PostHog",
                                "emoji": True,
                            },
                            "url": task_url,
                        },
                    ],
                }
            )

        self._delete_progress_and_post(header, blocks)

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
