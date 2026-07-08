"""Resolve ReviewHog's canonical pulled skills from a team's `LLMSkill` rows.

ReviewHog's review **perspectives**, its **validation criteria**, and its **blind-spot check** are
stored and synced the way Signals' scouts store theirs: canonical `SKILL.md` on disk
(`products/review_hog/skills/`) mirrored into per-team `LLMSkill` rows by `lazy_seed.sync_canonical_*`.
Delivery is **pull** — the review / validation prompts instruct the sandbox agent to `skill-get` the
skill body over the PostHog MCP — so these loaders only need to pin the current version per skill
(not the body).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from posthog.models.scoping.manager import resolve_effective_team_id

from products.review_hog.backend.models import ReviewSkillConfig
from products.review_hog.backend.reviewer.models.issues_review import PerspectiveType
from products.skills.backend.models.skills import LLMSkill

logger = logging.getLogger(__name__)

# Naming contract for review perspectives (mirrors `SIGNALS_SCOUT_SKILL_PREFIX`): any team skill with
# this prefix is a perspective. Canonical and custom are identical except canonicals auto-seed enabled.
REVIEW_HOG_PERSPECTIVE_PREFIX = "review-hog-perspective-"

# Canonical perspectives that auto-seed. `PerspectiveType` is just this seed list now — NOT an identity
# (skill_name is, stamped at review time), so a custom perspective without an enum member is first-class.
PERSPECTIVES: tuple[tuple[PerspectiveType, str], ...] = (
    (PerspectiveType.LOGIC_CORRECTNESS, f"{REVIEW_HOG_PERSPECTIVE_PREFIX}logic-correctness"),
    (PerspectiveType.CONTRACTS_SECURITY, f"{REVIEW_HOG_PERSPECTIVE_PREFIX}contracts-security"),
    (PerspectiveType.PERFORMANCE_RELIABILITY, f"{REVIEW_HOG_PERSPECTIVE_PREFIX}performance-reliability"),
)

# The canonical perspective skill names — the set `register_missing_perspective_configs` auto-enables.
CANONICAL_PERSPECTIVE_SKILL_NAMES: tuple[str, ...] = tuple(name for _, name in PERSPECTIVES)


class NoEnabledPerspectivesError(LookupError):
    """No enabled review perspective resolves to a live skill — there is nothing to review with."""


@dataclass(frozen=True)
class LoadedPerspective:
    """A perspective resolved for one run: its per-run index, skill name, and pinned version."""

    # Per-run index (1-based position in the run's enabled, sorted set). A dumb ordinal that scopes
    # finding ids (`{pass}-{chunk}-{issue}`) — NOT a perspective identity; that is `skill_name`.
    pass_number: int
    skill_name: str
    # Snapshotted so the sandbox agent's `skill-get` pulls the exact version this run was planned
    # against, even if a new version is published mid-run.
    version: int
    # The skill's frontmatter description — injected into the blind-spot check's prompt so it knows
    # which lenses already ran.
    description: str


def _register_missing_configs(team_id: int, user_id: int, skill_names: tuple[str, ...]) -> None:
    """Seed an enabled `ReviewSkillConfig` for each canonical skill this user lacks.

    The one allowed canonical/custom difference: the canonicals auto-enable on a user's first run
    ("auto-added on the start"); customs are switched on explicitly via the config API. Idempotent
    (`get_or_create` on the `(team, user, skill_name)` unique key), and a row the user disabled is
    left untouched — seeding never re-enables. `team_id` / `user_id` stay in the create kwargs: the
    fail-closed `for_team()` filter does not propagate into `create` — which is why the id must be
    canonicalized first, or the create kwarg and the filter disagree on environment-scoped calls
    (never-matching get, then IntegrityError on the unique key).
    """
    team_id = resolve_effective_team_id(team_id)
    configs = ReviewSkillConfig.objects.for_team(team_id, canonical=True)
    for skill_name in skill_names:
        configs.get_or_create(team_id=team_id, user_id=user_id, skill_name=skill_name, defaults={"enabled": True})


def register_missing_perspective_configs(team_id: int, user_id: int) -> None:
    """Seed an enabled `ReviewSkillConfig` for each canonical perspective this user lacks."""
    _register_missing_configs(team_id, user_id, CANONICAL_PERSPECTIVE_SKILL_NAMES)


def load_perspectives_for_run(team_id: int, acting_user_id: int) -> list[LoadedPerspective]:
    """Resolve the acting user's enabled perspectives, each pinned to its current latest version.

    Seeds the canonical configs first (so a cold user gets the 3 canonicals), then reads the user's
    enabled set and resolves each name to its live `LLMSkill` (latest, non-deleted). `pass_number`
    is a per-run index over the resolved set sorted by name — a re-run with the same enabled set is
    deterministic. An enabled perspective with no live skill row (e.g. an archived custom) is
    skipped with a warning rather than failing the run; restoring the skill resumes it. Raises
    `NoEnabledPerspectivesError` when nothing resolves — zero enabled (min-1 floor) or every
    enabled name is dead.
    """
    register_missing_perspective_configs(team_id, acting_user_id)
    # Prefix-scope: perspectives and validators share this table — read only perspective rows here.
    enabled_names = sorted(
        ReviewSkillConfig.objects.for_team(team_id)
        .filter(user_id=acting_user_id, enabled=True, skill_name__startswith=REVIEW_HOG_PERSPECTIVE_PREFIX)
        .values_list("skill_name", flat=True)
    )
    if not enabled_names:
        raise NoEnabledPerspectivesError(
            f"User {acting_user_id} has no enabled review perspective on team {team_id} — enable at least one"
        )
    latest_by_name: dict[str, tuple[int, str]] = {
        name: (version, description)
        for name, version, description in LLMSkill.objects.filter(
            team_id=team_id,
            name__in=enabled_names,
            deleted=False,
            is_latest=True,
        ).values_list("name", "version", "description")
    }
    loaded: list[LoadedPerspective] = []
    for skill_name in enabled_names:
        resolved = latest_by_name.get(skill_name)
        if resolved is None:
            # Enabled config pointing at a dead skill (e.g. archived from the Skills UI): drop it
            # from this run instead of failing the review; restoring the skill resumes it.
            logger.warning(
                "review_hog: enabled perspective '%s' has no live skill on team %s; skipping it this run",
                skill_name,
                team_id,
            )
            continue
        version, description = resolved
        loaded.append(
            LoadedPerspective(
                pass_number=len(loaded) + 1, skill_name=skill_name, version=version, description=description
            )
        )
    if not loaded:
        raise NoEnabledPerspectivesError(
            f"None of user {acting_user_id}'s enabled perspectives has a live skill on team {team_id}"
        )
    return loaded


# Naming contract for the canonical validation-criteria skill — a single skill (not a registry): the
# bar for "does this issue matter" that the validator agent pulls and applies. Its own prefix keeps it
# distinct from the perspective skills both on disk and in the sync's prefix-scoped prune.
REVIEW_HOG_VALIDATION_PREFIX = "review-hog-validation-"
REVIEW_HOG_VALIDATION_SKILL_NAME = f"{REVIEW_HOG_VALIDATION_PREFIX}criteria"

# Canonical validator names `register_missing_validation_config` auto-enables — one today, kept a
# tuple to mirror the multi-name perspective seed.
CANONICAL_VALIDATION_SKILL_NAMES: tuple[str, ...] = (REVIEW_HOG_VALIDATION_SKILL_NAME,)


class ValidationSkillNotFoundError(LookupError):
    """The acting user's selected validator has no live `LLMSkill` row (a real setup/archival error)."""


