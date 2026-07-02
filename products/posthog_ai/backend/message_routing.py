"""In-process session opener for the sandbox runtime.

`SandboxSession.open()` resolves a sandbox conversation to a `products/tasks`
`(task, run)` and drives one turn — warming when there's no message, starting the
first Run, signaling a follow-up onto the live Run, or resuming into a successor
after a terminal Run — all via direct Python calls, never HTTP-to-self and never a
Django SSE relay. Control verbs (cancel, permission reply, warm release) go through
the generic `runs/{run}/command/` relay, not this module.
"""

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast

from django.db import transaction

import structlog
from pydantic import BaseModel
from rest_framework import exceptions

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
from products.posthog_ai.backend.services.system_prompt.service import PromptService
from products.posthog_ai.backend.wire_types import UnknownFrame, is_user_message_params, parse_log_entry
from products.tasks.backend.facade import (
    api as tasks_facade,
    warm as warm_facade,
)
from products.tasks.backend.facade.run_config import INITIAL_PERMISSION_MODE_CHOICES, InitialPermissionMode
from products.tasks.backend.facade.temporal import execute_task_processing_workflow, signal_task_followup_message

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun

logger = structlog.get_logger(__name__)

DEFAULT_INITIAL_PERMISSION_MODE: InitialPermissionMode = "auto"
POSTHOG_AI_INTERACTION_ORIGIN = tasks_facade.TaskOriginProduct.POSTHOG_AI.value

# A PostHog AI sandbox session is a live chat: if the user goes quiet for this long
# they've moved on, so the Run's workflow times out and reclaims the sandbox. Passed
# as the per-task `inactivity_timeout_seconds` override on every Run we create, so the
# workflow's idle timer and the SSE relay's freshness window both honor it (both read
# it from Run state). Shorter than the generic user-origin default, which assumes a
# human may still return much later.
SANDBOX_INACTIVITY_TIMEOUT_SECONDS = 10 * 60


class SandboxRouteResult(BaseModel):
    """Outcome of routing one sandbox message — the IDs the frontend opens SSE against."""

    task_id: str
    run_id: str
    trace_id: str | None
    run_status: str
    just_created_run: bool
    # Count of attached context items the message carried, for the routing endpoint's telemetry.
    attached_context_count: int = 0


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


