"""Narrow test-fixture surface for consumers of the subscriptions facade."""

from datetime import datetime
from uuid import UUID

from posthog.models import Team

from ..models import ProactiveSubscriptionConfig, PublicResearchSubject


def create_public_research_subject_for_test(
    *, team: Team, name: str, canonical_domain: str, reviewed_at: datetime
) -> UUID:
    subject = PublicResearchSubject.objects.for_team(team.id).create(
        team=team,
        name=name,
        canonical_domain=canonical_domain,
        reviewed_at=reviewed_at,
    )
    return subject.id


def proactive_config_exists_for_test(*, team_id: int, subscription_id: int | None = None) -> bool:
    configs = ProactiveSubscriptionConfig.objects.for_team(team_id)
    if subscription_id is not None:
        configs = configs.filter(subscription_id=subscription_id)
    return configs.exists()


__all__ = ["create_public_research_subject_for_test", "proactive_config_exists_for_test"]
