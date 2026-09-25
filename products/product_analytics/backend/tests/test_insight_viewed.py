from posthog.test.base import BaseTest

from django.apps import apps
from django.utils.timezone import now

from products.product_analytics.backend.models.insight import Insight, InsightViewed


class TestInsightViewedDashboardHistory(BaseTest):
    def test_dashboard_deletion_preserves_view_history_and_context(self) -> None:
        dashboard = apps.get_model("dashboards", "Dashboard").objects.create(team=self.team)
        insight = Insight.objects.create(team=self.team)
        row = InsightViewed.objects.create(
            team=self.team,
            user=self.user,
            insight=insight,
            dashboard=dashboard,
            source="web",
            last_viewed_at=now(),
        )
        dashboard_id = dashboard.pk
        viewed_at = row.last_viewed_at

        for deleted in (True, False):
            dashboard.deleted = deleted
            dashboard.save(update_fields=["deleted"])
            row.refresh_from_db()
            assert row.dashboard_id == dashboard_id
            assert row.last_viewed_at == viewed_at

        dashboard.delete()
        row.refresh_from_db()
        assert row.dashboard_id == dashboard_id
        assert row.last_viewed_at == viewed_at
        assert not InsightViewed.objects.filter(pk=row.pk, dashboard_id__isnull=True).exists()
