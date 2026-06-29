"""Resolve ReviewHog's canonical pulled skills from a team's `LLMSkill` rows.

ReviewHog's review **perspectives** and its **validation criteria** are stored and synced the way
Signals' scouts store theirs: canonical `SKILL.md` on disk (`products/review_hog/skills/`) mirrored
into per-team `LLMSkill` rows by `lazy_seed.sync_canonical_*`. Delivery is **pull** — the review /
validation prompts instruct the sandbox agent to `skill-get` the skill body over the PostHog MCP — so
these loaders only need to pin the current version per skill (not the body).
"""

from __future__ import annotations

from dataclasses import dataclass

from products.review_hog.backend.models import ReviewSkillConfig
from products.review_hog.backend.reviewer.models.issues_review import PerspectiveType
from products.skills.backend.models.skills import LLMSkill

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


class PerspectiveSkillNotFoundError(LookupError):
    """A user has an enabled perspective config whose `LLMSkill` row is missing (a real sync error)."""


class NoEnabledPerspectivesError(LookupError):
    """A user has zero enabled review perspectives on the team — there is nothing to review with."""


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


def register_missing_perspective_configs(team_id: int, user_id: int) -> None:
    """Seed an enabled `ReviewSkillConfig` for each canonical perspective this user lacks.

    The one allowed canonical/custom difference: the canonicals auto-enable on a user's first run
    ("auto-added on the start"); customs are switched on explicitly via the config API. Idempotent
    (`get_or_create` on the `(team, user, skill_name)` unique key), and a row the user disabled is
    left untouched — seeding never re-enables. `team_id` / `user_id` stay in the create kwargs: the
    fail-closed `for_team()` filter does not propagate into `create`.
    """
    configs = ReviewSkillConfig.objects.for_team(team_id)
    for skill_name in CANONICAL_PERSPECTIVE_SKILL_NAMES:
        configs.get_or_create(team_id=team_id, user_id=user_id, skill_name=skill_name, defaults={"enabled": True})


def load_perspectives_for_run(team_id: int, acting_user_id: int) -> list[LoadedPerspective]:
    """Resolve the acting user's enabled perspectives, each pinned to its current latest version.

    Seeds the canonical configs first (so a cold user gets the 3 canonicals), then reads the user's
    enabled set and resolves each name to its live `LLMSkill` (latest, non-deleted). `pass_number`
    is a per-run index over the enabled set sorted by name — a re-run with the same enabled set is
    deterministic. Raises `NoEnabledPerspectivesError` if the user has zero enabled (min-1 floor)
    and `PerspectiveSkillNotFoundError` if an enabled perspective's skill row is missing (a real
    setup error — the caller cold-start-syncs the canonicals first).
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
    latest_by_name: dict[str, int] = dict(
        LLMSkill.objects.filter(
            team_id=team_id,
            name__in=enabled_names,
            deleted=False,
            is_latest=True,
        ).values_list("name", "version")
    )
    loaded: list[LoadedPerspective] = []
    for pass_number, skill_name in enumerate(enabled_names, start=1):
        version = latest_by_name.get(skill_name)
        if version is None:
            raise PerspectiveSkillNotFoundError(
                f"No live skill '{skill_name}' on team {team_id} — run sync_review_hog_skills first"
            )
        loaded.append(LoadedPerspective(pass_number=pass_number, skill_name=skill_name, version=version))
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
    first run; custom validators are picked explicitly via the config API. Idempotent on the
    `(team, user, skill_name)` unique key, and a row the user changed is left untouched. Single-active
    is enforced in app code (the select endpoint), so this only ever seeds the one canonical.
    """
    configs = ReviewSkillConfig.objects.for_team(team_id)
    for skill_name in CANONICAL_VALIDATION_SKILL_NAMES:
        configs.get_or_create(team_id=team_id, user_id=user_id, skill_name=skill_name, defaults={"enabled": True})


def load_validation_skill_for_run(team_id: int, acting_user_id: int) -> LoadedValidationSkill:
    """Resolve the acting user's selected validator, pinned to its current latest version.

    Mirrors `load_perspectives_for_run` but single-active: seeds the canonical config (so a cold user
    has the canonical selected), reads the user's one enabled `review-hog-validation-*` row, and pins
    its latest non-deleted version. Falls back to the canonical validator when no validation row is
    enabled — there is always a default, so no min-1 floor. Raises `ValidationSkillNotFoundError` if
    the selected skill's row is missing (surfaced loudly like perspectives). The enabled set is
    single-active in app code; `sorted(...)[0]` is only a deterministic tiebreak.
    """
    register_missing_validation_config(team_id, acting_user_id)
    enabled_names = sorted(
        ReviewSkillConfig.objects.for_team(team_id)
        .filter(user_id=acting_user_id, enabled=True, skill_name__startswith=REVIEW_HOG_VALIDATION_PREFIX)
        .values_list("skill_name", flat=True)
    )
    skill_name = enabled_names[0] if enabled_names else REVIEW_HOG_VALIDATION_SKILL_NAME
    version = (
        LLMSkill.objects.filter(team_id=team_id, name=skill_name, deleted=False, is_latest=True)
        .values_list("version", flat=True)
        .first()
    )
    if version is None:
        raise ValidationSkillNotFoundError(
            f"No live skill '{skill_name}' on team {team_id} — run sync_review_hog_skills first"
        )
    return LoadedValidationSkill(skill_name=skill_name, version=version)
