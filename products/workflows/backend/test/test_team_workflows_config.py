from posthog.test.base import APIBaseTest

from django.contrib.admin import AdminSite
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models import OrganizationMembership

from products.workflows.backend.admin.team_workflows_config_admin import TeamWorkflowsConfigAdmin
from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig


class TestTeamWorkflowsConfigAdmin(SimpleTestCase):
    def setUp(self) -> None:
        self.admin = TeamWorkflowsConfigAdmin(TeamWorkflowsConfig, AdminSite())
        self.request = RequestFactory().get("/admin/workflows/teamworkflowsconfig/")

    def test_team_is_editable_only_when_adding_a_config(self) -> None:
        assert self.admin.get_readonly_fields(self.request) == ()
        assert self.admin.get_readonly_fields(self.request, TeamWorkflowsConfig()) == ("team",)

    def test_config_cannot_be_deleted(self) -> None:
        assert self.admin.has_delete_permission(self.request) is False
        assert self.admin.has_delete_permission(self.request, TeamWorkflowsConfig()) is False


class TestTeamWorkflowsConfig(APIBaseTest):
    """End-to-end coverage of the ``workflows_config`` nested field on the team API.

    Mirrors the pattern used for other team-extension configs (e.g. customer_analytics_config,
    session_replay_config) so that future regressions in the diff / update plumbing get caught
    on the team API path rather than only by the plugin-server consumer of the config.
    """

    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.url = f"/api/environments/{self.team.id}/"

    def test_defaults_to_capture_disabled_when_no_extension_row_exists(self) -> None:
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["workflows_config"] == {
            "capture_workflows_engagement_events": False,
            "email_tracking_consent_mode": "off",
            "workflow_task_rate_limit_per_day": None,
            "workflow_task_team_rate_limit_per_day": None,
            "marketing_frequency_cap_max_messages": None,
            "marketing_frequency_cap_window_days": None,
        }

    def test_patch_enables_capture(self) -> None:
        # APIBaseTest.setUp may trigger the workflows_config cached_property (which calls
        # get_or_create_team_extension) so the extension row can already exist with the default
        # value. Either way, the patch must end with the row present and capture enabled.
        response = self.client.patch(self.url, {"workflows_config": {"capture_workflows_engagement_events": True}})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["workflows_config"]["capture_workflows_engagement_events"] is True

        row = TeamWorkflowsConfig.objects.get(team=self.team)
        assert row.capture_workflows_engagement_events is True

    def test_patch_can_toggle_capture_back_off(self) -> None:
        self.client.patch(self.url, {"workflows_config": {"capture_workflows_engagement_events": True}})
        response = self.client.patch(self.url, {"workflows_config": {"capture_workflows_engagement_events": False}})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["workflows_config"]["capture_workflows_engagement_events"] is False
        assert TeamWorkflowsConfig.objects.get(team=self.team).capture_workflows_engagement_events is False

    def test_patch_with_other_team_fields_does_not_disturb_workflows_config(self) -> None:
        self.client.patch(self.url, {"workflows_config": {"capture_workflows_engagement_events": True}})

        response = self.client.patch(self.url, {"name": "renamed team"})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["workflows_config"]["capture_workflows_engagement_events"] is True
        assert TeamWorkflowsConfig.objects.get(team=self.team).capture_workflows_engagement_events is True

    def test_patch_sets_email_tracking_consent_mode(self) -> None:
        response = self.client.patch(self.url, {"workflows_config": {"email_tracking_consent_mode": "opt_in"}})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["workflows_config"]["email_tracking_consent_mode"] == "opt_in"
        assert TeamWorkflowsConfig.objects.get(team=self.team).email_tracking_consent_mode == "opt_in"

    def test_patch_rejects_unknown_email_tracking_consent_mode(self) -> None:
        response = self.client.patch(self.url, {"workflows_config": {"email_tracking_consent_mode": "sometimes"}})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "workflows_config__email_tracking_consent_mode"

    def test_patch_rejects_non_boolean_capture_workflows_engagement_events(self) -> None:
        response = self.client.patch(
            self.url, {"workflows_config": {"capture_workflows_engagement_events": "yes please"}}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # DRF nested-serializer validation surfaces the inner field path, not the parent name.
        assert response.json()["attr"] == "workflows_config__capture_workflows_engagement_events"

    def test_patch_ignores_unknown_keys_in_workflows_config(self) -> None:
        # ModelSerializer silently drops fields not in Meta.fields — this regression-tests that
        # behaviour so we notice if a future serializer change starts rejecting unknown keys
        # (which would break clients that send forward-compatible payloads).
        response = self.client.patch(
            self.url, {"workflows_config": {"capture_workflows_engagement_events": True, "future_flag": "ignored"}}
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["workflows_config"] == {
            "capture_workflows_engagement_events": True,
            "email_tracking_consent_mode": "off",
            "workflow_task_rate_limit_per_day": None,
            "workflow_task_team_rate_limit_per_day": None,
            "marketing_frequency_cap_max_messages": None,
            "marketing_frequency_cap_window_days": None,
        }

    @parameterized.expand(
        [
            ["count with no saved window", None, {"marketing_frequency_cap_max_messages": 3}, 400, (None, None)],
            ["count change on a saved cap", (2, 7), {"marketing_frequency_cap_max_messages": 3}, 200, (3, 7)],
            ["one field cleared on a saved cap", (2, 7), {"marketing_frequency_cap_window_days": None}, 400, (2, 7)],
            [
                "both fields cleared",
                (2, 7),
                {"marketing_frequency_cap_max_messages": None, "marketing_frequency_cap_window_days": None},
                200,
                (None, None),
            ],
        ]
    )
    def test_patch_frequency_cap_needs_both_fields_or_neither(
        self,
        _name: str,
        saved: tuple[int, int] | None,
        patch: dict,
        expected_status: int,
        expected_cap: tuple[int | None, int | None],
    ) -> None:
        if saved:
            response = self.client.patch(
                self.url,
                {
                    "workflows_config": {
                        "marketing_frequency_cap_max_messages": saved[0],
                        "marketing_frequency_cap_window_days": saved[1],
                    }
                },
            )
            assert response.status_code == status.HTTP_200_OK

        response = self.client.patch(self.url, {"workflows_config": patch})

        assert response.status_code == expected_status, response.json()
        stored = (
            TeamWorkflowsConfig.objects.filter(team=self.team)
            .values_list("marketing_frequency_cap_max_messages", "marketing_frequency_cap_window_days")
            .first()
        )
        assert (stored or (None, None)) == expected_cap