class SandboxSession(BaseSandboxService):
    """Resolve a sandbox conversation to a products/tasks `(task, run)` and drive one turn in-process.

    The session opener for the sandbox runtime. `open()` either warms (no message), starts the first
    Run, signals a follow-up onto the live Run, or resumes into a successor after a terminal Run.
    Control verbs (cancel, permission reply, warm release) are not here — they go through the generic
    `runs/{run}/command/` relay.
    """

    # Entity types whose id must be an integer (vs short_id / UUID strings).
    _INTEGER_ID_TYPES: frozenset[str] = frozenset({"dashboard", "action"})

    # Run statuses that accept a follow-up signal without creating a successor Run.
    _IN_PROGRESS_STATUSES: frozenset[str] = frozenset(
        {tasks_facade.TaskRunStatus.QUEUED, tasks_facade.TaskRunStatus.IN_PROGRESS}
    )

    def __init__(self, conversation: "Conversation", user: User) -> None:
        super().__init__(team=conversation.team, user=user)
        self.conversation: Conversation = conversation

    def open(
        self,
        data: Mapping[str, Any],
        *,
        resumed_context: str | None = None,
        convert_to_acp: bool = False,
        repository: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> SandboxRouteResult | None:
        """Route one sandbox turn. `model` / `reasoning_effort` only apply when this call creates a
        new Run (first message or resume after a terminal Run) — a follow-up signaled onto an
        already-running Run keeps that Run's model, so they're not threaded into that path."""
        initial_permission_mode = self._initial_permission_mode(data.get("initial_permission_mode"))
        content = data.get("content")
        if not isinstance(content, str) or not content.strip():
            # No message — warm intent: boot a Run that idles awaiting the first `user_message`.
            # Returns the warm handle, or None when the pool is full and nothing was provisioned.
            return self._warm(trace_id=data.get("trace_id"), initial_permission_mode=initial_permission_mode)

        trace_id = data.get("trace_id")
        attached_context = self._validate_attached_context(data.get("attached_context"))

        if self.conversation.task_id is None:
            # `resumed_context` / `convert_to_acp` only apply to the conversion event, which is
            # always a first message (the gate requires `task_id is None`). `repository` is the
            # auto-routed repo for this first message — followups/resumes reuse the existing Task.
            return self._handle_first_message(
                content=content,
                trace_id=trace_id,
                attached_context=attached_context,
                initial_permission_mode=initial_permission_mode,
                resumed_context=resumed_context,
                convert_to_acp=convert_to_acp,
                repository=repository,
                model=model,
                reasoning_effort=reasoning_effort,
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
            initial_permission_mode=initial_permission_mode,
            model=model,
            reasoning_effort=reasoning_effort,
        )

    def _initial_permission_mode(self, value: Any) -> InitialPermissionMode:
        if isinstance(value, str) and value in INITIAL_PERMISSION_MODE_CHOICES:
            return cast(InitialPermissionMode, value)
        return DEFAULT_INITIAL_PERMISSION_MODE

    def _warm(
        self, *, trace_id: str | None, initial_permission_mode: InitialPermissionMode
    ) -> SandboxRouteResult | None:
        """Boot a sandbox Run ahead of the first message (the message-less `open`).

        Ensures the conversation's Task exists under the row lock (so two tabs can't create two
        Tasks), then hands provisioning to the tasks warming facade, which enforces the AI-credit
        quota + warm-pool cap, serializes on the Task row, and dispatches the workflow after commit.
        Returns the warm Run's handle so the caller can open SSE / later release it through the relay;
        returns None when the pool is full and nothing was provisioned (best-effort — the AI-credit
        quota still surfaces as 402). Idempotent: an existing non-terminal Run is reused, not duplicated.
        """
        # Gate before creating the Task: an over-quota or over-cap warm must not leave the conversation
        # with a runless Task that the next message can't continue. The facade re-checks both.
        warm_facade.enforce_warm_quota(tasks_facade.TaskOriginProduct.POSTHOG_AI, self.team.pk, self.user.pk)
        if warm_facade.warm_pool_at_capacity(tasks_facade.TaskOriginProduct.POSTHOG_AI, self.team.pk, self.user.pk):
            logger.info(
                "sandbox_warm_capacity_reached",
                conversation_id=str(self.conversation.id),
                user_id=self.user.pk,
            )
            return None

        system_prompt = PromptService(self.team, self.user).build()

        with lock_conversation_for_followup(str(self.conversation.id), self.team.pk) as locked:
            task_id = locked.task_id
            if task_id is None:
                task_id = tasks_facade.create_task_without_run(
                    team=self.team,
                    user_id=self.user.pk,
                    origin_product=tasks_facade.TaskOriginProduct.POSTHOG_AI,
                    repository=None,
                )
                locked.task_id = task_id
                locked.save(update_fields=["task", "updated_at"])

        # Conversation lock released. The facade provisions under its own Task-row lock and
        # dispatches the workflow on commit; it is idempotent (an existing non-terminal Run is returned
        # as-is). `systemPrompt` is the one PostHog AI-specific Run-state key the generic warmer can't know.
        try:
            result = warm_facade.warm_task_run(
                task_id,
                self.team.pk,
                self.user.pk,
                extra_state={
                    "interaction_origin": POSTHOG_AI_INTERACTION_ORIGIN,
                    "systemPrompt": system_prompt,
                    "initial_permission_mode": initial_permission_mode,
                    "inactivity_timeout_seconds": SANDBOX_INACTIVITY_TIMEOUT_SECONDS,
                },
            )
        except exceptions.Throttled:
            # Warm-pool cap reached between the pre-check and the lock — best-effort no-op (no handle).
            logger.info(
                "sandbox_warm_capacity_reached",
                conversation_id=str(self.conversation.id),
                user_id=self.user.pk,
            )
            return None

        return SandboxRouteResult(
            task_id=str(task_id),
            run_id=str(result.run_id),
            trace_id=trace_id,
            run_status=result.run_status,
            just_created_run=result.just_created,
        )

    def _handle_first_message(
        self,
        *,
        content: str,
        trace_id: str | None,
        attached_context: list[AttachedContext],
        initial_permission_mode: InitialPermissionMode,
        resumed_context: str | None = None,
        convert_to_acp: bool = False,
        repository: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> SandboxRouteResult:
        context_service = ContextService()
        # First turn — the prior-seen set is empty, so dedupe is a no-op.
        deduped = context_service.prune_repeated_entity_refs(attached_context, prior=[])
        wrapped = context_service.wrap_user_message(content, deduped)
        if resumed_context:
            # Conversion event: lead the first prompt with the legacy conversation window so the
            # sandbox agent has continuity, then the user's own attachments + message.
            wrapped = f"{resumed_context}\n\n{wrapped}"

        system_prompt = PromptService(self.team, self.user).build()

        # Only forward a caller-selected model / reasoning effort, so an unset selection keeps
        # `Task.create_and_run`'s own defaults instead of being clobbered by an explicit `None`.
        runtime_selection: dict[str, str] = {}
        if model is not None:
            runtime_selection["model"] = model
        if reasoning_effort is not None:
            runtime_selection["reasoning_effort"] = reasoning_effort

        created = tasks_facade.create_and_run_task(
            team=self.team,
            title=content[:80],
            description=content,
            origin_product=tasks_facade.TaskOriginProduct.POSTHOG_AI,
            user_id=self.user.pk,
            repository=repository,
            create_pr=False,
            mode="interactive",
            interaction_origin=POSTHOG_AI_INTERACTION_ORIGIN,
            inactivity_timeout_seconds=SANDBOX_INACTIVITY_TIMEOUT_SECONDS,
            # Defer the workflow so the initial run state can carry the PostHog AI keys.
            start_workflow=False,
            **runtime_selection,
        )

        run_dto = created.latest_run
        if run_dto is None:
            raise exceptions.ValidationError("Failed to create sandbox task run.")

        # Seed the PostHog AI per-Run state keys. `attached_context` keeps the full,
        # undeduped list. These aren't `create_and_run` arguments, so merge them into the
        # run state here, before the workflow starts and reads it. `exclude_unset` keeps the
        # merge limited to exactly these keys — model defaults must not leak into the bag.
        ph_state = PostHogAIRunState(
            system_prompt=system_prompt,
            attached_context=attached_context,
            initial_permission_mode=initial_permission_mode,
            interaction_origin=POSTHOG_AI_INTERACTION_ORIGIN,
            pending_user_message=wrapped,
        )
        state_updates = ph_state.model_dump(mode="json", by_alias=True, exclude_unset=True)
        # Persist the enriched run state and conversation linkage together, under the row lock so a
        # concurrent first message / conversion in another tab can't double-link. Re-check
        # `task_id is None` inside the lock; a half-write would orphan the run (enriched state, but
        # conversation.task still NULL) and the next retry would look like a fresh first message. On
        # a conversion, the runtime flip to sandbox happens here too, atomically with the link.
        with lock_conversation_for_followup(str(self.conversation.id), self.team.pk) as locked:
            if locked.task_id is not None:
                raise Conflict("This conversation was just resumed in another tab. Please try again.")
            tasks_facade.update_task_run_state(run_dto.id, updates=state_updates)
            locked.task_id = created.task_id
            update_fields = ["task", "updated_at"]
            if convert_to_acp:
                locked.agent_runtime = Conversation.AgentRuntime.SANDBOX
                update_fields = ["task", "agent_runtime", "updated_at"]
            locked.save(update_fields=update_fields)

        # Mirror the committed writes onto the in-memory instance for the response + the rollback below.
        self.conversation.task_id = created.task_id
        if convert_to_acp:
            self.conversation.agent_runtime = Conversation.AgentRuntime.SANDBOX

        # Start the run after the commit. `posthog_mcp_scopes="full"` mirrors the legacy
        # first-message path: the agent creates insights, dashboards, and notebooks, so it
        # needs write scopes (the workflow client otherwise defaults to read-only). If the
        # start fails, un-link the conversation so the user's retry is a fresh first message
        # rather than a follow-up onto a run that never started; on a conversion, also revert the
        # runtime flip so the user is left on a clean idle LangGraph conversation.
        try:
            execute_task_processing_workflow(
                task_id=str(created.task_id),
                run_id=str(run_dto.id),
                team_id=self.team.id,
                user_id=self.user.pk,
                create_pr=False,
                posthog_mcp_scopes="full",
            )
        except Exception:
            self.conversation.task_id = None
            revert_fields = ["task", "updated_at"]
            if convert_to_acp:
                self.conversation.agent_runtime = Conversation.AgentRuntime.LANGGRAPH
                revert_fields = ["task", "agent_runtime", "updated_at"]
            self.conversation.save(update_fields=revert_fields)
            raise

        return SandboxRouteResult(
            task_id=str(created.task_id),
            run_id=str(run_dto.id),
            trace_id=trace_id,
            run_status=run_dto.status,
            just_created_run=True,
            attached_context_count=len(attached_context),
        )

    def _handle_in_progress_followup(
        self,
        *,
        run: "TaskRun",
        wrapped: str,
        trace_id: str | None,
        attached_context: list[AttachedContext],
    ) -> SandboxRouteResult:
        """Follow-up while the current Run is queued / in-progress.

        Signal the live Temporal workflow in-process — no new Run, no SSE re-open.
        The full undeduped context is recorded on the logged message's
        `_meta.attached_context` so the persisted ACP log stays a complete record.
        """
        try:
            signal_task_followup_message(run.workflow_id, wrapped, artifact_ids=[])
        except Exception as e:
            # Status race: the run still reads in-progress but its workflow has already finished or
            # was terminated, so the signal can't be delivered. Surface a recoverable conflict
            # instead of an unhandled 500, and don't log the turn — a retry then routes cleanly
            # without leaving a duplicated `_posthog/user_message` entry behind.
            logger.warning(
                "sandbox_followup_signal_failed",
                run_id=str(run.id),
                workflow_id=run.workflow_id,
                error=str(e),
            )
            raise Conflict("The sandbox run is no longer accepting messages. Please try again.") from e

        # The Run has received its first human message, so it is no longer speculative — drop the
        # warm flag so the warm-pool cap stops counting it (it's now an active Run governed by AI
        # credits). Best-effort: a failure only over-counts the warm pool until the Run terminates,
        # and the key is simply absent on Runs that were never warm (the remove is then a no-op).
        try:
            tasks_facade.update_task_run_state(run.id, remove_keys=["await_user_message"])
        except Exception as e:
            logger.warning("sandbox_followup_activation_flip_failed", run_id=str(run.id), error=str(e))

        try:
            # Persist only after the signal was accepted, so the log never records a message the
            # agent never received.
            self._log_user_message(run, wrapped, attached_context)
        except Exception as e:
            # The agent already has the message; a log-append failure must not fail the request —
            # it only degrades context-dedup on the next follow-up.
            logger.warning("sandbox_followup_log_failed", run_id=str(run.id), error=str(e))

        return SandboxRouteResult(
            task_id=str(self.conversation.task_id),
            run_id=str(run.id),
            trace_id=trace_id,
            run_status=run.status,
            just_created_run=False,
            attached_context_count=len(attached_context),
        )

    def _handle_terminal_resume(
        self,
        *,
        run: "TaskRun",
        wrapped: str,
        trace_id: str | None,
        attached_context: list[AttachedContext],
        initial_permission_mode: InitialPermissionMode,
        model: str | None = None,
        reasoning_effort: str | None = None,
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
                "interaction_origin": POSTHOG_AI_INTERACTION_ORIGIN,
                "resume_from_run_id": str(run.id),
                "pending_user_message": wrapped,
                "systemPrompt": system_prompt,
                # The full, undeduped list — survives for the life of the new Run.
                "attached_context": attached_context,
                "initial_permission_mode": initial_permission_mode,
                "inactivity_timeout_seconds": SANDBOX_INACTIVITY_TIMEOUT_SECONDS,
            }
            # Same non-None guard as the first-message path: an unset selection must not overwrite
            # `Task.create_and_run`'s runtime defaults with an explicit `None`.
            if model is not None:
                extra_state["model"] = model
            if reasoning_effort is not None:
                extra_state["reasoning_effort"] = reasoning_effort
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
            attached_context_count=len(attached_context),
        )

    def _collect_seen_entity_refs(self, run: "TaskRun") -> list[tuple[str, str | int]]:
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

    def _log_user_message(self, run: "TaskRun", wrapped: str, attached_context: list[AttachedContext]) -> None:
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
