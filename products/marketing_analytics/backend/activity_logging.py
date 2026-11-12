from typing import Any

from django.utils.text import Truncator

from posthog.models.activity_logging.activity_log import ActivityScope, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.user import User

from products.marketing_analytics.backend.models.recommendation_resolution import RecommendationResolution

MAX_NAME_LENGTH = 200


@mutable_receiver(model_activity_signal, sender=RecommendationResolution)
def handle_recommendation_resolution_change(
    sender: type[RecommendationResolution],
    scope: ActivityScope,
    before_update: RecommendationResolution | None,
    after_update: RecommendationResolution | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    resolution = after_update or before_update
    assert resolution is not None
    log_activity(
        organization_id=resolution.team.organization_id,
        team_id=resolution.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=resolution.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=Truncator(
                resolution.subject or resolution.campaign_id or resolution.customer_id or resolution.rule
            ).chars(MAX_NAME_LENGTH),
        ),
    )
