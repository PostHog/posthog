import shlex
from dataclasses import dataclass

from django.conf import settings

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.services.sandbox import Sandbox, wait_for_health_check
from products.tasks.backend.temporal.observability import log_activity_execution

from .server_state import (
    HOGBOT_LAUNCHER_LOG_PATH,
    HOGBOT_SERVER_EXIT_CODE_PATH,
    HOGBOT_SERVER_LOG_PATH,
    HOGBOT_SERVER_PID_PATH,
    HOGBOT_STATE_DIR,
)

HOGBOT_WORKSPACE_PATH = "/tmp/workspace"
HOGBOT_SERVER_BIN_PATH = "/scripts/node_modules/@posthog/products-hogbot/server/dist/bin.js"


@dataclass
class StartHogbotServerInput:
    sandbox_id: str
    team_id: int
    server_command: str | None = None
    sandbox_url: str | None = None
    connect_token: str | None = None


@dataclass
class StartHogbotServerOutput:
    server_url: str
    connect_token: str | None = None


def _build_default_server_command(*, team_id: int, port: int, public_base_url: str, connect_token: str | None) -> str:
    command = [
        "node",
        HOGBOT_SERVER_BIN_PATH,
        "--port",
        str(port),
        "--teamId",
        str(team_id),
        "--workspacePath",
        HOGBOT_WORKSPACE_PATH,
        "--publicBaseUrl",
        public_base_url,
    ]
    if connect_token:
        command.extend(["--sandboxConnectToken", connect_token])
    return " ".join(shlex.quote(part) for part in command)


def _render_server_command(
    *,
    team_id: int,
    port: int,
    public_base_url: str,
    connect_token: str | None,
    server_command: str | None,
) -> str:
    if not server_command:
        return _build_default_server_command(
            team_id=team_id,
            port=port,
            public_base_url=public_base_url,
            connect_token=connect_token,
        )

    sandbox_connect_token_arg = ""
    if connect_token:
        sandbox_connect_token_arg = (
            f" --sandboxConnectToken {shlex.quote(connect_token)}"
        )

    template_values = {
        "port": str(port),
        "team_id": str(team_id),
        "workspace_path": shlex.quote(HOGBOT_WORKSPACE_PATH),
        "public_base_url": shlex.quote(public_base_url),
        "sandbox_connect_token": shlex.quote(connect_token) if connect_token else "",
        "sandbox_connect_token_arg": sandbox_connect_token_arg,
    }
    try:
        return server_command.format(**template_values)
    except (KeyError, ValueError):
        return server_command


def _build_server_launcher_command(server_command: str) -> str:
    launcher_script = (
        "set -euo pipefail; "
        f"echo $$ > {shlex.quote(HOGBOT_SERVER_PID_PATH)}; "
        f"trap 'code=$?; echo $code > {shlex.quote(HOGBOT_SERVER_EXIT_CODE_PATH)}' EXIT; "
        f"bash -lc {shlex.quote(server_command)} > {shlex.quote(HOGBOT_SERVER_LOG_PATH)} 2>&1"
    )

    return (
        f"mkdir -p {shlex.quote(HOGBOT_STATE_DIR)} && "
        f"rm -f {shlex.quote(HOGBOT_SERVER_PID_PATH)} "
        f"{shlex.quote(HOGBOT_SERVER_EXIT_CODE_PATH)} "
        f"{shlex.quote(HOGBOT_SERVER_LOG_PATH)} "
        f"{shlex.quote(HOGBOT_LAUNCHER_LOG_PATH)} && "
        "nohup bash -lc "
        f"{shlex.quote(launcher_script)} "
        f"> {shlex.quote(HOGBOT_LAUNCHER_LOG_PATH)} 2>&1 &"
    )


@activity.defn(name="hogbot_start_server")
@asyncify
def start_hogbot_server(input: StartHogbotServerInput) -> StartHogbotServerOutput:
    with log_activity_execution(
        "start_hogbot_server",
        sandbox_id=input.sandbox_id,
    ):
        sandbox = Sandbox.get_by_id(input.sandbox_id)

        server_url = input.sandbox_url or sandbox.get_connect_credentials().url
        connect_token = input.connect_token

        provider = getattr(settings, "SANDBOX_PROVIDER", None)
        port = 47821 if provider == "docker" else 8080
        rendered_command = _render_server_command(
            team_id=input.team_id,
            port=port,
            public_base_url=server_url,
            connect_token=connect_token,
            server_command=input.server_command,
        )

        result = sandbox.execute(_build_server_launcher_command(rendered_command), timeout_seconds=30)
        if result.exit_code != 0:
            error = result.stderr or result.stdout or "Failed to start hogbot server"
            raise RuntimeError(error)

        healthy = wait_for_health_check(
            sandbox.execute,
            input.sandbox_id,
            port=port,
        )
        if not healthy:
            server_log_result = sandbox.execute(
                f"cat {shlex.quote(HOGBOT_SERVER_LOG_PATH)} 2>/dev/null || echo 'No server log found'",
                timeout_seconds=10,
            )
            launcher_log_result = sandbox.execute(
                f"cat {shlex.quote(HOGBOT_LAUNCHER_LOG_PATH)} 2>/dev/null || echo 'No launcher log found'",
                timeout_seconds=10,
            )
            raise RuntimeError(
                f"Hogbot server failed health check on port {port}.\n"
                f"Server logs:\n{server_log_result.stdout.strip()}\n"
                f"Launcher logs:\n{launcher_log_result.stdout.strip()}"
            )

        return StartHogbotServerOutput(
            server_url=server_url,
            connect_token=connect_token,
        )
