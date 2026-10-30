from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import OrganizationMembership
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.temporal.oauth import SANDBOX_OAUTH_APP_CLIENT_IDS

from products.signals.backend.agent_instructions import AGENT_STEERING_MAX_LENGTH, STEERING_FIELDS
from products.signals.backend.facade.api import set_default_slack_notification_channel
from products.signals.backend.implementation_repositories import MAX_IMPLEMENTATION_REPOSITORIES
from products.signals.backend.models import SignalReport, SignalTeamConfig
from products.signals.backend.serializers import MAX_AUTOSTART_BASE_BRANCH_ENTRIES, SignalTeamConfigSerializer
from products.signals.backend.views import SignalTeamConfigViewSet


class TestSignalTeamConfigAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.config = get_or_create_team_extension(self.team, SignalTeamConfig)

    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/signals/config/"

    def _activity(self) -> list[ActivityLog]:
        return list(ActivityLog.objects.filter(team_id=self.team.pk, scope="SignalTeamConfig").order_by("created_at"))

    @parameterized.expand([OrganizationMembership.Level.MEMBER, OrganizationMembership.Level.ADMIN])
    def test_project_member_can_save_and_clear_roles_independently(self, level: int) -> None:
        self.organization_membership.level = level
        self.organization_membership.save()
        initial = {field: f"Instructions for {role}." for role, field in STEERING_FIELDS.items()}
        response = self.client.post(self._url(), initial, format="json")
        assert response.status_code == 200, response.content
        assert all(response.json()[field] == text for field, text in initial.items())

        response = self.client.post(self._url(), {"research_instructions": ""}, format="json")
        assert response.status_code == 200, response.content
        saved = self.client.get(self._url()).json()
        assert saved["research_instructions"] == ""
        assert saved["scout_instructions"] == initial["scout_instructions"]
        assert saved["implementation_instructions"] == initial["implementation_instructions"]
        entries = self._activity()
        assert len(entries) == 2
        assert entries[0].user == self.user
        assert entries[0].detail is not None
        assert {change["field"] for change in entries[0].detail["changes"]} == {
            "scout instructions",
            "research instructions",
            "implementation instructions",
        }

    @parameterized.expand([*STEERING_FIELDS.values(), "implementation_repositories"])
    def test_non_member_cannot_change_protected_settings(self, field: str) -> None:
        self.organization_membership.delete()
        value = ["example/assets"] if field == "implementation_repositories" else "Check product intent."
        response = self.client.post(self._url(), {field: value}, format="json")
        assert response.status_code == 403, response.content

    @parameterized.expand([*STEERING_FIELDS.values(), "implementation_repositories"])
    def test_sandbox_cannot_change_protected_settings(self, field: str) -> None:
        application = OAuthApplication.objects.create(
            client_id=sorted(SANDBOX_OAUTH_APP_CLIENT_IDS)[0],
            name="Settings test",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm=OAuthApplication.RS256_ALGORITHM,
        )
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token="pha_settings_test_token",
            scope="task:read task:write internal_run:read",
            expires=timezone.now() + timedelta(hours=1),
            scoped_teams=[self.team.id],
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.token}")
        value = ["example/assets"] if field == "implementation_repositories" else "Check product intent."
        response = self.client.post(self._url(), {field: value}, format="json")
        assert response.status_code == 403, response.content
        assert (
            response.json()["detail"]
            == "Task agents cannot modify steering instructions or implementation repositories."
        )
        assert self.client.get(self._url()).status_code == 200
        self.config.refresh_from_db()
        assert getattr(self.config, field) in (None, [])

    def test_steering_save_preserves_a_concurrent_autonomy_change(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        stale_config = SignalTeamConfig.objects.get(pk=self.config.pk)
        self.config.autostart_enabled = False
        self.config.save(update_fields=["autostart_enabled"])

        with patch.object(SignalTeamConfigViewSet, "_get_config", return_value=stale_config):
            response = self.client.post(self._url(), {"research_instructions": "Check product intent."}, format="json")
        assert response.status_code == 200, response.content
        self.config.refresh_from_db()
        assert self.config.autostart_enabled is False
        assert self.config.research_instructions == "Check product intent."

    def test_get_config_includes_default_settings(self):
        response = self.client.get(self._url())
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["default_slack_notification_channel"] is None
        for field in STEERING_FIELDS.values():
            assert getattr(self.config, field) is None
            assert data[field] == ""
        assert data["default_autostart_priority"] == "P4"
        # Null until a team explicitly opts out; the guard treats null as autostart-on.
        assert data["autostart_enabled"] is None
        assert data["anomaly_scoring_enabled"] is True

    @parameterized.expand([("covered", True), ("not_covered", False)])
    def test_anomaly_scoring_available_follows_the_scoring_payload(self, _name, covered):
        payload = {"enabled": True, "organization_ids": [str(self.organization.id)] if covered else []}
        with patch("products.signals.backend.serializers.read_payload", return_value=payload):
            data = self.client.get(self._url()).json()

        assert data["anomaly_scoring_available"] is covered

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
            ("set", None, "C123|#posthog-signals", False, "C123|#posthog-signals", False),
            ("set_with_workspace", None, "C123|#posthog-signals", True, "C123|#posthog-signals", True),
            ("change_without_workspace", "C999|#old", "C123|#posthog-signals", False, "C123|#posthog-signals", False),
            ("clear", "C123|#posthog-signals", None, False, None, False),
        ]
    )
    def test_update_default_slack_notification_channel(
        self, _name, initial, sent, send_workspace, expected, expect_bound
    ):
        workspace = Integration.objects.create(team=self.team, kind="slack", integration_id="T123", config={})
        if initial is not None:
            self.config.default_slack_notification_channel = initial
            self.config.default_slack_notification_integration_id = workspace.id
            self.config.save(
                update_fields=["default_slack_notification_channel", "default_slack_notification_integration_id"]
            )
        payload: dict = {"default_slack_notification_channel": sent}
        if send_workspace:
            payload["default_slack_notification_integration"] = workspace.id
        response = self.client.post(self._url(), data=payload, format="json")
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["default_slack_notification_channel"] == expected
        self.config.refresh_from_db()
        assert self.config.default_slack_notification_channel == expected
        assert self.config.default_slack_notification_integration_id == (workspace.id if expect_bound else None)

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

    @parameterized.expand(
        [
            ("enable", {"pull_request_label_enabled": True, "pull_request_label": "ours"}, True, "ours"),
            ("clear_name", {"pull_request_label": ""}, False, None),
        ]
    )
    def test_update_pull_request_label(self, _name, sent, expected_enabled, expected_label):
        response = self.client.post(self._url(), data=sent, format="json")
        data = response.json()
        assert response.status_code == status.HTTP_200_OK, data
        assert data["pull_request_label_enabled"] is expected_enabled
        assert data["pull_request_label"] == expected_label
        self.config.refresh_from_db()
        assert self.config.pull_request_label_enabled is expected_enabled
        assert self.config.pull_request_label == expected_label

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
            (
                "pr_state",
                "default_open_pull_request_ready",
                True,
                "PRs open as",
                "changed",
                False,
                True,
            ),
            ("anomaly_scoring", "anomaly_scoring_enabled", False, "anomaly scoring", "changed", True, False),
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
        set_default_slack_notification_channel(self.team.pk, "C123|#posthog-signals", integration_id=None)

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

    @parameterized.expand(
        [
            (
                "reachable_entries_are_normalized",
                [],
                ["Acme/Assets", "acme/assets", "acme/docs"],
                status.HTTP_200_OK,
                ["acme/assets", "acme/docs"],
            ),
            ("unreachable_entry_is_rejected", [], ["acme/assets", "other/secret"], status.HTTP_400_BAD_REQUEST, []),
            # A stored entry that lost access can still be removed, and kept, without a fresh check.
            ("stored_entry_skips_the_check", ["acme/gone"], ["acme/gone"], status.HTTP_200_OK, ["acme/gone"]),
            ("stored_entry_can_be_removed", ["acme/gone"], [], status.HTTP_200_OK, []),
        ]
    )
    def test_update_implementation_repositories_checks_new_entries_against_the_installation(
        self, _name: str, stored: list[str], sent: list[str], expected_status: int, expected: list[str]
    ) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.config.implementation_repositories = stored
        self.config.save(update_fields=["implementation_repositories"])
        Integration.objects.create(team=self.team, kind="github", config={"account": {"name": "acme"}})

        with patch.object(
            GitHubIntegration,
            "list_all_cached_repositories",
            return_value=[{"full_name": "acme/assets"}, {"full_name": "acme/docs"}],
        ):
            response = self.client.post(self._url(), {"implementation_repositories": sent}, format="json")

        assert response.status_code == expected_status, response.content
        self.config.refresh_from_db()
        assert self.config.implementation_repositories == (
            expected if expected_status == status.HTTP_200_OK else stored
        )


class TestSignalTeamConfigSerializerValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("not_owner_slash_repo", ["assets"]),
            ("too_many_entries", [f"acme/repo{i}" for i in range(MAX_IMPLEMENTATION_REPOSITORIES + 1)]),
        ]
    )
    def test_implementation_repositories_rejects_malformed_input(self, _name: str, value: list[str]) -> None:
        serializer = SignalTeamConfigSerializer(data={"implementation_repositories": value}, partial=True)
        assert not serializer.is_valid()
        assert "implementation_repositories" in serializer.errors

    @parameterized.expand(list(STEERING_FIELDS.values()))
    def test_steering_rejects_oversized_instructions(self, field: str) -> None:
        serializer = SignalTeamConfigSerializer(data={field: "x" * AGENT_STEERING_MAX_LENGTH}, partial=True)
        assert serializer.is_valid(), serializer.errors
        serializer = SignalTeamConfigSerializer(data={field: "x" * (AGENT_STEERING_MAX_LENGTH + 1)}, partial=True)
        assert not serializer.is_valid()
        assert field in serializer.errors

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

    @parameterized.expand([("blank", ""), ("whitespace", "   "), ("null", None)])
    def test_pull_request_label_normalizes_an_empty_name_to_null(self, _name, value):
        # One stored shape for "use the default", so a team that clears the box does not save a
        # name GitHub would refuse.
        serializer = SignalTeamConfigSerializer(data={"pull_request_label": value}, partial=True)
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["pull_request_label"] is None

    def test_pull_request_label_rejects_a_name_github_would_refuse(self):
        serializer = SignalTeamConfigSerializer(data={"pull_request_label": "l" * 51}, partial=True)
        assert not serializer.is_valid()
        assert "pull_request_label" in serializer.errors
