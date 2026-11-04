from __future__ import annotations

import os
import sys
import json
import subprocess
from pathlib import Path

REGISTRY_PATH = Path.home() / ".config" / "posthog" / "hogli_devbox_worktrees.json"


def event_worktree_path(event_json: str) -> Path | None:
    try:
        path = json.loads(event_json)["data"]["worktree"]["path"]
    except (ValueError, KeyError, TypeError):
        return None
    return Path(path) if isinstance(path, str) and path else None


def main_checkout_for(worktree_path: Path, registry: dict[str, dict[str, str]]) -> Path | None:
    for registered_path, record in registry.items():
        if Path(registered_path).resolve() == worktree_path.resolve() and record.get("git_dir"):
            # git_dir is <main checkout>/.git/worktrees/<name>.
            return Path(record["git_dir"]).parent.parent.parent
    return None


def run(command: list[str], cwd: Path) -> int:
    return subprocess.run(
        command,
        cwd=cwd,
        env={key: value for key, value in os.environ.items() if key not in ("VIRTUAL_ENV", "PYTHONPATH")},
        stdin=subprocess.DEVNULL,
        check=False,
    ).returncode


def on_created(worktree_path: Path) -> int:
    hook = worktree_path / "bin" / "devbox-worktree-hook"
    if not hook.exists():
        return 0
    return run([str(hook), "created", "herdr"], worktree_path)


def on_removed(worktree_path: Path) -> int:
    # herdr emits worktree.removed after the directory is gone, so the box is found through hogli's registry.
    try:
        registry = json.loads(REGISTRY_PATH.read_text())
    except (OSError, ValueError):
        return 0
    main_checkout = main_checkout_for(worktree_path, registry) if isinstance(registry, dict) else None
    if main_checkout is None or not (main_checkout / "bin" / "hogli").exists():
        return 0
    return run(
        [str(main_checkout / "bin" / "hogli"), "devbox:worktree:prune", "--path", str(worktree_path)], main_checkout
    )


def main() -> int:
    worktree_path = event_worktree_path(os.environ.get("HERDR_PLUGIN_EVENT_JSON", ""))
    if worktree_path is None:
        return 0
    event = os.environ.get("HERDR_PLUGIN_EVENT")
    if event == "worktree.created":
        return on_created(worktree_path)
    if event == "worktree.removed":
        return on_removed(worktree_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
