from posthog.test.base import APIBaseTest

from posthog.models import Team
from posthog.models.integration import Integration

from products.slack_app.backend.models import SlackSettings
from products.slack_app.backend.services.slack_app_home import _resolve_run_defaults_state
from products.tasks.backend.models import TeamTasksConfig

WORKSPACE = "TWORKSPACE"


class TestRunDefaultsCardRouting(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team_b = Team.objects.create(organization=self.organization, name="B")
        self.int_a = Integration.objects.create(
            team=self.team, kind="slack", integration_id=WORKSPACE, sensitive_config={"access_token": "x"}
        )
        self.int_b = Integration.objects.create(
            team=self.team_b, kind="slack", integration_id=WORKSPACE, sensitive_config={"access_token": "x"}
        )
        TeamTasksConfig.objects.update_or_create(
            team=self.team,
            defaults={"ai_run_preferences": {"runtime_adapter": "claude", "model": "model-a"}},
        )
        TeamTasksConfig.objects.update_or_create(
            team=self.team_b,
            defaults={"ai_run_preferences": {"runtime_adapter": "claude", "model": "model-b"}},
        )

    # The card must never read a project outside the viewer's accessible set — the
    # install's own team and even the workspace default can both point at a project
    # the viewer can't reach, whose configuration would otherwise leak (and whose
    # default their runs would not use anyway).
    def test_card_reads_the_routed_accessible_project_not_the_installs(self):
        SlackSettings.objects.create(slack_workspace_id=WORKSPACE, slack_user_id=None, default_integration=self.int_b)
        state = _resolve_run_defaults_state(self.int_b, "U1", accessible=[self.int_a])
        assert state.model == "model-a"
        assert state.settings_url is not None and f"/project/{self.team.id}/" in state.settings_url

    def test_card_renders_empty_without_an_accessible_project(self):
        state = _resolve_run_defaults_state(self.int_b, "U1", accessible=[])
        assert state.model is None
        assert state.settings_url is None
