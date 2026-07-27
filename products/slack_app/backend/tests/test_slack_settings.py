import pytest

from django.db import IntegrityError

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.models import SlackSettings


class TestSlackSettings:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Org")
        self.team_a = Team.objects.create(organization=self.organization, name="Team A")
        self.team_b = Team.objects.create(organization=self.organization, name="Team B")
        self.integration_a = Integration.objects.create(
            team=self.team_a,
            kind="slack",
            integration_id="T_WS",
            sensitive_config={"access_token": "xoxb-a"},
        )
        self.integration_b = Integration.objects.create(
            team=self.team_b,
            kind="slack",
            integration_id="T_WS",
            sensitive_config={"access_token": "xoxb-b"},
        )

    # --- per-user rows ---------------------------------------------------------

    def test_uniqueness_per_workspace_and_slack_user(self):
        SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id="T_WS",
            slack_user_id="U001",
        )

        with pytest.raises(IntegrityError):
            SlackSettings.objects.create(
                default_integration=self.integration_b,
                slack_workspace_id="T_WS",
                slack_user_id="U001",
            )

    def test_distinct_workspaces_allow_same_slack_user(self):
        SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id="T_WS",
            slack_user_id="U001",
        )
        SlackSettings.objects.create(
            default_integration=self.integration_b,
            slack_workspace_id="T_OTHER",
            slack_user_id="U001",
        )

        assert SlackSettings.objects.filter(slack_user_id="U001").count() == 2

    def test_distinct_slack_users_in_same_workspace(self):
        SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id="T_WS",
            slack_user_id="U001",
        )
        SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id="T_WS",
            slack_user_id="U002",
        )

        assert SlackSettings.objects.filter(slack_workspace_id="T_WS").count() == 2

    # --- workspace-wide rows ---------------------------------------------------

    def test_workspace_default_row_with_null_user(self):
        row = SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id="T_WS",
            slack_user_id=None,
        )
        assert row.slack_user_id is None

    def test_uniqueness_workspace_default_per_workspace(self):
        SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id="T_WS",
            slack_user_id=None,
        )

        # A second workspace-wide row for the same workspace must not be allowed
        # — partial uniqueness applies even though Postgres treats NULL as distinct.
        with pytest.raises(IntegrityError):
            SlackSettings.objects.create(
                default_integration=self.integration_b,
                slack_workspace_id="T_WS",
                slack_user_id=None,
            )

    def test_workspace_default_coexists_with_user_rows(self):
        SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id="T_WS",
            slack_user_id=None,
        )
        SlackSettings.objects.create(
            default_integration=self.integration_b,
            slack_workspace_id="T_WS",
            slack_user_id="U001",
        )

        rows = SlackSettings.objects.filter(slack_workspace_id="T_WS")
        assert rows.count() == 2
        assert rows.filter(slack_user_id__isnull=True).count() == 1
        assert rows.filter(slack_user_id="U001").count() == 1

    def test_distinct_workspaces_each_allow_their_own_workspace_default(self):
        SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id="T_WS",
            slack_user_id=None,
        )
        SlackSettings.objects.create(
            default_integration=self.integration_b,
            slack_workspace_id="T_OTHER",
            slack_user_id=None,
        )

        assert SlackSettings.objects.filter(slack_user_id__isnull=True).count() == 2

    # --- cascade behavior ------------------------------------------------------

    def test_cascade_when_integration_deleted(self):
        row = SlackSettings.objects.create(
            default_integration=self.integration_a,
            slack_workspace_id="T_WS",
            slack_user_id="U001",
        )
        self.integration_a.delete()
        assert not SlackSettings.objects.filter(pk=row.pk).exists()
