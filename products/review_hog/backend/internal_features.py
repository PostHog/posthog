import logging

from posthog.models.team.team import Team
from posthog.permissions import posthog_feature_flag_enabled

logger = logging.getLogger(__name__)

# Gates the parts of ReviewHog that stay internal: automatic reviews, the label trigger, resolution,
# manual Flash, Inbox reviews, and the tiered review arms. The `review-hog` flag stays the product switch.
REVIEW_HOG_INTERNAL_FLAG = "review-hog-internal"


def has_internal_features(team_id: int) -> bool:
    """Whether the `review-hog-internal` flag is on for this project.

    Evaluated with the project group, the same way the `review-hog` permission evaluates the product flag.
    A flag service failure reads as off, so an outage cannot turn on writes for a project.
    """
    try:
        team = Team.objects.filter(id=team_id).values_list("organization_id", "uuid").first()
        if team is None:
            return False
        organization_id, team_uuid = team
        return posthog_feature_flag_enabled(
            REVIEW_HOG_INTERNAL_FLAG, str(team_uuid), organization_id=organization_id, team_id=team_id
        )
    except Exception:
        logger.exception("Could not evaluate %s for team %s; treating it as off", REVIEW_HOG_INTERNAL_FLAG, team_id)
        return False
