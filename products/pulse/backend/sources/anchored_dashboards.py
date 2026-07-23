from django.db.models import QuerySet

from posthog.models.team import Team
from posthog.rbac.user_access_control import UserAccessControl

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

    def gather(
        self, team: Team, config: BriefConfig | None, lookback_days: int, user_access_control: UserAccessControl
    ) -> list[SourceItem]:
        settings = BriefSettings.from_config(config)
        return self._strategy.gather_items(
            self._dashboard_insights(team, config, settings, user_access_control),
            team,
            lookback_days,
            settings,
            user_access_control,
            source_name=self.name,
        )

    def _dashboard_insights(
        self,
        team: Team,
        config: BriefConfig | None,
        settings: BriefSettings,
        user_access_control: UserAccessControl,
    ) -> QuerySet[Insight]:
        dashboard_ids = (config.anchors.get("dashboards") if config else None) or []
        if dashboard_ids:
            dashboards: QuerySet[Dashboard] = user_access_control.filter_queryset_by_access_level(
                Dashboard.objects.filter(team=team, deleted=False, id__in=dashboard_ids)
            )
        elif config is None:
            # Zero-config default brief only: the team's most recently accessed dashboards. A saved
            # config that anchors no dashboards gathers nothing here — its other anchors (e.g.
            # insights) are their own source's job, so the fallback would just duplicate them.
            dashboards = user_access_control.filter_queryset_by_access_level(
                Dashboard.objects.filter(team=team, deleted=False, last_accessed_at__isnull=False)
            ).order_by("-last_accessed_at")[: settings.fallback_dashboard_count]
        else:
            return Insight.objects.none()
        return user_access_control.filter_queryset_by_access_level(
            Insight.objects.filter(team=team, deleted=False, dashboards__in=dashboards).distinct()
        )
