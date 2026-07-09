from __future__ import annotations

import re
import json
import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import InterfaceError, OperationalError, close_old_connections

from asgiref.sync import sync_to_async

from posthog.models.team.team import Team
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError
from posthog.temporal.oauth import PosthogMcpScopes

from products.tasks.backend.models import Task, TaskRun

if TYPE_CHECKING:
    from temporalio.client import WorkflowHandle

    from products.tasks.backend.logic.services.sandbox import SandboxResources

logger = logging.getLogger(__name__)

# Type for an optional output callback (e.g. management command's self.stdout.write)
OutputFn = Callable[[str], object] | None

# Sandbox logs polling from S3
POLL_INTERVAL_SECONDS = 10
MAX_POLL_SECONDS = 30 * 60  # 30 minutes (matches sandbox TTL)
MAX_CONSECUTIVE_STORAGE_ERRORS = 3
# Continuous log silence required before salvaging a dropped-finalization turn — one SSE read window
# (SSE_READ_TIMEOUT_SECONDS). The null-cost finalization fingerprint (_ended_on_pending_finalization)
# is the real safety gate; this floor only rules out salvaging a turn caught mid-stream. It must sit
# well below the 1800s poll budget: a floor near the budget would only salvage turns that fell silent
# in the first few minutes and reject a turn that does real work late and *then* drops end_turn — the
# exact case this path exists to recover. The relay's true continuous-silence ceiling is
# 6 × SSE_READ_TIMEOUT_SECONDS = 1800s, which can't be fully observed inside the 1800s budget; keying
# salvage off a real terminal signal instead of the poll deadline stays the layer-2 follow-up.
STALE_TURN_SALVAGE_SECONDS = 300

# Notification method the sandbox agent emits on a terminal failure. The agent
# classifies upstream failures (rate limits, stream/connection drops, provider
# errors) via classifyAgentError() and writes the category + raw message here, so
# the PostHog side can surface the real cause instead of Temporal's opaque
# "Activity task failed" wrapper.
AGENT_ERROR_METHOD = "_posthog/error"

# Observability side-channels the relay interleaves into the turn log asynchronously
# (agentsh network-audit dumps and sandbox credential refreshes ride on `_posthog/console`,
# sandbox stdout/stderr on `_posthog/sandbox_output`, setup steps on `_posthog/progress`).
# They carry no turn-state and routinely land *after* the agent's closing usage_update, so the
# dropped-finalization tail check skips them rather than treating one as the decisive tail.
TRANSIENT_SIDE_CHANNEL_METHODS = frozenset(
    {
        "_posthog/console",
        "_posthog/progress",
        "_posthog/sandbox_output",
    }
)

# `_posthog/progress` is normally an informational setup step (status in_progress/completed), but the
# workflow's failure and cancel handlers emit a progress marker with this status *before* the TaskRun
# reaches its terminal state. A salvage reread that lands in that window must not skip past it to an
# earlier finalization fingerprint and report a bogus success, so a failed progress line stays decisive.
FAILED_PROGRESS_STATUS = "failed"


@dataclass(frozen=True)
class AgentError:
    """A terminal error the sandbox agent reported in its S3 log."""

    message: str
    category: str | None = None

    def describe(self) -> str:
        return f"{self.category}: {self.message}" if self.category else self.message


@dataclass(frozen=True)
class CustomPromptSandboxContext:
    """Everything needed to spawn a sandbox agent for a given team/repo."""

    team_id: int
    user_id: int
    repository: str | None = None
    sandbox_environment_id: str | None = None
    posthog_mcp_scopes: PosthogMcpScopes | None = None
    model: str | None = None
    """Override the agent model (e.g. ``"claude-opus-4-8"``). Falls back to the
    agent server's default when ``None``. Used by evals to pin a specific
    model so cross-run comparisons are stable."""
    runtime_adapter: str | None = None
    """The harness serving ``model`` (``"claude"`` | ``"codex"``); the agent server derives the
    provider from it, so a pinned model must ship with its matching runtime. ``None`` = default."""
    reasoning_effort: str | None = None
    """Agent reasoning effort (``"low"``…``"max"``); valid values depend on runtime+model."""
    sandbox_resources: SandboxResources | None = None
    """Override the sandbox's compute (CPU / memory). Unset fields keep the
    SandboxConfig defaults (4 cores / 16 GB)."""
    sandbox_timeout_seconds: int | None = None
    """Override the sandbox's max lifetime (Modal TTL). Falls back to SANDBOX_TTL_SECONDS."""


