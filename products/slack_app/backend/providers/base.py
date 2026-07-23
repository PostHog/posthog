"""Provider seam for the chat surfaces this product serves.

The slack_app product is growing into a multi-provider chat product (Telegram is the
first planned addition). ``ChatProvider`` is the boundary that a new provider has to
implement for the minimal conversation loop: authenticate inbound webhooks, resolve the
sender to a PostHog user, read conversation history, and post replies. Everything
richer — interactive elements, App Home, settings surfaces — deliberately stays
provider-private until a second provider actually needs it.

Implementations are pure delegation onto their provider-specific modules; behavior
lives with the existing code, this class only names the seam.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol
from uuid import UUID

from django.http import HttpRequest

from posthog.models.integration import Integration
from posthog.models.user import User


class ChatProviderError(Exception):
    """A chat provider could not authenticate a webhook or complete an operation."""


@dataclass(frozen=True)
class ConversationRef:
    """Provider-neutral pointer to one thread-like conversation, scoped to the provider
    instance's bound ``Integration`` (one workspace credential).

    For Slack, ``channel_id`` is the channel id and ``thread_id`` the ``thread_ts``.
    Future providers map the fields onto their closest native concepts (for Telegram:
    chat id and reply-root message id).
    """

    channel_id: str
    thread_id: str


class ChatProvider(ABC):
    """One chat surface (Slack today), bound to one ``Integration`` row.

    Workspace-agnostic concerns are classmethods (webhook signature validation, the
    cross-region claims secret, identity-link lookup); conversation operations require
    an instance bound to the workspace credential.
    """

    kind: ClassVar[str]
    """Registry key, e.g. ``"slack"``."""

    integration_kinds: ClassVar[tuple[str, ...]]
    """``Integration.kind`` values this provider owns."""

    def __init__(self, integration: Integration) -> None:
        self.integration = integration

    @classmethod
    @abstractmethod
    def validate_webhook(cls, request: HttpRequest) -> None:
        """Raise ``ChatProviderError`` when the inbound webhook signature is invalid."""

    @classmethod
    @abstractmethod
    def region_claims_secret(cls) -> str:
        """Shared US/EU secret used to sign cross-region workspace-claims probes."""

    @classmethod
    @abstractmethod
    def find_linked_user(cls, *, external_user_id: str, workspace_id: str, candidate_org_ids: set[UUID]) -> User | None:
        """The PostHog user explicitly linked to this provider identity, if any.

        The most-recently-linked accessible link wins when several exist; callers still
        own the access-level check on the resolved user.
        """

    @abstractmethod
    def get_user_email(self, external_user_id: str) -> str | None:
        """Best-effort email for membership matching.

        ``None`` when the surface exposes no email (identity then rests entirely on
        ``find_linked_user``) or the lookup fails.
        """

    @abstractmethod
    def post_message(self, ref: ConversationRef, text: str) -> None:
        """Post plain text into the conversation as a threaded reply."""

    def add_reaction(self, ref: ConversationRef, message_id: str, reaction: str) -> None:  # noqa: B027 — deliberate no-op default for providers without reactions
        """Optional acknowledgement affordance; no-op for providers without reactions."""

    @abstractmethod
    def collect_thread_messages(self, ref: ConversationRef) -> list[dict[str, str]]:
        """Fetch the conversation history that seeds the agent's task context.

        Each message dict carries ``user`` (display name), ``user_id``, ``text``, and
        ``ts`` — the wire shape the task-description builder consumes.
        """


class ChatThreadHandler(Protocol):
    """Structural interface for posting task-lifecycle updates back into the
    conversation that spawned a task run.

    ``SlackThreadHandler`` (products/slack_app/backend/slack_thread.py) is today's only
    implementation; the signatures here are copied from it verbatim. A ``Protocol``
    rather than an ABC keeps ``slack_thread`` free of any providers import (the registry
    imports it, not the other way around), so the handler class itself is untouched by
    the seam. Consumers obtain instances via the registry / facade factories and
    annotate with this type.
    """

    def update_reaction(self, emoji: str) -> None: ...

    def start_status_stream(
        self,
        first_task_id: str | None = ...,
        first_task_title: str | None = ...,
        first_task_details: str | None = ...,
        first_markdown_text: str | None = ...,
    ) -> str | None: ...

    def append_status_chunks(
        self,
        ts: str,
        task_updates: list[dict[str, Any]] | None = ...,
        markdown_text: str | None = ...,
    ) -> None: ...

    def stop_status_stream(
        self,
        ts: str,
        complete_task_id: str | None = ...,
        complete_task_title: str | None = ...,
        complete_task_details: str | None = ...,
        final_markdown: str | None = ...,
    ) -> None: ...

    def post_or_update_progress(self, stage: str, task_url: str | None = ...) -> None: ...

    def post_pr_opened(
        self,
        pr_url: str,
        task_url: str | None,
        reply_target_slack_user_id: str | None = ...,
    ) -> None: ...

    def post_thread_message(self, text: str) -> None: ...

    def post_completion(self, task_url: str | None) -> None: ...

    def post_error(self, error: str, task_url: str | None, recovery_hint: str | None = ...) -> None: ...

    def post_cancelled(self, task_url: str | None, recovery_hint: str | None = ...) -> None: ...

    def post_note(self, text: str) -> None: ...

    def delete_progress(self) -> None: ...
