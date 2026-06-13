"""Seed a legacy LangGraph conversation onto the sandbox runtime, on demand.

Reads a LangGraph thread's ``state.messages`` (via the shared serializer graph-compile path),
maps each message to an ACP frame with ``langgraph_to_acp.messages_to_acp_frames``, seeds a
synthetic terminal ``TaskRun`` log in S3, links a new ``Task``, and flips the conversation's
``agent_runtime`` to sandbox. The converted thread is read-only-historical: there is no live
agent turn, so the workflow is never started.

The conversion is one-way and lossy by construction (see the migration plan's lossiness
contract). It is idempotent (guarded on ``task_id is None``), serialized under the conversation
row lock so two concurrent opens cannot create two Tasks, and only runs on IDLE conversations so
a live approval is never stranded. The S3 write happens before the atomic flip so a rollback
leaves an orphan log (harmless, GC-able) rather than a flipped conversation with no log.
"""

import time
from collections.abc import Sequence
from typing import Any

import structlog
import posthoganalytics
from asgiref.sync import async_to_sync
from rest_framework import exceptions

from posthog.models.user import User

from products.posthog_ai.backend.helpers import BaseSandboxService
from products.posthog_ai.backend.langgraph_to_acp import (
    METHOD_SESSION_UPDATE,
    METHOD_USER_MESSAGE,
    messages_to_acp_frames,
)
from products.posthog_ai.backend.message_routing import lock_conversation_for_followup
from products.posthog_ai.backend.models.assistant import Conversation
from products.tasks.backend.models import Task, TaskRun

from ee.hogai.api.serializers import aget_conversation_state
from ee.hogai.utils.helpers import should_output_assistant_message

logger = structlog.get_logger(__name__)


class LegacyConversionService(BaseSandboxService):
    """Convert one IDLE LangGraph conversation to a read-only sandbox conversation."""

    def __init__(self, conversation: Conversation, user: User) -> None:
        super().__init__(team=conversation.team, user=user)
        self.conversation = conversation

    def convert_if_needed(self) -> bool:
        """Convert the conversation if it is an eligible, unconverted LangGraph thread.

        Returns True if a conversion was performed, False if it was skipped (already converted,
        not LangGraph, not idle, or another tab won the race). Idempotent and concurrency-safe:
        the decision + writes happen under the conversation row lock.
        """
        if not self._is_eligible(self.conversation):
            return False

        # Read the LangGraph history and build frames outside the lock — the graph-compile +
        # checkpoint replay is read-only and must not hold the row lock while it runs.
        state, _, _ = async_to_sync(aget_conversation_state)(self.conversation, self.team, self.user)
        if state is None:
            logger.info(
                "phai_legacy_conversion_no_state",
                conversation_id=str(self.conversation.id),
            )
            return False

        messages: list[Any] = [m for m in state.messages if should_output_assistant_message(m)]
        return self._seed(messages)

    def _seed(self, messages: Sequence[Any]) -> bool:
        started_at = time.monotonic()
        frames = messages_to_acp_frames(messages)

        task = Task.create_and_run(
            team=self.team,
            title=self._title(),
            description=self.conversation.title or "",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            user_id=self.user.pk,
            repository=None,
            create_pr=False,
            mode="interactive",
            # No live turn: the run only hosts the seeded historical log, never a workflow.
            start_workflow=False,
        )
        task_run = task.latest_run
        if task_run is None:
            raise exceptions.ValidationError("Failed to create sandbox task run for conversion.")

        # Mark the run terminal directly (not via mark_completed) so a synthetic historical run
        # emits no stream/notification side effects. `bootstrapRun` reads this terminal status
        # and treats the converted thread as read-only.
        task_run.status = TaskRun.Status.COMPLETED
        task_run.save(update_fields=["status"])

        # S3 write before the atomic flip — it is an irreversible side effect, so a rollback of
        # the flip below must leave an orphan log rather than a flipped conversation with no log.
        # `ttl_days=None` exempts converted history from the default 30-day expiry.
        task_run.append_log(frames, ttl_days=None)

        # Re-check + flip under the conversation row lock. A concurrent open that already flipped
        # this conversation makes us a no-op (the orphan Task we created is harmless, GC-able).
        with lock_conversation_for_followup(str(self.conversation.id), self.team.pk) as locked:
            if not self._is_eligible(locked):
                logger.info(
                    "phai_legacy_conversion_lost_race",
                    conversation_id=str(self.conversation.id),
                )
                return False
            locked.task = task
            locked.agent_runtime = Conversation.AgentRuntime.SANDBOX
            locked.save(update_fields=["task", "agent_runtime", "updated_at"])

        # Keep the in-memory instance consistent for callers that re-serialize after conversion.
        self.conversation.task = task
        self.conversation.agent_runtime = Conversation.AgentRuntime.SANDBOX

        self._capture_telemetry(messages, frames, started_at)
        return True

    @staticmethod
    def _is_eligible(conversation: Conversation) -> bool:
        """Only convert an unconverted, idle LangGraph conversation."""
        return (
            conversation.agent_runtime == Conversation.AgentRuntime.LANGGRAPH
            and conversation.task_id is None
            and conversation.status == Conversation.Status.IDLE
        )

    def _title(self) -> str:
        return (self.conversation.title or "")[:80]

    def _capture_telemetry(self, messages: Sequence[Any], frames: Sequence[dict[str, Any]], started_at: float) -> None:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        emitted_user = sum(1 for f in frames if _frame_method(f) == METHOD_USER_MESSAGE)
        emitted_session = sum(1 for f in frames if _frame_method(f) == METHOD_SESSION_UPDATE)
        # Per-source-type drop accounting: a source message that produced zero frames was dropped.
        dropped_by_type: dict[str, int] = {}
        for message in messages:
            type_name = type(message).__name__
            if not messages_to_acp_frames([message]):
                dropped_by_type[type_name] = dropped_by_type.get(type_name, 0) + 1

        posthoganalytics.capture(
            distinct_id=str(self.user.distinct_id),
            event="phai_legacy_conversion",
            properties={
                "conversation_id": str(self.conversation.id),
                "messages_total": len(messages),
                "frames_total": len(frames),
                "frames_user_message": emitted_user,
                "frames_session_update": emitted_session,
                "frames_dropped_by_type": dropped_by_type,
                "duration_ms": duration_ms,
            },
            groups={"organization": str(self.team.organization_id)},
        )


def _frame_method(frame: dict[str, Any]) -> str | None:
    notification = frame.get("notification")
    if not isinstance(notification, dict):
        return None
    method = notification.get("method")
    return method if isinstance(method, str) else None
