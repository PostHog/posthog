from posthog.models.team.team import Team


def organization_deactivated(team_id: int) -> bool:
    """Whether the team's organization is deactivated, so its warehouse work must stand down.

    Only an explicit `is_active=False` counts. NULL means billing never set the state, and such an
    organization keeps syncing. Raises when the read fails; each caller decides what a failed read means.
    """
    is_active = Team.objects.filter(id=team_id).values_list("organization__is_active", flat=True).first()
    return is_active is False
