from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from pathlib import Path

from django.db import IntegrityError, transaction

import yaml

from posthog.models.team.team import Team

from products.ai_observability.backend.models.skills import LLMSkill, LLMSkillFile
from products.signals.backend.scout_harness.skill_loader import SIGNALS_SCOUT_SKILL_PREFIX

logger = logging.getLogger(__name__)

# Canonical signals-scout-* skills live on disk under `products/signals/skills/` so they're
# usable both as in-repo packaged skills (consumed by `hogli build:skills` for the AI plugin
# and shipped via the dist/skills.zip release) and seeded into each team's LLMSkill namespace
# by the headless harness. Single source of truth, two distribution paths.
_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"

# Mirrors the regex in `products/posthog_ai/scripts/build_skills.py` so frontmatter parsing
# stays consistent across the two consumers. Keep these in sync if the skill spec evolves.
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
# Bundled subdirs walked recursively. Kept in lockstep with `_ALLOWED_SUBDIRS` in
# `products/posthog_ai/scripts/build_skills.py` — diverging here means a file format
# `hogli build:skills` ignores would silently land in the team's `LLMSkillFile` rows
# (or vice versa). The agentskills.io spec also defines `assets/`; if we ever want to
# support binary attachments, add to both consumers in the same change.
_ALLOWED_BUNDLE_SUBDIRS = ("references", "scripts")
# Mirror the per-skill contract limits enforced by the REST API at
# `products/llm_analytics/backend/api/skill_services.py` (`MAX_SKILL_*`). The seed
# bypasses the service layer (no "create from scratch with files" helper exists), so
# these are inlined and checked at parse time. Inlined rather than imported because
# `skill_services.py` pulls in Django app surface that triggers a circular import
# from this module's call sites. Keep the values in sync with skill_services.py.
_MAX_SKILL_BODY_BYTES = 1_000_000
_MAX_SKILL_FILE_BYTES = 1_000_000
_MAX_SKILL_FILE_COUNT = 50
# Matches `LLMSkillFile.path` model `max_length` — checked at parse time so an oversized
# canonical path fails with a clear error instead of a Postgres `value too long` DataError.
_MAX_SKILL_FILE_PATH_LENGTH = 500


@dataclass(frozen=True)
class CanonicalSkillFile:
    path: str
    content: str
    content_type: str = "text/plain"


@dataclass(frozen=True)
class CanonicalSkill:
    """A canonical `signals-scout-*` skill discovered from `products/signals/skills/`.

    `name` and `description` come from SKILL.md frontmatter. `body` is the markdown after the
    frontmatter. `allowed_tools` is optional in frontmatter — defaults to empty (no narrowing).
    The agentskills.io spec uses `allowed-tools` (hyphen); we accept both, preferring the
    spec form. `files` is the recursive content of the `_ALLOWED_BUNDLE_SUBDIRS` directories
    alongside SKILL.md.
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

    `created_skill_names` is empty when the team already had at least one signals-scout-*
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
    if not name.startswith(SIGNALS_SCOUT_SKILL_PREFIX):
        raise CanonicalSkillParseError(
            f"Canonical skill name must start with '{SIGNALS_SCOUT_SKILL_PREFIX}': got {name!r} in {skill_file}"
        )

    # The agentskills.io spec uses `allowed-tools` (hyphen). We prefer the spec form, but accept
    # the underscore form too — it predated the spec alignment in this codebase and is used by
    # other PHS skills. Reject if both keys are set so a future divergence doesn't go unnoticed.
    if "allowed-tools" in frontmatter and "allowed_tools" in frontmatter:
        raise CanonicalSkillParseError(
            f"SKILL.md frontmatter has both 'allowed-tools' and 'allowed_tools'; pick one: {skill_file}"
        )
    # Branch on key presence rather than truthiness: a falsy-but-invalid value
    # (`allowed-tools:` / null, `false`, `""`) must fail validation, not silently
    # fall back to `[]` — which means "no narrowing" and would broaden tool access.
    if "allowed-tools" in frontmatter:
        raw_allowed = frontmatter["allowed-tools"]
    elif "allowed_tools" in frontmatter:
        raw_allowed = frontmatter["allowed_tools"]
    else:
        raw_allowed = []
    if not isinstance(raw_allowed, list) or not all(isinstance(t, str) for t in raw_allowed):
        # Mention both accepted keys. The validator runs after we've merged the two forms
        # above, so we can't tell which the author wrote — naming only the spec form would
        # send authors using the underscore form looking for a key they didn't write.
        raise CanonicalSkillParseError(
            f"SKILL.md frontmatter 'allowed-tools'/'allowed_tools' must be a list of strings: {skill_file}"
        )

    body = raw[match.end() :]
    # Enforce the same per-skill limits the REST API uses (skill_services.py). The seed
    # bypasses `create_skill_file` (no service-layer "create from scratch with files"
    # helper exists), so check at parse time — a canonical too big to seed should fail
    # loudly in CI / local seed runs, not silently exceed the documented capacity.
    if len(body.encode("utf-8")) > _MAX_SKILL_BODY_BYTES:
        raise CanonicalSkillParseError(f"SKILL.md body exceeds the {_MAX_SKILL_BODY_BYTES} byte limit: {skill_file}")

    files: list[CanonicalSkillFile] = []
    for subdir_name in _ALLOWED_BUNDLE_SUBDIRS:
        subdir = skill_dir / subdir_name
        if not subdir.is_dir():
            continue
        for file_path in sorted(subdir.rglob("*")):
            if not file_path.is_file():
                continue
            rel_path = file_path.relative_to(skill_dir).as_posix()
            if len(rel_path) > _MAX_SKILL_FILE_PATH_LENGTH:
                raise CanonicalSkillParseError(
                    f"Bundled file path '{rel_path}' exceeds the {_MAX_SKILL_FILE_PATH_LENGTH} char limit: {file_path}"
                )
            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError as e:
                raise CanonicalSkillParseError(f"Bundled skill file is not UTF-8 text: {file_path}: {e}") from e
            if len(content.encode("utf-8")) > _MAX_SKILL_FILE_BYTES:
                raise CanonicalSkillParseError(
                    f"Bundled file '{rel_path}' exceeds the {_MAX_SKILL_FILE_BYTES} byte limit: {file_path}"
                )
            files.append(CanonicalSkillFile(path=rel_path, content=content))

    if len(files) > _MAX_SKILL_FILE_COUNT:
        raise CanonicalSkillParseError(
            f"Canonical skill has {len(files)} bundled files, exceeding the {_MAX_SKILL_FILE_COUNT} limit: {skill_dir}"
        )

    return CanonicalSkill(
        name=name,
        description=description.strip(),
        body=body,
        allowed_tools=tuple(raw_allowed),
        files=tuple(files),
        source_path=skill_dir,
    )


def discover_canonical_skills(skills_dir: Path | None = None) -> tuple[CanonicalSkill, ...]:
    """Walk `products/signals/skills/signals-scout-*/` and return the parsed manifest.

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
        if not entry.name.startswith(SIGNALS_SCOUT_SKILL_PREFIX):
            continue
        if not (entry / "SKILL.md").is_file():
            continue
        discovered.append(_parse_canonical_skill(entry))
    return tuple(discovered)


