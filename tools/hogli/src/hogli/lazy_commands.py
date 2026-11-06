"""Lazy command import resolution for hogli manifests."""

from __future__ import annotations

import sys
import importlib
from pathlib import Path
from typing import Any

import click


def add_repo_root_to_path(repo_root: Path) -> None:
    """Make top-level repo packages importable via their dotted name.

    Lets command modules write ``from common.migration_utils import ...`` (or
    any other repo-rooted package) without each consumer mutating ``sys.path``
    in its own ``__init__.py``. Bootstrap belongs at the entry point.

    Appended, not prepended, so installed packages of the same name win.
    """
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.append(repo_root_str)


def add_commands_dir_to_path(commands_dir: Path | None) -> None:
    """Make a configured local commands package importable.

    ``commands_dir`` points at the package/module directory inside the repo, so
    Python needs its parent on ``sys.path``. When it is omitted, imports still
    work for installed packages or modules already on ``PYTHONPATH``.

    Appended (not prepended) so that an installed package of the same name
    wins over the repo-local checkout — same convention as Python's own
    ``site-packages`` ordering.
    """
    if commands_dir is None:
        return

    parent_dir = str(commands_dir.parent)
    if parent_dir not in sys.path:
        sys.path.append(parent_dir)


def _parse_import_string(command_name: str, import_string: Any) -> tuple[str, str]:
    if not isinstance(import_string, str) or import_string.count(":") != 1:
        raise click.ClickException(
            f"hogli: command {command_name!r} has invalid import string {import_string!r}; expected 'module.path:attr'"
        )

    module_path, attr = import_string.split(":", 1)
    if not module_path or not attr:
        raise click.ClickException(
            f"hogli: command {command_name!r} has invalid import string {import_string!r}; expected 'module.path:attr'"
        )

    return module_path, attr


def resolve_click_command(command_name: str, import_string: Any) -> click.Command:
    """Resolve a lazy ``click:`` manifest entry to its ``click.Command`` object.

    Raises ``click.ClickException`` for any failure (bad import string, missing
    module/attr, wrong type, name drift between the manifest key and the Click
    decorator's ``name=``). The CLI surfaces these directly to the user.
    """
    module_path, attr = _parse_import_string(command_name, import_string)

    try:
        module = importlib.import_module(module_path)
    except Exception as exc:
        raise click.ClickException(f"hogli: command {command_name!r} could not import {module_path!r}: {exc}") from exc

    try:
        command = getattr(module, attr)
    except AttributeError as exc:
        raise click.ClickException(
            f"hogli: command {command_name!r} could not resolve {import_string!r}: {exc}"
        ) from exc

    if not isinstance(command, click.Command):
        raise click.ClickException(
            f"hogli: command {command_name!r} resolved {import_string!r} to "
            f"{type(command).__name__}, expected click.Command"
        )

    if command.name != command_name:
        raise click.ClickException(
            f"hogli: command {command_name!r} resolved {import_string!r} with Click name "
            f"{command.name!r}; the names must match"
        )

    return command
