"""Local config helpers for hogli devbox preferences."""

from __future__ import annotations

import os
import json
import fcntl
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TypedDict


class DevboxConfig(TypedDict, total=False):
    git_name: str
    git_email: str
    dotfiles_uri: str
    region: str
    worktree_box_cleanup: str
    worktree_auto_box: str


_PERSISTED_FIELDS = ("git_name", "git_email", "dotfiles_uri", "region", "worktree_box_cleanup", "worktree_auto_box")

WORKTREE_BOX_CLEANUP_ACTIONS = ("stop", "delete")
WORKTREE_AUTO_SOURCES = ("claude", "codex", "posthog-code", "phw", "other")


def get_config_path() -> Path:
    """Return the config path for persisted hogli devbox preferences."""
    return Path.home() / ".config" / "posthog" / "hogli_devbox.json"


def get_worktree_boxes_path() -> Path:
    return Path.home() / ".config" / "posthog" / "hogli_devbox_worktrees.json"


def load_config() -> DevboxConfig:
    """Load persisted hogli devbox preferences from disk."""
    try:
        data = json.loads(get_config_path().read_text())
    except Exception:
        return DevboxConfig()

    if not isinstance(data, dict):
        return DevboxConfig()

    config = DevboxConfig()
    for key in _PERSISTED_FIELDS:
        value = data.get(key)
        if isinstance(value, str):
            stripped_value = value.strip()
            if stripped_value:
                config[key] = stripped_value
    return config


def save_config(config: DevboxConfig) -> None:
    """Persist hogli devbox preferences to disk."""
    normalized = DevboxConfig()
    for key in _PERSISTED_FIELDS:
        value = config.get(key)
        if isinstance(value, str):
            stripped_value = value.strip()
            if stripped_value:
                normalized[key] = stripped_value

    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, indent=2) + "\n")


def save_git_identity(git_name: str, git_email: str) -> DevboxConfig:
    """Persist Git identity defaults for new workspaces."""
    config = load_config()
    config["git_name"] = git_name
    config["git_email"] = git_email
    save_config(config)
    return config


def save_dotfiles_uri(dotfiles_uri: str) -> DevboxConfig:
    """Persist dotfiles repo URL for new workspaces."""
    config = load_config()
    config["dotfiles_uri"] = dotfiles_uri
    save_config(config)
    return config


def clear_dotfiles_uri(config: DevboxConfig | None = None) -> DevboxConfig:
    """Remove any saved dotfiles repo URL so new workspaces don't clone one.

    Pass ``config`` to reuse an already-loaded dict and avoid a redundant disk read.
    """
    if config is None:
        config = load_config()
    config.pop("dotfiles_uri", None)
    save_config(config)
    return config


def clear_git_identity(config: DevboxConfig | None = None) -> DevboxConfig:
    """Remove any saved Git identity defaults for new workspaces.

    Pass ``config`` to reuse an already-loaded dict and avoid a redundant disk read.
    """
    if config is None:
        config = load_config()
    config.pop("git_name", None)
    config.pop("git_email", None)
    save_config(config)
    return config


def save_region(region: str) -> DevboxConfig:
    """Persist the preferred region for new workspaces."""
    config = load_config()
    config["region"] = region
    save_config(config)
    return config


def clear_region(config: DevboxConfig | None = None) -> DevboxConfig:
    """Drop the saved preferred region so new workspaces fall back to the built-in default.

    Pass ``config`` to reuse an already-loaded dict and avoid a redundant disk read.
    """
    if config is None:
        config = load_config()
    config.pop("region", None)
    save_config(config)
    return config


def save_worktree_box_cleanup(action: str) -> DevboxConfig:
    config = load_config()
    config["worktree_box_cleanup"] = action
    save_config(config)
    return config


def clear_worktree_box_cleanup(config: DevboxConfig | None = None) -> DevboxConfig:
    if config is None:
        config = load_config()
    config.pop("worktree_box_cleanup", None)
    save_config(config)
    return config


def saved_worktree_box_cleanup() -> str | None:
    action = load_config().get("worktree_box_cleanup")
    return action if action in WORKTREE_BOX_CLEANUP_ACTIONS else None


def save_worktree_auto_sources(sources: Sequence[str]) -> DevboxConfig:
    config = load_config()
    config["worktree_auto_box"] = ",".join(sources)
    save_config(config)
    return config


def clear_worktree_auto_sources(config: DevboxConfig | None = None) -> DevboxConfig:
    if config is None:
        config = load_config()
    config.pop("worktree_auto_box", None)
    save_config(config)
    return config


def saved_worktree_auto_sources() -> frozenset[str]:
    saved = load_config().get("worktree_auto_box", "")
    return frozenset(source.strip() for source in saved.split(",")) & frozenset(WORKTREE_AUTO_SOURCES)


def load_worktree_boxes() -> dict[str, str]:
    """Map each worktree path that `devbox:worktree` set up to the workspace it owns.

    `worktrees:clean` acts only on boxes listed here, so a hand-made labeled box
    that happens to share a name with a branch is never stopped or deleted.
    """
    try:
        data = json.loads(get_worktree_boxes_path().read_text())
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {path: name for path, name in data.items() if isinstance(path, str) and isinstance(name, str) and name}


@contextmanager
def _locked_worktree_boxes() -> Iterator[None]:
    path = get_worktree_boxes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(f"{path.name}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _save_worktree_boxes(boxes: dict[str, str]) -> None:
    path = get_worktree_boxes_path()
    staging = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    staging.write_text(json.dumps(dict(sorted(boxes.items())), indent=2) + "\n")
    staging.replace(path)


def record_worktree_box(worktree_path: Path, workspace_name: str) -> None:
    with _locked_worktree_boxes():
        boxes = load_worktree_boxes()
        boxes[str(worktree_path)] = workspace_name
        _save_worktree_boxes(boxes)


def forget_worktree_boxes(worktree_paths: list[Path]) -> None:
    with _locked_worktree_boxes():
        boxes = load_worktree_boxes()
        remaining = {path: name for path, name in boxes.items() if path not in {str(p) for p in worktree_paths}}
        if remaining != boxes:
            _save_worktree_boxes(remaining)