class EmptyAgentTurnError(RuntimeError):
    """Raised when the agent emitted end_turn but no agent_message (Claude Agent SDK short-circuits)."""

    def __init__(self, message: str, *, total_lines: int, printed_lines: int):
        super().__init__(message)
        self.total_lines = total_lines
        self.printed_lines = printed_lines


async def create_task_and_trigger(
    description: str,
    context: CustomPromptSandboxContext,
    branch: str | None = None,
    step_name: str = "",
    origin_product: Task.OriginProduct | None = None,
    signal_report_id: str | None = None,
    ai_stage: str | None = None,
    internal: bool = False,
):
    title = f"[sandbox_prompt:{step_name}] {description[:80]}" if step_name else description[:100]
    team = await sync_to_async(Team.objects.get, thread_sensitive=False)(id=context.team_id)
    # Mirror Task.create_and_run's "full" default when the caller didn't set scopes — passing
    # None would clobber it. sandbox_environment_id already accepts None.
    posthog_mcp_scopes: PosthogMcpScopes = (
        context.posthog_mcp_scopes if context.posthog_mcp_scopes is not None else "full"
    )
    # thread_sensitive=False: create_and_run is slow, self-contained sync work (ORM +
    # GitHub + workflow submission); on the shared thread-sensitive executor, N parallel
    # callers (parallel eval cases) serialize into a single-file queue.
    task = await sync_to_async(Task.create_and_run, thread_sensitive=False)(
        team=team,
        title=title,
        description=description,
        origin_product=origin_product or Task.OriginProduct.USER_CREATED,
        user_id=context.user_id,
        repository=context.repository,
        create_pr=False,
        mode="background",
        branch=branch,
        signal_report_id=signal_report_id,
        ai_stage=ai_stage,
        posthog_mcp_scopes=posthog_mcp_scopes,
        sandbox_environment_id=context.sandbox_environment_id,
        model=context.model,
        runtime_adapter=context.runtime_adapter,
        reasoning_effort=context.reasoning_effort,
        internal=internal,
        sandbox_resources=context.sandbox_resources,
        sandbox_timeout_seconds=context.sandbox_timeout_seconds,
    )
    # lambda wrap: task.latest_run is a lazy ORM property; sync_to_async needs a callable
    task_run = await sync_to_async(lambda: task.latest_run, thread_sensitive=False)()
    if not task_run:
        raise RuntimeError("Task.create_and_run did not produce a TaskRun")
    return task, task_run


async def _refresh_task_run(task_run_id) -> TaskRun:
    """Re-read a ``TaskRun`` mid-poll, tolerating a dropped pooled DB connection.

    ``poll_for_turn`` runs for many minutes while the activity's threadpool connection
    sits idle; pgbouncer can drop it underneath us. The activity's ``@close_db_connections``
    decorator only resets connections at the activity boundaries, not inside this loop, so
    without this guard the next ORM read raises ``OperationalError``/``InterfaceError`` and
    aborts the whole report run. ``close_old_connections()`` clears any stale/errored
    connection before the read, and we retry once so a transparent reconnect recovers the
    drop instead of failing the run. Mirrors the handling in ``push_dispatcher``.
    """

    def _read() -> TaskRun:
        # Guarded like push_dispatcher: close_old_connections() health-checks live connections,
        # which trips pytest-django's DB-access guard in unit tests that patch the ORM read.
        if not settings.TEST:
            close_old_connections()
        return TaskRun.objects.get(id=task_run_id)

    try:
        return await sync_to_async(_read)()
    except (OperationalError, InterfaceError):
        logger.warning(
            "custom_prompt - poll_for_turn: DB connection dropped during TaskRun refresh, reconnecting, run=%s",
            task_run_id,
            exc_info=True,
        )
        return await sync_to_async(_read)()


