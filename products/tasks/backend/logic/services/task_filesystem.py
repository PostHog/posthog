import shlex
from pathlib import Path

TASK_FILESYSTEM_SCRIPT = "/opt/posthog/task-filesystem.py"
TASK_FILESYSTEM_VERSION = "/tmp/workspace/.posthog/task-filesystem/version"
TASK_FILESYSTEM_LOCAL_SCRIPT = Path(__file__).resolve().parents[2] / "sandbox/images/task_filesystem.py"


def read_task_filesystem_script() -> bytes:
    return TASK_FILESYSTEM_LOCAL_SCRIPT.read_bytes()


def task_filesystem_command(command: str) -> str:
    return f"/usr/bin/python3 -I {TASK_FILESYSTEM_SCRIPT} enter -- /bin/bash -c {shlex.quote(command)}"
