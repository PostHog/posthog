import json
import time
import shlex
import asyncio
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.temporal.common.utils import asyncify, close_db_connections, retry_on_db_connection_drop
from posthog.utils import absolute_uri

from products.tasks.backend.constants import DEV_STACK_PREVIEW_PORT, DEV_STACK_PREVIEW_STATE_KEY
from products.tasks.backend.logic.services.sandbox import (
    Sandbox,
    SandboxBase,
    redact_sandbox_command,
    sandbox_repo_path,
)
from products.tasks.backend.metrics import DEV_STACK_PREVIEW_BOOT_SECONDS, DEV_STACK_PREVIEW_TOTAL
from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.observability import emit_agent_log, emit_progress, log_activity_execution
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext

logger = structlog.get_logger(__name__)

SCRIPT_LOCAL_PATH = Path("products/tasks/backend/sandbox/images/start-dev-stack-preview.sh")
SCRIPT_SANDBOX_PATH = "/tmp/start-dev-stack-preview.sh"
STATE_DIR = "/tmp/posthog-preview"
STATUS_FILE = f"{STATE_DIR}/status.json"
LOCK_FILE = f"{STATE_DIR}/lock"
LOG_FILE = f"{STATE_DIR}/start.log"

LAUNCH_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/local/go/bin"
LAUNCH_HOME = "/root"

BAKE_MANIFEST_PATH = "/opt/posthog/dev-stack-bake.json"

STEP_TIMEOUT_SECONDS = 30
LAUNCH_TIMEOUT_SECONDS = 30
POLL_TIMEOUT_SECONDS = 30
POLL_INTERVAL_SECONDS = 10
READY_TIMEOUT_SECONDS = 12 * 60

PROGRESS_STEP = "preview"
PROGRESS_GROUP = "setup"

_LOG_TAIL_CHARS = 1_500
LOCK_HELD_EXIT_CODE = 75
SKIPPED_REASONS = frozenset({"disabled", "already_ready", "not_dev_stack_image"})


@frozen
class StartDevStackPreviewInput:
    context: TaskProcessingContext
    sandbox_id: str
    repository: str


@frozen
class StartDevStackPreviewOutput:
    started: bool
    attached: bool = False
    reason: str | None = None


@frozen
class WaitDevStackPreviewInput:
    context: TaskProcessingContext
    sandbox_id: str


@frozen
class WaitDevStackPreviewOutput:
    ready: bool
    boot_seconds: float | None = None
    reason: str | None = None


@frozen
class PreviewStatus:
    state: str
    error: str | None = None


def preview_url(*, team_id: int, task_id: str, run_id: str) -> str:
    return absolute_uri(f"/api/projects/{team_id}/tasks/{task_id}/runs/{run_id}/preview/")


def _preview_host(url: str) -> str | None:
    parsed = urlparse(url)
    return parsed.netloc or None


def _launch_command(*, host: str, repo_path: str) -> str:
    return (
        f"/usr/bin/env -i "
        f"HOME={shlex.quote(LAUNCH_HOME)} "
        f"PATH={shlex.quote(LAUNCH_PATH)} "
        f"MODAL_HOST={shlex.quote(host)} "
        f"PREVIEW_PORT={shlex.quote(str(DEV_STACK_PREVIEW_PORT))} "
        f"REPO_PATH={shlex.quote(repo_path)} "
        f"setsid /bin/bash {shlex.quote(SCRIPT_SANDBOX_PATH)} "
        f">>{shlex.quote(LOG_FILE)} 2>&1 </dev/null &"
    )


def _already_previewing(run_id: str, sandbox_id: str) -> bool:
    run = TaskRun.objects.filter(id=run_id).values_list("state", flat=True).first()
    state = run if isinstance(run, dict) else {}
    preview = state.get(DEV_STACK_PREVIEW_STATE_KEY)
    return isinstance(preview, dict) and preview.get("sandbox_id") == sandbox_id