async def poll_for_turn(
    task_run,
    *,
    skip_lines: int = 0,
    printed_lines: int = 0,
    verbose: bool = False,
    output_fn: OutputFn = None,
    workflow_handle: WorkflowHandle | None = None,
    max_poll_seconds: int | None = None,
) -> tuple[str, str | None, int, int]:
    """Poll S3 logs until the agent finishes a turn.

    `max_poll_seconds` overrides the default poll budget for callers whose activity
    timeout is shorter than `MAX_POLL_SECONDS` — the dropped-finalization salvage only
    runs once this budget is exhausted, so a caller must keep it below its own activity
    `start_to_close_timeout` or the salvage never gets a chance to fire (the Signals
    scout passes its 15-minute per-run budget for exactly this reason).
    """
    poll_budget = MAX_POLL_SECONDS if max_poll_seconds is None else max_poll_seconds
    # Track the timing/errors
    elapsed = 0
    consecutive_storage_errors = 0
    # Elapsed time when we last saw new log lines
    last_new_lines_at = 0
    # Remember assistant text, as the agent message and end_message could arrive in different poll slices
    latest_assistant_text: str | None = None
    # Cursor at start of this turn — passed to _drain_final_log so the terminal-status drain can
    # recover an agent_message emitted earlier in *this* turn without crossing the previous turn's
    # boundary (which would return a stale previous-turn response in multi-turn sessions).
    original_skip_lines = skip_lines
    while elapsed < poll_budget:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS
        # Send heartbeat signals to the ProcessTaskWorkflow on each poll cycle to prevent
        # the workflow's inactivity timeout from firing while the agent is still working
        if workflow_handle is not None:
            try:
                await workflow_handle.signal("heartbeat")
            except Exception:
                logger.warning("custom_prompt - poll_for_turn: failed to send workflow heartbeat", exc_info=True)
        try:
            # Poll the logs.
            finished, last_message, full_log, total_lines, empty_end_turn = await sync_to_async(
                # thread_sensitive=False because of pure I/O (object_storage.read + JSON parsing) and doesn't touch the ORM
                _check_logs,
                thread_sensitive=False,
            )(task_run, skip_lines)
        except ObjectStorageError:
            consecutive_storage_errors += 1
            logger.warning(
                "custom_prompt - poll_for_turn: transient storage error reading logs (%d/%d)",
                consecutive_storage_errors,
                MAX_CONSECUTIVE_STORAGE_ERRORS,
                exc_info=True,
            )
            if consecutive_storage_errors >= MAX_CONSECUTIVE_STORAGE_ERRORS:
                raise
            continue
        consecutive_storage_errors = 0
        # Track the timings
        if total_lines > skip_lines:
            last_new_lines_at = elapsed
        stale_seconds = elapsed - last_new_lines_at
        # Warn once per minute of silence (not every poll) so stalls surface without flooding logs.
        if stale_seconds >= 60 and stale_seconds % 60 < POLL_INTERVAL_SECONDS:
            logger.warning(
                "custom_prompt - poll_for_turn: no new S3 log lines for %ds, run=%s, total_lines=%d",
                stale_seconds,
                task_run.id,
                total_lines,
            )
        # Detect how many lines were printed in this poll
        printed_lines = _stream_new_lines(full_log, printed_lines, verbose=verbose, output_fn=output_fn)
        if last_message:
            latest_assistant_text = last_message
        # If success
        if finished and last_message:
            return last_message, full_log, total_lines, printed_lines
        # Surface empty end_turn to the multi-turn session, so it can retry
        # the prompt instead of us polling until MAX_POLL_SECONDS.
        if empty_end_turn:
            # If the agent emitted text in an earlier poll of this same turn, the turn
            # is genuinely complete — end_turn just landed in a later slice.
            if latest_assistant_text is not None:
                return latest_assistant_text, full_log, total_lines, printed_lines
            logger.warning(
                "custom_prompt - poll_for_turn: empty end_turn detected (no agent_message), run=%s total_lines=%d",
                task_run.id,
                total_lines,
            )
            # Actual end_turn with no message, need to retry the step
            raise EmptyAgentTurnError(
                f"Agent emitted end_turn with no agent_message for run={task_run.id}",
                total_lines=total_lines,
                printed_lines=printed_lines,
            )
        # Keep the cursor monotonic — S3 eventual-consistency can briefly return fewer lines than the
        # prior poll; without the clamp we'd re-parse old lines. Doubles as the line-count high-water
        # mark handed to salvage: every line up to here was seen (and watched go quiet) during polling.
        skip_lines = max(skip_lines, total_lines)
        refreshed = await _refresh_task_run(task_run.id)
        if refreshed.status in {
            TaskRun.Status.COMPLETED,
            TaskRun.Status.FAILED,
            TaskRun.Status.CANCELLED,
        }:
            logger.warning(
                "custom_prompt - poll_for_turn: TaskRun reached terminal status=%s, error_message=%s, "
                "run=%s, elapsed=%ds, stale_for=%ds, total_lines=%d",
                refreshed.status,
                refreshed.error_message,
                task_run.id,
                elapsed,
                elapsed - last_new_lines_at,
                total_lines,
            )
            return await _drain_final_log(
                task_run,
                refreshed_status=refreshed.status,
                error_message=refreshed.error_message,
                printed_lines=printed_lines,
                original_skip_lines=original_skip_lines,
                verbose=verbose,
                output_fn=output_fn,
            )
    # Poll budget exhausted. A run already terminal here was marked by something else (cancel,
    # relay-detected crash) — drain it; otherwise try to salvage below.
    refreshed = await _refresh_task_run(task_run.id)
    if refreshed.status in {
        TaskRun.Status.COMPLETED,
        TaskRun.Status.FAILED,
        TaskRun.Status.CANCELLED,
    }:
        logger.warning(
            "custom_prompt - poll_for_turn: terminal status=%s at poll timeout, run=%s, elapsed=%ds",
            refreshed.status,
            task_run.id,
            elapsed,
        )
        return await _drain_final_log(
            task_run,
            refreshed_status=refreshed.status,
            error_message=refreshed.error_message,
            printed_lines=printed_lines,
            original_skip_lines=original_skip_lines,
            verbose=verbose,
            output_fn=output_fn,
        )
    # Otherwise salvage a dropped-finalization turn, but only after enough continuous silence.
    stale_seconds = elapsed - last_new_lines_at
    if stale_seconds >= STALE_TURN_SALVAGE_SECONDS:
        salvaged = await _salvage_dropped_finalization(
            task_run,
            printed_lines=printed_lines,
            original_skip_lines=original_skip_lines,
            max_total_lines_seen=skip_lines,
            elapsed=elapsed,
            stale_seconds=stale_seconds,
            verbose=verbose,
            output_fn=output_fn,
        )
        if salvaged is not None:
            return salvaged
    raise RuntimeError(f"custom_prompt - poll_for_turn: timed out after {elapsed}s")


