from uuid import UUID

from django.db.models import Q

from posthog.models import Team

from products.signals.backend.models import SignalSpend
from products.signals.backend.trial.policy import TrialPolicy

__all__ = ["claim_trial", "trial_incomplete_sources"]


def claim_trial(*, team: Team, user_id: int) -> UUID:
    return TrialPolicy(team).claim(user_id=user_id).id


def trial_incomplete_sources(*, team: Team, grant_id: UUID) -> int:
    return (
        SignalSpend.objects.unscoped()
        .filter(trial_grant_id=grant_id, trial_grant__team_id=team.parent_team_id or team.id)
        .filter(Q(accounting_pending=True) | Q(accounting_failed=True))
        .count()
    )
