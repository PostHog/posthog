from posthog.test.base import BaseTest

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from posthog.models.activity_logging.activity_log import ActivityLog

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.admin import InsightAdmin
from products.product_analytics.backend.models.insight import Insight


class TestInsightAdminRestore(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.admin = InsightAdmin(Insight, AdminSite())
        self.factory = RequestFactory()

    def _post_request(self):
        request = self.factory.post("/")
        request.user = self.user
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    def test_restore_selected_reactivates_tiles_on_live_dashboards_only_and_logs_activity(self):
        live_dashboard = Dashboard.objects.create(team=self.team, name="live dashboard")
        deleted_dashboard = Dashboard.objects.create(team=self.team, name="deleted dashboard", deleted=True)
        deleted_insight = Insight.objects.create(team=self.team, name="deleted insight", deleted=True)
        tile_on_live = DashboardTile.objects_including_soft_deleted.create(
            dashboard=live_dashboard, insight=deleted_insight, deleted=True
        )
        tile_on_deleted = DashboardTile.objects_including_soft_deleted.create(
            dashboard=deleted_dashboard, insight=deleted_insight, deleted=True
        )
        live_insight = Insight.objects.create(team=self.team, name="live insight")

        queryset = Insight.objects_including_soft_deleted.filter(id__in=[deleted_insight.id, live_insight.id])
        self.admin.restore_selected(self._post_request(), queryset)

        deleted_insight.refresh_from_db()
        tile_on_live.refresh_from_db()
        tile_on_deleted.refresh_from_db()
        assert deleted_insight.deleted is False
        assert tile_on_live.deleted is False
        # The dashboard itself is still deleted, so its tile must stay hidden.
        assert tile_on_deleted.deleted is True

        restored_logs = ActivityLog.objects.filter(scope="Insight", activity="restored", team_id=self.team.id)
        assert [log.item_id for log in restored_logs] == [str(deleted_insight.id)]

    def test_bulk_hard_delete_action_is_not_offered(self):
        actions = self.admin.get_actions(self._post_request())
        assert "delete_selected" not in actions
        assert "restore_selected" in actions
