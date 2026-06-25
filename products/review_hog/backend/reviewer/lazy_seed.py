"""Canonical review-perspective skill sync — mirror disk `SKILL.md` into per-team `LLMSkill` rows.

Ported from Signals' `scout_harness/lazy_seed.py` (the scout fleet's canonical-skill sync) and
trimmed to ReviewHog's needs: no companion skills, no per-team holdback. Reads
`products/review_hog/skills/review-hog-perspective-*/` from disk and reconciles each against a
team's `LLMSkill` rows — creating missing rows, updating ones the team hasn't edited, leaving
diverged / hand-authored rows alone, tombstoning rows whose canonical was deleted. Only rows we
seeded (`metadata.seeded_by == "review_hog"`) are ever updated.

Called lazily at the start of a review run (cold-start sync, `prune=False`) and explicitly via the
`sync_review_hog_perspectives` management command (`prune=True`). The perspectives become first-class,
independently versioned skills the sandbox agent pulls over MCP — the same store the Signals scouts
ship into.
"""

from __future__ import annotations

import re
import json
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from django.db import IntegrityError, transaction

import yaml

from posthog.models.team.team import Team

from products.review_hog.backend.reviewer.skill_loader import REVIEW_HOG_PERSPECTIVE_PREFIX
from products.skills.backend.models.skills import LLMSkill, LLMSkillFile

logger = logging.getLogger(__name__)

# Canonical review-hog-perspective-* skills live on disk under `products/review_hog/skills/`.
_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"

# Mirrors the frontmatter regex used by the scout sync + `build_skills.py` so parsing stays
# consistent across consumers.
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
# Bundled subdirs walked recursively, in lockstep with the scout sync's `_ALLOWED_BUNDLE_SUBDIRS`.
_ALLOWED_BUNDLE_SUBDIRS = ("references", "scripts")
# Per-skill contract limits, mirroring `products/skills/backend/api/skill_services.py` (the seed
# bypasses the service layer, so they're checked at parse time).
_MAX_SKILL_BODY_BYTES = 1_000_000
_MAX_SKILL_FILE_BYTES = 1_000_000
_MAX_SKILL_FILE_COUNT = 50
_MAX_SKILL_FILE_PATH_LENGTH = 500

# Stamped on `LLMSkill.metadata.seeded_by` for every ReviewHog-managed row. Its presence is the
# single source of truth for "ReviewHog owns this row": it gates which rows the sync may
# update/prune, and distinguishes a canonical perspective from a team's hand-authored skill.
REVIEW_HOG_SEEDED_BY = "review_hog"

# Stamped on `LLMSkill.category` so the skills surface can group review perspectives into their own
# tab without knowing the `review-hog-perspective-*` naming convention.
PERSPECTIVE_SKILL_CATEGORY = "review_perspective"

_SOURCE = "products/review_hog/skills"


@dataclass(frozen=True)
class CanonicalSkillFile:
    path: str
    content: str
    content_type: str = "text/plain"


@dataclass(frozen=True)
class CanonicalSkill:
    """A canonical `review-hog-perspective-*` skill discovered on disk.

    `name` / `description` come from SKILL.md frontmatter; `body` is the markdown after it.
    `allowed_tools` is optional (defaults to empty — no narrowing). `files` is the recursive content
    of the `_ALLOWED_BUNDLE_SUBDIRS` directories alongside SKILL.md.
    """

    name: str
    description: str
    body: str
    allowed_tools: tuple[str, ...]
    files: tuple[CanonicalSkillFile, ...]
    source_path: Path


@dataclass(frozen=True)
class SyncResult:
    """Outcome of `sync_canonical_perspectives` for one team. See the scout sync for the full
    decision table; each tuple lists the canonical skill names that fell into that branch."""

    created_skill_names: tuple[str, ...] = ()
    updated_skill_names: tuple[str, ...] = ()
    diverged_skill_names: tuple[str, ...] = ()
    tombstoned_skill_names: tuple[str, ...] = ()
    pruned_skill_names: tuple[str, ...] = ()
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
    if not name.startswith(REVIEW_HOG_PERSPECTIVE_PREFIX):
        raise CanonicalSkillParseError(
            f"Perspective skill name must start with '{REVIEW_HOG_PERSPECTIVE_PREFIX}': got {name!r} in {skill_file}"
        )

    # The agentskills.io spec uses `allowed-tools` (hyphen); accept the underscore form too, but
    # reject if both are set so a future divergence doesn't go unnoticed.
    if "allowed-tools" in frontmatter and "allowed_tools" in frontmatter:
        raise CanonicalSkillParseError(
            f"SKILL.md frontmatter has both 'allowed-tools' and 'allowed_tools'; pick one: {skill_file}"
        )
    if "allowed-tools" in frontmatter:
        raw_allowed = frontmatter["allowed-tools"]
    elif "allowed_tools" in frontmatter:
        raw_allowed = frontmatter["allowed_tools"]
    else:
        raw_allowed = []
    if not isinstance(raw_allowed, list) or not all(isinstance(t, str) for t in raw_allowed):
        raise CanonicalSkillParseError(
            f"SKILL.md frontmatter 'allowed-tools'/'allowed_tools' must be a list of strings: {skill_file}"
        )

    body = raw[match.end() :]
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


