import pytest

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.models import SlackSettings, SlackThreadTaskMapping
from products.slack_app.backend.services.integration_resolver import load_integrations

WORKSPACE = "T_WS"
SLACK_USER = "U001"


class TestResolveIntegration:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Org")
        self.team_a = Team.objects.create(organization=self.organization, name="A")
        self.team_b = Team.objects.create(organization=self.organization, name="B")
        # team_c lives in a separate org the user has no membership in.
        self.other_org = Organization.objects.create(name="Other")
        self.team_c = Team.objects.create(organization=self.other_org, name="C")

        self.user = User.objects.create(email="dev@example.com", distinct_id="u-1")
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)

        self.integration_a = self._mk_integration(self.team_a)
        self.integration_b = self._mk_integration(self.team_b)
        self.integration_c = self._mk_integration(self.team_c)
        # Different workspace; should never match the WORKSPACE-scoped lookups.
        self.integration_other_workspace = Integration.objects.create(
            team=self.team_a,
            kind="slack-posthog-code",
            integration_id="T_OTHER",
            sensitive_config={"access_token": "xoxb-other"},
        )

    def _mk_integration(self, team: Team) -> Integration:
        return Integration.objects.create(
            team=team,
            kind="slack-posthog-code",
            integration_id=WORKSPACE,
            sensitive_config={"access_token": "xoxb"},
        )

    def _workspace_integrations(self) -> list[Integration]:
        return list(
            Integration.objects.filter(kind="slack-posthog-code", integration_id=WORKSPACE).select_related(
                "team", "team__organization"
            )
        )

    def test_thread_mapping_wins_over_everything(self):
        from products.tasks.backend.models import Task, TaskRun

        task = Task.objects.create(team=self.team_b, title="t")
        task_run = TaskRun.objects.create(team=self.team_b, task=task)
        SlackThreadTaskMapping.objects.create(
            team=self.team_b,
            integration=self.integration_b,
            slack_workspace_id=WORKSPACE,
            channel="C1",
            thread_ts="123.456",
            task=task,
            task_run=task_run,
            mentioning_slack_user_id=SLACK_USER,
        )
        # Even with an unrelated user_default pointing at A, the thread mapping wins.
        SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id=WORKSPACE,
            slack_user_id=SLACK_USER,
        )

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack-posthog-code"],
            slack_user_id=SLACK_USER,
            user=self.user,
            channel="C1",
            thread_ts="123.456",
        )

        assert result.source == "thread"
        assert result.integration == self.integration_b

    def test_user_default_used_when_accessible(self):
        SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id=WORKSPACE,
            slack_user_id=SLACK_USER,
        )

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack-posthog-code"],
            slack_user_id=SLACK_USER,
            user=self.user,
        )

        assert result.source == "user_default"
        assert result.integration == self.integration_a

    def test_user_default_ignored_when_target_no_longer_accessible(self):
        # Default points at team_c, which the user has no membership in.
        SlackSettings.objects.create(
            default_integration=self.integration_c,
            slack_workspace_id=WORKSPACE,
            slack_user_id=SLACK_USER,
        )

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack-posthog-code"],
            slack_user_id=SLACK_USER,
            user=self.user,
        )

        # Falls through past user_default: A and B remain accessible → picker.
        assert result.source == "needs_picker"
        assert {i.id for i in result.candidates} == {self.integration_a.id, self.integration_b.id}

    def test_user_default_wins_over_workspace_default(self):
        SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id=WORKSPACE,
            slack_user_id=None,  # workspace-wide
        )
        SlackSettings.objects.create(
            default_integration=self.integration_b,
            slack_workspace_id=WORKSPACE,
            slack_user_id=SLACK_USER,
        )

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack-posthog-code"],
            slack_user_id=SLACK_USER,
            user=self.user,
        )

        assert result.source == "user_default"
        assert result.integration == self.integration_b

    def test_workspace_default_used_when_no_user_row(self):
        SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id=WORKSPACE,
            slack_user_id=None,
        )

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack-posthog-code"],
            slack_user_id=SLACK_USER,
            user=self.user,
        )

        assert result.source == "workspace_default"
        assert result.integration == self.integration_a

    def test_workspace_default_ignored_when_target_not_accessible(self):
        # Workspace default points at team_c — the user has no access.
        SlackSettings.objects.create(
            default_integration=self.integration_c,
            slack_workspace_id=WORKSPACE,
            slack_user_id=None,
        )

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack-posthog-code"],
            slack_user_id=SLACK_USER,
            user=self.user,
        )

        # Falls through to candidate selection.
        assert result.source == "needs_picker"
        assert {i.id for i in result.candidates} == {self.integration_a.id, self.integration_b.id}

    def test_sole_candidate_auto_used(self):
        # Remove integration B so only A is accessible to the user in this workspace.
        self.integration_b.delete()

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack-posthog-code"],
            slack_user_id=SLACK_USER,
            user=self.user,
        )

        assert result.source == "sole_candidate"
        assert result.integration == self.integration_a

    def test_picker_with_multiple_candidates(self):
        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack-posthog-code"],
            slack_user_id=SLACK_USER,
            user=self.user,
        )

        assert result.integration is None
        assert result.source == "needs_picker"
        assert {i.id for i in result.candidates} == {self.integration_a.id, self.integration_b.id}

    def test_unresolved_user_falls_back_to_full_candidates(self):
        # user=None is the webhook routing layer's call: skip accessibility filtering
        # and trust saved routing rows. Without any defaults, every workspace
        # integration becomes a candidate.
        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack-posthog-code"],
            slack_user_id=SLACK_USER,
            user=None,
        )

        assert result.integration is None
        assert result.source == "needs_picker"
        assert {i.id for i in result.candidates} == {
            self.integration_a.id,
            self.integration_b.id,
            self.integration_c.id,
        }

    def test_unresolved_user_still_honors_user_default(self):
        SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id=WORKSPACE,
            slack_user_id=SLACK_USER,
        )

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack-posthog-code"],
            slack_user_id=SLACK_USER,
            user=None,
        )

        assert result.source == "user_default"
        assert result.integration == self.integration_a

    def test_unresolved_user_still_honors_thread_mapping(self):
        from products.tasks.backend.models import Task, TaskRun

        task = Task.objects.create(team=self.team_b, title="t")
        task_run = TaskRun.objects.create(team=self.team_b, task=task)
        SlackThreadTaskMapping.objects.create(
            team=self.team_b,
            integration=self.integration_b,
            slack_workspace_id=WORKSPACE,
            channel="C1",
            thread_ts="123.456",
            task=task,
            task_run=task_run,
            mentioning_slack_user_id=SLACK_USER,
        )

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack-posthog-code"],
            slack_user_id=SLACK_USER,
            user=None,
            channel="C1",
            thread_ts="123.456",
        )

        assert result.source == "thread"
        assert result.integration == self.integration_b

    def test_unresolved_user_trusts_inaccessible_default(self):
        # team_c is in another org. With user=None we don't check accessibility, so
        # the saved default still wins. The workflow's user-resolution will reject
        # the event downstream if needed.
        SlackSettings.objects.create(
            default_integration=self.integration_c,
            slack_workspace_id=WORKSPACE,
            slack_user_id=SLACK_USER,
        )

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack-posthog-code"],
            slack_user_id=SLACK_USER,
            user=None,
        )

        assert result.source == "user_default"
        assert result.integration == self.integration_c

    def test_other_workspace_integrations_are_excluded(self):
        # Delete integration_b so only integration_a in WORKSPACE remains accessible —
        # verifies the unrelated T_OTHER integration is filtered out by workspace.
        self.integration_b.delete()

        result = load_integrations(
            slack_team_id=WORKSPACE,
            kinds=["slack-posthog-code"],
            slack_user_id=SLACK_USER,
            user=self.user,
        )

        assert result.source == "sole_candidate"
        assert result.integration == self.integration_a
