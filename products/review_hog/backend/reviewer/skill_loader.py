"""Resolve the canonical review perspectives from a team's `LLMSkill` rows.

ReviewHog's three review perspectives are stored and synced the way Signals' scouts store theirs:
canonical `SKILL.md` on disk (`products/review_hog/skills/review-hog-perspective-*/`) mirrored into
per-team `LLMSkill` rows by `lazy_seed.sync_canonical_perspectives`. Delivery is **pull** — the
issues-review prompt instructs the sandbox agent to `skill-get` each perspective's body over the
PostHog MCP — so this loader only needs to pin the current version per perspective (not the body).
"""

from __future__ import annotations

from dataclasses import dataclass

from products.review_hog.backend.reviewer.models.issues_review import PerspectiveType
from products.skills.backend.models.skills import LLMSkill

# Naming contract for the canonical review perspectives, mirroring `SIGNALS_SCOUT_SKILL_PREFIX`.
REVIEW_HOG_PERSPECTIVE_PREFIX = "review-hog-perspective-"

# The canonical review perspectives, in order. The list position (1-based) is the perspective's
# ordinal "pass number" — the pipeline recovers which perspective found an issue by that ordinal
# (`combine_issues` does `list(PerspectiveType)[pass_number - 1]`, and the issue id is
# `{pass}-{chunk}-{issue}`), so this order MUST match the `PerspectiveType` declaration order. A
# unit test asserts it. Every run executes all three; per-team custom perspectives are a later
# iteration.
PERSPECTIVES: tuple[tuple[PerspectiveType, str], ...] = (
    (PerspectiveType.LOGIC_CORRECTNESS, f"{REVIEW_HOG_PERSPECTIVE_PREFIX}logic-correctness"),
    (PerspectiveType.CONTRACTS_SECURITY, f"{REVIEW_HOG_PERSPECTIVE_PREFIX}contracts-security"),
    (PerspectiveType.PERFORMANCE_RELIABILITY, f"{REVIEW_HOG_PERSPECTIVE_PREFIX}performance-reliability"),
)


class PerspectiveSkillNotFoundError(LookupError):
    """A team has no live `LLMSkill` row for a canonical review perspective."""


@dataclass(frozen=True)
class LoadedPerspective:
    """A canonical perspective resolved for one run: its ordinal, skill name, and pinned version."""

    # 1-based ordinal (position in `PERSPECTIVES`) — the pipeline's `pass_number`.
    pass_number: int
    perspective: PerspectiveType
    skill_name: str
    # Snapshotted so the sandbox agent's `skill-get` pulls the exact version this run was planned
    # against, even if a new version is published mid-run.
    version: int


def load_perspectives_for_run(team_id: int) -> list[LoadedPerspective]:
    """Resolve every canonical perspective on the team and pin its current latest version.

    Reads the team's live `LLMSkill` rows directly (latest, non-deleted). Raises
    `PerspectiveSkillNotFoundError` if any perspective is missing — the caller is expected to have
    run `sync_canonical_perspectives` (cold-start sync) first, so a missing row is a real setup
    error, not a soft miss.
    """
    latest_by_name: dict[str, int] = dict(
        LLMSkill.objects.filter(
            team_id=team_id,
            name__in=[name for _, name in PERSPECTIVES],
            deleted=False,
            is_latest=True,
        ).values_list("name", "version")
    )
    loaded: list[LoadedPerspective] = []
    for pass_number, (perspective, skill_name) in enumerate(PERSPECTIVES, start=1):
        version = latest_by_name.get(skill_name)
        if version is None:
            raise PerspectiveSkillNotFoundError(
                f"No live skill '{skill_name}' on team {team_id} — run sync_review_hog_perspectives first"
            )
        loaded.append(
            LoadedPerspective(pass_number=pass_number, perspective=perspective, skill_name=skill_name, version=version)
        )
    return loaded