def discover_canonical_perspectives(skills_dir: Path | None = None) -> tuple[CanonicalSkill, ...]:
    """Walk `products/review_hog/skills/` and return every parsed `review-hog-perspective-*` skill.

    A malformed canonical entry propagates `CanonicalSkillParseError` so the sync fails loud and the
    source gets fixed. Frontmatter `name`s must be unique across the set — a collision is rejected
    here so a misauthored set fails on first read instead of flapping per sync.
    """
    base = skills_dir or _SKILLS_DIR
    if not base.is_dir():
        return ()
    discovered: list[CanonicalSkill] = []
    by_name: dict[str, Path] = {}
    for entry in sorted(base.iterdir()):
        if not entry.is_dir() or not entry.name.startswith(REVIEW_HOG_PERSPECTIVE_PREFIX):
            continue
        if not (entry / "SKILL.md").is_file():
            continue
        skill = _parse_canonical_skill(entry)
        if skill.name in by_name:
            raise CanonicalSkillParseError(
                f"Duplicate canonical skill name {skill.name!r}: declared in both {by_name[skill.name]} and {entry}"
            )
        by_name[skill.name] = entry
        discovered.append(skill)
    return tuple(discovered)


def _compute_canonical_hash(canonical: CanonicalSkill) -> str:
    """Stable content fingerprint for a canonical skill — description, body, allowed-tools, bundle."""
    payload = {
        "description": canonical.description,
        "body": canonical.body,
        "allowed_tools": sorted(canonical.allowed_tools),
        "files": sorted([(f.path, f.content, f.content_type) for f in canonical.files]),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _compute_row_hash(skill: LLMSkill, files: list[LLMSkillFile]) -> str:
    """Hash a team's `LLMSkill` row in the same shape as `_compute_canonical_hash` for direct compare."""
    payload = {
        "description": skill.description,
        "body": skill.body,
        "allowed_tools": sorted(skill.allowed_tools or []),
        "files": sorted([(f.path, f.content, f.content_type) for f in files]),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _create_skill_from_canonical(team: Team, canonical: CanonicalSkill, canonical_hash: str) -> None:
    """Insert a brand-new row for a (team, canonical.name) with no prior history.

    The unique constraint on `(team, name, is_latest=True, deleted=False)` is the race guard — a
    concurrent create raises `IntegrityError`, which the caller swallows.
    """
    with transaction.atomic():
        skill = LLMSkill.objects.create(
            team=team,
            name=canonical.name,
            description=canonical.description,
            body=canonical.body,
            allowed_tools=list(canonical.allowed_tools),
            metadata={
                "seeded_by": REVIEW_HOG_SEEDED_BY,
                "source": _SOURCE,
                "canonical_hash": canonical_hash,
            },
            category=PERSPECTIVE_SKILL_CATEGORY,
            version=1,
            is_latest=True,
        )
        if canonical.files:
            LLMSkillFile.objects.bulk_create(
                [
                    LLMSkillFile(skill=skill, path=f.path, content=f.content, content_type=f.content_type)
                    for f in canonical.files
                ]
            )


def _update_skill_from_canonical(
    team: Team, current_latest: LLMSkill, canonical: CanonicalSkill, canonical_hash: str
) -> None:
    """Replace the team's live row with the latest canonical content, bumping the version.

    Mirrors a user-facing edit's version bump — old rows aren't mutated; we mark them
    `is_latest=False` and create a new row at `version+1`. `select_for_update` serializes concurrent
    edits behind us; a racing user edit makes our insert collide on the unique constraint, which the
    caller swallows (their edit wins, we re-evaluate next sync).
    """
    with transaction.atomic():
        locked = LLMSkill.objects.select_for_update().get(pk=current_latest.pk)
        new_version = locked.version + 1
        locked.is_latest = False
        locked.save(update_fields=["is_latest", "updated_at"])

        new_metadata = dict(locked.metadata or {})
        new_metadata["seeded_by"] = REVIEW_HOG_SEEDED_BY
        new_metadata["source"] = _SOURCE
        new_metadata["canonical_hash"] = canonical_hash

        new_skill = LLMSkill.objects.create(
            team=team,
            name=canonical.name,
            description=canonical.description,
            body=canonical.body,
            allowed_tools=list(canonical.allowed_tools),
            metadata=new_metadata,
            category=PERSPECTIVE_SKILL_CATEGORY,
            version=new_version,
            is_latest=True,
        )
        if canonical.files:
            LLMSkillFile.objects.bulk_create(
                [
                    LLMSkillFile(skill=new_skill, path=f.path, content=f.content, content_type=f.content_type)
                    for f in canonical.files
                ]
            )


def sync_canonical_perspectives(team: Team, *, prune: bool = False) -> SyncResult:
    """Reconcile a team's rows with the canonical `review-hog-perspective-*` skills on disk.

    Per skill: create if missing, update if we seeded it and the team hasn't edited it, otherwise
    leave it alone (diverged / hand-authored / tombstoned). Only rows tagged
    `metadata.seeded_by == "review_hog"` are ever updated.

    `prune` (default off) additionally tombstones live `review-hog-perspective-*` rows we seeded
    whose canonical was removed from disk. Reserved for the explicit `sync_review_hog_perspectives`
    command; the cold-start sync leaves it off (an ad-hoc run only ensures its own perspectives
    exist and are current, not reap the rest). Idempotent — writes only when content changed;
    IntegrityError on races is logged-and-swallowed.
    """
    canonicals = discover_canonical_perspectives()
    if not canonicals:
        return SyncResult(skipped_reason="no canonical review-hog-perspective-* skills on disk")

    created: list[str] = []
    updated: list[str] = []
    diverged: list[str] = []
    tombstoned: list[str] = []
    pruned: list[str] = []

    for canonical in canonicals:
        canonical_hash = _compute_canonical_hash(canonical)
        rows = list(LLMSkill.objects.filter(team=team, name=canonical.name).order_by("-version"))

        if not rows:
            try:
                _create_skill_from_canonical(team, canonical, canonical_hash)
                created.append(canonical.name)
            except IntegrityError:
                logger.info(
                    "review_hog: concurrent create lost the race; skipping",
                    extra={"team_id": team.id, "skill_name": canonical.name},
                )
            continue

        live = next((r for r in rows if not r.deleted and r.is_latest), None)
        if live is None:
            # All rows deleted / non-latest — the team removed this perspective. Don't resurrect.
            tombstoned.append(canonical.name)
            continue

        if (live.metadata or {}).get("seeded_by") != REVIEW_HOG_SEEDED_BY:
            # Hand-authored row sharing a canonical name — never touch it.
            diverged.append(canonical.name)
            continue

        live_files = list(live.files.all())
        live_hash = _compute_row_hash(live, live_files)
        stored_hash = (live.metadata or {}).get("canonical_hash")

        if stored_hash is None:
            # One of our rows with no baseline hash — can't tell if the team edited it, so leave it.
            diverged.append(canonical.name)
            continue
        if live_hash == canonical_hash:
            continue  # already current
        if live_hash != stored_hash:
            # Team edited their copy since our last write → leave it alone.
            diverged.append(canonical.name)
            continue

        try:
            _update_skill_from_canonical(team, live, canonical, canonical_hash)
            updated.append(canonical.name)
        except IntegrityError:
            logger.info(
                "review_hog: concurrent update lost the race; skipping",
                extra={"team_id": team.id, "skill_name": canonical.name},
            )

    if prune:
        # Reverse reconciliation: tombstone live rows WE seeded whose canonical was removed from
        # disk. The `canonical_names` guard (and the `not canonicals` early-return above) keep a
        # broken/empty disk read from reaping the whole set; an edited fork (hash diverged, or no
        # baseline hash) is left alone, same as the update path.
        canonical_names = {c.name for c in canonicals}
        orphan_rows = LLMSkill.objects.filter(
            team=team,
            deleted=False,
            is_latest=True,
            name__startswith=REVIEW_HOG_PERSPECTIVE_PREFIX,
            metadata__seeded_by=REVIEW_HOG_SEEDED_BY,
        ).exclude(name__in=canonical_names)
        for row in orphan_rows:
            stored_hash = (row.metadata or {}).get("canonical_hash")
            if stored_hash is None or _compute_row_hash(row, list(row.files.all())) != stored_hash:
                diverged.append(row.name)
                continue
            LLMSkill.objects.filter(
                team=team, name=row.name, deleted=False, metadata__seeded_by=REVIEW_HOG_SEEDED_BY
            ).update(deleted=True, is_latest=False)
            pruned.append(row.name)

    if created or updated or pruned:
        logger.info(
            "review_hog: synced canonical perspectives",
            extra={
                "team_id": team.id,
                "created_skills": created,
                "updated_skills": updated,
                "diverged_skills": diverged,
                "tombstoned_skills": tombstoned,
                "pruned_skills": pruned,
            },
        )

    return SyncResult(
        created_skill_names=tuple(created),
        updated_skill_names=tuple(updated),
        diverged_skill_names=tuple(diverged),
        tombstoned_skill_names=tuple(tombstoned),
        pruned_skill_names=tuple(pruned),
    )
