from __future__ import annotations

import json
import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from asgiref.sync import sync_to_async

from posthog.temporal.oauth import PosthogMcpScopes

if TYPE_CHECKING:
    from temporalio.client import WorkflowHandle

logger = logging.getLogger(__name__)

# Type for an optional output callback (e.g. management command's self.stdout.write)
OutputFn = Callable[[str], object] | None

# Sandbox logs polling from S3
POLL_INTERVAL_SECONDS = 10
MAX_POLL_SECONDS = 30 * 60  # 30 minutes (matches sandbox TTL)


@dataclass(frozen=True)
class CustomPromptSandboxContext:
    """Everything needed to spawn a sandbox agent for a given team/repo."""

    team_id: int
    user_id: int
    repository: str | None = None
    sandbox_environment_id: str | None = None
    posthog_mcp_scopes: PosthogMcpScopes | None = None


def resolve_sandbox_context_for_local_dev(repository: str) -> CustomPromptSandboxContext:
    """Build a CustomPromptSandboxContext from the first team/user in the local database.

    Requires a GitHub integration to exist for the team (Task.create_and_run
    resolves it automatically).
    """
    from posthog.models.integration import Integration
    from posthog.models.organization import OrganizationMembership
    from posthog.models.team.team import Team

    team = Team.objects.select_related("organization").first()
    if not team:
        raise RuntimeError("No team found in local database")

    membership = OrganizationMembership.objects.filter(organization=team.organization).order_by("id").first()
    if not membership:
        raise RuntimeError(f"No users in organization '{team.organization.name}' (team {team.id})")
    user = membership.user

    # Validate the integration exists upfront so we fail early with a clear message.
    gh = Integration.objects.filter(team=team, kind="github").first()
    if not gh:
        raise RuntimeError(
            f"No GitHub integration found for team {team.id}. "
            "Set up a GitHub App installation first: "
            "go to /settings/integrations in your local PostHog."
        )

    return CustomPromptSandboxContext(
        team_id=team.id,
        user_id=user.id,
        repository=repository,
    )


async def run_prompt(
    prompt: str,
    context: CustomPromptSandboxContext,
    *,
    branch: str = "master",
    step_name: str = "",
    verbose: bool = False,
    output_fn: OutputFn = None,
) -> tuple[str, str]:
    """Spawn a sandbox agent with the given prompt and return (last_message, full_log)."""
    task, task_run = await _create_task_and_trigger(prompt, context, branch, step_name)
    logger.info("custom_prompt: started task=%s run=%s step=%s", task.id, task_run.id, step_name or "unknown")
    # No try/catch, propagating to the caller, if it fails,
    # to turn into a clear failure instead of JSON parse error
    last_message, full_log, _, _ = await _poll_for_turn(task_run, verbose=verbose, output_fn=output_fn)
    logger.info("custom_prompt: finished run=%s", task_run.id)
    return last_message, full_log or ""


async def _create_task_and_trigger(
    description: str,
    context: CustomPromptSandboxContext,
    branch: str = "master",
    step_name: str = "",
    origin_product: str | None = None,
    signal_report_id: str | None = None,
):
    from posthog.models.team.team import Team

    from products.tasks.backend.models import Task

    title = f"[sandbox_prompt:{step_name}] {description[:80]}" if step_name else description[:100]
    team = await sync_to_async(Team.objects.get)(id=context.team_id)
    task = await sync_to_async(Task.create_and_run)(
        team=team,
        title=title,
        description=description,
        origin_product=Task.OriginProduct(origin_product) if origin_product else Task.OriginProduct.USER_CREATED,
        user_id=context.user_id,
        repository=context.repository,
        create_pr=False,
        mode="background",
        branch=branch if branch and branch != "master" else None,
        signal_report_id=signal_report_id,
    )
    task_run = await sync_to_async(lambda: task.latest_run)()
    if not task_run:
        raise RuntimeError("Task.create_and_run did not produce a TaskRun")
    return task, task_run


MAX_CONSECUTIVE_STORAGE_ERRORS = 3


