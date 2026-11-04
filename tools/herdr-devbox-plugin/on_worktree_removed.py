import os
import sys
import json
import subprocess
from pathlib import Path

REGISTRY_PATH = Path.home() / ".config" / "posthog" / "hogli_devbox_worktrees.json"


def removed_worktree_path(event_json: str) -> Path | None:
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


def main() -> int:
    worktree_path = removed_worktree_path(os.environ.get("HERDR_PLUGIN_EVENT_JSON", ""))
    if worktree_path is None:
        return 0
    try:
        registry = json.loads(REGISTRY_PATH.read_text())
    except (OSError, ValueError):
        return 0
    main_checkout = main_checkout_for(worktree_path, registry) if isinstance(registry, dict) else None
    if main_checkout is None or not (main_checkout / "bin" / "hogli").exists():
        return 0
    return subprocess.run(
        [str(main_checkout / "bin" / "hogli"), "devbox:worktree:prune", "--path", str(worktree_path)],
        cwd=main_checkout,
        env={key: value for key, value in os.environ.items() if key not in ("VIRTUAL_ENV", "PYTHONPATH")},
        stdin=subprocess.DEVNULL,
        check=False,
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
