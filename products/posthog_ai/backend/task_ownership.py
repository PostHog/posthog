from uuid import UUID

from django.db.models import Q

from products.posthog_ai.backend.models.assistant import Conversation


def detach_conversations_for_task_handoff(task_id: UUID, new_owner_id: int | None) -> int:
    """Detach conversations that must remain private to a previous task owner."""
    conversations = Conversation.objects.filter(Q(task_id=task_id) | Q(sandbox_task_id=task_id))
    if new_owner_id is not None:
        conversations = conversations.exclude(user_id=new_owner_id)
    return conversations.update(task=None, sandbox_task_id=None, sandbox_run_id=None)
