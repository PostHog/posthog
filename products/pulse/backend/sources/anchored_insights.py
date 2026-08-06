from django.db.models import QuerySet

from posthog.models.team import Team
from posthog.rbac.user_access_control import UserAccessControl

from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.config import BriefSettings
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.base import SourceItem
from products.pulse.backend.sources.strategy import MovementScoringStrategy


class AnchoredInsightsSource:
    """Gathers movements from the insights a config anchors on directly (by short_id)."""

    name = "anchored_insights"

    def __init__(self, strategy: MovementScoringStrategy) -> None:
        self._strategy = strategy

    def gather(
        self, team: Team, config: BriefConfig | None, lookback_days: int, user_access_control: UserAccessControl
    ) -> list[SourceItem]:
        settings = BriefSettings.from_config(config)
        return self._strategy.gather_items(
            self._anchor_insights(team, config, user_access_control),
            team,
            lookback_days,
            settings,
            user_access_control,
            source_name=self.name,
        )

    def _anchor_insights(
        self, team: Team, config: BriefConfig | None, user_access_control: UserAccessControl
    ) -> QuerySet[Insight]:
        insight_short_ids = (config.anchors.get("insights") if config else None) or []
        if not insight_short_ids:
            return Insight.objects.none()
        return user_access_control.filter_queryset_by_access_level(
            Insight.objects.filter(team=team, deleted=False, short_id__in=insight_short_ids).distinct()
        )
