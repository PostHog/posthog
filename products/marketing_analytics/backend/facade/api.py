from datetime import datetime
from typing import TYPE_CHECKING

from posthog.schema import (
    MarketingAnalyticsRecommendationIdentity,
    MarketingAnalyticsRecommendationIdentitySourceType,
    MarketingAnalyticsRecommendationResolutionState,
    MarketingAnalyticsRecommendationRule,
)

from posthog.dataclasses import frozen

from products.marketing_analytics.backend import recommendation_access, recommendation_resolutions
from products.marketing_analytics.backend.hogql_queries.recommendation_identity import (
    InvalidRecommendationIdentity,
    RecommendationKey,
)
from products.marketing_analytics.backend.models.recommendation_resolution import RecommendationResolution

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl

__all__ = [
    "InvalidRecommendationIdentity",
    "RecommendationResolver",
    "ResolveOutcome",
    "ResolvedRecommendation",
    "can_resolve_recommendations",
    "resolve_recommendation",
    "restore_recommendation",
]


@frozen
class RecommendationResolver:
    id: int
    uuid: str
    distinct_id: str | None
    first_name: str
    last_name: str
    email: str


@frozen
class ResolvedRecommendation:
    id: str
    identity: MarketingAnalyticsRecommendationIdentity
    key: str
    resolution: MarketingAnalyticsRecommendationResolutionState
    resolved_by: RecommendationResolver | None
    resolved_at: datetime
    created_at: datetime


@frozen
class ResolveOutcome:
    resolution: ResolvedRecommendation
    created: bool


def resolve_recommendation(
    team_id: int,
    identity: MarketingAnalyticsRecommendationIdentity,
    resolution: MarketingAnalyticsRecommendationResolutionState,
    user_id: int,
) -> ResolveOutcome:
    """Dismiss a recommendation or mark it as applied. Raises InvalidRecommendationIdentity for an identity its rule
    cannot produce."""
    row, created = recommendation_resolutions.resolve(team_id, identity, resolution, user_id)
    return ResolveOutcome(resolution=_to_contract(row), created=created)


def restore_recommendation(team_id: int, resolution_id: str) -> bool:
    """Delete a resolution so its recommendation shows again. Returns False when the team has no such resolution."""
    return recommendation_resolutions.restore(team_id, resolution_id)


def can_resolve_recommendations(team_id: int, user_access_control: "UserAccessControl") -> bool:
    """Whether the user may read every Google Ads and Search Console table of the team, which resolving needs."""
    return recommendation_access.can_resolve(team_id, user_access_control)


def _to_contract(row: RecommendationResolution) -> ResolvedRecommendation:
    identity = MarketingAnalyticsRecommendationIdentity(
        rule=MarketingAnalyticsRecommendationRule(row.rule),
        source_type=MarketingAnalyticsRecommendationIdentitySourceType(row.source_type),
        customer_id=row.customer_id,
        campaign_id=row.campaign_id,
        subject=row.subject,
    )
    user = row.resolved_by
    return ResolvedRecommendation(
        id=str(row.id),
        identity=identity,
        key=RecommendationKey.from_identity(identity).encoded,
        resolution=MarketingAnalyticsRecommendationResolutionState(row.resolution),
        resolved_by=RecommendationResolver(
            id=user.id,
            uuid=str(user.uuid),
            distinct_id=user.distinct_id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )
        if user is not None
        else None,
        resolved_at=row.resolved_at,
        created_at=row.created_at,
    )
