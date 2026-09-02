from datetime import UTC, datetime

from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog

from products.signals.backend.facade.api import set_default_slack_notification_channel
from products.signals.backend.models import SignalReport, SignalTeamConfig
from products.signals.backend.serializers import MAX_AUTOSTART_BASE_BRANCH_ENTRIES, SignalTeamConfigSerializer


class TestSignalTeamConfigAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # A SignalTeamConfig is auto-created for every team via register_team_extension_signal.
        self.config = SignalTeamConfig.objects.get(team=self.team)

    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/config/"

    def _activity(self) -> list[ActivityLog]:
        return list(ActivityLog.objects.filter(team_id=self.team.pk, scope="SignalTeamConfig").order_by("created_at"))

    def test_get_config_includes_default_slack_notification_channel(self):
        response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["default_slack_notification_channel"] is None
        assert data["default_autostart_priority"] == "P4"
        # Null until a team explicitly opts out; the guard treats null as autostart-on.
        assert data["autostart_enabled"] is None

    def test_get_config_lazily_creates_when_no_config_exists(self):
        self.config.delete()
        assert not SignalTeamConfig.objects.filter(team=self.team).exists()
        response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["default_autostart_priority"] == "P4"
        assert data["default_slack_notification_channel"] is None
        assert SignalTeamConfig.objects.filter(team=self.team).exists()

    def test_post_config_lazily_creates_when_no_config_exists(self):
        self.config.delete()
        assert not SignalTeamConfig.objects.filter(team=self.team).exists()
        response = self.client.post(
            self._url(),
            data={"default_slack_notification_channel": "C123|#posthog-signals"},
            format="json",
        )
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["default_slack_notification_channel"] == "C123|#posthog-signals"
        config = SignalTeamConfig.objects.get(team=self.team)
        assert config.default_slack_notification_channel == "C123|#posthog-signals"

    @parameterized.expand(
        [
            ("set", None, "C123|#posthog-signals", "C123|#posthog-signals"),
            ("clear", "C123|#posthog-signals", None, None),
        ]
    )
    def test_update_default_slack_notification_channel(self, _name, initial, sent, expected):
        if initial is not None:
            self.config.default_slack_notification_channel = initial
            self.config.save(update_fields=["default_slack_notification_channel"])
        response = self.client.post(
            self._url(),
            data={"default_slack_notification_channel": sent},
            format="json",
        )
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["default_slack_notification_channel"] == expected
        self.config.refresh_from_db()
        assert self.config.default_slack_notification_channel == expected

    def test_partial_update_preserves_default_autostart_priority(self):
        self.config.default_autostart_priority = "P2"
        self.config.save(update_fields=["default_autostart_priority"])
        response = self.client.post(
            self._url(),
            data={"default_slack_notification_channel": "C123|#posthog-signals"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        self.config.refresh_from_db()
        assert self.config.default_autostart_priority == "P2"
        assert self.config.default_slack_notification_channel == "C123|#posthog-signals"

    def test_get_config_includes_autostart_base_branches(self):
        self.config.autostart_base_branches = {"acme/web": "staging"}
        self.config.save(update_fields=["autostart_base_branches"])
        response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["autostart_base_branches"] == {"acme/web": "staging"}

    def test_update_autostart_base_branches_normalizes_and_persists(self):
        response = self.client.post(
            self._url(),
            # Mixed case key is lowercased; blank-branch entry is dropped.
            data={"autostart_base_branches": {"Acme/Web": "  staging  ", "acme/api": ""}},
            format="json",
        )
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["autostart_base_branches"] == {"acme/web": "staging"}
        self.config.refresh_from_db()
        assert self.config.autostart_base_branches == {"acme/web": "staging"}

    def test_update_autostart_base_branches_rejects_malformed_repo_key(self):
        response = self.client.post(
            self._url(),
            data={"autostart_base_branches": {"not-a-repo": "staging"}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "autostart_base_branches"

    def test_partial_update_preserves_autostart_base_branches(self):
        self.config.autostart_base_branches = {"acme/web": "staging"}
        self.config.save(update_fields=["autostart_base_branches"])
        response = self.client.post(
            self._url(),
            data={"default_slack_notification_channel": "C123|#posthog-signals"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        self.config.refresh_from_db()
        assert self.config.autostart_base_branches == {"acme/web": "staging"}

    @parameterized.expand(
        [
            ("disable", True, False),
            ("enable", False, True),
        ]
    )
    def test_update_autostart_enabled(self, _name, initial, sent):
        self.config.autostart_enabled = initial
        self.config.save(update_fields=["autostart_enabled"])
        response = self.client.post(self._url(), data={"autostart_enabled": sent}, format="json")
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["autostart_enabled"] is sent
        self.config.refresh_from_db()
        assert self.config.autostart_enabled is sent

    def test_get_config_defaults_daily_report_limit_fields(self):
        response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["max_reports_per_day"] is None
        assert data["reports_generated_today"] == 0
        assert data["daily_report_limit_reached"] is False

    @parameterized.expand(
        [
            ("set", None, 5, 5),
            ("clear", 5, None, None),
        ]
    )
    def test_update_max_reports_per_day(self, _name, initial, sent, expected):
        if initial is not None:
            self.config.max_reports_per_day = initial
            self.config.save(update_fields=["max_reports_per_day"])
        response = self.client.post(self._url(), data={"max_reports_per_day": sent}, format="json")
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["max_reports_per_day"] == expected
        self.config.refresh_from_db()
        assert self.config.max_reports_per_day == expected

    @parameterized.expand([("zero", 0), ("negative", -3), ("above_int4", 2147483648)])
    def test_update_max_reports_per_day_rejects_out_of_range(self, _name, sent):
        response = self.client.post(self._url(), data={"max_reports_per_day": sent}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["attr"] == "max_reports_per_day"

    def test_reports_generated_today_is_zero_without_a_limit(self):
        # No limit set: the count is never shown, so the serializer reports 0 without counting even
        # when visible reports exist today.
        SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, first_visible_at=datetime.now(UTC)
        )
        response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["max_reports_per_day"] is None
        assert data["reports_generated_today"] == 0

    def test_daily_report_limit_reached_reflects_todays_visible_reports(self):
        self.config.max_reports_per_day = 1
        self.config.save(update_fields=["max_reports_per_day"])
        SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, first_visible_at=datetime.now(UTC)
        )
        response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["reports_generated_today"] == 1
        assert data["daily_report_limit_reached"] is True

    def test_partial_update_preserves_autostart_enabled(self):
        # A team that turned autostart off must not have it silently re-enabled when it later
        # edits an unrelated field.
        self.config.autostart_enabled = False
        self.config.save(update_fields=["autostart_enabled"])
        response = self.client.post(
            self._url(),
            data={"default_slack_notification_channel": "C123|#posthog-signals"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        self.config.refresh_from_db()
        assert self.config.autostart_enabled is False

    # Each case starts from the model default, so the POST is the only change on the row.
    @parameterized.expand(
        [
            ("threshold", "default_autostart_priority", "P1", "project PR threshold", "changed", "P4", "P1"),
            ("pr_generation", "autostart_enabled", False, "PR generation", "created", None, False),
            (
                "slack_channel",
                "default_slack_notification_channel",
                "C123|#posthog-signals",
                "team Slack channel",
                "created",
                None,
                "C123|#posthog-signals",
            ),
            (
                "base_branches",
                "autostart_base_branches",
                {"acme/web": "staging"},
                "base branch overrides",
                "created",
                None,
                {"acme/web": "staging"},
            ),
        ]
    )
    def test_update_is_recorded_in_the_activity_log(self, _name, field, sent, label, action, before, after):
        response = self.client.post(self._url(), data={field: sent}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()

        entries = self._activity()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.activity == "updated"
        assert entry.item_id == str(self.config.id)
        assert entry.user == self.user
        assert entry.detail is not None
        assert entry.detail["changes"] == [
            {"type": "SignalTeamConfig", "action": action, "field": label, "before": before, "after": after}
        ]

    def test_reading_config_does_not_record_activity(self):
        # The viewset materializes a missing row on read. That is bookkeeping, so it must not
        # show up as whoever opened the settings having changed something.
        self.config.delete()
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert SignalTeamConfig.objects.filter(team=self.team).exists()
        assert self._activity() == []

    def test_create_carrying_a_nondefault_value_is_recorded_in_the_activity_log(self):
        # Slack onboarding sets a channel via update_or_create for teams whose row was never
        # materialized, so the row is created with the channel already set. That first choice
        # must still be audited even though it arrives as a create rather than an update.
        self.config.delete()
        set_default_slack_notification_channel(self.team.pk, "C123|#posthog-signals")

        entries = self._activity()
        assert len(entries) == 1
        assert entries[0].detail is not None
        assert entries[0].detail["changes"] == [
            {
                "type": "SignalTeamConfig",
                "action": "created",
                "field": "team Slack channel",
                "before": None,
                "after": "C123|#posthog-signals",
            }
        ]

    def test_resending_the_same_values_does_not_record_activity(self):
        self.client.post(self._url(), data={"default_autostart_priority": "P1"}, format="json")
        assert len(self._activity()) == 1

        response = self.client.post(self._url(), data={"default_autostart_priority": "P1"}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert len(self._activity()) == 1


class TestSignalTeamConfigSerializerValidation(SimpleTestCase):
    # No DB needed: these are field-level rejections that short-circuit in to_internal_value.
    # The endpoint wiring guard lives in TestSignalTeamConfigAPI.
    @parameterized.expand(
        [
            (
                "too_many_entries",
                {f"acme/repo{i}": "staging" for i in range(MAX_AUTOSTART_BASE_BRANCH_ENTRIES + 1)},
            ),
            ("oversized_repo_key", {"acme/" + "r" * 300: "staging"}),
        ]
    )
    def test_autostart_base_branches_rejects_oversized_input(self, _name, value):
        # Both cap the stored map and its full-copy activity-log row; without the bound a caller
        # with write access could append arbitrarily large rows by re-saving a huge map.
        serializer = SignalTeamConfigSerializer(data={"autostart_base_branches": value}, partial=True)
        assert not serializer.is_valid()
        assert "autostart_base_branches" in serializer.errors
