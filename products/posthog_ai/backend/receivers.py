"""Keep a copied chat and its task in step once the task runs for real.

Every hook connects through the tasks facade so no model class crosses the product boundary.

- Before a run starts: the copy runs a few seconds behind the chat, so a run started in that window
  would resume without the last turn. The guard copies what is still missing and refuses the run
  when it cannot, or when the chat's owner is not on the sandbox runtime yet.
- After a run is saved: the first run that is not the import run marks the chat as sandbox, whichever
  path created it. From then on the legacy chat screen routes the conversation through the sandbox
  path too, so a chat can never fork back into LangGraph after it has been continued as a task.
- When tasks are read: a user without the sandbox runtime does not see the copies of their chats. The
  copy is written for everyone so the switch is instant later, but until then their chats are chats.
- After a turn completes: the end-of-turn suggestion is queued (``turn_suggestions/dispatch.py``).
"""

import logging
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models.signals import post_delete, post_save

from asgiref.sync import async_to_sync

from posthog.models import Team, User
from posthog.models.oauth import OAuthRefreshToken
from posthog.models.personal_api_key import PersonalAPIKey

from products.posthog_ai.backend.models.agent_operation import AgentOperation
from products.posthog_ai.backend.models.assistant import Conversation
from products.posthog_ai.backend.services.agent_operations.service import stop_operations_for_revoked_credential
from products.posthog_ai.backend.turn_suggestions.dispatch import enqueue_turn_suggestion_on_turn_completed
from products.tasks.backend.facade.task_run_signals import (
    TaskOriginProduct,
    connect_task_run_post_save,
    connect_task_run_turn_completed,
    register_task_read_exclusion,
    register_task_run_start_guard,
)

logger = logging.getLogger(__name__)

COPY_BEHIND_MESSAGE = "This chat is still being copied into the task. Try again in a moment."
SANDBOX_MODE_REQUIRED_MESSAGE = "Continuing this chat as a task is not available to you yet."


def _feature_flags() -> Any:
    """The flag helpers, or None in a build without ``ee``, where every hook here is a no-op."""
    # Deferred: the flag helpers pull in the LLM clients; this module loads at Django startup and must stay light.
    try:
        from ee.hogai.utils import feature_flags  # noqa: PLC0415
    except ImportError:
        return None
    return feature_flags


def connect() -> None:
    register_task_read_exclusion(copied_chats_hidden_without_sandbox_mode, name="posthog_ai_copied_chats")
    register_task_run_start_guard(catch_up_conversation_copy_before_run, name="posthog_ai_conversation_copy")
    connect_task_run_post_save(
        mark_conversation_sandbox_on_first_run, dispatch_uid="posthog_ai_conversation_follows_task_run"
    )
    connect_task_run_turn_completed(
        enqueue_turn_suggestion_on_turn_completed, dispatch_uid="posthog_ai_turn_suggestion_on_turn_completed"
    )
    post_delete.connect(
        stop_agent_operations_on_api_key_delete, sender=PersonalAPIKey, dispatch_uid="posthog_ai_agent_op_api_key"
    )
    post_save.connect(
        stop_agent_operations_on_refresh_token_revoke,
        sender=OAuthRefreshToken,
        dispatch_uid="posthog_ai_agent_op_refresh_token",
    )


def stop_agent_operations_on_api_key_delete(sender: Any, instance: PersonalAPIKey, **kwargs: Any) -> None:
    key_id = str(instance.id)
    transaction.on_commit(
        lambda: stop_operations_for_revoked_credential(AgentOperation.ParentCredentialKind.PERSONAL_API_KEY, key_id)
    )


def stop_agent_operations_on_refresh_token_revoke(sender: Any, instance: OAuthRefreshToken, **kwargs: Any) -> None:
    # Rotation also revokes the old token, so the check runs after commit, when the family's new token exists.
    if instance.revoked is None or instance.token_family is None:
        return
    family = str(instance.token_family)
    transaction.on_commit(
        lambda: stop_operations_for_revoked_credential(AgentOperation.ParentCredentialKind.OAUTH_TOKEN_FAMILY, family)
    )


