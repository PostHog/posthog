"""Validation utilities for hogli manifest."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import yaml

from hogli.lazy_commands import LazyCommandError, add_commands_dir_to_path, resolve_boot_module, resolve_click_command
from hogli.manifest import MANIFEST_FILE, get_manifest


def get_bin_scripts() -> set[str]:
    """Get all executable scripts in scripts_dir (excludes entry points and config)."""
    manifest = get_manifest()
    scripts_dir = manifest.scripts_dir
    if not scripts_dir.exists():
        return set()

    # Exclude files listed in config.scripts_exclude (entry points, config files, etc)
    # lint-feature-flag-sorting.mjs is registered via cmd: not bin_script:
    default_excluded = {"hogli"}
    excluded = set(manifest.config.get("scripts_exclude", [])) | default_excluded

    scripts = set()
    for f in scripts_dir.iterdir():
        if f.name in excluded or not f.is_file() or f.is_symlink():
            continue
        # Check if executable and not a config file
        if (f.stat().st_mode & 0o111) and f.suffix not in {".yaml", ".yml", ".env"}:
            scripts.add(f.name)

    return scripts


def get_manifest_scripts() -> set[str]:
    """Get all bin_script entries from manifest."""
    manifest = get_manifest()
    scripts = set()

    for category, commands in manifest.data.items():
        if category == "metadata" or not isinstance(commands, dict):
            continue
        for cmd_config in commands.values():
            if isinstance(cmd_config, dict) and (script := cmd_config.get("bin_script")):
                scripts.add(script)

    return scripts


def _iter_manifest_commands() -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield every command config from the manifest."""
    manifest = get_manifest()
    for category_key, commands in manifest.data.items():
        if category_key in {"metadata", "config"} or not isinstance(commands, dict):
            continue
        for command_name, command_config in commands.items():
            if isinstance(command_config, dict):
                yield command_name, command_config


def _ensure_commands_dir_importable() -> None:
    """Put the configured commands package parent on sys.path."""
    add_commands_dir_to_path(get_manifest().commands_dir)


def find_click_command_errors() -> list[str]:
    """Validate lazy ``click:`` command targets in the manifest."""
    _ensure_commands_dir_importable()
    errors: list[str] = []

    for command_name, command_config in _iter_manifest_commands():
        import_string = command_config.get("click")
        if import_string is None:
            continue

        try:
            resolve_click_command(command_name, import_string)
        except LazyCommandError as exc:
            errors.append(str(exc))

    return errors


def find_boot_module_errors() -> list[str]:
    """Validate boot modules listed under ``config.boot_modules``."""
    _ensure_commands_dir_importable()
    manifest = get_manifest()
    boot_modules = manifest.config.get("boot_modules", [])
    if not isinstance(boot_modules, list):
        return ["config.boot_modules must be a list of module paths"]

    errors: list[str] = []
    for module_path in boot_modules:
        try:
            resolve_boot_module(module_path)
        except LazyCommandError as exc:
            errors.append(str(exc))

    return errors


def find_manifest_validation_errors() -> list[str]:
    """Validate manifest references that help output intentionally leaves lazy."""
    return [*find_boot_module_errors(), *find_click_command_errors()]


def find_missing_manifest_entries() -> set[str]:
    """Find bin scripts not in manifest."""
    bin_scripts = get_bin_scripts()
    manifest_scripts = get_manifest_scripts()
    return bin_scripts - manifest_scripts


def generate_missing_entries() -> dict[str, dict]:
    """Generate manifest entries for missing bin scripts.

    Auto-discovered commands are marked as hidden by default until reviewed.
    """
    missing = find_missing_manifest_entries()
    if not missing:
        return {}

    entries = {}
    for script in sorted(missing):
        # Strip common prefixes to generate command name
        cmd_name = script.replace(".py", "").replace(".sh", "").replace("-", ":")
        entries[cmd_name] = {
            "bin_script": script,
            "description": f"TODO: add description for {script}",
            "hidden": True,  # Hide auto-discovered commands until reviewed
        }

    return entries


def auto_update_manifest() -> set[str]:
    """Automatically add missing entries to manifest.

    Returns set of newly added command names.
    """
    entries = generate_missing_entries()
    if not entries:
        return set()

    if not MANIFEST_FILE.exists():
        return set()

    # Load existing manifest to check for duplicates
    with open(MANIFEST_FILE) as f:
        manifest = yaml.safe_load(f) or {}

    existing_tools = manifest.get("tools", {})
    new_entries = {k: v for k, v in entries.items() if k not in existing_tools}
    if not new_entries:
        return set()

    # Append new entries as YAML text to preserve existing file formatting.
    # Round-tripping the entire file through yaml.dump() destroys indentation
    # style and line wrapping, causing the whole file to show as modified.
    content = MANIFEST_FILE.read_text()

    if "tools" not in manifest:
        content = content.rstrip() + "\ntools:\n"

    fragment = yaml.dump(new_entries, default_flow_style=False, sort_keys=False, indent=4)
    # Indent the fragment to sit under the tools: key (4 spaces)
    indented = "\n".join("    " + line if line.strip() else line for line in fragment.splitlines())
    content = content.rstrip() + "\n" + indented + "\n"

    MANIFEST_FILE.write_text(content)
    return set(new_entries.keys())
