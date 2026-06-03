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
# `products/ai_observability/backend/api/skill_services.py` (`MAX_SKILL_*`). The seed
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
class SyncResult:
    """Outcome of `sync_canonical_skills` for one team.

    Each tuple lists the canonical skill names that fell into a particular branch:

    - `created_skill_names`: rows that didn't exist on the team and were created from canonical.
    - `updated_skill_names`: live rows whose stored hash matched their content (so the team had
      not edited them) but whose content differed from the latest canonical — overwritten with
      the latest canonical, version bumped, hash refreshed.
    - `diverged_skill_names`: live rows whose content hash no longer matches the stored
      `canonical_hash` — the team edited their copy. Left untouched.
    - `tombstoned_skill_names`: rows that exist only as soft-deleted tombstones — the team
      removed this skill from their rotation. Left untouched (no resurrection).
    - `backfilled_skill_names`: harness-seeded rows that pre-dated the hash-tracking change
      and had no `canonical_hash` in metadata. We backfilled the hash from the row's current
      content as a one-time baseline so future syncs can compare.
    - `pruned_skill_names`: live `signals-scout-*` rows whose canonical skill was removed from
      disk (no longer in the discovered fleet). Soft-deleted (`deleted=True`, `is_latest=False`)
      so the coordinator stops dispatching a scout that's no longer part of the canonical fleet.
      Unlike `tombstoned_skill_names` (a passive observation that the team already removed it),
      this is an active reconciliation we perform.

    A skill name appears in at most one tuple per call. `skipped_reason` is set when no per-skill
    work was even attempted (e.g. the canonical dir is missing on disk in tests).
    """

    created_skill_names: tuple[str, ...] = ()
    updated_skill_names: tuple[str, ...] = ()
    diverged_skill_names: tuple[str, ...] = ()
    tombstoned_skill_names: tuple[str, ...] = ()
    backfilled_skill_names: tuple[str, ...] = ()
    pruned_skill_names: tuple[str, ...] = ()
    skipped_reason: str | None = None


# Backwards-compat alias. The first emit-only deploy returned `SeedResult`; downstream callers
# may still import the old name. The new `SyncResult` is a strict superset (created_skill_names
# + skipped_reason are present and behave the same), so the alias is safe.
SeedResult = SyncResult


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


