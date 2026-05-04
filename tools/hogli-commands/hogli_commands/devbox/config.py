"""Local config helpers for hogli devbox preferences."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict


class DevboxConfig(TypedDict, total=False):
    git_name: str
    git_email: str
    dotfiles_uri: str


def get_config_path() -> Path:
    """Return the config path for persisted hogli devbox preferences."""
    return Path.home() / ".config" / "posthog" / "hogli_devbox.json"


def load_config() -> DevboxConfig:
    """Load persisted hogli devbox preferences from disk."""
    try:
        data = json.loads(get_config_path().read_text())
    except Exception:
        return DevboxConfig()

    if not isinstance(data, dict):
        return DevboxConfig()

    config = DevboxConfig()
    for key in ("git_name", "git_email", "dotfiles_uri"):
        value = data.get(key)
        if isinstance(value, str):
            stripped_value = value.strip()
            if stripped_value:
                config[key] = stripped_value
    return config


def save_config(config: DevboxConfig) -> None:
    """Persist hogli devbox preferences to disk."""
    normalized = DevboxConfig()
    for key in ("git_name", "git_email", "dotfiles_uri"):
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
