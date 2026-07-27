from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import OrganizationMembership

from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig


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
        assert response.json()["workflows_config"] == {"capture_workflows_engagement_events": False}

    def test_patch_enables_capture(self) -> None:
        # APIBaseTest.setUp may trigger the workflows_config cached_property (which calls
        # get_or_create_team_extension) so the extension row can already exist with the default
        # value. Either way, the patch must end with the row present and capture enabled.
        response = self.client.patch(self.url, {"workflows_config": {"capture_workflows_engagement_events": True}})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["workflows_config"] == {"capture_workflows_engagement_events": True}

        row = TeamWorkflowsConfig.objects.get(team=self.team)
        assert row.capture_workflows_engagement_events is True

    def test_patch_can_toggle_capture_back_off(self) -> None:
        self.client.patch(self.url, {"workflows_config": {"capture_workflows_engagement_events": True}})
        response = self.client.patch(self.url, {"workflows_config": {"capture_workflows_engagement_events": False}})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["workflows_config"] == {"capture_workflows_engagement_events": False}
        assert TeamWorkflowsConfig.objects.get(team=self.team).capture_workflows_engagement_events is False

    def test_patch_with_other_team_fields_does_not_disturb_workflows_config(self) -> None:
        self.client.patch(self.url, {"workflows_config": {"capture_workflows_engagement_events": True}})

        response = self.client.patch(self.url, {"name": "renamed team"})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["workflows_config"] == {"capture_workflows_engagement_events": True}
        assert TeamWorkflowsConfig.objects.get(team=self.team).capture_workflows_engagement_events is True

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
        assert response.json()["workflows_config"] == {"capture_workflows_engagement_events": True}