async def _read_turn_log_with_retry(
    task_run, *, skip_lines: int, context: str
) -> tuple[bool, str | None, str | None, int, bool]:
    """Read the turn log via _check_logs, retrying transient ObjectStorageError up to
    MAX_CONSECUTIVE_STORAGE_ERRORS times (one POLL_INTERVAL_SECONDS apart). Re-raises the error
    if every attempt fails, so a single S3 blip doesn't fail an otherwise-recoverable turn.
    `context` names the caller in the warning log. Shared by the terminal drain and the salvage
    path so the bounded-retry loop lives in one place."""
    for attempt in range(1, MAX_CONSECUTIVE_STORAGE_ERRORS + 1):
        try:
            return await sync_to_async(
                # thread_sensitive=False because of pure I/O (object_storage.read + JSON parsing) and doesn't touch the ORM
                _check_logs,
                thread_sensitive=False,
            )(task_run, skip_lines=skip_lines)
        except ObjectStorageError:
            logger.warning(
                "custom_prompt - %s: storage error on final log read (%d/%d), run=%s",
                context,
                attempt,
                MAX_CONSECUTIVE_STORAGE_ERRORS,
                task_run.id,
                exc_info=True,
            )
            if attempt >= MAX_CONSECUTIVE_STORAGE_ERRORS:
                raise
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    raise AssertionError("unreachable: loop returns on success or raises on exhaustion")  # pragma: no cover


