from datetime import UTC, datetime

from django.apps import apps
from django.test import TestCase

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.home_tab import HomeTabTask, apply_filters, build_home_view, gather_involved_tasks
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


def _task(
    status: str,
    *,
    pr_url: str | None = None,
    joined: bool = False,
    title: str = "T",
    order: int = 1,
    repository: str = "org/repo",
    org_id: str = "1",
) -> HomeTabTask:
    return HomeTabTask(
        task_id="t",
        team_id=1,
        title=title,
        repository=repository,
        status=status,
        stage=None,
        pr_url=pr_url,
        error_message=None,
        sort_key=datetime(2026, 1, order, tzinfo=UTC),
        joined=joined,
        org_id=org_id,
        org_name="Org",
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

    def test_groups_under_separate_headers_finished_first(self):
        view = build_home_view([_task("in_progress", title="A"), _task("completed", title="B")])
        section_texts = [b["text"]["text"] for b in view["blocks"] if b["type"] == "section"]
        assert "*Recently finished*" in section_texts
        assert "*In progress*" in section_texts
        # Finished group must come before the in-progress group.
        assert section_texts.index("*Recently finished*") < section_texts.index("*In progress*")

    def test_joined_task_shows_joined_marker(self):
        view = build_home_view([_task("completed", joined=True)])
        assert "joined" in str(view["blocks"])
        assert "joined" not in str(build_home_view([_task("completed", joined=False)])["blocks"])

    def test_completed_with_pr_links_to_pr(self):
        view = build_home_view([_task("completed", pr_url="https://github.com/o/r/pull/7")])
        assert "https://github.com/o/r/pull/7" in str(view["blocks"])

    def test_has_refresh_button(self):
        view = build_home_view([_task("completed")])
        action_ids = [el["action_id"] for b in view["blocks"] if b["type"] == "actions" for el in b["elements"]]
        assert "refresh_home" in action_ids


class TestFilters(TestCase):
    @parameterized.expand(
        [
            ("repo", {"repo": "a/one"}, ["keep"]),
            ("status_active", {"status": "active"}, ["run"]),
            ("status_finished", {"status": "finished"}, ["keep", "other-org"]),
            ("org", {"org": "9"}, ["other-org"]),
            ("none", {}, ["keep", "run", "other-org"]),
        ]
    )
    def test_apply_filters(self, _name, filters, expected_titles):
        tasks = [
            _task("completed", title="keep", repository="a/one", org_id="1"),
            _task("in_progress", title="run", repository="b/two", org_id="1"),
            _task("completed", title="other-org", repository="c/three", org_id="9"),
        ]
        assert sorted(t.title for t in apply_filters(tasks, filters)) == sorted(expected_titles)

    def test_repo_select_shown_when_multiple_repos(self):
        view = build_home_view([_task("completed", repository="a/one"), _task("completed", repository="b/two")])
        action_ids = [el["action_id"] for b in view["blocks"] if b["type"] == "actions" for el in b["elements"]]
        assert "home_filter_repo" in action_ids

    def test_repo_select_hidden_with_single_repo(self):
        view = build_home_view([_task("completed", repository="a/one"), _task("completed", repository="a/one")])
        action_ids = [el["action_id"] for b in view["blocks"] if b["type"] == "actions" for el in b["elements"]]
        assert "home_filter_repo" not in action_ids
        assert "home_filter_status" in action_ids  # status is always offered

    def test_filtered_to_empty_shows_no_match(self):
        view = build_home_view([_task("completed", repository="a/one")], {"repo": "does/not-exist"})
        assert "No tasks match" in str(view["blocks"])
