"""Operations: goals that an external MCP client delegates to PostHog AI.

An operation starts a PostHog AI sandbox conversation with the caller's permission limit, a fixed
project, an optional pinned repository commit, and a structured result schema. Reads reconcile the
operation with its current run, so the state is correct even when no worker reports it.
"""

import json
import base64
import hashlib
import binascii
from datetime import timedelta
from typing import Any

from django.db import IntegrityError, connection, transaction
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.user import User
from posthog.utils import absolute_uri

from products.posthog_ai.backend.message_routing import SandboxDispatchOptions, SandboxSession
from products.posthog_ai.backend.models import AgentOperation, AgentOperationReply, Conversation
from products.posthog_ai.backend.services.agent_operations.delegation import (
    caller_scopes,
    granted_scopes,
    parent_credential,
    parent_credential_active,
)
from products.posthog_ai.backend.services.agent_operations.progress import RunProgress, summarize_run_log
from products.posthog_ai.backend.services.agent_operations.result_schema import (
    AGENT_MCP_INSTRUCTIONS,
    AGENT_RESULT_SCHEMA,
    RESULT_STATUS_COMPLETE,
    RESULT_STATUS_FAILED,
    RESULT_STATUS_NEEDS_INPUT,
)
from products.tasks.backend.facade import (
    api as tasks_facade,
    cancellation as tasks_cancellation,
    repo_selection,
)

logger = structlog.get_logger(__name__)

State = AgentOperation.State

OPERATION_DEADLINE = timedelta(hours=2)
MAX_ACTIVE_OPERATIONS_PER_USER = 3
MAX_STEPS_PER_RESPONSE = 20
RETRY_AFTER_ACTIVE_SECONDS = 10
RETRY_AFTER_IDLE_SECONDS = 30
# One operation stays in one project, so the agent must not switch projects or reach other projects
# through connections.
EXCLUDED_MCP_TOOLS = ["posthog-connection-call", "posthog-connection-forward", "switch-project", "switch-organization"]
# `auto` relays every MCP approval to the client. A client without an approval UI would stall on each
# PostHog tool call, so its runs ask for none: the key's scopes, not per-call approvals, limit the run.
PERMISSION_MODES: dict[str, str] = {
    AgentOperation.Approvals.CLIENT: "auto",
    AgentOperation.Approvals.AUTO: "bypassPermissions",
}
ALLOW_REPLIES = frozenset({"allow", "approve", "approved", "yes", "y", "ok", "go ahead"})
ALLOW_ALWAYS_REPLIES = frozenset({"allow all", "always", "always allow", "allow always"})
DENY_REPLIES = frozenset({"deny", "reject", "no", "n"})


class AgentOperationError(Exception):
    """A request the operation cannot accept. ``code`` and ``status`` go to the client unchanged."""

    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@frozen