@dataclass(frozen=True)
class LoadedValidationSkill:
    """The validator resolved for one run: its skill name and pinned version."""

    skill_name: str
    # Snapshotted so the sandbox agent's `skill-get` pulls the exact version this run was planned
    # against, even if a new version is published mid-run.
    version: int


def register_missing_validation_config(team_id: int, user_id: int) -> None:
    """Seed an enabled `ReviewSkillConfig` for the canonical validator this user lacks.

    Mirrors `register_missing_perspective_configs`: the canonical validator auto-enables on a user's
    first run; custom validators are picked explicitly via the config API. Single-active is enforced
    in app code (the select endpoint), so this only ever seeds the one canonical.
    """
    _register_missing_configs(team_id, user_id, CANONICAL_VALIDATION_SKILL_NAMES)


def _load_single_active_skill(
    team_id: int, acting_user_id: int, *, prefix: str, canonical_name: str, error: type[LookupError]
) -> tuple[str, int]:
    """Resolve a user's single-active `<prefix>*` skill selection to a (name, pinned version).

    Reads the user's one enabled row for the prefix, falling back to the canonical when none is
    enabled — there is always a default, so no min-1 floor. A selected custom whose skill row is
    dead (e.g. archived from the Skills UI) also falls back to the canonical rather than failing
    the run. Raises `error` only when the canonical itself has no live row (the sync recreates
    archived canonicals, so this is a genuine seeding failure). The enabled set is single-active in
    app code; `sorted(...)[0]` is only a deterministic tiebreak.
    """
    enabled_names = sorted(
        ReviewSkillConfig.objects.for_team(team_id)
        .filter(user_id=acting_user_id, enabled=True, skill_name__startswith=prefix)
        .values_list("skill_name", flat=True)
    )
    skill_name = enabled_names[0] if enabled_names else canonical_name

    def _live_version(name: str) -> int | None:
        return (
            LLMSkill.objects.filter(team_id=team_id, name=name, deleted=False, is_latest=True)
            .values_list("version", flat=True)
            .first()
        )

    version = _live_version(skill_name)
    if version is None and skill_name != canonical_name:
        logger.warning(
            "review_hog: selected skill '%s' has no live row on team %s; falling back to canonical '%s'",
            skill_name,
            team_id,
            canonical_name,
        )
        skill_name = canonical_name
        version = _live_version(canonical_name)
    if version is None:
        raise error(f"No live skill '{skill_name}' on team {team_id} — the canonical sync has not seeded it")
    return skill_name, version


