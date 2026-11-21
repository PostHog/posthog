"""Checking the list of skills that the MCP `learn` command serves."""

from __future__ import annotations

import json
from pathlib import Path

SERVED_SKILLS_FILE = "services/mcp/src/skills/served-skills.json"


def _load_served_skill_names(repo_root: Path) -> set[str] | None:
    """Return the listed names that this repo must provide.

    Returns None if the list is absent, so the lint stays runnable in checkouts without the MCP service.
    """
    served_file = repo_root / SERVED_SKILLS_FILE
    if not served_file.is_file():
        return None
    return set(json.loads(served_file.read_text())["skills"])


def _check_served_skills(repo_root: Path, product_skill_names: set[str]) -> list[str]:
    """Return one error for each listed name that no product skill has."""
    served_names = _load_served_skill_names(repo_root)
    if served_names is None:
        return []
    return [
        f"{SERVED_SKILLS_FILE} lists '{name}', but no skill under products/*/skills/ has that name. "
        f"Fix the name or remove the entry."
        for name in sorted(served_names - product_skill_names)
    ]