async def _poll_for_turn(
    task_run,
    *,
    skip_lines: int = 0,
    printed_lines: int = 0,
    verbose: bool = False,
    output_fn: OutputFn = None,
    workflow_handle: WorkflowHandle | None = None,
) -> tuple[str, str | None, int, int]:
    """Poll S3 logs until the agent finishes a turn."""
    from posthog.storage.object_storage import ObjectStorageError

    from products.tasks.backend.models import TaskRun

    elapsed = 0
    consecutive_storage_errors = 0
    last_new_lines_at = 0  # elapsed time when we last saw new log lines
    while elapsed < MAX_POLL_SECONDS:
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
            finished, last_message, full_log, total_lines = await sync_to_async(_check_logs)(task_run, skip_lines)
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

        if total_lines > skip_lines:
            last_new_lines_at = elapsed
        stale_seconds = elapsed - last_new_lines_at
        if stale_seconds >= 60 and stale_seconds % 60 < POLL_INTERVAL_SECONDS:
            logger.warning(
                "custom_prompt - poll_for_turn: no new S3 log lines for %ds, run=%s, total_lines=%d",
                stale_seconds,
                task_run.id,
                total_lines,
            )

        printed_lines = _stream_new_lines(full_log, printed_lines, verbose=verbose, output_fn=output_fn)
        if finished and last_message:
            return last_message, full_log, total_lines, printed_lines

        skip_lines = total_lines
        refreshed = await sync_to_async(TaskRun.objects.get)(id=task_run.id)
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
            # Terminal status — one final log read with retries.
            final_message = None
            final_log = None
            final_lines = skip_lines
            for attempt in range(MAX_CONSECUTIVE_STORAGE_ERRORS):
                try:
                    _, final_message, final_log, final_lines = await sync_to_async(_check_logs)(task_run, skip_lines)
                    break
                except ObjectStorageError:
                    logger.warning(
                        "custom_prompt - poll_for_turn: storage error on final log read (%d/%d)",
                        attempt + 1,
                        MAX_CONSECUTIVE_STORAGE_ERRORS,
                        exc_info=True,
                    )
                    if attempt + 1 >= MAX_CONSECUTIVE_STORAGE_ERRORS:
                        raise
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
            printed_lines = _stream_new_lines(final_log, printed_lines, verbose=verbose, output_fn=output_fn)
            if final_message:
                return final_message, final_log, final_lines, printed_lines
            raise RuntimeError(
                f"custom_prompt - poll_for_turn: TaskRun reached terminal status={refreshed.status} with no agent message"
            )

    raise RuntimeError(f"custom_prompt - poll_for_turn: timed out after {elapsed}s")


def _stream_new_lines(
    full_log: str | None, printed_lines: int, *, verbose: bool = False, output_fn: OutputFn = None
) -> int:
    """Stream new log lines to output_fn if provided. Does nothing when output_fn is None."""
    if not full_log:
        return printed_lines
    lines = full_log.strip().split("\n")
    if output_fn is None:
        return len(lines)
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
    return len(lines)


def _check_logs(task_run, skip_lines: int = 0) -> tuple[bool, str | None, str | None, int]:
    """Parse S3 logs. Returns (agent_finished, last_agent_message, full_log_content, total_line_count).

    When skip_lines > 0, only lines after that offset are inspected for end_turn
    and agent messages. This avoids re-parsing the entire log on every poll cycle.
    """
    from posthog.storage import object_storage

    log_content = object_storage.read(task_run.log_url, missing_ok=True) or ""
    if not log_content.strip():
        return False, None, None, 0

    all_lines = log_content.strip().split("\n")
    total_lines = len(all_lines)

    # Eventual consistency: if S3 returns fewer lines than expected, no new data
    if total_lines <= skip_lines:
        return False, None, log_content, total_lines

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

    # If we found end_turn but no agent message in the new lines, keep polling rather than
    # rescanning from line 0. A full rescan could pull a previous turn's agent message (if multi turns),
    # and lead to duplicated results silently.
    if agent_finished and latest_text is None and skip_lines > 0:
        return False, None, log_content, total_lines

    return agent_finished, latest_text, log_content, total_lines


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
