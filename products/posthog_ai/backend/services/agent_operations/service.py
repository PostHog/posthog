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

from django.core.cache import cache
from django.db import IntegrityError, connection, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.user import User
from posthog.utils import absolute_uri

from products.posthog_ai.backend.message_routing import SandboxDispatchOptions, SandboxRouteResult, SandboxSession
from products.posthog_ai.backend.models import AgentOperation, AgentOperationReply, Conversation
from products.posthog_ai.backend.services.agent_operations.delegation import (
    caller_scopes,
    granted_scopes,
    parent_credential,
    parent_credential_active,
)
from products.posthog_ai.backend.services.agent_operations.progress import (
    PermissionRequest,
    RunProgress,
    summarize_run_log,
)
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
# Clients read the status every few seconds, and each read of the run log downloads it whole.
PROGRESS_CACHE_SECONDS = 5
# The sweep reconciles operations that no client read for this long, so a deadline, a revoked credential,
# an ended run or a failed stop takes effect without a reader.
UNWATCHED_AFTER = timedelta(minutes=2)
SWEEP_BATCH_SIZE = 200
# A start that stored no run after this long crashed during dispatch, so its operation must not keep a slot.
DISPATCH_TIMEOUT = timedelta(minutes=10)
# A stop request that the sandbox did not receive. The operation stays active, so the next reconcile retries it.
STOP_NOT_SENT_OUTCOMES = frozenset({None, "unavailable"})
CANCEL_RETRY_REASON = "cancel_retrying"
# One operation stays in one project, so the agent must not switch projects or reach other projects
# through connections.
EXCLUDED_MCP_TOOLS = ["posthog-connection-call", "posthog-connection-forward", "switch-project", "switch-organization"]
# `auto` relays every MCP approval to the client. A client without an approval UI would stall on each
# PostHog tool call, so its runs ask for none: the key's scopes, not per-call approvals, limit the run.
PERMISSION_MODES: dict[str, str] = {
    AgentOperation.Approvals.CLIENT: "auto",
    AgentOperation.Approvals.NONE: "bypassPermissions",
}
ALLOW_REPLIES = frozenset({"allow", "approve", "approved", "yes", "y", "ok", "go ahead"})
ALLOW_ALWAYS_REPLIES = frozenset({"allow all", "always", "always allow", "allow always"})
DENY_REPLIES = frozenset({"deny", "reject", "no", "n"})
# With no approval pending, an approval word is a late answer to an approval that is already answered,
# so it must not go to the agent as a chat message.
APPROVAL_ANSWERS = ALLOW_REPLIES | ALLOW_ALWAYS_REPLIES | DENY_REPLIES | frozenset({"allow", "allow all", "deny"})
# Sandbox harness tools that only report on the run, such as its summary, which the status already shows.
# The sandbox asks approval for them in client approval mode, so the service answers for the user.
AUTO_APPROVED_TOOLS = frozenset({"mcp__posthog-code-tools__task_summary_update"})


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
    approvals: str = AgentOperation.Approvals.NONE

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
class PinnedRepository:
    repository: str | None = None
    commit: str | None = None


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
    steps_total: int
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


def _normalize_reply(message: str) -> str:
    return message.strip().lower().rstrip(".!")


