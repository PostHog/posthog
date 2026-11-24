"""Checking who each product skill is for: a customer's agent, through the MCP `learn` command, or PostHog."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from . import discovery, frontmatter, skill_manifest

SERVED_SKILLS_FILE = "services/mcp/src/skills/served-skills.json"
INTERNAL_AUDIENCE = "internal"


def _load_served_skill_names(repo_root: Path) -> set[str] | None:
    """Return the listed names that this repo must provide, or None if the list is absent."""
    served_file = repo_root / SERVED_SKILLS_FILE
    if not served_file.is_file():
        return None
    return set(json.loads(served_file.read_text())["skills"])


def _skill_audience(skill: skill_manifest.DiscoveredSkill) -> str | None:
    """Return `metadata.audience` from the entry point's frontmatter, or None if it has none."""
    match = frontmatter._FRONTMATTER_RE.match(skill.source_file.read_text())
    if not match:
        return None
    try:
        parsed = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
    metadata = parsed.get("metadata") if isinstance(parsed, dict) else None
    audience = metadata.get("audience") if isinstance(metadata, dict) else None
    return None if audience is None else str(audience)


def _check_skill_audience(repo_root: Path, skills: list[skill_manifest.DiscoveredSkill]) -> list[str]:
    """Return one error for each skill with no audience, or with two, and for each listed name with no skill."""
    served_names = _load_served_skill_names(repo_root)
    if served_names is None:
        # A pass here would switch the check off for any job that does not check out the list.
        return [f"{SERVED_SKILLS_FILE} is missing, so the lint cannot check who each product skill is for."]

    errors: list[str] = []
    product_skill_names: set[str] = set()
    for skill in skills:
        name = discovery._unrendered_skill_name(skill)
        product_skill_names.add(name)
        label = skill.source_file.relative_to(repo_root)
        audience = _skill_audience(skill)
        if audience not in (None, INTERNAL_AUDIENCE):
            errors.append(
                f"{label}: `audience: {audience}` is not a known audience. The only value is `{INTERNAL_AUDIENCE}`."
            )
        elif audience == INTERNAL_AUDIENCE and name in served_names:
            errors.append(
                f"{label}: '{name}' is in {SERVED_SKILLS_FILE} and also has `audience: {INTERNAL_AUDIENCE}`. Keep one."
            )
        elif audience is None and name not in served_names:
            errors.append(
                f"{label}: '{name}' has no audience, and the MCP `learn` command serves only listed skills. "
                f'For a customer\'s agent, add "{name}": {{}} to {SERVED_SKILLS_FILE}. '
                f"For a PostHog job or for staff, add `audience: {INTERNAL_AUDIENCE}` under `metadata` "
                f"in the frontmatter."
            )

    errors.extend(
        f"{SERVED_SKILLS_FILE} lists '{name}', but no skill under products/*/skills/ has that name. "
        f"Fix the name or remove the entry."
        for name in sorted(served_names - product_skill_names)
    )
    return errors
