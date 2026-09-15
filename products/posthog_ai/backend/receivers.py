"""Mark a conversation as sandbox once its task runs for real.

A `post_save` receiver on task runs, connected through the tasks facade so no model class
crosses the product boundary. A LangGraph conversation that the mirror copied into a task stays on the
LangGraph runtime until someone continues it as a task, from the legacy chat screen, the task
page, or Desktop. The first run that is not the import run is that moment, whichever path created
it. From then on the legacy chat screen routes the conversation through the sandbox path too, so a
chat can never fork back into LangGraph after it has been continued as a task.
"""

import logging
from typing import Any

from products.posthog_ai.backend.models.assistant import Conversation
from products.tasks.backend.facade.api import TaskOriginProduct
from products.tasks.backend.facade.task_run_signals import connect_task_run_post_save

logger = logging.getLogger(__name__)


def connect() -> None:
    connect_task_run_post_save(
        mark_conversation_sandbox_on_first_run, dispatch_uid="posthog_ai_conversation_follows_task_run"
    )


def mark_conversation_sandbox_on_first_run(sender: type, instance: Any, created: bool, **kwargs: Any) -> None:
    # Runs on every TaskRun save (a hot model): cheapest checks first, and never raise into tasks' save path.
    if not created or (instance.state or {}).get("imported_from"):
        return
    try:
        if instance.task.origin_product != TaskOriginProduct.POSTHOG_AI:
            return
        Conversation.objects.filter(task_id=instance.task_id, agent_runtime=Conversation.AgentRuntime.LANGGRAPH).update(
            agent_runtime=Conversation.AgentRuntime.SANDBOX
        )
    except Exception:
        logger.exception("conversation_follows_task_run_failed", extra={"run_id": str(instance.id)})