def _choose_option(options: list[dict[str, str]], *, allow: bool, always: bool) -> dict[str, str] | None:
    wanted = [o for o in options if (not o["kind"].startswith("reject")) == allow]
    preferred_kinds = ("allow_always", "allow_once") if always else ("allow_once", "reject_once")
    preferred = next((o for kind in preferred_kinds for o in wanted if o["kind"] == kind), None)
    return preferred or (wanted[0] if wanted else None)


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
        pinned = self._resolve_repository(request, conversation)
        # A stored state changes only when someone reads the operation, so a run that ended unread
        # would still count toward the limit below.
        for running in self._operations_holding_a_sandbox():
            self.reconcile(running)
        scopes = granted_scopes(caller_scopes(authenticator))
        parent = parent_credential(authenticator)

        try:
            with transaction.atomic():
                self._lock_user()
                existing = self._existing(request.client_request_id, request_hash)
                if existing is not None:
                    return StartOutcome(operation=existing, created=False)
                active = self._operations_holding_a_sandbox().count()
                if active >= MAX_ACTIVE_OPERATIONS_PER_USER:
                    raise AgentOperationError(
                        "too_many_operations",
                        f"You have {active} PostHog Agent runs in progress. Wait for one to finish, or cancel one.",
                        status=409,
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
                    repository=pinned.repository,
                    requested_ref=request.ref,
                    resolved_commit=pinned.commit,
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
                repository=pinned.repository,
            )
        except Exception:
            logger.exception("agent_operation_dispatch_failed", operation_id=str(operation.id))
            self._finish(operation, State.FAILED, "dispatch_failed", stop_run=False)
            raise
        if routed is None:
            self._finish(operation, State.FAILED, "dispatch_failed", stop_run=False)
            return StartOutcome(operation=operation, created=True)
        return StartOutcome(operation=self._attach_run(operation, routed, None), created=True)

    def _operations_holding_a_sandbox(self) -> QuerySet[AgentOperation]:
        # A run that asked a question has already ended. A run that waits for an approval keeps its sandbox.
        return (
            AgentOperation.objects.for_team(self.team.pk)
            .filter(team=self.team, user=self.user)
            .filter(
                Q(state__in=(State.QUEUED, State.RUNNING, State.CANCELLING))
                | Q(state=State.NEEDS_INPUT, pending_permission_request__isnull=False)
            )
        )

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

    def _locked(self, operation: AgentOperation) -> AgentOperation:
        # Serializes the control changes of one operation. Call it inside a transaction, and never
        # hold the lock across a sandbox call.
        return AgentOperation.objects.for_team(self.team.pk).select_for_update().get(pk=operation.pk)

    def _attach_run(self, operation: AgentOperation, routed: SandboxRouteResult, state: str | None) -> AgentOperation:
        """Store the run that a dispatch started. A cancel that arrived during the dispatch stops it too."""
        with transaction.atomic():
            current = self._locked(operation)
            current.task_id = routed.task_id
            current.run_id = routed.run_id
            cancelled = current.state == State.CANCELLING or current.is_terminal
            if cancelled:
                current.state = State.CANCELLING
                current.state_reason = CANCEL_RETRY_REASON
                current.finished_at = None
            elif state is not None:
                if current.state == State.NEEDS_INPUT:
                    current.result = None
                current.state = state
                current.state_reason = None
            current.save(
                update_fields=["task_id", "run_id", "state", "state_reason", "result", "finished_at", "updated_at"]
            )
        return self._request_cancel(current) if cancelled else current

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

    def _resolve_repository(self, request: StartRequest, conversation: Conversation | None) -> PinnedRepository:
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
            return PinnedRepository(repository=pinned_repository, commit=first.resolved_commit if first else None)
        if not request.repository:
            if request.ref:
                raise AgentOperationError("ref_without_repository", "Set repository when you set ref.")
            return PinnedRepository()
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
        return PinnedRepository(repository=request.repository, commit=commit)

    def _dispatch_options(self, operation: AgentOperation) -> SandboxDispatchOptions:
        extra_run_state: dict[str, Any] = {"mcp_exclude_tools": EXCLUDED_MCP_TOOLS}
        if operation.repository:
            # The run gets a read-only GitHub token, so the prompt is not the only thing that keeps it from writing.
            extra_run_state["github_read_access"] = True
        return SandboxDispatchOptions(
            posthog_mcp_scopes=list(operation.granted_scopes),
            output_schema=AGENT_RESULT_SCHEMA,
            client_provenance=tasks_facade.TaskClientProvenance.AGENT_MCP,
            system_prompt_suffix=AGENT_MCP_INSTRUCTIONS,
            branch=operation.resolved_commit,
            extra_run_state=extra_run_state,
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
        steps_total = len(steps) if progress is not None else int(operation.progress_snapshot.get("steps_count") or 0)

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
            steps_total=steps_total,
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
        cache_key = f"agent_operation_progress:{operation.run_id}"
        cached = cache.get(cache_key)
        if isinstance(cached, RunProgress):
            return cached
        try:
            log_content = tasks_facade.read_task_run_logs(operation.run_id, operation.task_id, self.team.pk)
        except Exception:
            logger.warning("agent_operation_log_read_failed", operation_id=str(operation.id), exc_info=True)
            return None
        if log_content is None:
            return None
        progress = summarize_run_log(tasks_facade.parse_task_run_log_entries(log_content))
        cache.set(cache_key, progress, PROGRESS_CACHE_SECONDS)
        return progress

    def reconcile(self, operation: AgentOperation, *, progress: RunProgress | None = None) -> AgentOperation:
        if operation.is_terminal:
            return operation
        if operation.run_id is None or operation.task_id is None:
            if timezone.now() >= operation.created_at + DISPATCH_TIMEOUT:
                return self._finish(operation, State.FAILED, "dispatch_failed", stop_run=False)
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
            if operation.state_reason == CANCEL_RETRY_REASON:
                return self._request_cancel(operation)
            return operation
        if status in (tasks_facade.TaskRunStatus.QUEUED, tasks_facade.TaskRunStatus.NOT_STARTED):
            return self._set_state(operation, State.QUEUED, None)
        if progress is None and operation.pending_permission_request:
            # The log cannot be read now, so keep the approval that the last read found.
            return operation
        pending = progress.pending_permission if progress is not None else None
        if pending is not None and pending.request_id == operation.answered_permission_request_id:
            pending = None
        if pending is not None and pending.tool_name in AUTO_APPROVED_TOOLS:
            self._auto_approve(operation, pending)
            pending = None
        if pending is not None:
            operation.pending_permission_request = {
                "request_id": pending.request_id,
                "title": pending.title,
                "detail": pending.detail,
                "options": pending.options,
            }
            return self._set_state(operation, State.NEEDS_INPUT, "approval_required")
        operation.pending_permission_request = None
        return self._set_state(operation, State.RUNNING, None)

    def _auto_approve(self, operation: AgentOperation, request: PermissionRequest) -> None:
        option = _choose_option(request.options, allow=True, always=True)
        if option is None or not self._send_permission_response(operation, request.request_id, option["option_id"]):
            # The next read finds the request again and retries.
            logger.warning(
                "agent_operation_auto_approval_not_sent", operation_id=str(operation.id), tool_name=request.tool_name
            )

    def _send_permission_response(self, operation: AgentOperation, request_id: str, option_id: str) -> bool:
        if operation.run_id is None or operation.task_id is None:
            return False
        sent = tasks_facade.send_permission_response(
            operation.run_id,
            operation.task_id,
            self.team.pk,
            user_id=self.user.pk,
            request_id=request_id,
            option_id=option_id,
        )
        if sent:
            operation.answered_permission_request_id = request_id
            operation.save(update_fields=["answered_permission_request_id", "updated_at"])
        return sent

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
        if stop_run and self._stop_run(operation, reason or state) in STOP_NOT_SENT_OUTCOMES:
            # The sandbox can still run, so the operation stays active and the next reconcile tries the stop again.
            return self._set_state(operation, State.CANCELLING, reason)
        operation.finished_at = timezone.now()
        operation.pending_permission_request = None
        self._set_state(operation, state, reason)
        operation.save(update_fields=["finished_at", "updated_at"])
        return operation

    def _stop_run(self, operation: AgentOperation, reason: str) -> str | None:
        if operation.run_id is None or operation.task_id is None:
            return "not_found"
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
        with transaction.atomic():
            operation = self._locked(operation)
            if operation.is_terminal:
                return operation
            # Stored before the stop request, so a reply that starts a run meanwhile stops that run too.
            operation = self._set_state(operation, State.CANCELLING, CANCEL_RETRY_REASON)
        if operation.run_id is None:
            # The first run is still being dispatched. `_attach_run` stops it when the dispatch returns.
            return self._finish(operation, State.CANCELLED, "cancelled", stop_run=False)
        return self._request_cancel(operation)

    def _request_cancel(self, operation: AgentOperation) -> AgentOperation:
        outcome = self._stop_run(operation, "cancelled")
        if outcome in STOP_NOT_SENT_OUTCOMES:
            return operation
        if outcome in ("already_terminal", "not_found"):
            operation = self._set_state(operation, State.CANCELLING, "cancel_requested")
            operation = self.reconcile(operation)
            if not operation.is_terminal:
                return self._finish(operation, State.CANCELLED, "cancelled", stop_run=False)
            return operation
        return self._set_state(operation, State.CANCELLING, "cancel_requested")

    def reply(
        self, operation: AgentOperation, message: str, client_request_id: str, *, authenticator: object
    ) -> AgentOperation:
        # The reply resumes the run with the operation's grant, so a narrower credential must not steer it.
        if not set(operation.granted_scopes) <= set(granted_scopes(caller_scopes(authenticator))):
            raise AgentOperationError(
                "insufficient_scope",
                "This credential has fewer permissions than the one that started the operation. Reply with that credential, or start a new operation.",
                status=403,
            )
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
        # A pending question takes any reply, so only an operation that waits for nothing rejects these words.
        if operation.state != State.NEEDS_INPUT and _normalize_reply(message) in APPROVAL_ANSWERS:
            raise AgentOperationError(
                "no_pending_approval", "This approval was already answered, so no reply is needed.", status=409
            )

        try:
            reply = AgentOperationReply.objects.for_team(self.team.pk).create(
                team=self.team, operation=operation, client_request_id=client_request_id, request_hash=request_hash
            )
        except IntegrityError:
            return operation

        try:
            if operation.state == State.NEEDS_INPUT and operation.pending_permission_request:
                return self._answer_permission(operation, message)
            return self._send_message(operation, message)
        except Exception:
            reply.delete()
            raise

    def _answer_permission(self, operation: AgentOperation, message: str) -> AgentOperation:
        pending = operation.pending_permission_request or {}
        normalized = _normalize_reply(message)
        always = normalized in ALLOW_ALWAYS_REPLIES
        allow = always or normalized in ALLOW_REPLIES
        option = _choose_option(pending.get("options") or [], allow=allow, always=always)
        if option is None or operation.run_id is None or operation.task_id is None:
            raise AgentOperationError("no_matching_option", "The pending approval has no option for this reply.")
        if not self._send_permission_response(operation, pending["request_id"], option["option_id"]):
            raise AgentOperationError(
                "reply_not_delivered", "The sandbox did not accept the reply. Try again.", status=503
            )
        operation.pending_permission_request = None
        self._set_state(operation, State.RUNNING, None)
        if not allow and normalized not in DENY_REPLIES:
            return self._send_message(operation, message)
        return operation

    def _send_message(self, operation: AgentOperation, message: str) -> AgentOperation:
        conversation = Conversation.objects.get(id=operation.conversation_id, team=self.team)
        routed = SandboxSession(conversation, self.user, options=self._dispatch_options(operation)).open(
            {"content": message, "initial_permission_mode": PERMISSION_MODES[operation.approvals]}
        )
        if routed is None:
            raise AgentOperationError(
                "reply_not_delivered", "The sandbox did not accept the reply. Try again.", status=503
            )
        return self._attach_run(operation, routed, State.QUEUED if routed.just_created_run else State.RUNNING)


def _reconcile_each(operations: QuerySet[AgentOperation]) -> int:
    count = 0
    for operation in operations.select_related("team", "user"):
        try:
            AgentOperationService(operation.team, operation.user).reconcile(operation)
            count += 1
        except Exception:
            logger.exception("agent_operation_reconcile_failed", operation_id=str(operation.id))
    return count


def stop_operations_for_revoked_credential(kind: str, ref: str) -> None:
    """Stop the active operations that a now-revoked credential started, so their sandboxes lose access."""
    _reconcile_each(
        AgentOperation.objects.unscoped().filter(
            parent_credential_kind=kind, parent_credential_ref=ref, state__in=AgentOperation.ACTIVE_STATES
        )
    )


def stop_operations_for_revoked_oauth(user_id: int | None) -> None:
    """Stop the active operations whose OAuth parent is revoked. ``None`` checks every user's operations."""
    operations = AgentOperation.objects.unscoped().filter(
        parent_credential_kind__in=(
            AgentOperation.ParentCredentialKind.OAUTH_TOKEN_FAMILY,
            AgentOperation.ParentCredentialKind.OAUTH_APPLICATION,
        ),
        state__in=AgentOperation.ACTIVE_STATES,
    )
    if user_id is not None:
        operations = operations.filter(user_id=user_id)
    _reconcile_each(operations)


def reconcile_unwatched_operations() -> int:
    """Reconcile the active operations that no client read recently or that passed their deadline."""
    now = timezone.now()
    ids = list(
        AgentOperation.objects.unscoped()
        .filter(state__in=AgentOperation.ACTIVE_STATES)
        .filter(Q(updated_at__lt=now - UNWATCHED_AFTER) | Q(deadline_at__lte=now))
        .order_by("updated_at")
        .values_list("id", flat=True)[:SWEEP_BATCH_SIZE]
    )
    return _reconcile_each(AgentOperation.objects.unscoped().filter(id__in=ids))
