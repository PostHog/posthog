"""Spec-compliant SKILL.md serialization and marketplace/zip file-tree assembly.

The single source of truth for turning a skill into Agent Skills spec artifacts
(https://agentskills.io/specification). Three consumers share this core:

- zip export (per-skill ``SKILL.md`` + bundled files)
- the live plugin marketplace (synthesized git repo, served over Smart HTTP)
- plain-HTTP marketplace file serving

It is Django-free on purpose — it operates on the plain dataclasses below, so a thin
model adapter (see ``adapters.py``) is the only place that touches the ORM. That keeps
the spec serialization and tree assembly unit-testable without booting the app.
"""

import io
import json
import zipfile
from dataclasses import dataclass, field

import yaml

from .git_smart_http import FileTree

# Spec caps (https://agentskills.io/specification). Description is 1024 in the spec
# but stored at 4096 today — export validates rather than silently truncating.
SPEC_DESCRIPTION_MAX_LENGTH = 1024


@dataclass(frozen=True)
class SkillFileExport:
    path: str
    content: str
    content_type: str = "text/plain"


@dataclass(frozen=True)
class SkillExport:
    name: str
    description: str
    body: str
    version: int
    license: str = ""
    compatibility: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    files: list[SkillFileExport] = field(default_factory=list)


def render_frontmatter(skill: SkillExport) -> str:
    """Serialize a skill's spec fields as a YAML frontmatter block (with delimiters).

    Maps storage shape -> spec shape: ``allowed_tools`` (list) becomes the spec's
    hyphenated, space-separated ``allowed-tools`` string, and the platform ``version``
    is parked under ``metadata`` since the spec defines no top-level version field.
    """
    document: dict[str, object] = {"name": skill.name, "description": skill.description}
    if skill.license:
        document["license"] = skill.license
    if skill.compatibility:
        document["compatibility"] = skill.compatibility

    # Spec metadata is a string->string map; carry version here, then any stored metadata.
    metadata: dict[str, str] = {"version": str(skill.version)}
    metadata.update({str(k): str(v) for k, v in skill.metadata.items()})
    document["metadata"] = metadata

    if skill.allowed_tools:
        document["allowed-tools"] = " ".join(skill.allowed_tools)

    body = yaml.safe_dump(document, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{body}---\n"


def render_skill_md(skill: SkillExport) -> str:
    return render_frontmatter(skill) + "\n" + skill.body


def validate_for_export(skill: SkillExport) -> list[str]:
    """Return spec-compliance problems that should block or warn on export. Empty == clean."""
    problems: list[str] = []
    if len(skill.description) > SPEC_DESCRIPTION_MAX_LENGTH:
        problems.append(
            f"description is {len(skill.description)} characters; the spec maximum is {SPEC_DESCRIPTION_MAX_LENGTH}"
        )
    if not skill.description.strip():
        problems.append("description is required and must be non-empty")
    return problems


def build_skill_tree(skill: SkillExport) -> FileTree:
    """Files for one skill relative to its own root: ``SKILL.md`` + bundled files.

    The bundled file ``path`` already encodes its ``scripts/`` / ``references/`` /
    ``assets/`` subdirectory, so it maps straight through.
    """
    tree: FileTree = {"SKILL.md": render_skill_md(skill)}
    for skill_file in skill.files:
        tree[skill_file.path] = skill_file.content
    return tree


def build_skill_zip(skill: SkillExport) -> bytes:
    """A spec-compliant skill directory zipped under a top-level folder named after the skill.

    The ``<name>/`` top directory satisfies the spec's "name must match the parent
    directory" rule for the unpacked result.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for rel_path, content in build_skill_tree(skill).items():
            archive.writestr(f"{skill.name}/{rel_path}", content)
    return buffer.getvalue()


def compute_plugin_version(latest_change_epoch_seconds: int) -> str:
    """Content-derived, monotonic plugin version so auto-update fires on any change.

    Keyed off the most recent change time across all of a team's skill rows (see
    ``adapters._team_plugin_version``): publishes and file edits add/refresh a row's
    ``updated_at``, and archive bumps it too, so this advances on every change and never
    regresses. Whether Claude Code re-pulls on any version *difference* vs. strictly-greater
    is the open question the auto-update spike answers — this scheme is safe for either.
    """
    return f"1.0.{latest_change_epoch_seconds}"


def build_marketplace_tree(
    *,
    plugin_name: str,
    plugin_description: str,
    plugin_version: str,
    owner_name: str,
    marketplace_name: str,
    skills: list[SkillExport],
) -> FileTree:
    """Assemble the full Claude Code plugin-marketplace file tree for one plugin.

    Layout (skills are auto-discovered from the ``skills/`` directory; we don't emit an
    explicit skills array, matching the known-working reference implementation)::

        .claude-plugin/marketplace.json
        plugins/<plugin>/.claude-plugin/plugin.json
        plugins/<plugin>/skills/<name>/SKILL.md
        plugins/<plugin>/skills/<name>/<bundled file path>
    """
    tree: FileTree = {}

    tree[".claude-plugin/marketplace.json"] = json.dumps(
        {
            "name": marketplace_name,
            "owner": {"name": owner_name},
            "plugins": [
                {
                    "name": plugin_name,
                    "source": f"./plugins/{plugin_name}",
                    "description": plugin_description,
                    "version": plugin_version,
                }
            ],
        },
        indent=2,
    )

    prefix = f"plugins/{plugin_name}"
    tree[f"{prefix}/.claude-plugin/plugin.json"] = json.dumps(
        {"name": plugin_name, "version": plugin_version, "description": plugin_description},
        indent=2,
    )

    for skill in skills:
        skill_prefix = f"{prefix}/skills/{skill.name}"
        for rel_path, content in build_skill_tree(skill).items():
            tree[f"{skill_prefix}/{rel_path}"] = content

    return tree
