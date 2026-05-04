"""Lazy command import resolution for hogli manifests."""

from __future__ import annotations

import sys
import importlib
from pathlib import Path
from types import ModuleType
from typing import Any

import click


class LazyCommandError(ValueError):
    """Raised when a manifest import target cannot be resolved."""


def add_commands_dir_to_path(commands_dir: Path | None) -> None:
    """Make a configured local commands package importable.

    ``commands_dir`` points at the package/module directory inside the repo, so
    Python needs its parent on ``sys.path``. When it is omitted, imports still
    work for installed packages or modules already on ``PYTHONPATH``.
    """
    if commands_dir is None:
        return

    parent_dir = str(commands_dir.parent)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)


def parse_import_string(label: str, import_string: Any) -> tuple[str, str]:
    """Parse a ``module.path:attribute`` import target."""
    if not isinstance(import_string, str) or import_string.count(":") != 1:
        raise LazyCommandError(f"{label} has invalid import string {import_string!r}; expected 'module.path:attr'")

    module_path, attr = import_string.split(":", 1)
    if not module_path or not attr:
        raise LazyCommandError(f"{label} has invalid import string {import_string!r}; expected 'module.path:attr'")

    return module_path, attr


def resolve_click_command(command_name: str, import_string: Any) -> click.Command:
    """Resolve and validate a lazy ``click:`` manifest entry."""
    module_path, attr = parse_import_string(f"command {command_name!r}", import_string)

    try:
        module = importlib.import_module(module_path)
    except Exception as exc:
        raise LazyCommandError(f"command {command_name!r} could not import {module_path!r}: {exc}") from exc

    try:
        command = getattr(module, attr)
    except AttributeError as exc:
        raise LazyCommandError(f"command {command_name!r} could not resolve {import_string!r}: {exc}") from exc

    if not isinstance(command, click.Command):
        raise LazyCommandError(
            f"command {command_name!r} resolved {import_string!r} to {type(command).__name__}, expected click.Command"
        )

    if command.name != command_name:
        raise LazyCommandError(
            f"command {command_name!r} resolved {import_string!r} with Click name {command.name!r}; "
            "the names must match"
        )

    return command


def resolve_boot_module(module_path: Any) -> ModuleType:
    """Import and validate a boot module path."""
    if not isinstance(module_path, str) or not module_path:
        raise LazyCommandError(f"boot module {module_path!r} is invalid; expected a non-empty module path")

    try:
        return importlib.import_module(module_path)
    except Exception as exc:
        raise LazyCommandError(f"boot module {module_path!r} could not import: {exc}") from exc
