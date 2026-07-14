"""Canonical review-hog skill sync — mirror disk `SKILL.md` into per-team `LLMSkill` rows.

Ported from Signals' `scout_harness/lazy_seed.py` (the scout fleet's canonical-skill sync) and
trimmed to ReviewHog's needs: no per-team holdback. The reconcile is
prefix-and-category-driven so the same machinery seeds every skill set — the review
**perspectives** (`review-hog-perspective-*`), the **validation criteria**
(`review-hog-validation-*`), the **blind-spot check** (`review-hog-blind-spots-*`), and the
**authoring companion** (`review-hog-authoring`, scouts'-`authoring-scouts` counterpart).
It reads the matching dirs under `products/review_hog/skills/` and
reconciles each against a team's `LLMSkill` rows — creating missing rows, updating ones the team
hasn't edited, leaving diverged / hand-authored rows alone, tombstoning rows whose canonical was
deleted. Only rows we seeded (`metadata.seeded_by == "review_hog"`) are ever updated.

Called at the start of every review run (the cold-start sync, `prune=True`) — creation, updates,
and the pruning of disk-removed canonicals all ride the run path, scout-coordinator-style; there is
no separate ops command. Each skill becomes a first-class, independently versioned skill the sandbox
agent pulls over MCP — the same store the Signals scouts ship into.
"""

from __future__ import annotations

import re
import json
import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from django.db import IntegrityError, transaction
from django.utils import timezone

import yaml

from posthog.models.team.team import Team

from products.review_hog.backend.reviewer.skill_loader import (
    REVIEW_HOG_AUTHORING_PREFIX,
    REVIEW_HOG_BLIND_SPOTS_PREFIX,
    REVIEW_HOG_PERSPECTIVE_PREFIX,
    REVIEW_HOG_VALIDATION_PREFIX,
)
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

# Stamped on `LLMSkill.category` so the skills surface can group all of ReviewHog's pulled skills into
# one "Code review" tab without knowing the naming convention. Both skill sets share this one
# category — the perspective-vs-validation split is carried by the skill-name prefix
# (`review-hog-perspective-*` vs `review-hog-validation-*`), which the skills UI can group on — so a
# single tab covers both. The sync owns this tag (it re-stamps a seeded row whose category drifted).
REVIEW_HOG_SKILL_CATEGORY = "review_hog"

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
    resurrected_skill_names: tuple[str, ...] = ()
    pruned_skill_names: tuple[str, ...] = ()
    skipped_reason: str | None = None


class CanonicalSkillParseError(ValueError):
    """A canonical SKILL.md on disk is malformed (missing frontmatter, bad YAML, etc.)."""


def _parse_canonical_skill(skill_dir: Path, *, prefix: str) -> CanonicalSkill:
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
    if not name.startswith(prefix):
        raise CanonicalSkillParseError(f"Canonical skill name must start with '{prefix}': got {name!r} in {skill_file}")

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


