from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from django.db import transaction

import structlog

from ee.models.assistant import Conversation

logger = structlog.get_logger(__name__)


@contextmanager
def lock_conversation_for_followup(conversation_id: str, team_id: int) -> Iterator[Conversation]:
    """Serialize concurrent sandbox follow-ups for a single conversation (02_CORE.md § 12 #6 / § 9).

    Two browser tabs that both POST a follow-up to the same conversation while its current Run is
    terminal can each resolve "terminal → create successor Run" and end up creating two Runs. If
    products/tasks' Run-create is not idempotent on `(conversation, resume_from_run_id)`, that race
    produces duplicate Runs. This helper takes a row-level `SELECT FOR UPDATE` on the `Conversation`
    so the second tab blocks until the first commits, then re-reads the (now-updated) run pointer
    and skips the duplicate create.

    Usage (to be wired into the `POST /sandbox/` follow-up branch when I2.5 lands)::

        with lock_conversation_for_followup(conversation_id, team_id) as conversation:
            # re-resolve run pointer from `conversation` here (it reflects any concurrent winner)
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
            sandbox_run_id=str(conversation.sandbox_run_id) if conversation.sandbox_run_id else None,
        )
        yield conversation
