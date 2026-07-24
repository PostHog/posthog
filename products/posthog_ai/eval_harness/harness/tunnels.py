from __future__ import annotations

import os
import json
import time
import shutil
import signal
import logging
import tempfile
import subprocess
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import yaml

from .ports import NGROK_WEB_PORT

logger = logging.getLogger(__name__)

SETUP_GUIDE = "docs/internal/sandboxes-setup-guide.md"

NGROK_DEFAULT_CONFIG_PATHS: tuple[Path, ...] = (
    Path.home() / ".config" / "ngrok" / "ngrok.yml",
    Path.home() / "Library" / "Application Support" / "ngrok" / "ngrok.yml",
    Path.home() / ".ngrok2" / "ngrok.yml",
)
"""Where the ngrok agent keeps the token written by ``ngrok config add-authtoken``,
on Linux, macOS, and the legacy v2 location respectively."""


class NgrokError(RuntimeError):
    """ngrok tunnels could not be established for the eval run."""


def resolve_authtoken() -> str | None:
    """Find the user's ngrok authtoken without inheriting the rest of their config.

    The harness generates its own config (its tunnels point at eval ports, not the
    dev-stack ports the setup guide documents), so it cannot just hand ngrok the
    user's file. The token is the one thing worth lifting out of it.
    """
    from_env = os.environ.get("NGROK_AUTHTOKEN")
    if from_env:
        return from_env

    for path in NGROK_DEFAULT_CONFIG_PATHS:
        if not path.is_file():
            continue
        try:
            config = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(config, dict):
            continue
        # Config version 3 nests it under ``agent``; version 2 keeps it top-level.
        agent = config.get("agent")
        token = agent.get("authtoken") if isinstance(agent, dict) else None
        token = token or config.get("authtoken")
        if isinstance(token, str) and token:
            return token
    return None


class NgrokTunnels:
    """Modal-only ngrok lifecycle: publicly exposes the host services a remote
    Modal sandbox must reach (Django API, LLM gateway, MCP server).

    While a run is live the tunnel URLs are reachable by anyone on the internet
    who learns them, so they exist only for the duration of the run.
    """

    def __init__(self, ports: dict[str, int]) -> None:
        self._ports: dict[str, int] = dict(ports)
        self._proc: subprocess.Popen[bytes] | None = None
        self._config_dir: Path | None = None
        self._log_path: Path | None = None
        self._public_urls: dict[str, str] = {}

    def start(self) -> None:
        self._config_dir = Path(tempfile.mkdtemp(prefix="posthog-eval-ngrok-"))
        config_path = self._config_dir / "ngrok.yml"
        self._log_path = self._config_dir / "ngrok.log"
        config_path.write_text(yaml.safe_dump(self._build_config(), sort_keys=False), encoding="utf-8")

        # ngrok's own log goes to a file, never to a pipe: nothing drains a pipe
        # for the length of a run, and a full 64 KB buffer would block the agent
        # and stall every tunnel mid-eval.
        self._proc = subprocess.Popen(
            ["ngrok", "start", "--all", "--config", str(config_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                detail = f"ngrok exited early with code {self._proc.returncode}.\n{self._read_log_tail()}"
                self.stop()
                raise NgrokError(self._failure_message(detail))

            urls = self._read_tunnel_urls()
            if all(name in urls for name in self._ports):
                self._public_urls = {name: urls[name] for name in self._ports}
                logger.info("ngrok tunnels ready: %s", self._public_urls)
                return

            time.sleep(0.5)

        detail = f"Timed out waiting for all tunnels to report a public URL.\n{self._read_log_tail()}"
        self.stop()
        raise NgrokError(self._failure_message(detail))

    def url_for(self, name: str) -> str:
        return self._public_urls[name].rstrip("/")

    def stop(self) -> None:
        proc = self._proc
        if proc is not None:
            self._proc = None
            self._terminate_process_group(proc)

        config_dir = self._config_dir
        if config_dir is not None:
            self._config_dir = None
            self._log_path = None
            shutil.rmtree(config_dir, ignore_errors=True)

    def _build_config(self) -> dict[str, Any]:
        # Config version 3: agent-level options live under ``agent``, tunnels stay
        # top-level. Same shape as the config in the setup guide.
        agent: dict[str, Any] = {
            # A dedicated web_addr so the harness never adopts, or collides with,
            # a developer's already-running ngrok agent on the default 4040.
            "web_addr": f"127.0.0.1:{NGROK_WEB_PORT}",
            "log": str(self._log_path),
            "log_level": "info",
        }
        authtoken = resolve_authtoken()
        if authtoken:
            agent["authtoken"] = authtoken

        tunnels = {name: {"proto": "http", "addr": port, "schemes": ["https"]} for name, port in self._ports.items()}
        return {"version": "3", "agent": agent, "tunnels": tunnels}

    def _read_tunnel_urls(self) -> dict[str, str]:
        try:
            # The fixed loopback HTTP origin prevents callers from selecting another urllib scheme.
            # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            with urlopen(f"http://127.0.0.1:{NGROK_WEB_PORT}/api/tunnels", timeout=2) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (URLError, OSError, json.JSONDecodeError):
            return {}

        urls: dict[str, str] = {}
        for tunnel in payload.get("tunnels", []):
            # A tunnel restricted to ``schemes: [https]`` is reported under its
            # config name; strip any ``" (https)"``-style suffix defensively.
            name = str(tunnel.get("name", "")).split(" ", 1)[0]
            public_url = tunnel.get("public_url")
            if name and public_url:
                urls[name] = public_url
        return urls

    def _terminate_process_group(self, proc: subprocess.Popen[bytes]) -> None:
        if proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def _read_log_tail(self, lines: int = 20) -> str:
        if self._log_path is None or not self._log_path.is_file():
            return ""
        try:
            return "\n".join(self._log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
        except OSError:
            return ""

    def _failure_message(self, detail: str) -> str:
        return (
            f"{detail}\n"
            "ngrok could not serve the Django, LLM gateway, and MCP tunnels simultaneously. "
            "The free ngrok plan covers a single tunnel, so multi-tunnel eval runs need an "
            "authtoken on a paid plan (ngrok Hobbyist or above), or Cloudflare Tunnel instead. "
            f"See {SETUP_GUIDE}."
        )