async def _salvage_dropped_finalization(
    task_run,
    *,
    printed_lines: int,
    original_skip_lines: int,
    max_total_lines_seen: int,
    elapsed: int,
    stale_seconds: int,
    verbose: bool,
    output_fn: OutputFn,
) -> tuple[str, str | None, int, int] | None:
    """Recover a turn whose closing end_turn was dropped (final message + null-cost usage_update,
    then silence). Re-reads from the start-of-turn cursor so a chunked response is recovered in full.

    Classified by the reread's tail:
    - the real end_turn present -> the turn completed (the close just landed late); return it;
    - the null-cost finalization fingerprint -> dropped-finalization; salvage the last message — but
      only if nothing new arrived since polling beyond that single accounting line. A null-cost
      usage_update is also emitted *between* chunks of an active turn, so fresh activity that landed
      after the final poll has had no silence window and may still be live; decline it;
    - anything else (a tool call / bare message / error tail) -> still live or failed; decline.

    Declining falls back to the caller's timeout failure. A storage outage on the reread propagates
    (like the poll loop and terminal drain) rather than masquerading as a timeout."""
    finished, last_message, full_log, total_lines, _ = await _read_turn_log_with_retry(
        task_run, skip_lines=original_skip_lines, context="salvage_dropped_finalization"
    )
    if finished and last_message is not None:
        printed_lines = _stream_new_lines(full_log, printed_lines, verbose=verbose, output_fn=output_fn)
        logger.warning(
            "custom_prompt - salvage_dropped_finalization: end_turn recovered on reread at poll timeout "
            "(%ds) — completing, run=%s total_lines=%d",
            elapsed,
            task_run.id,
            total_lines,
        )
        return last_message, full_log, total_lines, printed_lines
    if last_message is None or not _ended_on_pending_finalization(full_log):
        return None
    # The fingerprint also matches a mid-turn pause between chunks. The log is append-only, so the only
    # benign turn-relevant growth since polling is the finalization usage_update itself landing late
    # (+1 line beyond the high-water mark). Any more than that — a new message chunk, a tool call, etc.
    # — is fresh activity that has had no silence window and could still be live, so decline rather than
    # truncate. Transient relay side-channels (network audits, credential refreshes, stdout) also land
    # in this post-poll window; they carry no turn-state and must be discounted, or one arriving
    # alongside the late usage_update would push raw growth past the threshold and wrongly decline the
    # very dropped-finalization case this path recovers.
    new_lines = (full_log or "").strip().split("\n")[max_total_lines_seen:]
    relevant_growth = (total_lines - max_total_lines_seen) - _transient_growth(new_lines)
    if relevant_growth > 1:
        logger.warning(
            "custom_prompt - salvage_dropped_finalization: reread grew %d turn-relevant line(s) past "
            "the high-water mark (%d) — fresh activity, no silence window; declining salvage, run=%s",
            relevant_growth,
            max_total_lines_seen,
            task_run.id,
        )
        return None
    printed_lines = _stream_new_lines(full_log, printed_lines, verbose=verbose, output_fn=output_fn)
    logger.warning(
        "custom_prompt - salvage_dropped_finalization: end_turn missing, turn-accounting tail present, "
        "stale %ds at poll timeout (%ds) — salvaging last message, run=%s total_lines=%d",
        stale_seconds,
        elapsed,
        task_run.id,
        total_lines,
    )
    return last_message, full_log, total_lines, printed_lines


