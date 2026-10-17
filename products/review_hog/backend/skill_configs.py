"""Per-user review skill menus: which team review skills a user sees, and which run on their reviews.

A review skill is any team `LLMSkill` whose name carries the prefix of its kind (canonical or custom,
handled identically at run time). The skill itself is team-level; a `ReviewSkillConfig` row per
(team, user, skill name) controls whether it runs on that user's PR reviews. Visibility is per-user:
a menu shows the canonicals plus the customs the user authored, never a teammate's custom
(`visible_skill_names`).

Perspectives are multi-enable with a floor of one. The other kinds are single-active: a review runs
exactly one, and there is always a default (the canonical), so no floor is needed.
"""

from collections.abc import Callable

from django.db import transaction
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team.team import Team

from products.review_hog.backend.facade.contracts import (
    LastEnabledPerspectiveError,
    ReviewSkill,
    ReviewSkillChoice,
    ReviewSkillNameError,
    ReviewSkillNotFoundError,
)
from products.review_hog.backend.facade.enums import ReviewSkillKind
from products.review_hog.backend.models import ReviewSkillConfig
from products.review_hog.backend.reviewer.lazy_seed import (
    SyncResult,
    seed_canonicals_tolerantly,
    sync_canonical_blind_spots,
    sync_canonical_perspectives,
    sync_canonical_resolution,
    sync_canonical_validation,
)
from products.review_hog.backend.reviewer.skill_loader import (
    CANONICAL_BLIND_SPOTS_SKILL_NAMES,
    CANONICAL_PERSPECTIVE_SKILL_NAMES,
    CANONICAL_RESOLUTION_SKILL_NAMES,
    CANONICAL_VALIDATION_SKILL_NAMES,
    REVIEW_HOG_BLIND_SPOTS_PREFIX,
    REVIEW_HOG_PERSPECTIVE_PREFIX,
    REVIEW_HOG_RESOLUTION_PREFIX,
    REVIEW_HOG_VALIDATION_PREFIX,
    register_missing_blind_spots_config,
    register_missing_perspective_configs,
    register_missing_resolution_config,
    register_missing_validation_config,
    visible_skill_names,
)
from products.skills.backend.models.skills import LLMSkill


@frozen
class ReviewSkillFamily:
    prefix: str
    canonical_names: tuple[str, ...]
    sync_canonicals: Callable[[Team], SyncResult]
    register_missing_configs: Callable[[int, int], None]


REVIEW_SKILL_FAMILIES: dict[ReviewSkillKind, ReviewSkillFamily] = {
    ReviewSkillKind.PERSPECTIVE: ReviewSkillFamily(
        prefix=REVIEW_HOG_PERSPECTIVE_PREFIX,
        canonical_names=CANONICAL_PERSPECTIVE_SKILL_NAMES,
        sync_canonicals=sync_canonical_perspectives,
        register_missing_configs=register_missing_perspective_configs,
    ),
    ReviewSkillKind.VALIDATION: ReviewSkillFamily(
        prefix=REVIEW_HOG_VALIDATION_PREFIX,
        canonical_names=CANONICAL_VALIDATION_SKILL_NAMES,
        sync_canonicals=sync_canonical_validation,
        register_missing_configs=register_missing_validation_config,
    ),
    ReviewSkillKind.BLIND_SPOTS: ReviewSkillFamily(
        prefix=REVIEW_HOG_BLIND_SPOTS_PREFIX,
        canonical_names=CANONICAL_BLIND_SPOTS_SKILL_NAMES,
        sync_canonicals=sync_canonical_blind_spots,
        register_missing_configs=register_missing_blind_spots_config,
    ),
    ReviewSkillKind.RESOLUTION: ReviewSkillFamily(
        prefix=REVIEW_HOG_RESOLUTION_PREFIX,
        canonical_names=CANONICAL_RESOLUTION_SKILL_NAMES,
        sync_canonicals=sync_canonical_resolution,
        register_missing_configs=register_missing_resolution_config,
    ),
}


