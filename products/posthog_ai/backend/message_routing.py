"""In-process routing for sandbox-runtime conversation messages.

Entry point for the non-streaming `POST /conversations/{id}/sandbox/` endpoint.
Wraps + dedupes the user message, then starts a `products/tasks` Run (first
message), signals a follow-up on the in-progress Run, or resumes into a new Run
after a terminal Run — all via direct Python calls, never HTTP-to-self and never
a Django SSE relay.
"""

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, cast

from django.db import transaction

import structlog
from pydantic import BaseModel
from rest_framework import exceptions, status

from posthog.exceptions import Conflict
from posthog.models.user import User
from posthog.storage import object_storage

from products.posthog_ai.backend.context_wrapper import (
    ALLOWED_TYPES,
    MAX_ATTACHED_ITEMS,
    MAX_TEXT_LENGTH,
    AttachedContext,
    ContextService,
)
from products.posthog_ai.backend.helpers import BaseSandboxService
from products.posthog_ai.backend.models.assistant import Conversation
from products.posthog_ai.backend.run_state import PostHogAIRunState
from products.posthog_ai.backend.system_prompt import PromptService
from products.posthog_ai.backend.wire_types import UnknownFrame, is_user_message_params, parse_log_entry
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.services.agent_command import send_cancel
from products.tasks.backend.temporal.client import execute_task_processing_workflow, signal_task_followup_message

logger = structlog.get_logger(__name__)


class SandboxRouteResult(BaseModel):
    """Outcome of routing one sandbox message — the IDs the frontend opens SSE against."""

    task_id: str
    run_id: str
    trace_id: str | None
    run_status: str
    just_created_run: bool


class SandboxCancelResult(BaseModel):
    """Outcome of cancelling the conversation's current sandbox Run."""

    task_id: str
    run_id: str
    run_status: str


class SandboxCommandError(exceptions.APIException):
    """A control command could not be delivered to the sandbox agent."""

    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Failed to deliver the command to the sandbox agent."
    default_code = "sandbox_command_failed"