async def _drain_final_log(
    task_run,
    *,
    refreshed_status: str,
    error_message: str | None = None,
    printed_lines: int,
    original_skip_lines: int,
    verbose: bool,
    output_fn: OutputFn,
) -> tuple[str, str | None, int, int]:
    """
    Drain one last S3 read after the TaskRun hit a terminal status. S3 may not have flushed the final agent_message
    before Temporal marked the run done, so we retry the read. Raises RuntimeError if no message is recoverable.

    Re-parses from the start-of-turn cursor (`original_skip_lines`) rather than only the slice past the *last* poll
    cursor: when the agent emits text mid-run but never reaches `end_turn` (e.g. killed by inactivity timeout
    mid-tool-call), the agent_message landed in an earlier poll slice and the per-poll cursor has advanced past
    it. Scanning from start-of-turn recovers it without crossing into the previous turn (which would return a
    stale earlier-turn response in multi-turn sessions). For single-turn callers `original_skip_lines == 0`, so
    the scan covers the full log as before. The walk is idempotent and only runs once at terminal status.
    """
    _, final_message, final_log, final_lines, final_empty_end_turn = await _read_turn_log_with_retry(
        task_run, skip_lines=original_skip_lines, context="drain_final_log"
    )
    printed_lines = _stream_new_lines(final_log, printed_lines, verbose=verbose, output_fn=output_fn)
    if final_message:
        return final_message, final_log, final_lines, printed_lines
    # Prefer the agent's own classified error over the generic terminal-status message
    # (Temporal's "Activity task failed"). Only on FAILED — CANCELLED is a user action and
    # COMPLETED-with-no-message is the empty-turn path, neither of which we want to relabel.
    if refreshed_status == TaskRun.Status.FAILED:
        agent_error = _extract_agent_error(final_log, skip_lines=original_skip_lines)
        if agent_error is not None:
            cause_text = agent_error.describe()
            # Persist the real cause so the TaskRun stops showing "Activity task failed".
            await _persist_task_run_error_message(str(task_run.id), cause_text)
            raise RuntimeError(
                f"custom_prompt - drain_final_log: TaskRun reached terminal status={refreshed_status} "
                f"(cause: {cause_text})"
            )
    reason = "end_turn with empty response" if final_empty_end_turn else "no agent message"
    cause = f" (cause: {error_message})" if error_message else ""
    raise RuntimeError(
        f"custom_prompt - drain_final_log: TaskRun reached terminal status={refreshed_status}{cause} — {reason}"
    )


def _extract_agent_error(log_content: str | None, skip_lines: int = 0) -> AgentError | None:
    """Scan log lines for the agent's structured terminal-error notification.

    Returns the last `_posthog/error` entry carrying a non-empty message (with the
    classified `error_category` when the agent build provides it), or None when no
    such entry exists — e.g. an older agent build or a non-agent failure — in which
    case the caller falls back to the generic terminal-status message.
    """
    if not log_content:
        return None
    lines = log_content.strip().split("\n")
    found: AgentError | None = None
    for line in lines[skip_lines:]:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        notification = entry.get("notification")
        if not isinstance(notification, dict) or notification.get("method") != AGENT_ERROR_METHOD:
            continue
        params = notification.get("params")
        if not isinstance(params, dict):
            continue
        message = params.get("message")
        if not isinstance(message, str) or not message.strip():
            continue
        raw_category = params.get("error_category")
        category = raw_category.strip() if isinstance(raw_category, str) and raw_category.strip() else None
        found = AgentError(message=message.strip(), category=category)
    return found


def _update_task_run_error_message(run_id: str, message: str) -> None:
    TaskRun.objects.filter(id=run_id).update(error_message=message)


async def _persist_task_run_error_message(run_id: str, message: str) -> None:
    """Best-effort write of the agent's real error onto the TaskRun. The raised
    RuntimeError already carries the message for Temporal, so a failed write here
    must not mask the underlying failure."""
    try:
        await sync_to_async(_update_task_run_error_message)(run_id, message)
    except Exception:
        logger.warning(
            "custom_prompt - drain_final_log: failed to persist agent error to TaskRun run=%s",
            run_id,
            exc_info=True,
        )


