from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from pathlib import Path

from django.db import IntegrityError, transaction

import yaml

from posthog.models.team.team import Team

from products.llm_analytics.backend.models.skills import LLMSkill, LLMSkillFile
from products.signals.backend.agent_harness.skill_loader import SIGNALS_AGENT_SKILL_PREFIX

logger = logging.getLogger(__name__)

# Canonical signals-agent-* skills live on disk under `products/signals/skills/` so they're
# usable both as in-repo packaged skills (consumed by `hogli build:skills` for the AI plugin
# and shipped via the dist/skills.zip release) and seeded into each team's LLMSkill namespace
# by the headless harness. Single source of truth, two distribution paths.
_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"

# Mirrors the regex in `products/posthog_ai/scripts/build_skills.py` so frontmatter parsing
# stays consistent across the two consumers. Keep these in sync if the skill spec evolves.
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
# Bundled subdirs (references / scripts / assets per agentskills.io spec) walked recursively.
_ALLOWED_BUNDLE_SUBDIRS = ("references", "scripts", "assets")


@dataclass(frozen=True)
class CanonicalSkillFile:
    path: str
    content: str
    content_type: str = "text/plain"


@dataclass(frozen=True)
class CanonicalSkill:
    """A canonical `signals-agent-*` skill discovered from `products/signals/skills/`.

    `name` and `description` come from SKILL.md frontmatter. `body` is the markdown after the
    frontmatter. `allowed_tools` is optional in frontmatter — defaults to empty (no narrowing).
    The agentskills.io spec uses `allowed-tools` (hyphen); we accept both, preferring the
    spec form. `files` is the recursive content of `references/`, `scripts/`, and `assets/`
    subdirs alongside SKILL.md.
    """

    name: str
    description: str
    body: str
    allowed_tools: tuple[str, ...]
    files: tuple[CanonicalSkillFile, ...]
    source_path: Path


@dataclass(frozen=True)
class SeedResult:
    """Outcome of `seed_canonical_skills`.

    `created_skill_names` is empty when the team already had at least one signals-agent-*
    skill (the seed is a no-op in that case — edits and forks on team copies are preserved).
    """

    created_skill_names: tuple[str, ...]
    skipped_reason: str | None = None


class CanonicalSkillParseError(ValueError):
    """A canonical SKILL.md on disk is malformed (missing frontmatter, bad YAML, etc.)."""


def _parse_canonical_skill(skill_dir: Path) -> CanonicalSkill:
    skill_file = skill_dir / "SKILL.md"
    raw = skill_file.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        raise CanonicalSkillParseError(f"SKILL.md missing YAML frontmatter: {skill_file}")
    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        raise CanonicalSkillParseError(f"SKILL.md frontmatter is not valid YAML: {skill_file}: {e}") from e
    if not isinstance(frontmatter, dict):
        raise CanonicalSkillParseError(f"SKILL.md frontmatter must be a mapping: {skill_file}")

    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not isinstance(name, str) or not name:
        raise CanonicalSkillParseError(f"SKILL.md frontmatter missing 'name': {skill_file}")
    if not isinstance(description, str) or not description:
        raise CanonicalSkillParseError(f"SKILL.md frontmatter missing 'description': {skill_file}")
    if not name.startswith(SIGNALS_AGENT_SKILL_PREFIX):
        raise CanonicalSkillParseError(
            f"Canonical skill name must start with '{SIGNALS_AGENT_SKILL_PREFIX}': got {name!r} in {skill_file}"
        )

    # The agentskills.io spec uses `allowed-tools` (hyphen). We prefer the spec form, but accept
    # the underscore form too — it predated the spec alignment in this codebase and is used by
    # other PHS skills. Reject if both keys are set so a future divergence doesn't go unnoticed.
    if "allowed-tools" in frontmatter and "allowed_tools" in frontmatter:
        raise CanonicalSkillParseError(
            f"SKILL.md frontmatter has both 'allowed-tools' and 'allowed_tools'; pick one: {skill_file}"
        )
    raw_allowed = frontmatter.get("allowed-tools") or frontmatter.get("allowed_tools") or []
    if not isinstance(raw_allowed, list) or not all(isinstance(t, str) for t in raw_allowed):
        raise CanonicalSkillParseError(f"SKILL.md frontmatter 'allowed-tools' must be a list of strings: {skill_file}")

    body = raw[match.end() :]
    files: list[CanonicalSkillFile] = []
    for subdir_name in _ALLOWED_BUNDLE_SUBDIRS:
        subdir = skill_dir / subdir_name
        if not subdir.is_dir():
            continue
        for file_path in sorted(subdir.rglob("*")):
            if not file_path.is_file():
                continue
            rel_path = file_path.relative_to(skill_dir).as_posix()
            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError as e:
                raise CanonicalSkillParseError(f"Bundled skill file is not UTF-8 text: {file_path}: {e}") from e
            files.append(CanonicalSkillFile(path=rel_path, content=content))

    return CanonicalSkill(
        name=name,
        description=description.strip(),
        body=body,
        allowed_tools=tuple(raw_allowed),
        files=tuple(files),
        source_path=skill_dir,
    )


