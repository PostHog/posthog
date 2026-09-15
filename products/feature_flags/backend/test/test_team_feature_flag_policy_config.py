from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import OrganizationMembership

from products.feature_flags.backend.models.team_feature_flag_policy_config import TeamFeatureFlagPolicyConfig


class TestTeamFeatureFlagPolicyConfig(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.url = f"/api/environments/{self.team.id}/"

    def test_defaults_to_tags_not_required(self) -> None:
        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["feature_flag_policy_config"] == {"require_tags": False}

    def test_admin_can_toggle_require_tags(self) -> None:
        response = self.client.patch(self.url, {"feature_flag_policy_config": {"require_tags": True}})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["feature_flag_policy_config"]["require_tags"] is True
        assert TeamFeatureFlagPolicyConfig.objects.get(team=self.team).require_tags is True

        response = self.client.patch(self.url, {"feature_flag_policy_config": {"require_tags": False}})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["feature_flag_policy_config"]["require_tags"] is False
        assert TeamFeatureFlagPolicyConfig.objects.get(team=self.team).require_tags is False

    def test_member_cannot_toggle_require_tags(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.patch(self.url, {"feature_flag_policy_config": {"require_tags": True}})

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert TeamFeatureFlagPolicyConfig.objects.get(team=self.team).require_tags is False

    def test_patching_other_team_fields_leaves_require_tags_alone(self) -> None:
        self.client.patch(self.url, {"feature_flag_policy_config": {"require_tags": True}})

        response = self.client.patch(self.url, {"name": "renamed team"})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["feature_flag_policy_config"]["require_tags"] is True