def _stream_new_lines(
    full_log: str | None, printed_lines: int, *, verbose: bool = False, output_fn: OutputFn = None
) -> int:
    """Stream new log lines to output_fn if provided. Does nothing when output_fn is None."""
    if not full_log:
        return printed_lines
    lines = full_log.strip().split("\n")
    # Clamp to keep the cursor monotonic against S3 eventually-consistent reads
    if output_fn is None:
        return max(printed_lines, len(lines))
    for line in lines[printed_lines:]:
        line = line.strip()
        if not line:
            continue
        if verbose:
            output_fn(line)
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        notification = entry.get("notification")
        if not isinstance(notification, dict) or notification.get("method") != "session/update":
            continue
        params = notification.get("params")
        update = params.get("update") if isinstance(params, dict) else None
        if not isinstance(update, dict):
            continue
        text = _extract_text(update)
        if text:
            output_fn(text)
    return max(printed_lines, len(lines))


def _check_logs(task_run, skip_lines: int = 0) -> tuple[bool, str | None, str | None, int, bool]:
    """
    Parse S3 logs. When skip_lines > 0, only lines after that offset are inspected for end_turn
    and agent messages. This avoids re-parsing the entire log on every poll cycle.
    """
    log_content = object_storage.read(task_run.log_url, missing_ok=True) or ""
    if not log_content.strip():
        return False, None, None, 0, False
    all_lines = log_content.strip().split("\n")
    total_lines = len(all_lines)
    # Eventual consistency: if S3 returns fewer lines than expected, no new data
    if total_lines <= skip_lines:
        return False, None, log_content, total_lines, False
    lines_to_parse = all_lines[skip_lines:]
    agent_finished = False
    # Collect all parsed session updates so we can walk backwards at the end.
    parsed_updates: list[dict] = []
    for line in lines_to_parse:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        notification = entry.get("notification")
        if not isinstance(notification, dict):
            continue
        result = notification.get("result")
        if isinstance(result, dict) and result.get("stopReason") == "end_turn":
            agent_finished = True
        if notification.get("method") != "session/update":
            continue
        params = notification.get("params")
        update = params.get("update") if isinstance(params, dict) else None
        if not isinstance(update, dict):
            continue
        parsed_updates.append(update)
    # Walk backwards from the end to find the final agent response.
    # First, skip non-agent entries (e.g. usage_update) to find the last
    # agent message. Then collect consecutive agent messages until we hit
    # something else — the agent sometimes splits its response across entries.
    _AGENT_MSG_TYPES = {"agent_message", "agent_message_chunk"}
    trailing_parts: list[str] = []
    found_agent_msg = False
    for update in reversed(parsed_updates):
        is_agent_msg = update.get("sessionUpdate") in _AGENT_MSG_TYPES
        if not found_agent_msg:
            if is_agent_msg:
                found_agent_msg = True
            else:
                continue
        if found_agent_msg and not is_agent_msg:
            break
        text = _extract_text(update)
        if text:
            trailing_parts.append(text)
    trailing_parts.reverse()
    latest_text = "".join(trailing_parts) if trailing_parts else None
    # If we found end_turn but no agent message in the new lines, flag it as an empty turn.
    if agent_finished and latest_text is None:
        return False, None, log_content, total_lines, True
    return agent_finished, latest_text, log_content, total_lines, False


def _is_failed_progress(notification: dict) -> bool:
    """True for a `_posthog/progress` notification carrying the failed/cancelled status the workflow's
    exception and cancel handlers emit before writing the terminal TaskRun status."""
    if notification.get("method") != "_posthog/progress":
        return False
    params = notification.get("params")
    return isinstance(params, dict) and params.get("status") == FAILED_PROGRESS_STATUS


def _transient_growth(lines: list[str]) -> int:
    """Count how many of `lines` are transient relay side-channel notifications (network audits,
    credential refreshes, sandbox stdout, informational progress). A failed progress line is not
    transient — it must count as real activity so the growth check can't discount a failure away."""
    count = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            notification = json.loads(line).get("notification")
        except json.JSONDecodeError:
            continue
        if not isinstance(notification, dict) or notification.get("method") not in TRANSIENT_SIDE_CHANNEL_METHODS:
            continue
        if _is_failed_progress(notification):
            continue
        count += 1
    return count