def copied_chats_hidden_without_sandbox_mode(team_id: int, user_id: int | None) -> Iterable[UUID]:
    """The user's tasks that are copies of their LangGraph chats, while they are not on the sandbox runtime.

    Copies are only ever visible to the chat's owner, so the owner's own chats are the whole set.
    """
    flags = _feature_flags()
    if flags is None or user_id is None:
        return ()
    # Every task read calls this, and most users have no copied chat: answer that with one query
    # before paying for the team, the user and a flag evaluation.
    copied_task_ids = list(
        Conversation.objects.filter(
            team_id=team_id, user_id=user_id, task_id__isnull=False, agent_runtime=Conversation.AgentRuntime.LANGGRAPH
        ).values_list("task_id", flat=True)
    )
    if not copied_task_ids:
        return ()
    team = Team.objects.filter(id=team_id).only("id", "organization_id").first()
    user = User.objects.filter(id=user_id).only("id", "distinct_id").first()
    if team is None or user is None or flags.has_sandbox_mode_feature_flag(team, user):
        return ()
    return copied_task_ids


def catch_up_conversation_copy_before_run(task_id: str, team_id: int, user_id: int | None) -> str | None:
    """Copy a LangGraph chat's missing turns into its task before the task's first real run."""
    flags = _feature_flags()
    if flags is None:
        return None
    # Deferred: the copy pulls in the tasks facade and the LangGraph graph.
    from products.posthog_ai.backend.conversation_mirror import amirror_conversation  # noqa: PLC0415

    conversation = (
        Conversation.objects.select_related("user", "team")
        .filter(task_id=task_id, team_id=team_id, agent_runtime=Conversation.AgentRuntime.LANGGRAPH, deleted=False)
        .first()
    )
    if conversation is None:
        return None
    if not flags.has_sandbox_mode_feature_flag(conversation.team, conversation.user):
        return SANDBOX_MODE_REQUIRED_MESSAGE
    if not flags.has_conversation_task_mirror_feature_flag(conversation.team, conversation.user):
        # The kill switch stops copying altogether; a stale copy is then expected, not a reason to refuse.
        return None
    try:
        result = async_to_sync(amirror_conversation)(conversation.id, team_id, conversation.user_id)
    except Exception:
        logger.exception("conversation_copy_before_run_failed", extra={"task_id": task_id})
        return COPY_BEHIND_MESSAGE
    # Content the copy cannot read stays uncopied on every retry, so it must not hold the run back.
    if result.skipped_reason not in (None, "no_messages", "unsupported_content"):
        return COPY_BEHIND_MESSAGE
    return None


def mark_conversation_sandbox_on_first_run(sender: type, instance: Any, created: bool, **kwargs: Any) -> None:
    # Runs on every TaskRun save (a hot model): cheapest checks first, and never raise into tasks' save path.
    state = instance.state or {}
    # A warm run only prepares a sandbox; the chat moves when a run carries a message.
    if not created or state.get("imported_from") or state.get("await_user_message"):
        return
    try:
        if instance.task.origin_product != TaskOriginProduct.POSTHOG_AI:
            return
        flags = _feature_flags()
        if flags is None:
            return
        conversations = Conversation.objects.select_related("user", "team").filter(
            task_id=instance.task_id, agent_runtime=Conversation.AgentRuntime.LANGGRAPH
        )
        for conversation in conversations:
            if not flags.has_sandbox_mode_feature_flag(conversation.team, conversation.user):
                # Without the flag the legacy screen cannot send to the sandbox path, so the chat stays put.
                continue
            Conversation.objects.filter(id=conversation.id, agent_runtime=Conversation.AgentRuntime.LANGGRAPH).update(
                agent_runtime=Conversation.AgentRuntime.SANDBOX
            )
    except Exception:
        logger.exception("conversation_follows_task_run_failed", extra={"run_id": str(instance.id)})
