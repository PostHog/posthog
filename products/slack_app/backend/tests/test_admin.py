from datetime import UTC, datetime

from posthog.test.base import BaseTest

from django.urls import reverse

from parameterized import parameterized

from posthog.admin import register_all_admin

from products.slack_app.backend.models import SlackDailyFocus

register_all_admin()


class TestSlackDailyFocusAdmin(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        self.on, self.off = (
            SlackDailyFocus.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                slack_workspace_id="T0ADMIN",
                slack_user_id=slack_user_id,
                integration_id=1,
                next_run_at=next_run_at,
            )
            for slack_user_id, next_run_at in (("U0ON", datetime(2026, 11, 10, 8, 0, tzinfo=UTC)), ("U0OFF", None))
        )

    @parameterized.expand([("on", ["U0ON"]), ("off", ["U0OFF"]), ("", ["U0OFF", "U0ON"])])
    def test_the_list_shows_rows_without_a_team_scope_and_filters_by_state(self, state, shown):
        url = reverse("admin:slack_app_slackdailyfocus_changelist")
        response = self.client.get(url, {"state": state} if state else {})

        assert response.status_code == 200
        assert sorted(row.slack_user_id for row in response.context["cl"].result_list) == shown

    def test_the_change_page_is_read_only(self):
        response = self.client.get(reverse("admin:slack_app_slackdailyfocus_change", args=[self.on.pk]))

        assert response.status_code == 200
        assert not response.context["has_change_permission"]
        assert not response.context["has_delete_permission"]
