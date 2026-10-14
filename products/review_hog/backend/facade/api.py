"""PostHog Review's data surface for its own views and for other products.

Takes plain values and contracts, returns contracts. Keep heavy imports (Temporal, HogQL) off this
module: they go in their own facade submodule.
"""

import logging
from collections.abc import Mapping

from posthog.models.scoping.manager import resolve_effective_team_id

from products.review_hog.backend.facade.contracts import (
    ReviewProjectPreferenceDefaults,
    ReviewSkill,
    ReviewSkillChoice,
    ReviewUserPreferences,
)
from products.review_hog.backend.facade.enums import ReviewSkillKind
from products.review_hog.backend.models import ReviewUserSettings
from products.review_hog.backend.preferences import ReviewPreferences
from products.review_hog.backend.reviewer.lazy_seed import seed_canonicals_tolerantly, sync_canonical_authoring
from products.review_hog.backend.skill_configs import ReviewSkillMenu
from products.stamphog.backend.facade.api import has_reviewable_repo_config

logger = logging.getLogger(__name__)


def list_review_skill_choices(team_id: int, user_id: int, kind: ReviewSkillKind) -> list[ReviewSkillChoice]:
    """The review skills of `kind` the user can see, by name, with the user's state for each.

    Seeds the canonical skills and the user's canonical config rows first, so a cold team or user
    sees the defaults.
    """
    return ReviewSkillMenu(team_id, user_id, kind).choices()


def get_review_skill(team_id: int, user_id: int, kind: ReviewSkillKind, skill_name: str) -> ReviewSkill:
    """The live review skill of `kind` called `skill_name`, when the user can see it.

    Raises `ReviewSkillNameError` when the name does not carry the prefix of `kind`, and
    `ReviewSkillNotFoundError` when no such skill is visible to the user.
    """
    return ReviewSkillMenu(team_id, user_id, kind).get(skill_name)


def set_review_perspective_enabled(
    team_id: int, user_id: int, perspective: ReviewSkill, enabled: bool
) -> ReviewSkillChoice:
    """Enable or disable one perspective for the user.

    Raises `LastEnabledPerspectiveError` when the user would have no enabled perspective left.
    """
    return ReviewSkillMenu(team_id, user_id, ReviewSkillKind.PERSPECTIVE).set_enabled(perspective, enabled)


def select_review_skill(team_id: int, user_id: int, kind: ReviewSkillKind, skill: ReviewSkill) -> ReviewSkillChoice:
    """Make `skill` the user's single active skill of a single-active `kind`."""
    return ReviewSkillMenu(team_id, user_id, kind).select(skill)


def _stamphog_connected(team_id: int) -> bool:
    # This reads the stamphog product DB, which can fail fast on its own circuit breaker. An
    # informational UI flag must not fail the settings endpoint, so fall back to False.
    try:
        return has_reviewable_repo_config(team_id)
    except Exception:
        logger.exception("review_hog_stamphog_connected_check_failed")
        return False


def _user_preferences(team_id: int, preferences: ReviewPreferences) -> ReviewUserPreferences:
    return ReviewUserPreferences(
        default_review_mode=preferences.default_review_mode,
        review_drafts=preferences.review_drafts,
        resolve_comments=preferences.resolve_comments,
        urgency_threshold=preferences.urgency_threshold,
        celebrate_clean_reviews=preferences.celebrate_clean_reviews,
        review_inbox_prs=preferences.review_inbox_prs,
        stamphog_review_inbox_prs=preferences.stamphog_review_inbox_prs,
        sources=preferences.sources,
        project_defaults=ReviewProjectPreferenceDefaults(
            urgency_threshold=preferences.project.urgency_threshold,
            celebrate_clean_reviews=preferences.project.celebrate_clean_reviews,
        ),
        stamphog_connected=_stamphog_connected(team_id),
    )


def get_review_user_preferences(team_id: int, user_id: int) -> ReviewUserPreferences:
    """The user's effective review preferences on the project. Reading never creates a row."""
    team_id = resolve_effective_team_id(team_id)
    # Seed the authoring companion before any review has run: the "Create your own …" tasks
    # `skill-get` it over MCP, and this settings read backs the Code review tab's always-called
    # endpoint. `team_id` is already the effective (root) team, the same team the review runs
    # under, so the skill lands where the sandbox agent's `skill-get` will look.
    seed_canonicals_tolerantly(team_id, sync_canonical_authoring)
    return _user_preferences(team_id, ReviewUserSettings.load_preferences(team_id, user_id))


def update_review_user_preferences(team_id: int, user_id: int, changes: Mapping[str, object]) -> ReviewUserPreferences:
    """Apply `changes` to the user's preferences. A value equal to the inherited one clears the user's own value.

    Raises `InvalidPreference` for an unknown key or an invalid value.
    """
    # Resolve a raw environment URL id to its root team once: `for_team` canonicalizes its filter
    # but not the create kwargs, and mismatched ids mean a never-matching get plus 500s on re-read.
    team_id = resolve_effective_team_id(team_id)
    return _user_preferences(team_id, ReviewUserSettings.save_preference_changes(team_id, user_id, changes))
