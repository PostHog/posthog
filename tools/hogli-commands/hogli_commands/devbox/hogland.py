"""Hogland devboxes for `hogli devbox:worktree`, driven through the `hogland` CLI."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from .coder import _LABEL_RE, _fail

REMOTE_REPO_PATH = "/home/hog/posthog"
NAME_PREFIX = "wt-"
NAME_MAX_LENGTH = 32
_UP_TIMEOUT_SECONDS = 900
_CALL_TIMEOUT_SECONDS = 120
_SSH_DIR = Path.home() / ".hogli" / "hogland-ssh"


@dataclass(frozen=True)
class HoglandEndpoint:
    box_id: str
    host: str
    port: int


def ssh_config_path() -> Path:
    return _SSH_DIR / "config"


def ssh_alias(name: str) -> str:
    return f"hogland.{name}"


def name_for_label(label: str) -> str:
    if not _LABEL_RE.match(label):
        _fail(f"Invalid devbox label '{label}'. Use lowercase letters, digits and hyphens.")
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
    return HoglandEndpoint(box_id=str(box_id), host=host, port=port)


def up(name: str, branch: str | None) -> HoglandEndpoint:
    args = ["devbox", "up", name, "--no-connect"]
    if branch:
        args += ["--branch", branch]
    return parse_endpoint(_run_json(args, timeout=_UP_TIMEOUT_SECONDS))


def source_name(clone_from: str) -> str:
    if clone_from == "default" or clone_from.startswith(NAME_PREFIX):
        return clone_from
    return name_for_label(clone_from)


def clone(source: str, target: str) -> None:
    args = ["devbox", "clone", source, target]
    try:
        result = subprocess.run(["hogland", *args], capture_output=True, text=True, timeout=_UP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        _fail(f"`hogland {shlex.join(args)}` did not finish within {_UP_TIMEOUT_SECONDS}s.", cause="hogland_timeout")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = None
    if result.returncode != 0 and "unknown command" not in result.stderr:
        _fail(
            f"`hogland {shlex.join(args)}` failed: {result.stderr.strip() or result.stdout.strip()}",
            cause="hogland_command_failed",
        )
    if not isinstance(payload, dict) or payload.get("action") != "cloned":
        _fail(
            "Your `hogland` CLI can't clone devboxes. Update it with `brew upgrade posthog/tap/hogland`.",
            cause="hogland_cli_outdated",
        )


_START_APP_MARKER = "~/.config/hogli/start-app"


def save_start_app(name: str, enable: bool | None) -> bool:
    steps = []
    if enable is True:
        steps.append(f"mkdir -p ~/.config/hogli && touch {_START_APP_MARKER}")
    elif enable is False:
        steps.append(f"rm -f {_START_APP_MARKER}")
    steps.append(f"if [ -f {_START_APP_MARKER} ]; then echo enabled; fi")
    result = _run_on_box(name, " && ".join(steps), "read the start-app setting")
    return result is not None and result.stdout.strip() == "enabled"


def start_app(name: str) -> bool:
    script = f"cd {REMOTE_REPO_PATH} && flox activate -- ./bin/hogli up -d -y"
    return _run_on_box(name, script, "start the app") is not None


def _run_on_box(name: str, script: str, action: str) -> subprocess.CompletedProcess[str] | None:
    try:
        result = run_in_devbox(name, ["bash", "-lc", script], timeout=_UP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        click.echo(f"hogli: couldn't {action} on '{name}' within {_UP_TIMEOUT_SECONDS}s.", err=True)
        return None
    if result.returncode != 0:
        click.echo(f"hogli: couldn't {action} on '{name}': {result.stderr.strip() or result.stdout.strip()}", err=True)
        return None
    return result


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
    box_id_path = hosts_dir / f"{name}.box-id"
    known_box_id = box_id_path.read_text().strip() if box_id_path.exists() else None
    if known_box_id != endpoint.box_id and known_hosts.exists():
        subprocess.run(
            ["ssh-keygen", "-R", ssh_alias(name), "-f", str(known_hosts)],
            capture_output=True,
            check=False,
        )
    box_id_path.write_text(endpoint.box_id)


def forget_ssh_entry(name: str) -> None:
    hosts_dir = _SSH_DIR / "hosts"
    (hosts_dir / f"{name}.conf").unlink(missing_ok=True)
    (hosts_dir / f"{name}.box-id").unlink(missing_ok=True)


def run_in_devbox(name: str, command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", "-F", str(ssh_config_path()), ssh_alias(name), shlex.join(command)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