def _discover_canonical(prefix: str, skills_dir: Path | None = None) -> tuple[CanonicalSkill, ...]:
    """Walk `products/review_hog/skills/` and return every parsed `<prefix>*` skill.

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
        if not entry.is_dir() or not entry.name.startswith(prefix):
            continue
        if not (entry / "SKILL.md").is_file():
            continue
        skill = _parse_canonical_skill(entry, prefix=prefix)
        if skill.name in by_name:
            raise CanonicalSkillParseError(
                f"Duplicate canonical skill name {skill.name!r}: declared in both {by_name[skill.name]} and {entry}"
            )
        by_name[skill.name] = entry
        discovered.append(skill)
    return tuple(discovered)


def discover_canonical_perspectives(skills_dir: Path | None = None) -> tuple[CanonicalSkill, ...]:
    """Every parsed `review-hog-perspective-*` skill on disk."""
    return _discover_canonical(REVIEW_HOG_PERSPECTIVE_PREFIX, skills_dir)


def discover_canonical_validation(skills_dir: Path | None = None) -> tuple[CanonicalSkill, ...]:
    """Every parsed `review-hog-validation-*` skill on disk (the single criteria skill today)."""
    return _discover_canonical(REVIEW_HOG_VALIDATION_PREFIX, skills_dir)


def discover_canonical_blind_spots(skills_dir: Path | None = None) -> tuple[CanonicalSkill, ...]:
    """Every parsed `review-hog-blind-spots-*` skill on disk (the single general sweep today)."""
    return _discover_canonical(REVIEW_HOG_BLIND_SPOTS_PREFIX, skills_dir)


def discover_canonical_authoring(skills_dir: Path | None = None) -> tuple[CanonicalSkill, ...]:
    """Every parsed `review-hog-authoring*` skill on disk (the single companion guide today)."""
    return _discover_canonical(REVIEW_HOG_AUTHORING_PREFIX, skills_dir)


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


def _create_skill_from_canonical(team: Team, canonical: CanonicalSkill, canonical_hash: str, *, category: str) -> None:
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
            category=category,
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
    team: Team, current_latest: LLMSkill, canonical: CanonicalSkill, canonical_hash: str, *, category: str
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
            category=category,
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


def _resurrect_skill_from_canonical(
    team: Team, newest_dead: LLMSkill, canonical: CanonicalSkill, canonical_hash: str, *, category: str
) -> None:
    """Recreate a canonical whose rows were all soft-deleted (e.g. archived from the Skills UI).

    Skill deletion is not ReviewHog's opt-out signal — disabling the `ReviewSkillConfig` is — so the
    sync restores the canonical at the next version instead of honoring an archive made on an
    unrelated surface. A racing write collides on the unique constraint; the caller swallows it.
    """
    with transaction.atomic():
        new_skill = LLMSkill.objects.create(
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
            category=category,
            version=newest_dead.version + 1,
            is_latest=True,
        )
        if canonical.files:
            LLMSkillFile.objects.bulk_create(
                [
                    LLMSkillFile(skill=new_skill, path=f.path, content=f.content, content_type=f.content_type)
                    for f in canonical.files
                ]
            )


def _sync_canonicals(
    team: Team, *, canonicals: tuple[CanonicalSkill, ...], category: str, prefix: str, prune: bool = False
) -> SyncResult:
    """Reconcile a team's rows with a set of canonical `<prefix>*` skills on disk.

    Per skill: create if missing, update if we seeded it and the team hasn't edited it, resurrect
    if every row is soft-deleted (skill deletion is not ReviewHog's opt-out — the config toggle is),
    otherwise leave it alone (diverged / hand-authored). Only rows tagged
    `metadata.seeded_by == "review_hog"` are ever updated.

    `prune` (default off) additionally tombstones live `<prefix>*` rows we seeded whose canonical was
    removed from disk — safe on the automatic path because the `not canonicals` early-return and the
    hash checks keep a broken disk read or an edited fork from being reaped. The cold-start sync
    passes `prune=True` (the run path is the only recurring reconciliation moment). Idempotent —
    writes only when content changed; IntegrityError on races is logged-and-swallowed.
    """
    if not canonicals:
        return SyncResult(skipped_reason=f"no canonical {prefix}* skills on disk")

    created: list[str] = []
    updated: list[str] = []
    diverged: list[str] = []
    resurrected: list[str] = []
    pruned: list[str] = []

    for canonical in canonicals:
        canonical_hash = _compute_canonical_hash(canonical)
        rows = list(LLMSkill.objects.filter(team=team, name=canonical.name).order_by("-version"))

        if not rows:
            try:
                _create_skill_from_canonical(team, canonical, canonical_hash, category=category)
                created.append(canonical.name)
            except IntegrityError:
                logger.info(
                    "review_hog: concurrent create lost the race; skipping",
                    extra={"team_id": team.id, "skill_name": canonical.name},
                )
            continue

        live = next((r for r in rows if not r.deleted and r.is_latest), None)
        if live is None:
            # All rows dead (e.g. archived via the general Skills UI). Canonicals always come back:
            # disabling the ReviewSkillConfig is the opt-out lever, not skill deletion.
            try:
                _resurrect_skill_from_canonical(team, rows[0], canonical, canonical_hash, category=category)
                resurrected.append(canonical.name)
            except IntegrityError:
                logger.info(
                    "review_hog: concurrent resurrect lost the race; skipping",
                    extra={"team_id": team.id, "skill_name": canonical.name},
                )
            continue

        if (live.metadata or {}).get("seeded_by") != REVIEW_HOG_SEEDED_BY:
            # Hand-authored row sharing a canonical name — never touch it.
            diverged.append(canonical.name)
            continue

        if live.category != category:
            # The sync owns the category tag; re-stamp a seeded row whose category drifted (e.g. after
            # the canonical category was changed). In-place — it's our metadata, not user content, so
            # no version bump. Idempotent: only writes on actual drift.
            LLMSkill.objects.filter(pk=live.pk).update(category=category)

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
            _update_skill_from_canonical(team, live, canonical, canonical_hash, category=category)
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
            name__startswith=prefix,
            metadata__seeded_by=REVIEW_HOG_SEEDED_BY,
        ).exclude(name__in=canonical_names)
        for row in orphan_rows:
            stored_hash = (row.metadata or {}).get("canonical_hash")
            if stored_hash is None or _compute_row_hash(row, list(row.files.all())) != stored_hash:
                diverged.append(row.name)
                continue
            # `updated_at=now` matters: queryset updates bypass auto_now, and the marketplace plugin
            # version is Max(updated_at) over ALL team rows — without the bump, the cached repo keeps
            # serving the pruned skill (same invariant archive_skill guards in skill_services.py).
            LLMSkill.objects.filter(
                team=team, name=row.name, deleted=False, metadata__seeded_by=REVIEW_HOG_SEEDED_BY
            ).update(deleted=True, is_latest=False, updated_at=timezone.now())
            pruned.append(row.name)

    if created or updated or resurrected or pruned:
        logger.info(
            "review_hog: synced canonical skills",
            extra={
                "team_id": team.id,
                "category": category,
                "created_skills": created,
                "updated_skills": updated,
                "diverged_skills": diverged,
                "resurrected_skills": resurrected,
                "pruned_skills": pruned,
            },
        )

    return SyncResult(
        created_skill_names=tuple(created),
        updated_skill_names=tuple(updated),
        diverged_skill_names=tuple(diverged),
        resurrected_skill_names=tuple(resurrected),
        pruned_skill_names=tuple(pruned),
    )


def sync_canonical_perspectives(team: Team, *, prune: bool = False) -> SyncResult:
    """Reconcile a team's rows with the canonical `review-hog-perspective-*` skills on disk."""
    return _sync_canonicals(
        team,
        canonicals=discover_canonical_perspectives(),
        category=REVIEW_HOG_SKILL_CATEGORY,
        prefix=REVIEW_HOG_PERSPECTIVE_PREFIX,
        prune=prune,
    )


def sync_canonical_validation(team: Team, *, prune: bool = False) -> SyncResult:
    """Reconcile a team's rows with the canonical `review-hog-validation-*` criteria skill on disk."""
    return _sync_canonicals(
        team,
        canonicals=discover_canonical_validation(),
        category=REVIEW_HOG_SKILL_CATEGORY,
        prefix=REVIEW_HOG_VALIDATION_PREFIX,
        prune=prune,
    )


def sync_canonical_blind_spots(team: Team, *, prune: bool = False) -> SyncResult:
    """Reconcile a team's rows with the canonical `review-hog-blind-spots-*` skill on disk."""
    return _sync_canonicals(
        team,
        canonicals=discover_canonical_blind_spots(),
        category=REVIEW_HOG_SKILL_CATEGORY,
        prefix=REVIEW_HOG_BLIND_SPOTS_PREFIX,
        prune=prune,
    )


def sync_canonical_authoring(team: Team, *, prune: bool = False) -> SyncResult:
    """Reconcile a team's rows with the canonical `review-hog-authoring` companion guide on disk."""
    return _sync_canonicals(
        team,
        canonicals=discover_canonical_authoring(),
        category=REVIEW_HOG_SKILL_CATEGORY,
        prefix=REVIEW_HOG_AUTHORING_PREFIX,
        prune=prune,
    )


def seed_canonicals_tolerantly(team_id: int, sync: Callable[[Team], SyncResult]) -> None:
    """Cold-team seed for API reads: run one canonical sync, swallowing failures.

    The run path syncs (with prune) at the start of every review, but a team that has never run one
    has no `LLMSkill` rows — its config menus would render empty and selects would 404. The config
    viewsets call this before querying so the canonicals exist from the first read. Tolerant: a
    malformed canonical on disk must not break a config endpoint.
    """
    try:
        sync(Team.objects.get(id=team_id))
    except Exception:
        logger.warning("review_hog: canonical seed failed (%s)", getattr(sync, "__name__", "sync"), exc_info=True)
