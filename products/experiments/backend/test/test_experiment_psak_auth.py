from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.test.api_keys import create_project_secret_api_key

from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _create_experiment(team: Team, name: str, flag_key: str) -> Experiment:
    flag = FeatureFlag.objects.create(
        team=team,
        key=flag_key,
        filters={
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "multivariate": {
                "variants": [
                    {"key": "control", "name": "Control", "rollout_percentage": 50},
                    {"key": "test", "name": "Test", "rollout_percentage": 50},
                ]
            },
        },
    )
    return Experiment.objects.create(team=team, name=name, feature_flag=flag)


class TestExperimentPSAKAuth(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.experiment = _create_experiment(self.team, "First experiment", "psak-flag-1")
        self.other_experiment = _create_experiment(self.team, "Second experiment", "psak-flag-2")
        _, self.token = create_project_secret_api_key(self.team, scopes=["experiment:read"])
        # Log out the test client so only the PSAK header authenticates requests
        self.client.logout()

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_psak_can_list_experiments(self) -> None:
        response = self.client.get(
            f"/api/projects/{self.team.id}/experiments/",
            headers=self._auth_headers(self.token),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        data = response.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(
            {result["name"] for result in data["results"]},
            {"First experiment", "Second experiment"},
        )
        # Per-user access levels are meaningless for a service credential
        self.assertIsNone(data["results"][0]["user_access_level"])

    def test_psak_can_retrieve_experiment(self) -> None:
        response = self.client.get(
            f"/api/projects/{self.team.id}/experiments/{self.experiment.id}/",
            headers=self._auth_headers(self.token),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        data = response.json()
        self.assertEqual(data["id"], self.experiment.id)
        self.assertEqual(data["feature_flag_key"], "psak-flag-1")
        self.assertIsNone(data["user_access_level"])

    @parameterized.expand(
        [
            # PSAK must only authorize list/retrieve — writes, lifecycle actions, and
            # non-allowlisted reads all return 403, whatever scopes the key carries.
            ("create", "post", "", {"name": "New experiment", "feature_flag_key": "psak-new-flag"}),
            ("partial_update", "patch", "{id}/", {"name": "Renamed"}),
            ("launch", "post", "{id}/launch/", None),
            ("flag_cleanup_task", "get", "{id}/flag_cleanup_task/", None),
            ("stats", "get", "stats/", None),
        ]
    )
    def test_psak_blocked_on_non_allowlisted_actions(
        self, _name: str, method: str, path_suffix: str, body: dict | None
    ) -> None:
        _, wide_token = create_project_secret_api_key(
            self.team, label="wide", scopes=["experiment:read", "experiment:write", "activity_log:read"]
        )
        path_suffix = path_suffix.format(id=self.experiment.id)

        response = getattr(self.client, method)(
            f"/api/projects/{self.team.id}/experiments/{path_suffix}",
            data=body,
            content_type="application/json",
            headers=self._auth_headers(wide_token),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)

    def test_psak_without_experiment_scope_forbidden(self) -> None:
        _, token = create_project_secret_api_key(self.team, label="wrong-scope", scopes=["feature_flag:read"])

        response = self.client.get(
            f"/api/projects/{self.team.id}/experiments/",
            headers=self._auth_headers(token),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)

    def test_psak_from_another_team_forbidden(self) -> None:
        other_team = self.create_team_with_organization(organization=self.organization)
        _, other_token = create_project_secret_api_key(other_team, label="other-team", scopes=["experiment:read"])

        response = self.client.get(
            f"/api/projects/{self.team.id}/experiments/",
            headers=self._auth_headers(other_token),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)

    @parameterized.expand(
        [
            ("read_allowed", ["experiment:read"], status.HTTP_201_CREATED),
            ("write_rejected", ["experiment:write"], status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_key_creation_allowlist(self, _name: str, scopes: list[str], expected_status: int) -> None:
        self.client.force_login(self.user)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/project_secret_api_keys",
            {"label": "sync key", "scopes": scopes},
        )

        self.assertEqual(response.status_code, expected_status, response.content)
