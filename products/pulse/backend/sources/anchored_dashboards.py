from django.db.models import Q, QuerySet

from posthog.models.team import Team

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.facade import api as dashboards_api
from products.product_analytics.backend.facade.models import Insight
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
        anchored_ids = (config.anchors.get("dashboards") if config else None) or []
        if anchored_ids:
            dashboard_ids = dashboards_api.viewable_dashboard_ids(
                team_id=team.id, dashboard_ids=anchored_ids, user_access_control=user_access_control
            )
        elif config is None:
            # Zero-config default brief only: the team's most recently accessed dashboards. A saved
            # config that anchors no dashboards gathers nothing here — its other anchors (e.g.
            # insights) are their own source's job, so the fallback would just duplicate them.
            recent = dashboards_api.recently_accessed_dashboards(
                team_id=team.id, limit=settings.fallback_dashboard_count, user_access_control=user_access_control
            )
            dashboard_ids = {dashboard.id for dashboard in recent}
        else:
            dashboard_ids = set()
        if not dashboard_ids:
            return Insight.objects.none()
        # A removed tile counts too, matching the `Insight.dashboards` relation.
        on_dashboards = Q()
        for dashboard_id in sorted(dashboard_ids):
            on_dashboards |= Q(id__in=dashboards_api.insight_ids_on_dashboard(dashboard_id, include_removed_tiles=True))
        return user_access_control.filter_queryset_by_access_level(
            Insight.objects.filter(on_dashboards, team=team, deleted=False).distinct()
        )