def discover_canonical_skills(skills_dir: Path | None = None) -> tuple[CanonicalSkill, ...]:
    """Walk `products/signals/skills/signals-agent-*/` and return the parsed manifest.

    Skipping a malformed canonical entry would mask author errors; instead we let
    `CanonicalSkillParseError` propagate so the harness fails loud and the canonical source
    gets fixed.
    """
    base = skills_dir or _SKILLS_DIR
    if not base.is_dir():
        return ()
    discovered: list[CanonicalSkill] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        if not entry.name.startswith(SIGNALS_AGENT_SKILL_PREFIX):
            continue
        if not (entry / "SKILL.md").is_file():
            continue
        discovered.append(_parse_canonical_skill(entry))
    return tuple(discovered)


def seed_canonical_skills(team: Team) -> SeedResult:
    """Idempotently seed canonical `signals-agent-*` skills into a team's namespace.

    No-op when the team already has any `signals-agent-*` skill (deleted or live). Edits
    and forks on team copies are preserved across calls — once a team has been seeded
    (or has authored its own row under the prefix), the canonical set never overwrites
    their content. Existence of any row under the prefix counts as "already seeded",
    including archived (`deleted=True`) rows; re-seeding archived skills would resurrect
    content the team deliberately removed.

    Concurrent calls are safe: the create path uses `transaction.atomic()` plus the model's
    unique constraint (`unique_llm_skill_latest_per_team`) to drop duplicate inserts.
    """
    existing = list(
        LLMSkill.objects.filter(team=team, name__startswith=SIGNALS_AGENT_SKILL_PREFIX).values_list("name", flat=True)
    )
    if existing:
        return SeedResult(
            created_skill_names=(),
            skipped_reason=f"team already has {len(set(existing))} signals-agent-* skill(s)",
        )

    canonicals = discover_canonical_skills()
    if not canonicals:
        return SeedResult(created_skill_names=(), skipped_reason="no canonical signals-agent-* skills on disk")

    created: list[str] = []
    for canonical in canonicals:
        try:
            with transaction.atomic():
                skill = LLMSkill.objects.create(
                    team=team,
                    name=canonical.name,
                    description=canonical.description,
                    body=canonical.body,
                    allowed_tools=list(canonical.allowed_tools),
                    metadata={
                        "seeded_by": "signals_agent_harness",
                        "source": "products/signals/skills",
                    },
                    version=1,
                    is_latest=True,
                )
                if canonical.files:
                    LLMSkillFile.objects.bulk_create(
                        [
                            LLMSkillFile(
                                skill=skill,
                                path=f.path,
                                content=f.content,
                                content_type=f.content_type,
                            )
                            for f in canonical.files
                        ]
                    )
        except IntegrityError:
            # A concurrent caller (e.g. two coordinator-spawned runs for the same team)
            # raced us. The other writer's row stands; we move on.
            logger.info(
                "signals_agent: concurrent seed dropped, canonical skill already created",
                extra={"team_id": team.id, "skill_name": canonical.name},
            )
            continue
        created.append(canonical.name)

    if created:
        logger.info(
            "signals_agent: seeded canonical skills",
            extra={"team_id": team.id, "skill_names": created},
        )
    return SeedResult(created_skill_names=tuple(created))
