from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.organization import OrganizationMembership
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team import Team
from posthog.models.utils import hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _make_psak(team, label="psak", scopes=None):
    # Token must match _SECRET_API_KEY_RE = r"^phs_[a-zA-Z0-9]+$", so only alphanumerics after phs_.
    suffix = "".join(c for c in label if c.isalnum())
    token = "phs_" + ("a" * 35) + suffix
    psak = ProjectSecretAPIKey.objects.create(
        team=team,
        label=label,
        mask_value=f"phs_...{suffix[:4]}",
        secure_value=hash_key_value(token),
        scopes=["experiment:read"] if scopes is None else scopes,
    )
    return token, psak


class TestExperimentPSAKScopeAssignment(APIBaseTest):
    """experiment:read must be assignable to a project secret API key."""

    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def test_experiment_read_scope_can_be_assigned(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "warehouse sync", "scopes": ["experiment:read"]},
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert response.json()["scopes"] == ["experiment:read"]

    def test_experiment_write_scope_is_still_rejected(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "writer", "scopes": ["experiment:write"]},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "can not be assigned" in response.json()["detail"]


class TestExperimentViewSetPSAKAuth(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.flag = FeatureFlag.objects.create(team=self.team, key="psak-experiment-flag", created_by=self.user)
        self.experiment = Experiment.objects.create(
            team=self.team,
            name="PSAK readable experiment",
            feature_flag=self.flag,
            created_by=self.user,
        )
        # Log out the test client so only the PSAK header authenticates requests
        self.client.logout()

    def _auth_headers(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_psak_can_list_experiments(self):
        token, _ = _make_psak(self.team, label="listkey")

        response = self.client.get(
            f"/api/projects/{self.team.id}/experiments/",
            **self._auth_headers(token),
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert [item["name"] for item in response.json()["results"]] == ["PSAK readable experiment"]

    def test_psak_can_retrieve_experiment(self):
        token, _ = _make_psak(self.team, label="retrievekey")

        response = self.client.get(
            f"/api/projects/{self.team.id}/experiments/{self.experiment.id}/",
            **self._auth_headers(token),
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["name"] == "PSAK readable experiment"

    def test_psak_list_ignores_object_level_access_controls(self):
        # A PSAK authenticates as a synthetic user that has neither a membership nor a role, so
        # UserAccessControl cannot evaluate it. Object-level RBAC therefore does not apply, matching
        # AccessControlPermission.has_object_permission. Before the routing guard this raised a
        # TypeError instead, because the list filter passed the synthetic user into a created_by lookup.
        AccessControl.objects.create(
            team=self.team,
            resource="experiment",
            resource_id=str(self.experiment.id),
            access_level="none",
        )
        token, _ = _make_psak(self.team, label="rbackey")

        response = self.client.get(
            f"/api/projects/{self.team.id}/experiments/",
            **self._auth_headers(token),
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert [item["id"] for item in response.json()["results"]] == [self.experiment.id]

    def test_psak_cannot_create_experiment(self):
        token, _ = _make_psak(self.team, label="createkey")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            data={"name": "nope", "feature_flag_key": "nope"},
            content_type="application/json",
            **self._auth_headers(token),
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content

    def test_psak_cannot_update_experiment(self):
        token, _ = _make_psak(self.team, label="updatekey")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{self.experiment.id}/",
            data={"name": "renamed"},
            content_type="application/json",
            **self._auth_headers(token),
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content

    def test_psak_cannot_reach_non_read_actions(self):
        # psak_allowed_actions is an allowlist, so custom read actions stay closed even though
        # they only require experiment:read.
        token, _ = _make_psak(self.team, label="actionkey")

        response = self.client.get(
            f"/api/projects/{self.team.id}/experiments/{self.experiment.id}/flag_cleanup_target/",
            **self._auth_headers(token),
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content

    def test_psak_without_experiment_scope_is_rejected(self):
        token, _ = _make_psak(self.team, label="wrongscopekey", scopes=["endpoint:read"])

        response = self.client.get(
            f"/api/projects/{self.team.id}/experiments/",
            **self._auth_headers(token),
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content

    def test_psak_cannot_read_another_projects_experiments(self):
        other_team = Team.objects.create(organization=self.organization, name="other")
        token, _ = _make_psak(self.team, label="otherteamkey")

        response = self.client.get(
            f"/api/projects/{other_team.id}/experiments/",
            **self._auth_headers(token),
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
