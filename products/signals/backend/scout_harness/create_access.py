from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl


def can_create_scout(user: User, canonical_team: Team) -> bool:
    """Whether ``user`` may create a scout on ``canonical_team``: editor access to skills, because the
    skill body is the prompt the scout agent runs. Access to the project itself is a separate check."""
    return UserAccessControl(user=user, team=canonical_team).check_access_level_for_resource("llm_skill", "editor")
