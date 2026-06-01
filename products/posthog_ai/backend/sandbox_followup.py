from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from django.db import transaction

import structlog

from products.posthog_ai.backend.models.assistant import Conversation

logger = structlog.get_logger(__name__)


@contextmanager
def lock_conversation_for_followup(conversation_id: str, team_id: int) -> Iterator[Conversation]:
    """Serialize concurrent sandbox follow-ups for a single conversation.

    Two browser tabs that both POST a follow-up to the same conversation while its current Run is
    terminal can each resolve "terminal → create successor Run" and end up creating two Runs. If
    products/tasks' Run-create is not idempotent on `(conversation, resume_from_run_id)`, that race
    produces duplicate Runs. This helper takes a row-level `SELECT FOR UPDATE` on the `Conversation`
    so the second tab blocks until the first commits, then re-resolves the current Run (via the
    `task` FK) and skips the duplicate create.

    Usage (to be wired into the sandbox follow-up branch of the message-routing path)::

        with lock_conversation_for_followup(conversation_id, team_id) as conversation:
            # re-resolve `conversation.current_run` here (it reflects any concurrent winner)
            # ...resolve run + create successor Run...

    Keep the block narrow — no external side effects (Temporal dispatch, agent-server calls) inside
    it. Schedule those after the transaction commits (e.g. `transaction.on_commit`), so a rollback
    cannot leave an orphaned workflow.
    """
    with transaction.atomic():
        # nosemgrep: idor-lookup-without-team (team_id is part of the lookup below)
        conversation = Conversation.objects.select_for_update().get(id=conversation_id, team_id=team_id)
        logger.debug(
            "sandbox_followup_lock_acquired",
            conversation_id=conversation_id,
            task_id=str(conversation.task_id) if conversation.task_id else None,
        )
        yield conversation