def load_validation_skill_for_run(team_id: int, acting_user_id: int) -> LoadedValidationSkill:
    """Resolve the acting user's selected validator, pinned to its current latest version.

    Mirrors `load_perspectives_for_run` but single-active: seeds the canonical config (so a cold user
    has the canonical selected), then resolves the user's one enabled `review-hog-validation-*` row
    (canonical fallback when none is enabled or the selection's row is dead; loud
    `ValidationSkillNotFoundError` only when the canonical itself is missing).
    """
    register_missing_validation_config(team_id, acting_user_id)
    skill_name, version = _load_single_active_skill(
        team_id,
        acting_user_id,
        prefix=REVIEW_HOG_VALIDATION_PREFIX,
        canonical_name=REVIEW_HOG_VALIDATION_SKILL_NAME,
        error=ValidationSkillNotFoundError,
    )
    return LoadedValidationSkill(skill_name=skill_name, version=version)


# Naming contract for the blind-spot-check skills: the per-chunk sweep that hunts for what every
# perspective missed. Single-active per user, exactly the validator pattern.
REVIEW_HOG_BLIND_SPOTS_PREFIX = "review-hog-blind-spots-"
REVIEW_HOG_BLIND_SPOTS_SKILL_NAME = f"{REVIEW_HOG_BLIND_SPOTS_PREFIX}general"

# Canonical blind-spots names `register_missing_blind_spots_config` auto-enables — one today, kept a
# tuple to mirror the multi-name perspective seed.
CANONICAL_BLIND_SPOTS_SKILL_NAMES: tuple[str, ...] = (REVIEW_HOG_BLIND_SPOTS_SKILL_NAME,)


class BlindSpotsSkillNotFoundError(LookupError):
    """The acting user's selected blind-spots skill has no live `LLMSkill` row (a real setup error)."""


@dataclass(frozen=True)
class LoadedBlindSpotsSkill:
    """The blind-spots skill resolved for one run: its skill name and pinned version."""

    skill_name: str
    # Snapshotted so the sandbox agent's `skill-get` pulls the exact version this run was planned
    # against, even if a new version is published mid-run.
    version: int


def register_missing_blind_spots_config(team_id: int, user_id: int) -> None:
    """Seed an enabled `ReviewSkillConfig` for the canonical blind-spots skill this user lacks.

    Mirrors `register_missing_validation_config`: single-active is enforced in app code (the select
    endpoint), so this only ever seeds the one canonical.
    """
    _register_missing_configs(team_id, user_id, CANONICAL_BLIND_SPOTS_SKILL_NAMES)


def load_blind_spots_skill_for_run(team_id: int, acting_user_id: int) -> LoadedBlindSpotsSkill:
    """Resolve the acting user's selected blind-spots skill, pinned to its current latest version.

    Mirrors `load_validation_skill_for_run`: seeds the canonical config (so a cold user has the
    canonical selected), then resolves the user's one enabled `review-hog-blind-spots-*` row
    (canonical fallback when none is enabled or the selection's row is dead; loud
    `BlindSpotsSkillNotFoundError` only when the canonical itself is missing).
    """
    register_missing_blind_spots_config(team_id, acting_user_id)
    skill_name, version = _load_single_active_skill(
        team_id,
        acting_user_id,
        prefix=REVIEW_HOG_BLIND_SPOTS_PREFIX,
        canonical_name=REVIEW_HOG_BLIND_SPOTS_SKILL_NAME,
        error=BlindSpotsSkillNotFoundError,
    )
    return LoadedBlindSpotsSkill(skill_name=skill_name, version=version)


# Naming contract for the authoring companion (mirrors scouts' `authoring-scouts`): the one canonical
# guide the "Create your own …" tasks pull over MCP to author custom perspectives / blind-spot checks /
# validation criteria. Not a run skill — it has no loader and never gets `ReviewSkillConfig` rows; it
# only needs to exist as a synced team `LLMSkill` so any agent can `skill-get` it.
REVIEW_HOG_AUTHORING_PREFIX = "review-hog-authoring"
REVIEW_HOG_AUTHORING_SKILL_NAME = REVIEW_HOG_AUTHORING_PREFIX
