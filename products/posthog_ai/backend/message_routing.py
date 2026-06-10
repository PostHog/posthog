"""In-process routing for sandbox-runtime conversation messages.

Entry point for the non-streaming `POST /conversations/{id}/sandbox/` endpoint.
Wraps + dedupes the user message, then starts a `products/tasks` Run (first
message) via direct Python calls — never HTTP-to-self, never a Django SSE relay.

Follow-up and terminal-resume branches are out of scope for this pass (I2.5).
"""

from typing import TYPE_CHECKING, Any, cast

from django.db import transaction

from rest_framework import exceptions, status
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.event_usage import report_user_action
from posthog.models.user import User

from products.posthog_ai.backend.context_wrapper import (
    ALLOWED_TYPES,
    MAX_ATTACHED_ITEMS,
    MAX_TEXT_LENGTH,
    AttachedContext,
    ContextService,
)
from products.posthog_ai.backend.helpers import BaseSandboxService
from products.posthog_ai.backend.system_prompt import PromptService
from products.tasks.backend.models import Task
from products.tasks.backend.temporal.client import execute_task_processing_workflow

if TYPE_CHECKING:
    from products.posthog_ai.backend.models.assistant import Conversation


class MessageRoutingService(BaseSandboxService):
    """Route a sandbox-runtime conversation message to a products/tasks Run, in-process.

    First-message branch only (`conversation.task` is NULL). Follow-up and
    terminal-resume branches are out of scope (I2.5).
    """

    # Entity types whose id must be an integer (vs short_id / UUID strings).
    _INTEGER_ID_TYPES: frozenset[str] = frozenset({"dashboard", "action"})

    def __init__(self, request: Request, conversation: "Conversation") -> None:
        super().__init__(team=conversation.team, user=cast(User, request.user))
        self.request = request
        self.conversation = conversation

    def handle(self) -> Response:
        content = self.request.data.get("content")
        if not isinstance(content, str) or not content.strip():
            raise exceptions.ValidationError("`content` is required.")

        trace_id = self.request.data.get("trace_id")
        attached_context = self._validate_attached_context(self.request.data.get("attached_context"))

        if self.conversation.task_id is not None:
            # Follow-up / terminal-resume branches land here once I2.5 implements them.
            raise exceptions.ValidationError("Follow-up messages are not yet supported on the sandbox runtime.")

        return self._handle_first_message(
            content=content,
            trace_id=trace_id,
            attached_context=attached_context,
        )

    def _handle_first_message(
        self,
        *,
        content: str,
        trace_id: str | None,
        attached_context: list[AttachedContext],
    ) -> Response:
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
        # run state here, before the workflow starts and reads it.
        run_state: dict[str, Any] = dict(task_run.state or {})
        run_state.update(
            {
                "systemPrompt": system_prompt,
                "attached_context": attached_context,
                "initial_permission_mode": "default",
                "pending_user_message": wrapped,
            }
        )
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
        # rather than the not-yet-supported follow-up branch.
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

        report_user_action(
            self.user,
            "prompt sent",
            {
                "trace_id": trace_id,
                "conversation_id": str(self.conversation.id),
                "execution_type": "sandbox",
                "just_created_run": True,
            },
            team=self.team,
            request=self.request,
        )

        return Response(
            {
                "task_id": str(task.id),
                "run_id": str(task_run.id),
                "trace_id": trace_id,
                "run_status": task_run.status,
                "just_created_run": True,
            },
            status=status.HTTP_200_OK,
        )

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
