"""Local config helpers for hogli devbox preferences."""

from __future__ import annotations

import os
import json
import uuid
import fcntl
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TypedDict


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
_WORKTREE_ID_FILE = "hogli-devbox-worktree-id"


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


def read_worktree_id(git_dir: Path) -> str | None:
    try:
        return (git_dir / _WORKTREE_ID_FILE).read_text().strip() or None
    except OSError:
        return None


def ensure_worktree_id(git_dir: Path) -> str:
    """Return the random ID stored in this worktree's admin directory, writing one first if it has none.

    Git reuses an admin directory name when a worktree is recreated at the same
    path, but the new directory starts empty, so the ID tells the two apart.
    """
    existing = read_worktree_id(git_dir)
    if existing is not None:
        return existing
    worktree_id = uuid.uuid4().hex
    (git_dir / _WORKTREE_ID_FILE).write_text(f"{worktree_id}\n")
    return worktree_id


@dataclass(frozen=True)
class WorktreeBoxRecord:
    """The devbox that `devbox:worktree` set up for one worktree.

    ``workspace_id`` is Coder's immutable ID, so a box destroyed and recreated
    under the same name is never mistaken for this one. ``git_dir`` is the
    worktree's admin directory in the shared git dir, which survives
    `git worktree move` and an unmounted checkout. ``worktree_id`` is the ID
    that `ensure_worktree_id` stored in that directory.
    """

    workspace: str
    git_dir: str
    workspace_id: str | None = None
    worktree_id: str | None = None

    def tracks_worktree(self, git_dir: Path) -> bool:
        """Whether the worktree with admin directory *git_dir* is the one this record was saved for.

        A record without the ID cannot answer that, so it answers no, and
        `worktrees:clean` leaves its box alone.
        """
        return self.worktree_id is not None and read_worktree_id(git_dir) == self.worktree_id

    def owns(self, workspace: Mapping[str, Any]) -> bool:
        """Whether *workspace* is the box this record was saved for.

        A record without the ID cannot answer that, so it answers no: a run
        that stopped between provisioning and the workspace lookup saves no ID,
        and a box recreated under the same name must never be taken for the one
        this worktree set up and deleted with it.
        """
        return self.workspace_id is not None and workspace.get("id") == self.workspace_id

    def may_adopt(self, workspace: Mapping[str, Any]) -> bool:
        """Whether `devbox:worktree` may keep using *workspace* for this worktree.

        A record without the ID matches the box by name once more, which lets
        the re-run store the ID that `owns` needs.
        """
        return self.workspace_id is None or self.owns(workspace)


def load_worktree_boxes() -> dict[str, WorktreeBoxRecord]:
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
    boxes: dict[str, WorktreeBoxRecord] = {}
    for path, entry in data.items():
        if not isinstance(path, str) or not isinstance(entry, dict):
            continue
        workspace, git_dir = entry.get("workspace"), entry.get("git_dir")
        workspace_id, worktree_id = entry.get("workspace_id"), entry.get("worktree_id")
        if isinstance(workspace, str) and workspace and isinstance(git_dir, str) and git_dir:
            boxes[path] = WorktreeBoxRecord(
                workspace=workspace,
                git_dir=git_dir,
                workspace_id=workspace_id if isinstance(workspace_id, str) and workspace_id else None,
                worktree_id=worktree_id if isinstance(worktree_id, str) and worktree_id else None,
            )
    return boxes


@contextmanager
def _locked_worktree_boxes() -> Iterator[None]:
    path = get_worktree_boxes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(f"{path.name}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _save_worktree_boxes(boxes: dict[str, WorktreeBoxRecord]) -> None:
    path = get_worktree_boxes_path()
    staging = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    serialized = {key: asdict(record) for key, record in sorted(boxes.items())}
    staging.write_text(json.dumps(serialized, indent=2) + "\n")
    staging.replace(path)


def worktree_box_claimant(
    boxes: Mapping[str, WorktreeBoxRecord],
    worktree_path: Path,
    workspace: str,
    live_workspace: Mapping[str, Any] | None,
) -> str | None:
    """The other worktree that holds *workspace*, or None when the name is free.

    A record holds the name from the moment it is written, so two worktrees
    that derive the same label cannot both provision it. A record without
    Coder's ID still holds the name after the box appears, because its
    worktree may still be setting the box up. Once the ID is saved, only the
    record that matches it holds the box, and a record left behind by a
    worktree that is gone holds nothing.
    """
    for path, record in boxes.items():
        if path == str(worktree_path) or record.workspace != workspace:
            continue
        if live_workspace is not None and record.owns(live_workspace):
            return path
        if (live_workspace is None or record.workspace_id is None) and Path(path).exists():
            return path
    return None


def record_worktree_box(worktree_path: Path, record: WorktreeBoxRecord) -> None:
    with _locked_worktree_boxes():
        boxes = load_worktree_boxes()
        boxes[str(worktree_path)] = record
        _save_worktree_boxes(boxes)


def claim_worktree_box(
    worktree_path: Path, record: WorktreeBoxRecord, live_workspace: Mapping[str, Any] | None
) -> str | None:
    """Register *record* for this worktree unless another worktree holds the name.

    Returns the worktree that holds it, or None once the claim is saved. The
    check and the write share the registry lock, so two worktrees racing for the
    same label cannot both start the same box.
    """
    with _locked_worktree_boxes():
        boxes = load_worktree_boxes()
        owner = worktree_box_claimant(boxes, worktree_path, record.workspace, live_workspace)
        if owner is not None:
            return owner
        boxes[str(worktree_path)] = record
        _save_worktree_boxes(boxes)
    return None


def forget_worktree_boxes(worktree_paths: list[Path]) -> None:
    with _locked_worktree_boxes():
        boxes = load_worktree_boxes()
        remaining = {path: record for path, record in boxes.items() if path not in {str(p) for p in worktree_paths}}
        if remaining != boxes:
            _save_worktree_boxes(remaining)
