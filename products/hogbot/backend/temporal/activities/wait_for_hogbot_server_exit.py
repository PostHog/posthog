from __future__ import annotations

import shlex
import asyncio
from dataclasses import dataclass

from temporalio import activity

from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.observability import log_activity_execution

from .server_state import HOGBOT_SERVER_EXIT_CODE_PATH, HOGBOT_SERVER_PID_PATH

MAX_UNKNOWN_POLLS = 5


@dataclass
class WaitForHogbotServerExitInput:
    sandbox_id: str
    poll_interval_seconds: int = 2


@dataclass
class WaitForHogbotServerExitOutput:
    status: str
    exit_code: int | None = None
    error: str | None = None


def _build_status_script() -> str:
    return (
        f"if [ -s {shlex.quote(HOGBOT_SERVER_EXIT_CODE_PATH)} ]; then "
        f"  code=$(cat {shlex.quote(HOGBOT_SERVER_EXIT_CODE_PATH)}); "
        f'  if [ "$code" = "0" ]; then echo "status=completed"; else echo "status=failed"; fi; '
        f'  echo "exit_code=$code"; '
        "  exit 0; "
        "fi; "
        f"if [ ! -s {shlex.quote(HOGBOT_SERVER_PID_PATH)} ]; then "
        '  echo "status=unknown"; echo "error=pid_file_missing"; exit 0; '
        "fi; "
        f"pid=$(cat {shlex.quote(HOGBOT_SERVER_PID_PATH)}); "
        'if kill -0 "$pid" 2>/dev/null; then echo "status=running"; exit 0; fi; '
        'echo "status=unknown"; echo "error=process_exited_without_exit_code"; '
    )


def _parse_status_output(stdout: str, stderr: str) -> WaitForHogbotServerExitOutput:
    details: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        details[key.strip()] = value.strip()

    status = details.get("status", "unknown")
    if status not in {"running", "completed", "failed", "unknown"}:
        status = "unknown"

    exit_code_raw = details.get("exit_code")
    exit_code = int(exit_code_raw) if exit_code_raw and exit_code_raw.lstrip("-").isdigit() else None
    error = details.get("error") or stderr.strip() or None

    return WaitForHogbotServerExitOutput(status=status, exit_code=exit_code, error=error)


@activity.defn(name="hogbot_wait_for_server_exit")
async def wait_for_hogbot_server_exit(input: WaitForHogbotServerExitInput) -> WaitForHogbotServerExitOutput:
    with log_activity_execution(
        "wait_for_hogbot_server_exit",
        sandbox_id=input.sandbox_id,
    ):
        try:
            sandbox = Sandbox.get_by_id(input.sandbox_id)
        except Exception as e:
            return WaitForHogbotServerExitOutput(status="failed", error=str(e))

        unknown_polls = 0

        while True:
            activity.heartbeat()

            if not sandbox.is_running():
                return WaitForHogbotServerExitOutput(status="failed", error="Sandbox not running")

            try:
                result = sandbox.execute(_build_status_script(), timeout_seconds=10)
            except Exception as e:
                return WaitForHogbotServerExitOutput(status="failed", error=str(e))

            status_output = _parse_status_output(result.stdout, result.stderr)

            if status_output.status == "running":
                unknown_polls = 0
            elif status_output.status in {"completed", "failed"}:
                return status_output
            else:
                unknown_polls += 1
                if unknown_polls >= MAX_UNKNOWN_POLLS:
                    return WaitForHogbotServerExitOutput(
                        status="failed",
                        exit_code=status_output.exit_code,
                        error=status_output.error or "Hogbot server exited without writing an exit code",
                    )

            await asyncio.sleep(input.poll_interval_seconds)