@asyncify
def _launch_preview(input: StartDevStackPreviewInput) -> StartDevStackPreviewOutput:
    ctx = input.context
    if _already_previewing(ctx.run_id, input.sandbox_id):
        return StartDevStackPreviewOutput(started=False, reason="already_ready")

    sandbox: SandboxBase = Sandbox.get_by_id(input.sandbox_id)

    manifest = sandbox.execute(f"test -f {shlex.quote(BAKE_MANIFEST_PATH)}", timeout_seconds=STEP_TIMEOUT_SECONDS)
    if manifest.exit_code != 0:
        return StartDevStackPreviewOutput(started=False, reason="not_dev_stack_image")

    credentials = sandbox.create_preview_connect_credentials(
        port=DEV_STACK_PREVIEW_PORT,
        user_metadata={"run_id": ctx.run_id, "team_id": ctx.team_id},
    )
    host = _preview_host(credentials.url)
    if not host:
        return StartDevStackPreviewOutput(started=False, reason="no_preview_host")

    prepared = sandbox.execute(f"mkdir -p {shlex.quote(STATE_DIR)}", timeout_seconds=STEP_TIMEOUT_SECONDS)
    if prepared.exit_code != 0:
        return StartDevStackPreviewOutput(started=False, reason=f"prepare_exit_{prepared.exit_code}")

    lock = sandbox.execute(
        f"flock -n -E {LOCK_HELD_EXIT_CODE} {shlex.quote(LOCK_FILE)} true", timeout_seconds=STEP_TIMEOUT_SECONDS
    )
    if lock.exit_code == LOCK_HELD_EXIT_CODE:
        return StartDevStackPreviewOutput(started=True, attached=True)
    if lock.exit_code != 0:
        return StartDevStackPreviewOutput(started=False, reason=f"lock_exit_{lock.exit_code}")

    script = (Path(settings.BASE_DIR) / SCRIPT_LOCAL_PATH).read_text()
    uploaded = sandbox.write_file(SCRIPT_SANDBOX_PATH, script.encode(), timeout_seconds=STEP_TIMEOUT_SECONDS)
    if uploaded.exit_code != 0:
        return StartDevStackPreviewOutput(started=False, reason=f"upload_exit_{uploaded.exit_code}")

    result = sandbox.execute(
        _launch_command(host=host, repo_path=sandbox_repo_path(input.repository)),
        timeout_seconds=LAUNCH_TIMEOUT_SECONDS,
    )
    if result.exit_code != 0:
        return StartDevStackPreviewOutput(started=False, reason=f"launch_exit_{result.exit_code}")
    return StartDevStackPreviewOutput(started=True)


@asyncify
def _resolve_sandbox(sandbox_id: str) -> SandboxBase:
    return Sandbox.get_by_id(sandbox_id)


async def _read_status(sandbox: SandboxBase) -> PreviewStatus | None:
    return await sync_to_async(_read_status_sync, thread_sensitive=False)(sandbox)


def _read_status_sync(sandbox: SandboxBase) -> PreviewStatus | None:
    result = sandbox.execute(f"cat {shlex.quote(STATUS_FILE)} 2>/dev/null", timeout_seconds=POLL_TIMEOUT_SECONDS)
    if result.exit_code != 0 or not result.stdout.strip():
        return None
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    state = payload.get("state")
    error = payload.get("error")
    if not isinstance(state, str):
        return None
    return PreviewStatus(state=state, error=error if isinstance(error, str) else None)


@asyncify
def _read_log_tail(sandbox: SandboxBase) -> str:
    try:
        result = sandbox.execute(f"tail -c {_LOG_TAIL_CHARS} {shlex.quote(LOG_FILE)} 2>/dev/null", timeout_seconds=30)
    except Exception:
        return ""
    return redact_sandbox_command(result.stdout.strip())[:_LOG_TAIL_CHARS]


@asyncify
def _stamp_preview_ready(run_id: str, sandbox_id: str, ready_at: str) -> None:
    def _mutator(state: dict) -> None:
        existing = state.get(DEV_STACK_PREVIEW_STATE_KEY)
        preview = dict(existing) if isinstance(existing, dict) else {}
        preview.update({"port": DEV_STACK_PREVIEW_PORT, "sandbox_id": sandbox_id, "ready_at": ready_at})
        state[DEV_STACK_PREVIEW_STATE_KEY] = preview

    retry_on_db_connection_drop(lambda: TaskRun.mutate_state_atomic(run_id, _mutator))


@asyncify
def _emit_preview_progress(*, run_id: str, status: str, label: str, detail: str | None = None) -> None:
    emit_progress(
        run_id=run_id,
        step=PROGRESS_STEP,
        status=status,
        label=label,
        group=f"{PROGRESS_GROUP}:{run_id}",
        detail=detail,
    )


@asyncify
def _emit_preview_warning(run_id: str, message: str) -> None:
    emit_agent_log(run_id, "warn", message)


