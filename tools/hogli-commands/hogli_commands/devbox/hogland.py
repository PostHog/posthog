"""Hogland devboxes for `hogli devbox:worktree`, driven through the `hogland` CLI."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .coder import _fail

REMOTE_REPO_PATH = "/home/hog/posthog"
NAME_PREFIX = "wt-"
NAME_MAX_LENGTH = 32
_UP_TIMEOUT_SECONDS = 900
_CALL_TIMEOUT_SECONDS = 120
_SSH_DIR = Path.home() / ".hogli" / "hogland-ssh"
_FRESH_BOX_ACTIONS = frozenset({"running"})


@dataclass(frozen=True)
class HoglandEndpoint:
    box_id: str
    host: str
    port: int
    fresh_box: bool


def ssh_config_path() -> Path:
    return _SSH_DIR / "config"


def ssh_alias(name: str) -> str:
    return f"hogland.{name}"


def name_for_label(label: str) -> str:
    return f"{NAME_PREFIX}{label}"


def label_of(name: str) -> str | None:
    if not name.startswith(NAME_PREFIX):
        return None
    return name[len(NAME_PREFIX) :] or None


def ensure_cli() -> None:
    if shutil.which("hogland") is None:
        _fail(
            "The `hogland` CLI is not installed. Install it with `brew install posthog/tap/hogland`, "
            "then sign in with `hogland auth login`.",
            cause="hogland_cli_missing",
        )


def _run_json(args: list[str], *, timeout: float) -> Any:
    try:
        result = subprocess.run(["hogland", *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        _fail(f"`hogland {shlex.join(args)}` did not finish within {int(timeout)}s.", cause="hogland_timeout")
    if result.returncode != 0:
        _fail(
            f"`hogland {shlex.join(args)}` failed: {result.stderr.strip() or result.stdout.strip()}",
            cause="hogland_command_failed",
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        _fail(f"`hogland {shlex.join(args)}` did not print JSON.", cause="hogland_bad_output")


def devbox_status(devbox: dict[str, Any]) -> str:
    if devbox.get("current_box_id"):
        return "running"
    if devbox.get("latest_snapshot_id"):
        return "hibernated"
    return "stopped"


def as_workspace(devbox: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": devbox.get("name"),
        "id": devbox.get("created_at"),
        "status": devbox_status(devbox),
        "last_used_at": devbox.get("updated_at"),
    }


def fetch_devboxes() -> list[dict[str, Any]]:
    devboxes = _run_json(["devbox", "list"], timeout=_CALL_TIMEOUT_SECONDS)
    if not isinstance(devboxes, list):
        _fail("`hogland devbox list` returned an unexpected shape.", cause="hogland_bad_output")
    return [as_workspace(devbox) for devbox in devboxes if isinstance(devbox, dict)]


def parse_endpoint(payload: Any) -> HoglandEndpoint:
    box = payload.get("box") if isinstance(payload, dict) else None
    if not isinstance(box, dict):
        _fail("`hogland devbox up` returned no box.", cause="hogland_bad_output")
    host, port, box_id = box.get("public_ip"), box.get("guest_ssh_port"), box.get("id")
    if box.get("status") != "running" or not isinstance(host, str) or not isinstance(port, int):
        _fail(
            f"Hogland box {box_id} is {box.get('status')!r}, not running with SSH. "
            f"{payload.get('warning', '')}".strip(),
            cause="hogland_box_not_running",
        )
    return HoglandEndpoint(
        box_id=str(box_id),
        host=host,
        port=port,
        fresh_box=payload.get("action") in _FRESH_BOX_ACTIONS,
    )


def up(name: str, branch: str | None) -> HoglandEndpoint:
    args = ["devbox", "up", name, "--no-connect"]
    if branch:
        args += ["--branch", branch]
    return parse_endpoint(_run_json(args, timeout=_UP_TIMEOUT_SECONDS))


def hibernate(name: str) -> None:
    _run_json(["devbox", "hibernate", name], timeout=_UP_TIMEOUT_SECONDS)


def delete(name: str) -> None:
    _run_json(["devbox", "delete", name], timeout=_CALL_TIMEOUT_SECONDS)


def render_host_entry(name: str, endpoint: HoglandEndpoint, known_hosts: Path) -> str:
    alias = ssh_alias(name)
    return (
        f"Host {alias}\n"
        f"    HostName {endpoint.host}\n"
        f"    Port {endpoint.port}\n"
        "    User hog\n"
        f"    HostKeyAlias {alias}\n"
        "    StrictHostKeyChecking accept-new\n"
        f'    UserKnownHostsFile "{known_hosts}"\n'
    )


def render_main_config(hosts_dir: Path) -> str:
    return f'Include "{hosts_dir}/*.conf"\n\nMatch all\n    Include ~/.ssh/config\n'


def write_ssh_entry(name: str, endpoint: HoglandEndpoint) -> None:
    hosts_dir = _SSH_DIR / "hosts"
    known_hosts = _SSH_DIR / "known_hosts"
    hosts_dir.mkdir(parents=True, exist_ok=True)
    _SSH_DIR.chmod(0o700)
    ssh_config_path().write_text(render_main_config(hosts_dir))
    (hosts_dir / f"{name}.conf").write_text(render_host_entry(name, endpoint, known_hosts))
    if endpoint.fresh_box and known_hosts.exists():
        subprocess.run(
            ["ssh-keygen", "-R", ssh_alias(name), "-f", str(known_hosts)],
            capture_output=True,
            check=False,
        )


def forget_ssh_entry(name: str) -> None:
    (_SSH_DIR / "hosts" / f"{name}.conf").unlink(missing_ok=True)


def run_in_devbox(name: str, command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", "-F", str(ssh_config_path()), ssh_alias(name), shlex.join(command)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
