from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models import User

from products.tasks.backend.models import UserTasksConfig

DEFAULTS = {
    "custom_instructions": "",
    "simplified_technical_english": False,
    "start_in_plan_mode": False,
    "auto_publish_cloud_runs": False,
}


class TestAgentPreferencesAPI(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/tasks/@me/agent_preferences/"

    def test_returns_defaults_when_nothing_is_stored(self):
        response = self.client.get(self._url())

        assert response.status_code == 200
        assert response.json() == DEFAULTS

    def test_partial_updates_keep_the_other_stored_values(self):
        self.client.post(self._url(), {"custom_instructions": "Keep pull requests small."}, format="json")
        response = self.client.post(self._url(), {"start_in_plan_mode": True}, format="json")

        assert response.status_code == 200
        assert response.json() == {
            **DEFAULTS,
            "custom_instructions": "Keep pull requests small.",
            "start_in_plan_mode": True,
        }
        assert self.client.get(self._url()).json() == response.json()

    def test_update_keeps_the_stored_model_preference(self):
        UserTasksConfig.objects.for_team(self.team.id).create(
            team=self.team, user=self.user, ai_run_preferences={"runtime_adapter": "claude", "model": "m"}
        )

        self.client.post(self._url(), {"simplified_technical_english": True}, format="json")

        config = UserTasksConfig.objects.for_team(self.team.id).get(user=self.user)
        assert config.ai_run_preferences == {"runtime_adapter": "claude", "model": "m"}
        assert config.agent_preferences is not None
        assert config.agent_preferences["simplified_technical_english"] is True

    def test_another_users_preferences_do_not_leak(self):
        other = User.objects.create_and_join(self.organization, "other@example.com", "password")
        UserTasksConfig.objects.for_team(self.team.id).create(
            team=self.team, user=other, agent_preferences={"custom_instructions": "Theirs only."}
        )

        assert self.client.get(self._url()).json() == DEFAULTS

    @parameterized.expand(
        [
            ("instructions_over_the_limit", {"custom_instructions": "x" * 10_001}),
            ("a_flag_that_is_not_a_boolean", {"start_in_plan_mode": "sometimes"}),
        ]
    )
    def test_rejects_invalid_values(self, _name: str, payload: dict):
        response = self.client.post(self._url(), payload, format="json")

        assert response.status_code == 400
        assert self.client.get(self._url()).json() == DEFAULTS
