#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

SCRIPT_PATH = Path(__file__).resolve()
HOGBOT_ROOT = SCRIPT_PATH.parent.parent
POSTHOG_ROOT = HOGBOT_ROOT.parent.parent
BASE_IMAGE_NAME = "posthog-sandbox-base"
HOGBOT_IMAGE_NAME = "posthog-hogbot-local:manual"
SERVER_PORT = 47821
POSTHOG_API_KEY = "test-posthog-api-key"
DEFAULT_TEAM_ID = 1
DEFAULT_SIGNAL_ID = "sig-manual"
SMOKE_ADMIN_PROMPT = "hello-manual"

SDK_FIXTURES_DIR = HOGBOT_ROOT / "server" / "src" / "__tests__" / "fixtures"


def run(cmd: list[str], *, check: bool = True, capture_output: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        capture_output=capture_output,
        env=env,
    )


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def build_base_image_if_needed() -> None:
    result = run(["docker", "image", "inspect", BASE_IMAGE_NAME], check=False)
    if result.returncode == 0:
        return

    dockerfile = POSTHOG_ROOT / "products" / "tasks" / "backend" / "sandbox" / "images" / "Dockerfile.sandbox-base"
    print(f"Building {BASE_IMAGE_NAME} from {dockerfile}")
    run(["docker", "build", "-f", str(dockerfile), "-t", BASE_IMAGE_NAME, str(POSTHOG_ROOT)], capture_output=False)


def build_hogbot_image(force_rebuild: bool) -> None:
    if not force_rebuild:
        result = run(["docker", "image", "inspect", HOGBOT_IMAGE_NAME], check=False)
        if result.returncode == 0:
            return

    build_base_image_if_needed()
    dockerfile = HOGBOT_ROOT / "server" / "images" / "Dockerfile.hogbot-local"
    print(f"Building {HOGBOT_IMAGE_NAME} from {dockerfile}")
    run(["docker", "build", "-f", str(dockerfile), "-t", HOGBOT_IMAGE_NAME, str(POSTHOG_ROOT)], capture_output=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload))
        handle.write("\n")


class FakePostHogRequestHandler(BaseHTTPRequestHandler):
    server_version = "HogbotFakePostHog/1.0"

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        server: FakePostHogServer = self.server  # type: ignore[assignment]
        prefix = f"/api/projects/{server.team_id}/hogbot"

        try:
            body = self._read_json()
        except json.JSONDecodeError:
            self._write_response(400, {"error": "Invalid JSON"})
            return

        if parsed.path == f"{prefix}/server/register/":
            write_json(server.logs_dir / "register.json", body)
            self._write_response(200, {"ok": True})
            return

        if parsed.path == f"{prefix}/server/heartbeat/":
            append_jsonl(server.logs_dir / "heartbeats.jsonl", body)
            self._write_response(200, {"ok": True})
            return

        if parsed.path == f"{prefix}/server/unregister/":
            append_jsonl(server.logs_dir / "unregister.jsonl", body)
            self._write_response(200, {"ok": True})
            return

        if parsed.path == f"{prefix}/admin/append_log/":
            for entry in body.get("entries", []):
                append_jsonl(server.logs_dir / "admin_logs.jsonl", entry)
            self._write_response(200, {"ok": True})
            return

        research_prefix = f"{prefix}/research/"
        research_suffix = "/append_log/"
        if parsed.path.startswith(research_prefix) and parsed.path.endswith(research_suffix):
            signal_id = parsed.path[len(research_prefix) : -len(research_suffix)]
            signal_id = signal_id.strip("/")
            for entry in body.get("entries", []):
                append_jsonl(server.logs_dir / "research" / f"{signal_id}.jsonl", entry)
            self._write_response(200, {"ok": True})
            return

        self._write_response(404, {"error": f"Unknown path: {parsed.path}"})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length == 0:
            return {}
        raw_body = self.rfile.read(content_length).decode("utf-8")
        return json.loads(raw_body)

    def _write_response(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FakePostHogServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, host: str, port: int, team_id: int, logs_dir: Path):
        super().__init__((host, port), FakePostHogRequestHandler)
        self.team_id = team_id
        self.logs_dir = logs_dir


def start_fake_posthog_server(team_id: int, logs_dir: Path) -> tuple[FakePostHogServer, threading.Thread, int]:
    port = find_free_port()
    server = FakePostHogServer("127.0.0.1", port, team_id, logs_dir)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, port


def create_workspace(workspace_arg: str | None) -> tuple[Path, bool]:
    if workspace_arg:
        workspace = Path(workspace_arg).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace, False

    workspace = Path(tempfile.mkdtemp(prefix="hogbot-local-workspace-"))
    (workspace / "sample.txt").write_text("workspace file\n", encoding="utf-8")
    return workspace, True