class StartRequest:
    goal: str
    client_request_id: str
    context: str | None = None
    conversation_id: str | None = None
    repository: str | None = None
    ref: str | None = None
    approvals: str = AgentOperation.Approvals.AUTO

    def request_hash(self) -> str:
        payload = {
            "goal": self.goal,
            "context": self.context,
            "conversation_id": self.conversation_id,
            "repository": self.repository,
            "ref": self.ref,
            "approvals": self.approvals,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@frozen
class StartOutcome:
    operation: AgentOperation
    created: bool


@frozen
class OperationView:
    """What a status read returns, beyond the stored operation."""

    operation: AgentOperation
    plan: list[dict[str, str]]
    new_steps: list[str]
    cursor: str
    retry_after_seconds: int
    posthog_url: str
    summary: str | None


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _encode_cursor(operation_id: str, position: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": operation_id, "n": position}).encode()).decode()


def _decode_cursor(cursor: str | None, operation_id: str) -> int | None:
    if not cursor:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise AgentOperationError("invalid_cursor", "The cursor is not valid.")
    if not isinstance(data, dict) or data.get("o") != operation_id or not isinstance(data.get("n"), int):
        raise AgentOperationError("invalid_cursor", "The cursor belongs to another operation.")
    return data["n"]


def _normalize_result(output: dict[str, Any]) -> dict[str, Any]:
    def links(items: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
        normalized = []
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict):
                entry: dict[str, str | None] = {key: str(item.get(key) or "") for key in keys}
                entry["url"] = str(item.get("url") or "") or None
                normalized.append(entry)
        return normalized

    def strings(items: Any) -> list[str]:
        return [str(item) for item in items if isinstance(item, str)] if isinstance(items, list) else []

    return {
        "status": output.get("status"),
        "answer": str(output.get("answer") or ""),
        "question": str(output.get("question") or "") or None,
        "assumptions": strings(output.get("assumptions")),
        "evidence": links(output.get("evidence"), ("label",)),
        "artifacts": links(output.get("artifacts"), ("type", "name")),
        "follow_ups": strings(output.get("follow_ups")),
    }


class AgentOperationService:
    def __init__(self, team: Team, user: User) -> None:
        self.team = team
        self.user = user

    # --- start ---

    def start(self, request: StartRequest, *, authenticator: object) -> StartOutcome:
        request_hash = request.request_hash()
        existing = self._existing(request.client_request_id, request_hash)
        if existing is not None:
            return StartOutcome(operation=existing, created=False)

        conversation = self._conversation_to_continue(request.conversation_id)
        repository, commit = self._resolve_repository(request, conversation)
        scopes = granted_scopes(caller_scopes(authenticator))
        parent = parent_credential(authenticator)

        try:
            with transaction.atomic():
                self._lock_user()
                existing = self._existing(request.client_request_id, request_hash)
                if existing is not None:
                    return StartOutcome(operation=existing, created=False)
                active = (
                    AgentOperation.objects.for_team(self.team.pk)
                    .filter(team=self.team, user=self.user, state__in=AgentOperation.ACTIVE_STATES)
                    .count()
                )
                if active >= MAX_ACTIVE_OPERATIONS_PER_USER:
                    raise AgentOperationError(
                        "too_many_operations",
                        f"You have {active} operations in progress. Wait for one to finish, or cancel one.",
                        status=429,
                    )
                if conversation is None:
                    conversation = Conversation.objects.create(
                        user=self.user,
                        team=self.team,
                        type=Conversation.Type.ASSISTANT,
                        agent_runtime=Conversation.AgentRuntime.SANDBOX,
                        title=request.goal[: Conversation.TITLE_MAX_LENGTH],
                    )
                elif (
                    AgentOperation.objects.for_team(self.team.pk)
                    .filter(conversation=conversation, state__in=AgentOperation.ACTIVE_STATES)
                    .exists()
                ):
                    raise AgentOperationError(
                        "conversation_busy",
                        "This conversation already has an operation in progress. Reply to it or cancel it.",
                        status=409,
                    )
                operation = AgentOperation.objects.for_team(self.team.pk).create(
                    team=self.team,
                    user=self.user,
                    conversation=conversation,
                    client_request_id=request.client_request_id,
                    request_hash=request_hash,
                    goal=request.goal,
                    granted_scopes=scopes,
                    parent_credential_kind=parent.kind,
                    parent_credential_ref=parent.ref,
                    repository=repository,
                    requested_ref=request.ref,
                    resolved_commit=commit,
                    approvals=request.approvals,
                    deadline_at=timezone.now() + OPERATION_DEADLINE,
                )
        except IntegrityError:
            existing = self._existing(request.client_request_id, request_hash)
            if existing is None:
                raise
            return StartOutcome(operation=existing, created=False)

        attached_context = [{"type": "text", "value": request.context}] if request.context else []
        try:
            routed = SandboxSession(conversation, self.user, options=self._dispatch_options(operation)).open(
                {
                    "content": request.goal,
                    "attached_context": attached_context,
                    "initial_permission_mode": PERMISSION_MODES[operation.approvals],
                },
                repository=repository,
            )
        except Exception:
            logger.exception("agent_operation_dispatch_failed", operation_id=str(operation.id))
            self._finish(operation, State.FAILED, "dispatch_failed", stop_run=False)
            raise
        if routed is None:
            self._finish(operation, State.FAILED, "dispatch_failed", stop_run=False)
            return StartOutcome(operation=operation, created=True)
        operation.task_id = routed.task_id
        operation.run_id = routed.run_id
        operation.save(update_fields=["task_id", "run_id", "updated_at"])
        return StartOutcome(operation=operation, created=True)

    def _existing(self, client_request_id: str, request_hash: str) -> AgentOperation | None:
        existing = (
            AgentOperation.objects.for_team(self.team.pk)
            .filter(team=self.team, user=self.user, client_request_id=client_request_id)
            .first()
        )
        if existing is not None and existing.request_hash != request_hash:
            raise AgentOperationError(
                "client_request_id_reused",
                "This client_request_id was used for a different request. Use a new id for a new goal.",
                status=409,
            )
        return existing

    def _lock_user(self) -> None:
        # Serializes starts per user so the active-operation limit cannot be passed by a burst.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))", [f"agent_operation:{self.team.pk}:{self.user.pk}"]
            )

    def _conversation_to_continue(self, conversation_id: str | None) -> Conversation | None:
        if conversation_id is None:
            return None
        conversation = Conversation.objects.filter(
            id=conversation_id, team=self.team, user=self.user, deleted=False
        ).first()
        if conversation is None:
            raise AgentOperationError("conversation_not_found", "The conversation does not exist.", status=404)
        if not AgentOperation.objects.for_team(self.team.pk).filter(conversation=conversation).exists():
            raise AgentOperationError(
                "conversation_not_delegated",
                "Only a conversation that an earlier operation started can be continued.",
            )
        return conversation

    def _resolve_repository(
        self, request: StartRequest, conversation: Conversation | None
    ) -> tuple[str | None, str | None]:
        if conversation is not None:
            first = (
                AgentOperation.objects.for_team(self.team.pk)
                .filter(conversation=conversation)
                .order_by("created_at")
                .first()
            )
            pinned_repository = first.repository if first else None
            if request.repository and request.repository != pinned_repository:
                raise AgentOperationError(
                    "repository_mismatch",
                    "A continued conversation keeps the repository of its first operation. Start a new conversation for another repository.",
                )
            return pinned_repository, first.resolved_commit if first else None
        if not request.repository:
            if request.ref:
                raise AgentOperationError("ref_without_repository", "Set repository when you set ref.")
            return None, None
        try:
            commit = repo_selection.resolve_repository_commit(
                self.team.pk, self.user.pk, request.repository, request.ref
            )
        except repo_selection.RepositoryCommitError as error:
            messages = {
                "no_github_integration": "Connect GitHub to this PostHog project before you send a repository.",
                "repository_inaccessible": "PostHog's GitHub connection cannot read this repository.",
                "invalid_ref": "The ref does not exist in this repository.",
            }
            raise AgentOperationError(error.code, messages[error.code])
        return request.repository, commit

    def _dispatch_options(self, operation: AgentOperation) -> SandboxDispatchOptions:
        return SandboxDispatchOptions(
            posthog_mcp_scopes=list(operation.granted_scopes),
            output_schema=AGENT_RESULT_SCHEMA,
            client_provenance=tasks_facade.TaskClientProvenance.AGENT_MCP,
            system_prompt_suffix=AGENT_MCP_INSTRUCTIONS,
            branch=operation.resolved_commit,
            extra_run_state={"mcp_exclude_tools": EXCLUDED_MCP_TOOLS},
        )

    # --- reconcile and read ---

    def view(self, operation: AgentOperation, cursor: str | None) -> OperationView:
        position = _decode_cursor(cursor, str(operation.id))
        progress = self._read_progress(operation)
        operation = self.reconcile(operation, progress=progress)

        steps = progress.steps if progress is not None else []
        if progress is not None:
            snapshot = {"plan": progress.plan, "steps_count": len(steps)}
            if operation.progress_snapshot != snapshot:
                operation.progress_snapshot = snapshot
                operation.save(update_fields=["progress_snapshot", "updated_at"])
        plan = progress.plan if progress is not None else list(operation.progress_snapshot.get("plan") or [])

        # A missing or unknown position restarts from the recent steps, never from an error.
        start = (
            position if position is not None and position <= len(steps) else max(0, len(steps) - MAX_STEPS_PER_RESPONSE)
        )
        new_steps = steps[start : start + MAX_STEPS_PER_RESPONSE]
        consumed = start + len(new_steps)
        retry_after = (
            RETRY_AFTER_ACTIVE_SECONDS if (new_steps or operation.state == State.QUEUED) else RETRY_AFTER_IDLE_SECONDS
        )
        return OperationView(
            operation=operation,
            plan=plan,
            new_steps=new_steps,
            cursor=_encode_cursor(str(operation.id), consumed),
            retry_after_seconds=retry_after,
            posthog_url=absolute_uri(f"/project/{self.team.pk}/ai?chat={operation.conversation_id}"),
            summary=self._run_summary(operation),
        )

    def _run_summary(self, operation: AgentOperation) -> str | None:
        if operation.run_id is None or operation.task_id is None:
            return None
        run = tasks_facade.get_task_run_detail(operation.run_id, operation.task_id, self.team.pk)
        return run.task_summary if run is not None else None

    def _read_progress(self, operation: AgentOperation) -> RunProgress | None:
        if operation.run_id is None or operation.task_id is None:
            return None
        try:
            log_content = tasks_facade.read_task_run_logs(operation.run_id, operation.task_id, self.team.pk)
        except Exception:
            logger.warning("agent_operation_log_read_failed", operation_id=str(operation.id), exc_info=True)
            return None
        if log_content is None:
            return None
        return summarize_run_log(tasks_facade.parse_task_run_log_entries(log_content))

    def reconcile(self, operation: AgentOperation, *, progress: RunProgress | None = None) -> AgentOperation:
        if operation.is_terminal or operation.run_id is None or operation.task_id is None:
            return operation
        if not parent_credential_active(operation):
            return self._finish(operation, State.FAILED, "credential_revoked")
        if timezone.now() >= operation.deadline_at:
            return self._finish(operation, State.EXPIRED, "deadline")

        run = tasks_facade.get_task_run_detail(operation.run_id, operation.task_id, self.team.pk)
        if run is None:
            return self._finish(operation, State.FAILED, "run_missing", stop_run=False)

        output = run.output if isinstance(run.output, dict) else None
        handled = operation.handled_output_run_id is not None and str(operation.handled_output_run_id) == str(run.id)
        if (
            not handled
            and output is not None
            and output.get("status")
            in (
                RESULT_STATUS_COMPLETE,
                RESULT_STATUS_NEEDS_INPUT,
                RESULT_STATUS_FAILED,
            )
        ):
            result = _normalize_result(output)
            operation.result = result
            operation.handled_output_run_id = run.id
            operation.pending_permission_request = None
            if result["status"] == RESULT_STATUS_COMPLETE:
                return self._finish(operation, State.SUCCEEDED, None, stop_run=False)
            if result["status"] == RESULT_STATUS_FAILED:
                return self._finish(operation, State.FAILED, "agent_reported_failure", stop_run=False)
            return self._set_state(operation, State.NEEDS_INPUT, "question")
        if handled:
            return operation

        status = run.status
        if status == tasks_facade.TaskRunStatus.COMPLETED:
            return self._finish(operation, State.FAILED, "no_result", stop_run=False)
        if status == tasks_facade.TaskRunStatus.FAILED:
            return self._finish(operation, State.FAILED, "run_failed", stop_run=False)
        if status == tasks_facade.TaskRunStatus.CANCELLED:
            reason = "cancelled" if operation.state == State.CANCELLING else "run_cancelled"
            return self._finish(operation, State.CANCELLED, reason, stop_run=False)
        if operation.state == State.CANCELLING:
            return operation
        if status in (tasks_facade.TaskRunStatus.QUEUED, tasks_facade.TaskRunStatus.NOT_STARTED):
            return self._set_state(operation, State.QUEUED, None)
        if progress is None and operation.pending_permission_request:
            # The log cannot be read now, so keep the approval that the last read found.
            return operation
        pending = progress.pending_permission if progress is not None else None
        if pending is not None:
            operation.pending_permission_request = {
                "request_id": pending.request_id,
                "title": pending.title,
                "options": pending.options,
            }
            return self._set_state(operation, State.NEEDS_INPUT, "approval_required")
        operation.pending_permission_request = None
        return self._set_state(operation, State.RUNNING, None)

    def _set_state(self, operation: AgentOperation, state: str, reason: str | None) -> AgentOperation:
        operation.state = state
        operation.state_reason = reason
        operation.save(
            update_fields=[
                "state",
                "state_reason",
                "result",
                "handled_output_run_id",
                "pending_permission_request",
                "updated_at",
            ]
        )
        return operation

    def _finish(
        self, operation: AgentOperation, state: str, reason: str | None, *, stop_run: bool = True
    ) -> AgentOperation:
        if stop_run:
            self._stop_run(operation, reason or state)
        operation.finished_at = timezone.now()
        operation.pending_permission_request = None
        self._set_state(operation, state, reason)
        operation.save(update_fields=["finished_at", "updated_at"])
        return operation

    def _stop_run(self, operation: AgentOperation, reason: str) -> str | None:
        if operation.run_id is None or operation.task_id is None:
            return None
        try:
            outcome, _ = tasks_cancellation.cancel_task_run(
                operation.run_id,
                operation.task_id,
                self.team.pk,
                reason=f"Agent MCP operation stopped: {reason}",
                source="agent_mcp",
                requested_by_user_id=self.user.pk,
                requested_by_distinct_id=self.user.distinct_id,
            )
            return outcome
        except Exception:
            logger.warning("agent_operation_stop_run_failed", operation_id=str(operation.id), exc_info=True)
            return None

    # --- control ---

    def cancel(self, operation: AgentOperation) -> AgentOperation:
        operation = self.reconcile(operation)
        if operation.is_terminal:
            return operation
        if operation.run_id is None:
            return self._finish(operation, State.CANCELLED, "cancelled", stop_run=False)
        outcome = self._stop_run(operation, "cancelled")
        if outcome in ("already_terminal", "not_found"):
            operation = self.reconcile(operation)
            if not operation.is_terminal:
                return self._finish(operation, State.CANCELLED, "cancelled", stop_run=False)
            return operation
        return self._set_state(operation, State.CANCELLING, "cancel_requested")

    def reply(self, operation: AgentOperation, message: str, client_request_id: str) -> AgentOperation:
        request_hash = _hash_text(message)
        previous = (
            AgentOperationReply.objects.for_team(self.team.pk)
            .filter(operation=operation, client_request_id=client_request_id)
            .first()
        )
        if previous is not None:
            if previous.request_hash != request_hash:
                raise AgentOperationError(
                    "client_request_id_reused",
                    "This client_request_id was used for a different reply. Use a new id for a new reply.",
                    status=409,
                )
            return operation

        operation = self.reconcile(operation, progress=self._read_progress(operation))
        if operation.is_terminal:
            raise AgentOperationError(
                "operation_finished",
                "This operation has finished. Start a new operation with the same conversation_id to continue.",
                status=409,
            )
        if operation.state in (State.CANCELLING, State.QUEUED):
            raise AgentOperationError(
                "operation_not_ready",
                "The operation cannot take a reply now. Try again after the next status.",
                status=409,
            )

        try:
            reply = AgentOperationReply.objects.for_team(self.team.pk).create(
                team=self.team, operation=operation, client_request_id=client_request_id, request_hash=request_hash
            )
        except IntegrityError:
            return operation

        try:
            if operation.state == State.NEEDS_INPUT and operation.pending_permission_request:
                self._answer_permission(operation, message)
            else:
                self._send_message(operation, message)
        except Exception:
            reply.delete()
            raise
        return operation

    def _answer_permission(self, operation: AgentOperation, message: str) -> None:
        pending = operation.pending_permission_request or {}
        options = pending.get("options") or []
        normalized = message.strip().lower().rstrip(".!")
        always = normalized in ALLOW_ALWAYS_REPLIES
        allow = always or normalized in ALLOW_REPLIES
        wanted = [o for o in options if (not o["kind"].startswith("reject")) == allow]
        preferred_kinds = ("allow_always", "allow_once") if always else ("allow_once", "reject_once")
        preferred = next((o for kind in preferred_kinds for o in wanted if o["kind"] == kind), None)
        option = preferred or (wanted[0] if wanted else None)
        if option is None or operation.run_id is None or operation.task_id is None:
            raise AgentOperationError("no_matching_option", "The pending approval has no option for this reply.")
        sent = tasks_facade.send_permission_response(
            operation.run_id,
            operation.task_id,
            self.team.pk,
            user_id=self.user.pk,
            request_id=pending["request_id"],
            option_id=option["option_id"],
        )
        if not sent:
            raise AgentOperationError(
                "reply_not_delivered", "The sandbox did not accept the reply. Try again.", status=503
            )
        operation.pending_permission_request = None
        self._set_state(operation, State.RUNNING, None)
        if not allow and normalized not in DENY_REPLIES:
            self._send_message(operation, message)

    def _send_message(self, operation: AgentOperation, message: str) -> None:
        conversation = Conversation.objects.get(id=operation.conversation_id, team=self.team)
        routed = SandboxSession(conversation, self.user, options=self._dispatch_options(operation)).open(
            {"content": message, "initial_permission_mode": PERMISSION_MODES[operation.approvals]}
        )
        if routed is None:
            raise AgentOperationError(
                "reply_not_delivered", "The sandbox did not accept the reply. Try again.", status=503
            )
        operation.run_id = routed.run_id
        operation.task_id = routed.task_id
        operation.save(update_fields=["run_id", "task_id", "updated_at"])
        if operation.state == State.NEEDS_INPUT:
            operation.result = None
        self._set_state(operation, State.RUNNING if not routed.just_created_run else State.QUEUED, None)


def stop_operations_for_revoked_credential(kind: str, ref: str) -> None:
    """Stop the active operations that a now-revoked credential started, so their sandboxes lose access."""
    operations = AgentOperation.objects.unscoped().filter(
        parent_credential_kind=kind, parent_credential_ref=ref, state__in=AgentOperation.ACTIVE_STATES
    )
    for operation in operations.select_related("team", "user"):
        try:
            AgentOperationService(operation.team, operation.user).reconcile(operation)
        except Exception:
            logger.exception("agent_operation_revocation_stop_failed", operation_id=str(operation.id))
