from datetime import UTC, datetime

from django.apps import apps
from django.test import TestCase

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.home_tab import HomeTabTask, build_home_view, gather_involved_tasks
from products.slack_app.backend.models import SlackThreadTaskMapping

WORKSPACE = "T_WS"
VIEWER = "U_VIEWER"


class TestGatherInvolvedTasks(TestCase):
    def setUp(self):
        self.Task = apps.get_model("tasks", "Task")
        self.TaskRun = apps.get_model("tasks", "TaskRun")
        self.org = Organization.objects.create(name="Org")
        self.team = Team.objects.create(organization=self.org, name="Team")
        self.user = User.objects.create(email="alice@test.com")
        self.integration = Integration.objects.create(team=self.team, kind="slack", integration_id=WORKSPACE, config={})

    def _make_task(self, *, title: str, participants: list[str], team: Team, channel: str, status=None) -> object:
        task = self.Task.objects.create(
            team=team,
            title=title,
            description="d",
            origin_product=self.Task.OriginProduct.SLACK,
            created_by=self.user,
            repository="org/repo",
        )
        run = self.TaskRun.objects.create(
            task=task,
            team=team,
            status=status or self.TaskRun.Status.IN_PROGRESS,
        )
        SlackThreadTaskMapping.objects.create(
            team=team,
            integration=Integration.objects.filter(team=team, kind="slack").first(),
            slack_workspace_id=WORKSPACE,
            channel=channel,
            thread_ts=f"{channel}.0",
            task=task,
            task_run=run,
            mentioning_slack_user_id=participants[0] if participants else "",
            participant_slack_user_ids=participants,
        )
        return task

    def test_returns_task_the_user_participated_in(self):
        self._make_task(title="Mine", participants=[VIEWER], team=self.team, channel="C1")
        result = gather_involved_tasks(
            slack_workspace_id=WORKSPACE,
            slack_user_id=VIEWER,
            accessible_integrations=[self.integration],
        )
        assert [t.title for t in result] == ["Mine"]

    def test_excludes_task_the_user_did_not_participate_in(self):
        # Started and replied to only by someone else — the viewer must not see it.
        self._make_task(title="Theirs", participants=["U_OTHER"], team=self.team, channel="C1")
        result = gather_involved_tasks(
            slack_workspace_id=WORKSPACE,
            slack_user_id=VIEWER,
            accessible_integrations=[self.integration],
        )
        assert result == []

    def test_excludes_task_from_team_the_user_cannot_access(self):
        # Viewer IS a participant, but the task lives in a team not in accessible_integrations.
        other_org = Organization.objects.create(name="Org2")
        other_team = Team.objects.create(organization=other_org, name="Team2")
        Integration.objects.create(team=other_team, kind="slack", integration_id=WORKSPACE, config={})
        self._make_task(title="Forbidden", participants=[VIEWER], team=other_team, channel="C2")
        result = gather_involved_tasks(
            slack_workspace_id=WORKSPACE,
            slack_user_id=VIEWER,
            accessible_integrations=[self.integration],  # only self.team
        )
        assert result == []

    def test_multiplayer_replier_sees_task_started_by_someone_else(self):
        # Started by U_OTHER, viewer replied in-thread → both are participants.
        self._make_task(title="Shared", participants=["U_OTHER", VIEWER], team=self.team, channel="C1")
        result = gather_involved_tasks(
            slack_workspace_id=WORKSPACE,
            slack_user_id=VIEWER,
            accessible_integrations=[self.integration],
        )
        assert [t.title for t in result] == ["Shared"]


def _task(status: str, *, pr_url: str | None = None) -> HomeTabTask:
    return HomeTabTask(
        task_id="t",
        team_id=1,
        title="T",
        repository=None,
        status=status,
        stage=None,
        pr_url=pr_url,
        error_message=None,
        sort_key=datetime(2026, 1, 1, tzinfo=UTC),
    )


class TestBuildHomeView(TestCase):
    @parameterized.expand(
        [
            ("not_started", True),
            ("queued", True),
            ("in_progress", True),
            ("completed", False),
            ("failed", False),
            ("cancelled", False),
        ]
    )
    def test_status_classified_active_or_finished(self, status: str, expected_active: bool):
        assert _task(status).is_active is expected_active

    def test_empty_state_renders_prompt(self):
        view = build_home_view([])
        text = str(view["blocks"])
        assert view["type"] == "home"
        assert "Mention" in text

    def test_groups_active_and_finished_under_separate_headers(self):
        view = build_home_view([_task("in_progress"), _task("completed")])
        headers = [b["text"]["text"] for b in view["blocks"] if b["type"] == "section" and "*" in b["text"]["text"]]
        assert any("In progress (1)" in h for h in headers)
        assert any("Recently finished (1)" in h for h in headers)