def seed_canonical_skills(team: Team) -> SeedResult:
    """Idempotently seed canonical `signals-scout-*` skills into a team's namespace.

    No-op when the team already has any `signals-scout-*` skill (deleted or live). Edits
    and forks on team copies are preserved across calls — once a team has been seeded
    (or has authored its own row under the prefix), the canonical set never overwrites
    their content. Existence of any row under the prefix counts as "already seeded",
    including archived (`deleted=True`) rows; re-seeding archived skills would resurrect
    content the team deliberately removed.

    Concurrent calls are safe: the create path uses `transaction.atomic()` plus the model's
    unique constraint (`unique_llm_skill_latest_per_team`) to drop duplicate inserts.
    """
    existing = list(
        LLMSkill.objects.filter(team=team, name__startswith=SIGNALS_SCOUT_SKILL_PREFIX).values_list("name", flat=True)
    )
    if existing:
        return SeedResult(
            created_skill_names=(),
            skipped_reason=f"team already has {len(set(existing))} signals-scout-* skill(s)",
        )

    canonicals = discover_canonical_skills()
    if not canonicals:
        return SeedResult(created_skill_names=(), skipped_reason="no canonical signals-scout-* skills on disk")

    created: list[str] = []
    # Seed the full set in one transaction: a mid-loop failure rolls back every insert, so the
    # next run retries the whole set instead of getting wedged with a partial seed the
    # "already seeded" guard above would treat as complete.
    # Direct ORM path is intentional: there's no `create_skill_from_scratch_with_files` helper at
    # the service layer, and the universal contract limits are enforced at parse time in
    # `_parse_canonical_skill` to match the REST API.
    try:
        with transaction.atomic():
            for canonical in canonicals:
                skill = LLMSkill.objects.create(
                    team=team,
                    name=canonical.name,
                    description=canonical.description,
                    body=canonical.body,
                    allowed_tools=list(canonical.allowed_tools),
                    metadata={
                        "seeded_by": "signals_scout_harness",
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
                created.append(canonical.name)
    except IntegrityError:
        # A concurrent caller seeded this team first; their atomic stands, ours rolls back.
        logger.info(
            "signals_scout: concurrent seed dropped, canonical skills already created",
            extra={"team_id": team.id},
        )
        return SeedResult(created_skill_names=(), skipped_reason="concurrent seed won")

    if created:
        logger.info(
            "signals_scout: seeded canonical skills",
            extra={"team_id": team.id, "skill_names": created},
        )
    return SeedResult(created_skill_names=tuple(created))