@contextmanager
def lock_conversation_for_followup(conversation_id: str, team_id: int) -> Iterator[Conversation]:
    """Serialize concurrent sandbox follow-ups for a single conversation.

    Two browser tabs that both POST a follow-up to the same conversation while its current Run is
    terminal can each resolve "terminal → create successor Run" and end up creating two Runs. If
    products/tasks' Run-create is not idempotent on `(conversation, resume_from_run_id)`, that race
    produces duplicate Runs. This helper takes a row-level `SELECT FOR UPDATE` on the `Conversation`
    so the second tab blocks until the first commits, then re-resolves the current Run (via the
    `task` FK) and skips the duplicate create.

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


class MessageRoutingService(BaseSandboxService):
    """Route a sandbox-runtime conversation message to a products/tasks Run, in-process.

    Branches on the conversation's current Run:
    - No Task yet → first message creates the Task + Run.
    - Current Run in-progress → signal a follow-up onto the live Run.
    - Current Run terminal → resume into a brand-new successor Run.
    """

    # Entity types whose id must be an integer (vs short_id / UUID strings).
    _INTEGER_ID_TYPES: frozenset[str] = frozenset({"dashboard", "action"})

    # Run statuses that accept a follow-up signal without creating a successor Run.
    _IN_PROGRESS_STATUSES: frozenset[str] = frozenset({TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS})

    def __init__(self, conversation: "Conversation", user: User) -> None:
        super().__init__(team=conversation.team, user=user)
        self.conversation = conversation

    def handle(self, data: Mapping[str, Any]) -> SandboxRouteResult:
        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            raise exceptions.ValidationError("`content` is required.")

        trace_id = data.get("trace_id")
        attached_context = self._validate_attached_context(data.get("attached_context"))

        if self.conversation.task_id is None:
            return self._handle_first_message(
                content=content,
                trace_id=trace_id,
                attached_context=attached_context,
            )

        current_run = self.conversation.current_run
        if current_run is None:
            # The Task lost all of its Runs (e.g. cleanup) — there is nothing to
            # follow up on or resume from. Surface a recoverable error.
            raise exceptions.ValidationError("This conversation has no active run to continue.")

        # Dedupe against every entity already named earlier in the conversation.
        context_service = ContextService()
        prior_seen = self._collect_seen_entity_refs(current_run)
        deduped = context_service.prune_repeated_entity_refs(attached_context, prior=prior_seen)
        wrapped = context_service.wrap_user_message(content, deduped)

        if current_run.status in self._IN_PROGRESS_STATUSES:
            return self._handle_in_progress_followup(
                run=current_run,
                wrapped=wrapped,
                trace_id=trace_id,
                attached_context=attached_context,
            )

        return self._handle_terminal_resume(
            run=current_run,
            wrapped=wrapped,
            trace_id=trace_id,
            attached_context=attached_context,
        )

    def cancel(self) -> SandboxCancelResult:
        """Cancel the conversation's current sandbox Run in-process.

        Delegates to the products/tasks command path with `{"method": "cancel"}` —
        the same control command PostHog Code issues. Returns the resulting
        `run_status`; the frontend SSE then receives a terminal `task_run_state`.
        """
        if self.conversation.task_id is None:
            raise exceptions.ValidationError("This conversation has no backing task to cancel.")

        run = self.conversation.current_run
        if run is None:
            raise exceptions.ValidationError("This conversation has no active run to cancel.")

        if run.is_terminal:
            # Nothing to cancel — report the already-terminal status idempotently.
            return SandboxCancelResult(
                task_id=str(self.conversation.task_id), run_id=str(run.id), run_status=run.status
            )

        result = send_cancel(run)
        if not result.success:
            # Agent unreachable (no sandbox URL, blocked URL, connection error, timeout) —
            # the run is still live, so a 200 here would falsely tell the frontend it's cancelling.
            raise SandboxCommandError(f"Failed to cancel the run: {result.error}")
        run.refresh_from_db(fields=["status"])

        return SandboxCancelResult(task_id=str(self.conversation.task_id), run_id=str(run.id), run_status=run.status)

    def _handle_first_message(
        self,
        *,
        content: str,
        trace_id: str | None,
        attached_context: list[AttachedContext],
    ) -> SandboxRouteResult:
        context_service = ContextService()
        # First turn — the prior-seen set is empty, so dedupe is a no-op.
        deduped = context_service.prune_repeated_entity_refs(attached_context, prior=[])
        wrapped = context_service.wrap_user_message(content, deduped)

        system_prompt = PromptService(self.team, self.user).build()

        task = Task.create_and_run(
            team=self.team,
            title=content[:80],
            description=content,
            origin_product=Task.OriginProduct.POSTHOG_AI,
            user_id=self.user.pk,
            repository=None,
            create_pr=False,
            mode="interactive",
            # Defer the workflow so the initial run state can carry the PostHog AI keys.
            start_workflow=False,
        )

        task_run = task.latest_run
        if task_run is None:
            raise exceptions.ValidationError("Failed to create sandbox task run.")

        # Seed the PostHog AI per-Run state keys. `attached_context` keeps the full,
        # undeduped list. These aren't `create_and_run` arguments, so merge them into the
        # run state here, before the workflow starts and reads it. `exclude_unset` keeps the
        # merge limited to exactly these keys — model defaults must not leak into the bag.
        ph_state = PostHogAIRunState(
            system_prompt=system_prompt,
            attached_context=attached_context,
            initial_permission_mode="default",
            pending_user_message=wrapped,
        )
        run_state: dict[str, Any] = dict(task_run.state or {})
        run_state.update(ph_state.model_dump(mode="json", by_alias=True, exclude_unset=True))
        # Persist the enriched run state and conversation linkage together: a half-write
        # would orphan the run (enriched state, but conversation.task still NULL) and the
        # next retry would look like a fresh first message.
        with transaction.atomic():
            task_run.state = run_state
            task_run.save(update_fields=["state"])
            self.conversation.task = task
            self.conversation.save(update_fields=["task", "updated_at"])

        # Start the run after the commit. `posthog_mcp_scopes="full"` mirrors the legacy
        # first-message path: the agent creates insights, dashboards, and notebooks, so it
        # needs write scopes (the workflow client otherwise defaults to read-only). If the
        # start fails, un-link the conversation so the user's retry is a fresh first message
        # rather than a follow-up onto a run that never started.
        try:
            execute_task_processing_workflow(
                task_id=str(task.id),
                run_id=str(task_run.id),
                team_id=self.team.id,
                user_id=self.user.pk,
                create_pr=False,
                posthog_mcp_scopes="full",
            )
        except Exception:
            self.conversation.task = None
            self.conversation.save(update_fields=["task", "updated_at"])
            raise

        return SandboxRouteResult(
            task_id=str(task.id),
            run_id=str(task_run.id),
            trace_id=trace_id,
            run_status=task_run.status,
            just_created_run=True,
        )

    def _handle_in_progress_followup(
        self,
        *,
        run: TaskRun,
        wrapped: str,
        trace_id: str | None,
        attached_context: list[AttachedContext],
    ) -> SandboxRouteResult:
        """Follow-up while the current Run is queued / in-progress.

        Signal the live Temporal workflow in-process — no new Run, no SSE re-open.
        The full undeduped context is recorded on the logged message's
        `_meta.attached_context` so the persisted ACP log stays a complete record.
        """
        signal_task_followup_message(run.workflow_id, wrapped, artifact_ids=[])

        self._log_user_message(run, wrapped, attached_context)

        return SandboxRouteResult(
            task_id=str(self.conversation.task_id),
            run_id=str(run.id),
            trace_id=trace_id,
            run_status=run.status,
            just_created_run=False,
        )

    def _handle_terminal_resume(
        self,
        *,
        run: TaskRun,
        wrapped: str,
        trace_id: str | None,
        attached_context: list[AttachedContext],
    ) -> SandboxRouteResult:
        """Follow-up after the current Run reached a terminal status.

        Resume into a brand-new successor Run on the same Task, then start its
        workflow. `current_run` resolves to the new Run via the Task's reverse
        relation — the conversation's `task` FK is unchanged.

        The successor create runs under a row lock on the Conversation: two
        concurrent follow-ups that both saw the terminal Run would otherwise
        each create a successor. The loser blocks on the lock, re-resolves the
        current Run, and surfaces a 409 instead of duplicating the create; the
        workflow dispatch stays outside the lock's transaction so a rollback
        cannot leave an orphaned workflow behind.
        """
        task = self.conversation.task
        if task is None:
            raise exceptions.ValidationError("This conversation has no backing task to resume.")

        system_prompt = PromptService(self.team, self.user).build()

        with lock_conversation_for_followup(str(self.conversation.id), self.team.pk) as locked:
            current = locked.current_run
            if current is not None and current.status in self._IN_PROGRESS_STATUSES:
                raise Conflict("A concurrent message already resumed this conversation. Send the message again.")
            if current is not None:
                # The freshest terminal Run is the resume source — a concurrent winner's
                # successor may itself have finished while this request waited on the lock.
                run = current

            extra_state: dict[str, Any] = {
                "resume_from_run_id": str(run.id),
                "pending_user_message": wrapped,
                "systemPrompt": system_prompt,
                # The full, undeduped list — survives for the life of the new Run.
                "attached_context": attached_context,
                "initial_permission_mode": "default",
            }
            # Carry the prior Run's snapshot forward so the resume reuses its filesystem.
            snapshot_external_id = (run.state or {}).get("snapshot_external_id")
            if snapshot_external_id:
                extra_state["snapshot_external_id"] = snapshot_external_id

            new_run = task.create_run(mode="interactive", extra_state=extra_state)

        # Same write scopes as the first message — the resumed agent keeps creating
        # insights/dashboards/notebooks on follow-up turns.
        execute_task_processing_workflow(
            task_id=str(task.id),
            run_id=str(new_run.id),
            team_id=self.team.id,
            user_id=self.user.pk,
            create_pr=False,
            posthog_mcp_scopes="full",
        )

        return SandboxRouteResult(
            task_id=str(task.id),
            run_id=str(new_run.id),
            trace_id=trace_id,
            run_status=new_run.status,
            just_created_run=True,
        )

    def _collect_seen_entity_refs(self, run: TaskRun) -> list[tuple[str, str | int]]:
        """Collect `(type, id)` pairs for entities already named in the conversation.

        Walks the Run's `state.attached_context` (the first message's full list) plus
        every prior `_posthog/user_message` log entry's `_meta.attached_context`
        across the entire resume chain. One S3 read per chain run; `text` items are
        never deduped so they're skipped.
        """
        seen: list[tuple[str, str | int]] = []

        def _absorb(items: Any) -> None:
            if not isinstance(items, list):
                return
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type")
                item_id = item.get("id")
                if item_type in ALLOWED_TYPES and item_type != "text" and item_id is not None:
                    seen.append((item_type, item_id))

        for chain_run in run.get_resume_chain():
            _absorb((chain_run.state or {}).get("attached_context"))
            log_content = object_storage.read(chain_run.log_url, missing_ok=True) or ""
            for line in log_content.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue
                frame = parse_log_entry(data)
                if isinstance(frame, UnknownFrame):
                    continue
                notification = frame.notification
                if not is_user_message_params(notification.params, notification.method):
                    continue
                meta = notification.params.get("_meta")
                if isinstance(meta, dict):
                    _absorb(meta.get("attached_context"))

        return seen

    def _log_user_message(self, run: TaskRun, wrapped: str, attached_context: list[AttachedContext]) -> None:
        """Append a `_posthog/user_message` entry to the Run's ACP log.

        Records the wrapped content plus the full undeduped `attached_context` under
        `_meta` so the persisted log is a complete per-message record that
        `_collect_seen_entity_refs` reads on later follow-ups.
        """
        entry = {
            "notification": {
                "method": "_posthog/user_message",
                "params": {
                    "content": wrapped,
                    "_meta": {"attached_context": attached_context},
                },
            }
        }
        run.append_log([entry])

    def _validate_attached_context(self, raw: Any) -> list[AttachedContext]:
        """Validate user-supplied attached context at the boundary.

        Existence is intentionally NOT validated — the agent's read tool surfaces a
        missing-row error naturally, which is cheaper than a sync DB lookup per submit.
        """
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise exceptions.ValidationError("`attached_context` must be a list.")
        if len(raw) > MAX_ATTACHED_ITEMS:
            raise exceptions.ValidationError(f"`attached_context` cannot exceed {MAX_ATTACHED_ITEMS} items.")

        validated: list[AttachedContext] = []
        for item in raw:
            if not isinstance(item, dict):
                raise exceptions.ValidationError("Each `attached_context` item must be an object.")
            item_type = item.get("type")
            if item_type not in ALLOWED_TYPES:
                raise exceptions.ValidationError(f"Unsupported attached_context type: {item_type!r}.")

            if item_type == "text":
                value = item.get("value")
                if not isinstance(value, str):
                    raise exceptions.ValidationError("`text` attachments require a string `value`.")
                if len(value) > MAX_TEXT_LENGTH:
                    raise exceptions.ValidationError(f"`text` value cannot exceed {MAX_TEXT_LENGTH} characters.")
                validated.append(cast(AttachedContext, {"type": "text", "value": value}))
                continue

            item_id = item.get("id")
            item_id = self._validate_entity_id(item_type, item_id)
            entity: AttachedContext = {"type": item_type, "id": item_id}
            name = item.get("name")
            if isinstance(name, str) and name:
                if len(name) > MAX_TEXT_LENGTH:
                    raise exceptions.ValidationError(f"`name` cannot exceed {MAX_TEXT_LENGTH} characters.")
                entity["name"] = name
            validated.append(entity)

        return validated

    def _validate_entity_id(self, item_type: str, item_id: Any) -> str | int:
        if item_type in self._INTEGER_ID_TYPES:
            if isinstance(item_id, bool) or not isinstance(item_id, int):
                raise exceptions.ValidationError(f"`{item_type}` id must be an integer.")
            return item_id

        if not isinstance(item_id, str) or not item_id:
            raise exceptions.ValidationError(f"`{item_type}` id must be a non-empty string.")
        if len(item_id) > MAX_TEXT_LENGTH:
            raise exceptions.ValidationError(f"`{item_type}` id cannot exceed {MAX_TEXT_LENGTH} characters.")
        return item_id
