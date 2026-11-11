import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.process_task.activities.feature_flags import (
    AGENT_DESIGN_STATE_KEY,
    IsSlackAppAgentDesignEnabledForTaskActivityInput,
    is_slack_app_agent_design_enabled_for_task_activity,
)


class TestIsSlackAppAgentDesignEnabledForTaskActivity(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.task = Task.objects.create(
            team=self.team,
            title="Slack task",
            description="From Slack",
            origin_product=Task.OriginProduct.SLACK,
            created_by=self.user,
        )
        self.task_run = TaskRun.objects.create(task=self.task, team=self.team)
        other_org = Organization.objects.create(name="Other org")
        self.other_team = Team.objects.create(organization=other_org, name="Other team")

    def _slack_integration(self, team: Team) -> Integration:
        return Integration.objects.create(team=team, kind="slack", integration_id="T123", config={})

    @parameterized.expand(
        [
            ("same_team", "same_team", True, True),
            ("other_team", "other_team", True, False),
            ("missing_run", "same_team", False, False),
        ]
    )
    def test_evaluates_only_for_the_run_team(
        self, _name: str, integration_team: str, run_exists: bool, expected: bool
    ) -> None:
        integration = self._slack_integration(self.team if integration_team == "same_team" else self.other_team)
        run_id = str(self.task_run.id) if run_exists else str(uuid.uuid4())

        with patch(
            "products.slack_app.backend.feature_flags.posthoganalytics.feature_enabled", return_value=True
        ) as feature_enabled:
            enabled = is_slack_app_agent_design_enabled_for_task_activity(
                IsSlackAppAgentDesignEnabledForTaskActivityInput(integration_id=integration.id, run_id=run_id)
            )

        assert enabled is expected
        if expected:
            feature_enabled.assert_called_once()
            args, kwargs = feature_enabled.call_args
            assert args[1] == self.user.distinct_id
            assert kwargs["groups"] == {"organization": str(self.team.organization_id)}
        else:
            feature_enabled.assert_not_called()
        if run_exists:
            self.task_run.refresh_from_db()
            assert self.task_run.state[AGENT_DESIGN_STATE_KEY] is expected
