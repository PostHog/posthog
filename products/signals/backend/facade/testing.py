from uuid import UUID

from posthog.models import Team

from products.signals.backend.trial.models import SignalTrialGrant
from products.signals.backend.trial.policy import TrialPolicy

__all__ = ["claim_trial", "trial_incomplete_sources"]


def claim_trial(*, team: Team, user_id: int) -> UUID:
    return TrialPolicy(team).claim(user_id=user_id).id


def trial_incomplete_sources(*, team: Team, grant_id: UUID) -> int:
    return (
        SignalTrialGrant.objects.for_team(team.parent_team_id or team.id, canonical=True)
        .values_list("incomplete_sources", flat=True)
        .get(id=grant_id)
    )