def _compute_canonical_hash(canonical: CanonicalSkill) -> str:
    """Stable content fingerprint for a canonical skill on disk.

    Includes everything that could meaningfully change between revisions: description and body
    text, the allowed-tools list (sorted so reordering doesn't invalidate), and the bundle
    treated as a sorted list of `(path, content, content_type)` tuples. The bundle inclusion
    means a references-only change (e.g. tweaking `references/calibration.md`) still triggers
    an update — easy to forget if the hash only covered SKILL.md body.

    SHA-256 is overkill cryptographically but content-addressable hashes are cheap and we want
    no false positives.
    """
    payload = {
        "description": canonical.description,
        "body": canonical.body,
        "allowed_tools": sorted(canonical.allowed_tools),
        "files": sorted([(f.path, f.content, f.content_type) for f in canonical.files]),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _compute_row_hash(skill: LLMSkill, files: list[LLMSkillFile]) -> str:
    """Hash a team's `LLMSkill` row in the same shape as `_compute_canonical_hash` so the two
    can be compared directly. Caller must pre-fetch `files` to avoid an N+1 inside the hash."""
    payload = {
        "description": skill.description,
        "body": skill.body,
        "allowed_tools": sorted(skill.allowed_tools or []),
        "files": sorted([(f.path, f.content, f.content_type) for f in files]),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _create_skill_from_canonical(team: Team, canonical: CanonicalSkill, canonical_hash: str) -> None:
    """Insert a brand-new row for a (team, canonical.name) that has no prior history.

    Caller already verified no row exists. The unique constraint on
    `(team, name, deleted=False, is_latest=True)` is our race guard — if two coordinator runs
    fire for the same team at once, one wins and the other gets `IntegrityError`, which the
    caller swallows.
    """
    with transaction.atomic():
        skill = LLMSkill.objects.create(
            team=team,
            name=canonical.name,
            description=canonical.description,
            body=canonical.body,
            allowed_tools=list(canonical.allowed_tools),
            metadata={
                "seeded_by": "signals_scout_harness",
                "source": "products/signals/skills",
                "canonical_hash": canonical_hash,
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


def _update_skill_from_canonical(
    team: Team, current_latest: LLMSkill, canonical: CanonicalSkill, canonical_hash: str
) -> None:
    """Replace the team's live row for this skill with the latest canonical content, bumping
    the version. Mirrors the version-bump pattern a user-facing PHS edit would produce — old
    rows aren't mutated; we mark them `is_latest=False` and create a new row at `version+1`.
    The `metadata.seeded_by="signals_scout_harness"` tag distinguishes our updates from
    user edits in the version-history view.

    Concurrency: `select_for_update` on the existing latest row pins it for the duration of
    the txn. If a user-edit racing us has already bumped to `version+1`, we observe their
    write at lock acquisition and our subsequent insert at `version+1` collides with the
    unique constraint — caller swallows the IntegrityError (their edit wins, we'll re-evaluate
    next tick and find their content diverged).
    """
    with transaction.atomic():
        # Re-fetch under FOR UPDATE so concurrent edits serialize behind us.
        locked = LLMSkill.objects.select_for_update().get(pk=current_latest.pk)
        new_version = locked.version + 1
        locked.is_latest = False
        locked.save(update_fields=["is_latest", "updated_at"])

        new_metadata = dict(locked.metadata or {})
        new_metadata["seeded_by"] = "signals_scout_harness"
        new_metadata["source"] = "products/signals/skills"
        new_metadata["canonical_hash"] = canonical_hash

        new_skill = LLMSkill.objects.create(
            team=team,
            name=canonical.name,
            description=canonical.description,
            body=canonical.body,
            allowed_tools=list(canonical.allowed_tools),
            metadata=new_metadata,
            version=new_version,
            is_latest=True,
        )
        if canonical.files:
            LLMSkillFile.objects.bulk_create(
                [
                    LLMSkillFile(
                        skill=new_skill,
                        path=f.path,
                        content=f.content,
                        content_type=f.content_type,
                    )
                    for f in canonical.files
                ]
            )


def _backfill_canonical_hash(skill: LLMSkill, row_hash: str) -> None:
    """Stamp `canonical_hash` onto a harness-seeded row that pre-dates hash tracking.

    We write the *row's current content hash* (not the canonical hash), establishing a
    baseline that says "treat whatever the team has now as their snapshot of canonical."
    Any future drift — either a canonical update or a team edit — becomes detectable
    on subsequent ticks.
    """
    metadata = dict(skill.metadata or {})
    metadata["canonical_hash"] = row_hash
    LLMSkill.objects.filter(pk=skill.pk).update(metadata=metadata)


def sync_canonical_skills(team: Team, *, prune: bool = False) -> SyncResult:
    """Reconcile a team's `signals-scout-*` rows with the canonical fleet on disk.

    Walks each canonical skill in `products/signals/skills/` and decides per-skill whether
    to create, update, leave-as-diverged, leave-as-tombstone, or backfill a baseline hash.
    See `SyncResult` for the outcome buckets and the section comments below for the full
    decision table.

    `prune` (default off) additionally tombstones live `signals-scout-*` rows whose canonical
    was removed from disk. It's a destructive reconciliation reserved for the deliberate paths
    — the coordinator tick and the explicit `sync_signals_scout_skills` command. The runner's
    cold-start sync leaves it off: a single ad-hoc run should only ensure its own skill exists
    and is current, not reap the rest of the team's fleet.

    Idempotent and safe to call on every coordinator tick — the only DB writes happen when
    something actually needs to change, and IntegrityError on races is logged-and-swallowed.
    """
    canonicals = discover_canonical_skills()
    if not canonicals:
        return SyncResult(skipped_reason="no canonical signals-scout-* skills on disk")

    created: list[str] = []
    updated: list[str] = []
    diverged: list[str] = []
    tombstoned: list[str] = []
    backfilled: list[str] = []
    pruned: list[str] = []

    for canonical in canonicals:
        canonical_hash = _compute_canonical_hash(canonical)

        # Pull every row for this (team, name), live or tombstoned. Existence of any row —
        # including soft-deleted — counts as "team has seen this skill name before"; we
        # never resurrect tombstones.
        rows = list(LLMSkill.objects.filter(team=team, name=canonical.name).order_by("-version"))

        if not rows:
            # Brand-new for this team. Either a freshly-enabled team, or a specialist
            # added to the canonical fleet after this team was first seeded.
            try:
                _create_skill_from_canonical(team, canonical, canonical_hash)
                created.append(canonical.name)
            except IntegrityError:
                logger.info(
                    "signals_scout: concurrent create lost the race; skipping",
                    extra={"team_id": team.id, "skill_name": canonical.name},
                )
            continue

        live = next((r for r in rows if not r.deleted and r.is_latest), None)
        if live is None:
            # All rows for this name are deleted or non-latest archives. Treat as
            # tombstoned: the team explicitly removed this skill from their rotation.
            tombstoned.append(canonical.name)
            continue

        live_files = list(live.files.all())
        live_hash = _compute_row_hash(live, live_files)
        stored_hash = (live.metadata or {}).get("canonical_hash")

        if stored_hash is None:
            # Pre-existing harness-seeded row from before hash tracking landed. Establish a
            # baseline and defer any update decision to the next tick. We do this for any
            # signals-scout-* row regardless of provenance — a hand-authored row missing the
            # hash is treated the same way (its baseline becomes its current content, which
            # means it'll register as diverged on the next canonical change, which is correct).
            _backfill_canonical_hash(live, live_hash)
            backfilled.append(canonical.name)
            continue

        if live_hash == canonical_hash:
            # Already at the latest canonical content. No-op — we deliberately do *not*
            # refresh `metadata.canonical_hash` here. If an operator manually deleted
            # `canonical_hash` to force a re-evaluate, the next tick hits the `stored_hash
            # is None` branch and re-baselines via `_backfill_canonical_hash`; that's a
            # one-tick delay even when content already matches canonical, but the
            # alternative (writing every tick) churns metadata for no behavioral change.
            continue

        if live_hash != stored_hash:
            # The team's content drifted away from whatever canonical we last wrote — they
            # edited their copy. Leave it alone. They can opt back in via the management
            # command (`reset_signals_scout_skill`) if they want to.
            diverged.append(canonical.name)
            continue

        # Stored hash matches the team's current content (= they haven't edited since our
        # last write) but differs from current canonical (= we shipped a new revision).
        # Safe to overwrite.
        try:
            _update_skill_from_canonical(team, live, canonical, canonical_hash)
            updated.append(canonical.name)
        except IntegrityError:
            logger.info(
                "signals_scout: concurrent update lost the race; skipping",
                extra={"team_id": team.id, "skill_name": canonical.name},
            )

    if prune:
        # Reverse reconciliation: tombstone live `signals-scout-*` rows whose canonical was
        # removed from disk. The per-canonical loop above only visits skills still present in
        # the discovered fleet, so a scout deleted from `products/signals/skills/` would
        # otherwise leave orphaned live rows the coordinator keeps dispatching. Soft-delete them —
        # never hard-delete (run history + audit). The `not canonicals` early-return above
        # means a broken/empty disk read can't reach here and tombstone the whole fleet.
        #
        # Restrict to rows WE seeded (`metadata.seeded_by == "signals_scout_harness"`, stamped by
        # `_create_skill_from_canonical` / `_update_skill_from_canonical`). A team is free to
        # hand-author its own `signals-scout-*` skill; pruning by name+prefix alone would
        # silently soft-delete it every coordinator tick. We only reap our own seeded orphans.
        canonical_names = {c.name for c in canonicals}
        orphan_names = list(
            LLMSkill.objects.filter(
                team=team,
                deleted=False,
                name__startswith=SIGNALS_SCOUT_SKILL_PREFIX,
                metadata__seeded_by="signals_scout_harness",
            )
            .exclude(name__in=canonical_names)
            .values_list("name", flat=True)
            .distinct()
        )
        for name in orphan_names:
            # Re-scope the soft-delete to seeded rows too, so a team-authored row sharing the
            # name is never caught by the bulk update.
            LLMSkill.objects.filter(
                team=team, name=name, deleted=False, metadata__seeded_by="signals_scout_harness"
            ).update(deleted=True, is_latest=False)
            pruned.append(name)

    if created or updated or backfilled or pruned:
        logger.info(
            "signals_scout: synced canonical skills",
            extra={
                "team_id": team.id,
                "created_skills": created,
                "updated_skills": updated,
                "backfilled_skills": backfilled,
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
        backfilled_skill_names=tuple(backfilled),
        pruned_skill_names=tuple(pruned),
    )


def seed_canonical_skills(team: Team) -> SyncResult:
    """Backwards-compat alias for `sync_canonical_skills`.

    Older callsites and tests reference this name; they get the richer sync semantics for free.
    Prefer `sync_canonical_skills` in new code — the name reflects what it actually does.
    """
    return sync_canonical_skills(team)
