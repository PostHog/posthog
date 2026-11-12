from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpRequest
from django.test import RequestFactory

from posthog.models.activity_logging.activity_log import ActivityLog

from products.dashboards.backend.facade.testing import create_dashboard, create_insight_tile, insight_tile_is_deleted
from products.product_analytics.backend.admin import InsightAdmin
from products.product_analytics.backend.models.insight import Insight


def _attach_messages(request) -> None:
    # Untyped: session and _messages are set by middleware at runtime.
    request.session = {}
    request._messages = FallbackStorage(request)


class TestInsightAdminRestore(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.admin = InsightAdmin(Insight, AdminSite())
        self.factory = RequestFactory()

    def _post_request(self) -> HttpRequest:
        request = self.factory.post("/")
        request.user = self.user
        _attach_messages(request)
        return request

    def test_restore_selected_reactivates_tiles_on_live_dashboards_only_and_logs_activity(self):
        live_dashboard_id = create_dashboard(team_id=self.team.id, name="live dashboard")
        deleted_dashboard_id = create_dashboard(team_id=self.team.id, name="deleted dashboard", deleted=True)
        deleted_insight = Insight.objects.create(team=self.team, name="deleted insight", deleted=True)
        create_insight_tile(dashboard_id=live_dashboard_id, insight_id=deleted_insight.id, deleted=True)
        create_insight_tile(dashboard_id=deleted_dashboard_id, insight_id=deleted_insight.id, deleted=True)
        live_insight = Insight.objects.create(team=self.team, name="live insight")

        queryset = Insight.objects_including_soft_deleted.filter(id__in=[deleted_insight.id, live_insight.id])
        self.admin.restore_selected(self._post_request(), queryset)

        deleted_insight.refresh_from_db()
        assert deleted_insight.deleted is False
        # Last-modified touched, matching the bulk_restore endpoint.
        assert deleted_insight.last_modified_by == self.user
        assert insight_tile_is_deleted(dashboard_id=live_dashboard_id, insight_id=deleted_insight.id) is False
        # Dashboard still deleted, so its tile stays hidden.
        assert insight_tile_is_deleted(dashboard_id=deleted_dashboard_id, insight_id=deleted_insight.id) is True

        restored_logs = ActivityLog.objects.filter(scope="Insight", activity="restored", team_id=self.team.id)
        assert [log.item_id for log in restored_logs] == [str(deleted_insight.id)]

    def test_restore_reports_no_negative_skip_when_queryset_is_filtered_to_deleted(self):
        # The changelist passes a deleted=True-filtered queryset; a post-restore count would
        # drop the just-restored rows and report a negative skip.
        deleted_insight = Insight.objects.create(team=self.team, name="deleted insight", deleted=True)
        queryset = Insight.objects_including_soft_deleted.filter(id=deleted_insight.id, deleted=True)

        with patch.object(self.admin, "message_user") as message_user:
            self.admin.restore_selected(self._post_request(), queryset)

        assert message_user.call_args[0][1] == "Restored 1 insights."

    def test_bulk_hard_delete_action_is_not_offered(self):
        actions = self.admin.get_actions(self._post_request())
        assert "delete_selected" not in actions
        assert "restore_selected" in actions