class ReviewSkillMenu:
    """One user's menu of one kind of review skill on a project."""

    def __init__(self, team_id: int, user_id: int, kind: ReviewSkillKind) -> None:
        # Resolve a raw environment URL id to its root team once: the skills and config rows all live
        # on the canonical team, so an unresolved id would render an empty menu. `for_team`
        # canonicalizes its filter but not the create kwargs, and mismatched ids mean a never-matching
        # get plus 500s on the unique constraint from the second call on.
        self.team_id = resolve_effective_team_id(team_id)
        self.user_id = user_id
        self.kind = kind
        self.family = REVIEW_SKILL_FAMILIES[kind]

    def _seed_canonical_skills(self) -> None:
        # A team that never ran a review has no LLMSkill rows yet. Without the seed the menu renders
        # empty until the first run, and a canonical selected before that run 404s.
        seed_canonicals_tolerantly(self.team_id, self.family.sync_canonicals)

    def _visible_names(self) -> set[str]:
        return visible_skill_names(
            self.team_id, self.user_id, prefix=self.family.prefix, canonical_names=self.family.canonical_names
        )

    def _check_name(self, skill_name: str) -> None:
        if not skill_name.startswith(self.family.prefix):
            raise ReviewSkillNameError(skill_name)

    def choices(self) -> list[ReviewSkillChoice]:
        """The visible skills of this kind, by name, with the user's state for each."""
        self._seed_canonical_skills()
        self.family.register_missing_configs(self.team_id, self.user_id)
        # Prefix-scope: all kinds share this table, so only join this kind's rows to the menu.
        enabled_by_name = dict(
            ReviewSkillConfig.objects.for_team(self.team_id, canonical=True)
            .filter(user_id=self.user_id, skill_name__startswith=self.family.prefix)
            .values_list("skill_name", "enabled")
        )
        skills = LLMSkill.objects.filter(
            team_id=self.team_id, name__in=self._visible_names(), is_latest=True, deleted=False
        ).order_by("name")
        return [
            ReviewSkillChoice(
                skill_name=skill.name,
                enabled=enabled_by_name.get(skill.name, False),
                description=skill.description,
                body=skill.body,
            )
            for skill in skills
        ]

    def get(self, skill_name: str) -> ReviewSkill:
        """The live skill of this kind with this name, when the user can see it."""
        self._check_name(skill_name)
        self._seed_canonical_skills()
        skill = LLMSkill.objects.filter(team_id=self.team_id, name=skill_name, is_latest=True, deleted=False).first()
        # A teammate's custom 404s exactly like a missing skill — visibility is author-only, and a
        # distinct error would leak that the name exists.
        if skill is None or skill_name not in self._visible_names():
            raise ReviewSkillNotFoundError(skill_name)
        return ReviewSkill(skill_name=skill.name, description=skill.description, body=skill.body)

    def set_enabled(self, skill: ReviewSkill, enabled: bool) -> ReviewSkillChoice:
        """Enable or disable one perspective. Upserts the config row, so a fresh custom needs one call."""
        if self.kind != ReviewSkillKind.PERSPECTIVE:
            raise ValueError(f"{self.kind} skills are single-active; select one instead")
        self._check_name(skill.skill_name)
        # Seed the canonicals first so the min-1 floor counts a cold user's defaults, not zero.
        self.family.register_missing_configs(self.team_id, self.user_id)
        configs = ReviewSkillConfig.objects.for_team(self.team_id, canonical=True)
        if not enabled:
            # Best-effort floor (count + write, no lock) — same as scouts. The loader's
            # NoEnabledPerspectivesError is the backstop if a rare concurrent double-disable slips through.
            # Prefix-scope: the floor counts only perspectives — an enabled validator (same table)
            # must not let a user disable their last perspective.
            others_enabled = (
                configs.filter(user_id=self.user_id, enabled=True, skill_name__startswith=self.family.prefix)
                .exclude(skill_name=skill.skill_name)
                .count()
            )
            if others_enabled == 0:
                raise LastEnabledPerspectiveError(skill.skill_name)

        # `team_id` / `user_id` stay in the create kwargs — the fail-closed filter doesn't propagate.
        config, _created = configs.get_or_create(
            team_id=self.team_id, user_id=self.user_id, skill_name=skill.skill_name, defaults={"enabled": enabled}
        )
        if config.enabled != enabled:
            config.enabled = enabled
            config.save(update_fields=["enabled", "updated_at"])
        return ReviewSkillChoice(
            skill_name=skill.skill_name, enabled=enabled, description=skill.description, body=skill.body
        )

    def select(self, skill: ReviewSkill) -> ReviewSkillChoice:
        """Make one skill the user's single active skill of this kind, and switch the others off."""
        if self.kind == ReviewSkillKind.PERSPECTIVE:
            raise ValueError("perspectives are multi-enable; enable or disable them instead")
        self._check_name(skill.skill_name)
        self.family.register_missing_configs(self.team_id, self.user_id)
        configs = ReviewSkillConfig.objects.for_team(self.team_id, canonical=True)
        # Single-active: deactivate-others + activate-this must land together, or a crash between them
        # leaves the user with no active skill (the loader's canonical fallback would heal it).
        with transaction.atomic():
            configs.filter(user_id=self.user_id, skill_name__startswith=self.family.prefix, enabled=True).exclude(
                skill_name=skill.skill_name
            ).update(enabled=False, updated_at=timezone.now())
            # `team_id` / `user_id` stay in the create kwargs — the fail-closed filter doesn't propagate.
            config, _created = configs.get_or_create(
                team_id=self.team_id, user_id=self.user_id, skill_name=skill.skill_name, defaults={"enabled": True}
            )
            if not config.enabled:
                config.enabled = True
                config.save(update_fields=["enabled", "updated_at"])
        return ReviewSkillChoice(
            skill_name=skill.skill_name, enabled=True, description=skill.description, body=skill.body
        )