def create_mock_sdk_dir() -> Path:
    root = Path(tempfile.mkdtemp(prefix="hogbot-local-mock-sdk-"))
    package_dir = root / "node_modules" / "@anthropic-ai" / "claude-agent-sdk"
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "@anthropic-ai/claude-agent-sdk",
                "version": "0.0.0-test",
                "main": "./index.cjs",
                "exports": {
                    ".": {
                        "require": "./index.cjs",
                        "import": "./index.mjs",
                        "default": "./index.cjs",
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    shutil.copyfile(SDK_FIXTURES_DIR / "mock-claude-agent-sdk.cjs", package_dir / "index.cjs")
    shutil.copyfile(SDK_FIXTURES_DIR / "mock-claude-agent-sdk.mjs", package_dir / "index.mjs")
    register_path = root / "register-claude-sdk-mock.cjs"
    register_path.write_text(
        "\n".join(
            [
                'const Module = require("module");',
                'const path = require("path");',
                "const originalLoad = Module._load;",
                'const mockPath = path.join(__dirname, "node_modules", "@anthropic-ai", "claude-agent-sdk", "index.cjs");',
                "Module._load = function patchedLoad(request, parent, isMain) {",
                '    if (request === "@anthropic-ai/claude-agent-sdk") {',
                "        return originalLoad(mockPath, parent, isMain);",
                "    }",
                "    return originalLoad(request, parent, isMain);",
                "};",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return root


def collect_passthrough_env(extra_keys: list[str]) -> dict[str, str]:
    passthrough: dict[str, str] = {}
    default_keys = {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_REGION",
        "CLAUDE_CODE_USE_BEDROCK",
        "POSTHOG_CLAUDE_CODE_GATEWAY_TOKEN",
        "POSTHOG_CLAUDE_CODE_GATEWAY_URL",
    }
    for key in sorted(default_keys.union(extra_keys)):
        value = os.environ.get(key)
        if value:
            passthrough[key] = value
    return passthrough


def wait_for_health(base_url: str, timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            response = http_request("GET", f"{base_url}/health", timeout=2)
            if response["status"] == 200:
                return
        except OSError:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Hogbot server did not become healthy at {base_url} within {timeout_seconds} seconds")


def maybe_smoke_test(base_url: str, mock_sdk: bool, signal_id: str) -> None:
    health = http_request("GET", f"{base_url}/health", timeout=5)
    print(f"Smoke health: {health['status']} {health['text']}")

    admin = http_request(
        "POST",
        f"{base_url}/send_message",
        json={"content": SMOKE_ADMIN_PROMPT},
        timeout=60,
    )
    print(f"Smoke send_message: {admin['status']} {admin['text']}")

    if mock_sdk:
        research = http_request(
            "POST",
            f"{base_url}/research",
            json={"signal_id": signal_id, "prompt": "slow-research"},
            timeout=10,
        )
        print(f"Smoke research start: {research['status']} {research['text']}")


def http_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json: dict[str, Any] | None = None,
    timeout: float = 10,
) -> dict[str, Any]:
    body = None
    request_headers = dict(headers or {})
    if json is not None:
        body = json_module_dumps(json).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = Request(url, data=body, headers=request_headers, method=method)

    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
            return {
                "status": response.status,
                "text": payload,
                "headers": dict(response.headers.items()),
            }
    except HTTPError as error:
        return {
            "status": error.code,
            "text": error.read().decode("utf-8"),
            "headers": dict(error.headers.items()),
        }
    except URLError as error:
        raise OSError(str(error)) from error


def json_module_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"))


def print_manual_commands(base_url: str, workspace: Path, logs_dir: Path, container_name: str, signal_id: str) -> None:
    print("")
    print("Sandbox is running.")
    print(f"Server URL: {base_url}")
    print(f"Workspace: {workspace}")
    print(f"Fake PostHog log dir: {logs_dir}")
    print(f"Container name: {container_name}")
    print("")
    print("Export these in your shell:")
    print(f"export HOGBOT_URL={base_url}")
    print("")
    print("Try these commands:")
    print("curl -s \"$HOGBOT_URL/health\" | jq")
    print(
        "curl -s -X POST \"$HOGBOT_URL/send_message\" "
        "-H \"Content-Type: application/json\" "
        "-d '{\"content\":\"hello from curl\"}' | jq"
    )
    print(f"curl -N \"$HOGBOT_URL/logs?scope=research&signal_id={signal_id}\"")
    print(
        f"curl -s -X POST \"$HOGBOT_URL/research\" "
        "-H \"Content-Type: application/json\" "
        f"-d '{{\"signal_id\":\"{signal_id}\",\"prompt\":\"research the sample file\"}}' | jq"
    )
    print("curl -s \"$HOGBOT_URL/filesystem/content?path=/sample.txt\" | jq")
    print("curl -s -X POST \"$HOGBOT_URL/cancel\" | jq")
    print("")
    print("Useful inspection commands:")
    print(f"docker logs -f {container_name}")
    print(f"ls -R {logs_dir}")
    print(f"tail -f {logs_dir / 'admin_logs.jsonl'}")
    print("")
    print("Press Ctrl-C in this terminal to stop the container and fake API server.")


def remove_container(container_name: str) -> None:
    run(["docker", "rm", "-f", container_name], check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run hogbot-server inside a local Docker sandbox for manual testing.")
    parser.add_argument("--workspace", help="Host workspace directory to mount into the sandbox.")
    parser.add_argument("--team-id", type=int, default=DEFAULT_TEAM_ID)
    parser.add_argument("--host-port", type=int, help="Host port to expose hogbot-server on.")
    parser.add_argument("--signal-id", default=DEFAULT_SIGNAL_ID)
    parser.add_argument("--rebuild-image", action="store_true", help="Force rebuilding the hogbot local image.")
    parser.add_argument("--real-sdk", action="store_true", help="Use the real Claude SDK instead of the bundled mock.")
    parser.add_argument(
        "--passthrough-env",
        action="append",
        default=[],
        help="Environment variable name to pass through into the container. Can be used multiple times.",
    )
    parser.add_argument("--smoke", action="store_true", help="Run a simple smoke test after startup.")
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Do not delete the temporary workspace, fake API logs, or mock SDK files on exit.",
    )
    args = parser.parse_args()

    build_hogbot_image(force_rebuild=args.rebuild_image)

    workspace, workspace_is_temp = create_workspace(args.workspace)
    logs_dir = Path(tempfile.mkdtemp(prefix="hogbot-local-api-logs-"))
    api_server, api_thread, api_port = start_fake_posthog_server(args.team_id, logs_dir)
    mock_sdk_dir: Path | None = None
    host_port = args.host_port or find_free_port()
    container_name = f"hogbot-manual-{int(time.time())}"
    container_running = False

    def cleanup() -> None:
        nonlocal container_running
        if container_running:
            remove_container(container_name)
            container_running = False
        api_server.shutdown()
        api_server.server_close()
        if args.keep_artifacts:
            return
        if mock_sdk_dir is not None:
            shutil.rmtree(mock_sdk_dir, ignore_errors=True)
        if workspace_is_temp:
            shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(logs_dir, ignore_errors=True)

    def handle_signal(*_: Any) -> None:
        cleanup()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    base_url = f"http://127.0.0.1:{host_port}"
    posthog_api_url = f"http://host.docker.internal:{api_port}"

    env_args: list[str] = [
        "-e",
        "POSTHOG_API_URL",
        "-e",
        "POSTHOG_PERSONAL_API_KEY",
    ]
    env_values = {
        "POSTHOG_API_URL": posthog_api_url,
        "POSTHOG_PERSONAL_API_KEY": POSTHOG_API_KEY,
    }

    for key, value in collect_passthrough_env(args.passthrough_env).items():
        env_args.extend(["-e", key])
        env_values[key] = value

    volume_args = [
        "-v",
        f"{workspace}:/workspace",
    ]

    if not args.real_sdk:
        mock_sdk_dir = create_mock_sdk_dir()
        env_args.extend(["-e", "NODE_OPTIONS"])
        env_values["NODE_OPTIONS"] = "--require /deps/register-claude-sdk-mock.cjs"
        volume_args.extend(["-v", f"{mock_sdk_dir}:/deps"])

    docker_cmd = [
        "docker",
        "run",
        "-d",
        "--rm",
        "--name",
        container_name,
        "--add-host",
        "host.docker.internal:host-gateway",
        "-p",
        f"{host_port}:{SERVER_PORT}",
        *env_args,
        *volume_args,
        "-w",
        "/scripts",
        HOGBOT_IMAGE_NAME,
        "node",
        "/scripts/node_modules/@posthog/products-hogbot/server/dist/bin.js",
        "--port",
        str(SERVER_PORT),
        "--teamId",
        str(args.team_id),
        "--workspacePath",
        "/workspace",
        "--publicBaseUrl",
        f"http://host.docker.internal:{host_port}",
    ]

    print(f"Starting fake PostHog API on http://127.0.0.1:{api_port}")
    print(f"Starting container {container_name}")
    run(docker_cmd, env={**os.environ, **env_values})
    container_running = True

    try:
        wait_for_health(base_url)
    except Exception:
        logs = run(["docker", "logs", container_name], check=False)
        print("Container failed to become healthy.", file=sys.stderr)
        if logs.stdout:
            print(logs.stdout, file=sys.stderr)
        if logs.stderr:
            print(logs.stderr, file=sys.stderr)
        cleanup()
        return 1

    if args.smoke:
        maybe_smoke_test(base_url, mock_sdk=not args.real_sdk, signal_id=args.signal_id)

    print_manual_commands(base_url, workspace, logs_dir, container_name, args.signal_id)

    try:
        while True:
            time.sleep(1)
            if container_running:
                inspect = run(["docker", "inspect", "-f", "{{.State.Running}}", container_name], check=False)
                if inspect.returncode != 0 or inspect.stdout.strip() != "true":
                    print("Container exited.", file=sys.stderr)
                    logs = run(["docker", "logs", container_name], check=False)
                    if logs.stdout:
                        print(logs.stdout, file=sys.stderr)
                    if logs.stderr:
                        print(logs.stderr, file=sys.stderr)
                    break
    finally:
        cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
