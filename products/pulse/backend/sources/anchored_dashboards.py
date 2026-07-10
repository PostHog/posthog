from django.db.models import QuerySet

from posthog.models.team import Team

from products.dashboards.backend.models.dashboard import Dashboard
from products.product_analytics.backend.models.insight import Insight
from products.pulse.backend.config import BriefSettings
from products.pulse.backend.models import BriefConfig
from products.pulse.backend.sources.base import SourceItem
from products.pulse.backend.sources.strategy import MovementScoringStrategy


class AnchoredDashboardsSource:
    """Gathers movements from a config's anchored dashboards' insights.

    With no dashboard anchors (and no insight anchors either) it falls back to the team's most
    recently accessed dashboards — the zero-config default brief.
    """

    name = "anchored_dashboards"

    def __init__(self, strategy: MovementScoringStrategy) -> None:
        self._strategy = strategy

    def gather(self, team: Team, config: BriefConfig | None, lookback_days: int) -> list[SourceItem]:
        settings = BriefSettings.from_config(config)
        return self._strategy.gather_items(
            self._dashboard_insights(team, config, settings), team, lookback_days, settings, source_name=self.name
        )

    def _dashboard_insights(self, team: Team, config: BriefConfig | None, settings: BriefSettings) -> QuerySet[Insight]:
        anchors = config.anchors if config else {}
        dashboard_ids = anchors.get("dashboards") or []
        if dashboard_ids:
            dashboards: QuerySet[Dashboard] = Dashboard.objects.filter(team=team, deleted=False, id__in=dashboard_ids)
        elif anchors.get("insights"):
            # Insight anchors are set but no dashboard anchors: AnchoredInsightsSource covers those,
            # and the fallback is for the zero-config case only. Nothing to gather here.
            return Insight.objects.none()
        else:
            # Zero-config default: the team's most recently accessed dashboards.
            dashboards = Dashboard.objects.filter(team=team, deleted=False, last_accessed_at__isnull=False).order_by(
                "-last_accessed_at"
            )[: settings.fallback_dashboard_count]
        return Insight.objects.filter(team=team, deleted=False, dashboards__in=dashboards).distinct()
