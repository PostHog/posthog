"""Keep a copied chat and its task in step once the task runs for real.

Both hooks connect through the tasks facade so no model class crosses the product boundary.

- Before a run starts: the copy runs a few seconds behind the chat, so a run started in that window
  would resume without the last turn. The guard copies what is still missing and refuses the run
  when it cannot, or when the chat's owner is not on the sandbox runtime yet.
- After a run is saved: the first run that is not the import run marks the chat as sandbox, whichever
  path created it. From then on the legacy chat screen routes the conversation through the sandbox
  path too, so a chat can never fork back into LangGraph after it has been continued as a task.
- When tasks are read: a user without the sandbox runtime does not see the copies of their chats. The
  copy is written for everyone so the switch is instant later, but until then their chats are chats.
"""

import logging
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from asgiref.sync import async_to_sync

from posthog.models import Team, User

from products.posthog_ai.backend.models.assistant import Conversation
from products.tasks.backend.facade.task_run_signals import (
    TaskOriginProduct,
    connect_task_run_post_save,
    register_task_read_exclusion,
    register_task_run_start_guard,
)

logger = logging.getLogger(__name__)

COPY_BEHIND_MESSAGE = "This chat is still being copied into the task. Try again in a moment."
SANDBOX_MODE_REQUIRED_MESSAGE = "Continuing this chat as a task is not available to you yet."


def connect() -> None:
    register_task_read_exclusion(copied_chats_hidden_without_sandbox_mode, name="posthog_ai_copied_chats")
    register_task_run_start_guard(catch_up_conversation_copy_before_run, name="posthog_ai_conversation_copy")
    connect_task_run_post_save(
        mark_conversation_sandbox_on_first_run, dispatch_uid="posthog_ai_conversation_follows_task_run"
    )


def copied_chats_hidden_without_sandbox_mode(team_id: int, user_id: int | None) -> Iterable[UUID]:
    """The user's tasks that are copies of their LangGraph chats, while they are not on the sandbox runtime.

    Copies are only ever visible to the chat's owner, so the owner's own chats are the whole set.
    """
    from ee.hogai.utils.feature_flags import has_sandbox_mode_feature_flag  # noqa: PLC0415 — see the guard below

    if user_id is None:
        return ()
    team = Team.objects.filter(id=team_id).only("id", "organization_id").first()
    user = User.objects.filter(id=user_id).only("id", "distinct_id").first()
    if team is None or user is None or has_sandbox_mode_feature_flag(team, user):
        return ()
    return Conversation.objects.filter(
        team_id=team_id, user_id=user_id, task_id__isnull=False, agent_runtime=Conversation.AgentRuntime.LANGGRAPH
    ).values_list("task_id", flat=True)


def catch_up_conversation_copy_before_run(task_id: str, team_id: int, user_id: int | None) -> str | None:
    """Copy a LangGraph chat's missing turns into its task before the task's first real run."""
    # Deferred: the copy pulls in the tasks facade and the LangGraph graph, and the flag helpers pull in
    # the LLM clients; this module loads at Django startup and must stay light.
    from products.posthog_ai.backend.conversation_mirror import amirror_conversation  # noqa: PLC0415

    from ee.hogai.utils.feature_flags import (  # noqa: PLC0415
        has_conversation_task_mirror_feature_flag,
        has_sandbox_mode_feature_flag,
    )

    conversation = (
        Conversation.objects.select_related("user", "team")
        .filter(task_id=task_id, team_id=team_id, agent_runtime=Conversation.AgentRuntime.LANGGRAPH, deleted=False)
        .first()
    )
    if conversation is None:
        return None
    if not has_sandbox_mode_feature_flag(conversation.team, conversation.user):
        return SANDBOX_MODE_REQUIRED_MESSAGE
    if not has_conversation_task_mirror_feature_flag(conversation.team, conversation.user):
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
        from ee.hogai.utils.feature_flags import has_sandbox_mode_feature_flag  # noqa: PLC0415 — see the guard above

        conversations = Conversation.objects.select_related("user", "team").filter(
            task_id=instance.task_id, agent_runtime=Conversation.AgentRuntime.LANGGRAPH
        )
        for conversation in conversations:
            if not has_sandbox_mode_feature_flag(conversation.team, conversation.user):
                # Without the flag the legacy screen cannot send to the sandbox path, so the chat stays put.
                continue
            Conversation.objects.filter(id=conversation.id, agent_runtime=Conversation.AgentRuntime.LANGGRAPH).update(
                agent_runtime=Conversation.AgentRuntime.SANDBOX
            )
    except Exception:
        logger.exception("conversation_follows_task_run_failed", extra={"run_id": str(instance.id)})