@activity.defn
@close_db_connections
async def start_dev_stack_preview(input: StartDevStackPreviewInput) -> StartDevStackPreviewOutput:
    ctx = input.context
    with log_activity_execution("start_dev_stack_preview", sandbox_id=input.sandbox_id, **ctx.to_log_context()):
        if not ctx.dev_stack_preview_enabled:
            return StartDevStackPreviewOutput(started=False, reason="disabled")

        try:
            output = await _launch_preview(input)
        except Exception:
            logger.warning("dev_stack_preview_launch_failed", run_id=ctx.run_id, exc_info=True)
            DEV_STACK_PREVIEW_TOTAL.labels(outcome="launch_failed").inc()
            raise

        if not output.started:
            logger.info("dev_stack_preview_not_started", run_id=ctx.run_id, reason=output.reason)
            if output.reason not in SKIPPED_REASONS:
                DEV_STACK_PREVIEW_TOTAL.labels(outcome="launch_failed").inc()
                await _report_preview_failure(ctx.run_id, output.reason or "launch_failed")
            return output

        DEV_STACK_PREVIEW_TOTAL.labels(outcome="attached" if output.attached else "started").inc()
        await _emit_preview_progress(run_id=ctx.run_id, status="in_progress", label="Starting PostHog preview")
        return output


async def _await_ready(sandbox: SandboxBase, run_id: str) -> tuple[PreviewStatus | None, float]:
    started_at = time.monotonic()
    deadline = started_at + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        activity.heartbeat()
        try:
            status = await _read_status(sandbox)
        except Exception:
            logger.warning("dev_stack_preview_status_read_failed", run_id=run_id, exc_info=True)
            status = None
        if status is not None and status.state in ("ready", "failed"):
            return status, time.monotonic() - started_at
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
    return None, time.monotonic() - started_at


@activity.defn
@close_db_connections
async def wait_dev_stack_preview(input: WaitDevStackPreviewInput) -> WaitDevStackPreviewOutput:
    ctx = input.context
    with log_activity_execution("wait_dev_stack_preview", sandbox_id=input.sandbox_id, **ctx.to_log_context()):
        if not ctx.dev_stack_preview_enabled:
            return WaitDevStackPreviewOutput(ready=False, reason="disabled")

        try:
            output = await _wait_for_preview(input)
        except asyncio.CancelledError:
            DEV_STACK_PREVIEW_TOTAL.labels(outcome="cancelled").inc()
            raise
        DEV_STACK_PREVIEW_TOTAL.labels(outcome=_terminal_outcome(output)).inc()
        return output


def _terminal_outcome(output: WaitDevStackPreviewOutput) -> str:
    if output.ready:
        return "ready"
    return "timed_out" if output.reason == "timed_out" else "failed"


async def _report_preview_failure(run_id: str, detail: str, tail: str = "") -> None:
    await _emit_preview_progress(run_id=run_id, status="failed", label="Preview didn't start")
    await _emit_preview_warning(
        run_id,
        f"The PostHog preview did not start ({detail}). The task continues without it." + (f"\n{tail}" if tail else ""),
    )


async def _wait_for_preview(input: WaitDevStackPreviewInput) -> WaitDevStackPreviewOutput:
    ctx = input.context
    try:
        sandbox = await _resolve_sandbox(input.sandbox_id)
    except Exception:
        logger.warning("dev_stack_preview_sandbox_unavailable", run_id=ctx.run_id, exc_info=True)
        await _report_preview_failure(ctx.run_id, "sandbox unavailable")
        return WaitDevStackPreviewOutput(ready=False, reason="sandbox_unavailable")

    status, elapsed = await _await_ready(sandbox, ctx.run_id)

    if status is not None and status.state == "ready":
        DEV_STACK_PREVIEW_BOOT_SECONDS.observe(elapsed)
        try:
            await _stamp_preview_ready(ctx.run_id, input.sandbox_id, timezone.now().isoformat())
        except Exception:
            logger.warning("dev_stack_preview_state_write_failed", run_id=ctx.run_id, exc_info=True)
            await _report_preview_failure(ctx.run_id, "state write failed")
            return WaitDevStackPreviewOutput(ready=False, boot_seconds=elapsed, reason="state_write_failed")
        await _emit_preview_progress(
            run_id=ctx.run_id,
            status="completed",
            label="Preview ready",
            detail=preview_url(team_id=ctx.team_id, task_id=ctx.task_id, run_id=ctx.run_id),
        )
        return WaitDevStackPreviewOutput(ready=True, boot_seconds=elapsed)

    timed_out = status is None
    tail = await _read_log_tail(sandbox)
    detail = (status.error if status is not None and status.error else "") or "timed out"
    await _report_preview_failure(ctx.run_id, detail, tail)
    return WaitDevStackPreviewOutput(
        ready=False,
        boot_seconds=elapsed,
        reason="timed_out" if timed_out else "failed",
    )
