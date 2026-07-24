from posthog.models.team import Team


def is_ai_data_processing_approved(team_id: int) -> bool:
    """Fresh read of the org's AI data-processing consent, fail-closed when the team or org is missing."""
    return bool(
        Team.objects.filter(id=team_id).values_list("organization__is_ai_data_processing_approved", flat=True).first()
    )
