"""Who each product skill is for, and the list of served skills that the MCP `learn` command reads."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from . import discovery, frontmatter, skill_manifest

SERVED_SKILLS_FILE = "services/mcp/src/generated/served-skills.json"
CUSTOMER_AUDIENCE = "customer"
SCOUT_AUDIENCE = "scout"
INTERNAL_AUDIENCE = "internal"
SERVED_AUDIENCES = (CUSTOMER_AUDIENCE, SCOUT_AUDIENCE)
AUDIENCES = (*SERVED_AUDIENCES, INTERNAL_AUDIENCE)
# The PostHog-run agents that read skills through `learn`. The MCP server knows the same names in
# `services/mcp/src/skills/served-skills.ts`, and it refuses the whole served list if one entry names another.
KNOWN_CONSUMERS = ("slack", "posthog_ai")
FIX_COMMAND = "hogli lint:skills -- --fix"


def _skill_metadata(skill: skill_manifest.DiscoveredSkill) -> dict[str, str]:
    """Return the `metadata` map from the entry point's frontmatter, or an empty map if it has none."""
    match = frontmatter._FRONTMATTER_RE.match(skill.source_file.read_text())
    if not match:
        return {}
    try:
        parsed = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}
    metadata = parsed.get("metadata") if isinstance(parsed, dict) else None
    if not isinstance(metadata, dict):
        return {}
    return {str(key): str(value) for key, value in metadata.items() if value is not None}


def _consumers(metadata: dict[str, str]) -> list[str]:
    return [consumer.strip() for consumer in metadata.get("consumers", "").split(",") if consumer.strip()]


def _render_served_skills(skills: list[skill_manifest.DiscoveredSkill]) -> str:
    """Return the text of the served-skills file for these skill headers."""
    served: dict[str, dict[str, object]] = {}
    for skill in skills:
        metadata = _skill_metadata(skill)
        audience = metadata.get("audience")
        if audience not in SERVED_AUDIENCES:
            continue
        entry: dict[str, object] = {"audience": audience}
        if metadata.get("feature_flag"):
            entry["feature_flag"] = metadata["feature_flag"]
        if _consumers(metadata):
            entry["consumers"] = _consumers(metadata)
        served[discovery._unrendered_skill_name(skill)] = entry
    return json.dumps({"skills": dict(sorted(served.items()))}, indent=4) + "\n"


def write_served_skills(repo_root: Path, skills: list[skill_manifest.DiscoveredSkill]) -> Path:
    """Write the served-skills file from the skill headers and return its path."""
    served_file = repo_root / SERVED_SKILLS_FILE
    served_file.parent.mkdir(parents=True, exist_ok=True)
    served_file.write_text(_render_served_skills(skills))
    return served_file


def _check_skill_audience(repo_root: Path, skills: list[skill_manifest.DiscoveredSkill]) -> list[str]:
    """Return one error for each skill header with a wrong audience, and one if the served-skills file is stale."""
    errors: list[str] = []
    for skill in skills:
        label = skill.source_file.relative_to(repo_root)
        metadata = _skill_metadata(skill)
        audience = metadata.get("audience")
        if audience is None:
            errors.append(
                f"{label}: the frontmatter has no `metadata.audience`. Use `{CUSTOMER_AUDIENCE}` for a customer's "
                f"agent, `{SCOUT_AUDIENCE}` for a scheduled scout run, or `{INTERNAL_AUDIENCE}` for any other "
                f"PostHog job or for staff. The MCP `learn` command serves `{CUSTOMER_AUDIENCE}` and "
                f"`{SCOUT_AUDIENCE}` skills."
            )
        elif audience not in AUDIENCES:
            errors.append(
                f"{label}: `audience: {audience}` is not a known audience. Use one of: {', '.join(AUDIENCES)}."
            )
        elif audience == INTERNAL_AUDIENCE and (metadata.get("feature_flag") or _consumers(metadata)):
            errors.append(
                f"{label}: `feature_flag` and `consumers` limit who the MCP `learn` command serves a skill to, "
                f"and it does not serve an `{INTERNAL_AUDIENCE}` skill. Remove them or change the audience."
            )
        unknown_consumers = [consumer for consumer in _consumers(metadata) if consumer not in KNOWN_CONSUMERS]
        if unknown_consumers:
            errors.append(
                f"{label}: `consumers` names {', '.join(f'`{consumer}`' for consumer in unknown_consumers)}, "
                f"which the MCP server does not know. Use: {', '.join(KNOWN_CONSUMERS)}."
            )

    served_file = repo_root / SERVED_SKILLS_FILE
    if not served_file.is_file() or served_file.read_text() != _render_served_skills(skills):
        # A missing file fails too. A pass would switch this check off for a job that does not check the file out.
        errors.append(
            f"{SERVED_SKILLS_FILE} does not match the skill headers. Run `{FIX_COMMAND}` and commit the file."
        )
    return errors