def _ended_on_pending_finalization(full_log: str | None) -> bool:
    """True when the agent's last turn-relevant notification is a usage_update carrying an explicit
    null cost — the sandbox ran turn accounting but the closing end_turn was dropped. The cost key
    must be present and null: older usage_update lines omit it entirely and are not this fingerprint.
    Any other trailing turn-relevant notification (an end_turn/result, a `_posthog/error`, a mid-turn
    update) is decisive that this is not the dropped-finalization case, so we don't salvage and let
    the normal completion / terminal-status drain handle it.

    Observability side-channels (`TRANSIENT_SIDE_CHANNEL_METHODS`) are skipped while walking back:
    the relay appends agentsh network-audit events and credential-refresh notices to the turn log
    asynchronously, so one routinely lands after the closing usage_update. Treating such a line as
    the decisive tail (the prior behavior) masked the fingerprint and made the salvage decline a
    turn that had genuinely finished — the dominant cause of scout runs hanging out to the poll
    timeout and being marked failed. The one exception is a failed/cancelled `_posthog/progress`
    marker: the workflow emits it on its way to a terminal status, so it stays decisive."""
    if not full_log:
        return False
    for line in reversed(full_log.strip().split("\n")):
        line = line.strip()
        if not line:
            continue
        try:
            notification = json.loads(line).get("notification")
        except json.JSONDecodeError:
            continue
        if not isinstance(notification, dict):
            continue
        if notification.get("method") in TRANSIENT_SIDE_CHANNEL_METHODS:
            # A failed/cancelled progress marker is decisive — the workflow emits it on its way to a
            # terminal status, so we must not skip it to salvage an earlier finalization fingerprint.
            if _is_failed_progress(notification):
                return False
            continue
        params = notification.get("params")
        update = params.get("update") if isinstance(params, dict) else None
        if not isinstance(update, dict):
            # The last notification is a result/error/other — not a turn sitting on accounting.
            return False
        return update.get("sessionUpdate") == "usage_update" and "cost" in update and update["cost"] is None
    return False


def _extract_text(update: dict) -> str | None:
    content = update.get("content")
    if isinstance(content, dict) and content.get("type") == "text" and isinstance(content.get("text"), str):
        candidate = content["text"].strip()
        if candidate:
            return candidate
    message = update.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return None


def extract_json_from_text(text: str | None, label: str) -> Any:
    """Extract JSON from text that might contain markdown formatting or surrounding commentary."""
    if text is None:
        raise ValueError(f"Text to extract JSON from ({label}) is None")

    # 1. ```json ... ``` fenced code block (non-greedy to stop at first closing fence)
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        candidate = match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # 2. ``` ... ``` generic code block that happens to contain JSON
    match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        candidate = match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # 3. Bare JSON object in surrounding text — try each { from the left paired with the last }
    last_brace = text.rfind("}")
    if last_brace != -1:
        start = 0
        while True:
            brace_pos = text.find("{", start)
            if brace_pos == -1 or brace_pos >= last_brace:
                break
            try:
                return json.loads(text[brace_pos : last_brace + 1])
            except json.JSONDecodeError:
                start = brace_pos + 1

    # 4. Last resort — try the whole text as-is, then surface a classified error so
    # callers (and operators reading the failure) can tell empty / fenced / prose apart
    # instead of seeing a bare "Expecting value: line 1 column 1 (char 0)".
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as e:
        if not stripped:
            raise ValueError(f"No JSON in {label}: end-turn text was empty or whitespace-only") from e
        if "```" in text:
            raise ValueError(
                f"No valid JSON in {label}: text has a code fence but its contents did not parse as JSON"
            ) from e
        raise ValueError(
            f"No JSON in {label}: end-turn text was prose with no JSON object (starts with {stripped[:60]!r})"
        ) from e
