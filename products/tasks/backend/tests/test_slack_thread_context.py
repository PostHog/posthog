from typing import ClassVar
from urllib.parse import quote

from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings

from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Integration, Organization, OrganizationMembership, Team, User

from products.slack_app.backend.models import SlackThreadTaskMapping
from products.tasks.backend.models import Task, TaskRun


class _SlackThreadContextBase(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")
        cls.user = User.objects.create_user(email="alice@example.com", first_name="Alice", password="password")
        cls.organization.members.add(cls.user)
        OrganizationMembership.objects.filter(user=cls.user, organization=cls.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self._flag_patcher = patch(
            "posthoganalytics.feature_enabled", side_effect=lambda flag, *a, **k: flag == "tasks"
        )
        self._flag_patcher.start()
        # Production gate is `team_id == 2 AND CLOUD_DEPLOYMENT == "US"`; tests
        # can't easily force the test row to id 2, so substitute self.team.id
        # for the constant while keeping the deployment clause intact.
        self._gate_patcher = patch(
            "products.tasks.backend.api._is_internal_debug_team",
            side_effect=lambda team_id: team_id == self.team.id and settings.CLOUD_DEPLOYMENT == "US",
        )
        self._gate_patcher.start()

    def tearDown(self):
        self._gate_patcher.stop()
        self._flag_patcher.stop()
        super().tearDown()


@override_settings(CLOUD_DEPLOYMENT="US")
class TestSlackThreadContextEndpoint(_SlackThreadContextBase):
    def _url(self, slack_url: str | None = None) -> str:
        suffix = f"?url={quote(slack_url, safe='')}" if slack_url else ""
        return f"/api/projects/{self.team.id}/tasks/slack_thread_context/{suffix}"

    def _create_fixture(
        self,
        *,
        slack_mention_workflow_id: str | None = "posthog-code-mention-T_SLACK:Ev01",
    ) -> tuple[Task, TaskRun, SlackThreadTaskMapping]:
        integration = Integration.objects.create(
            team=self.team, kind="slack-posthog-code", integration_id="T_SLACK", config={}
        )
        task = Task.objects.create(
            team=self.team,
            title="Investigate flaky test",
            description="From slack thread",
            origin_product=Task.OriginProduct.SLACK,
            created_by=self.user,
            repository=None,
        )
        run_state: dict[str, object] = {"sandbox_url": "https://sandbox.example/abc"}
        if slack_mention_workflow_id is not None:
            run_state["slack_mention_workflow_id"] = slack_mention_workflow_id
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state=run_state,
            output={"pr_url": "https://github.com/posthog/posthog/pull/1"},
        )
        mapping = SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=integration,
            slack_workspace_id="T_SLACK",
            channel="C0ACRAMJUAG",
            thread_ts="1779956938.619299",
            task=task,
            task_run=run,
            mentioning_slack_user_id="U_ANDY",
        )
        return task, run, mapping

    def test_non_internal_team_is_forbidden(self):
        # Override the base-class gate patcher so this call lands on the
        # "not the internal team" branch of `_is_internal_debug_team`.
        with patch("products.tasks.backend.api._is_internal_debug_team", return_value=False):
            response = self.client.get(self._url("https://posthog.slack.com/archives/C0ACRAMJUAG/p1779956938619299"))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_malformed_url_returns_400(self):
        response = self.client.get(self._url("https://posthog.slack.com/not/a/permalink"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_url_returns_400(self):
        # validated_request raises a validation error → 400 from drf
        response = self.client.get(self._url(None))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_no_mapping_returns_404(self):
        response = self.client.get(self._url("https://posthog.slack.com/archives/C0ACRAMJUAG/p1779956938619299"))
        assert response.status_code == status.HTTP_404_NOT_FOUND
        body = response.json()
        assert body["detail"] == "no_mapping"
        assert body["thread"]["channel"] == "C0ACRAMJUAG"
        assert body["thread"]["thread_ts"] == "1779956938.619299"

    def test_happy_path_returns_task_and_runs(self):
        task, run, mapping = self._create_fixture()
        with patch(
            "products.tasks.backend.api.object_storage.get_presigned_url",
            return_value="https://s3.example/presigned",
        ):
            response = self.client.get(self._url("https://posthog.slack.com/archives/C0ACRAMJUAG/p1779956938619299"))
        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["thread"]["channel"] == "C0ACRAMJUAG"
        assert body["thread"]["thread_ts"] == "1779956938.619299"
        assert body["thread"]["slack_workspace_id"] == "T_SLACK"
        assert body["thread"]["mentioning_slack_user_id"] == "U_ANDY"

        assert body["task"]["id"] == str(task.id)
        assert body["task"]["team_id"] == self.team.id
        assert body["task"]["title"] == "Investigate flaky test"
        assert body["task"]["repository"] is None
        assert body["task"]["origin_product"] == Task.OriginProduct.SLACK
        # Links carry `?ph_debug=true` so reviewers don't lose the cross-creator
        # bypass when they click through to the regular task UI.
        assert body["task"]["url"].endswith(f"/project/{self.team.id}/tasks/{task.id}?ph_debug=true")

        assert len(body["runs"]) == 1
        run_payload = body["runs"][0]
        assert run_payload["id"] == str(run.id)
        assert run_payload["sandbox_url"] == "https://sandbox.example/abc"
        assert run_payload["pr_url"] == "https://github.com/posthog/posthog/pull/1"
        assert run_payload["task_processing_workflow_id"] == f"task-processing-{task.id}-{run.id}"
        assert run_payload["mention_workflow_id"] == "posthog-code-mention-T_SLACK:Ev01"
        assert run_payload["task_view_url"].endswith(
            f"/project/{self.team.id}/tasks/{task.id}?runId={run.id}&ph_debug=true"
        )
        assert run_payload["log_url"] == "https://s3.example/presigned"

    def test_reply_url_uses_thread_ts_query_param(self):
        self._create_fixture()
        reply_url = (
            "https://posthog.slack.com/archives/C0ACRAMJUAG/p1779957091477899"
            "?thread_ts=1779956938.619299&cid=C0ACRAMJUAG"
        )
        with patch("products.tasks.backend.api.object_storage.get_presigned_url", return_value=None):
            response = self.client.get(self._url(reply_url))
        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        # The reply's in-path ts (1779957091.477899) must NOT win — the thread_ts query
        # param identifies the originating thread that has the mapping.
        assert body["thread"]["thread_ts"] == "1779956938.619299"

    def test_multiple_runs_returned_oldest_first(self):
        task, first_run, _ = self._create_fixture()
        # A second run on the same task — resume after follow-up.
        second_run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            state={
                "resume_from_run_id": str(first_run.id),
                "slack_mention_workflow_id": "posthog-code-mention-T_SLACK:Ev02",
            },
        )
        with patch("products.tasks.backend.api.object_storage.get_presigned_url", return_value=None):
            response = self.client.get(self._url("https://posthog.slack.com/archives/C0ACRAMJUAG/p1779956938619299"))
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        run_ids = [r["id"] for r in body["runs"]]
        assert run_ids == [str(first_run.id), str(second_run.id)]
        assert body["runs"][1]["mention_workflow_id"] == "posthog-code-mention-T_SLACK:Ev02"

    @override_settings(TEMPORAL_UI_HOST="")
    def test_temporal_url_null_when_ui_host_unset(self):
        self._create_fixture()
        with patch("products.tasks.backend.api.object_storage.get_presigned_url", return_value=None):
            response = self.client.get(self._url("https://posthog.slack.com/archives/C0ACRAMJUAG/p1779956938619299"))
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        run_payload = body["runs"][0]
        assert run_payload["task_processing_workflow_url"] is None
        assert run_payload["mention_workflow_url"] is None

    @override_settings(TEMPORAL_UI_HOST="https://temporal.example.com", TEMPORAL_NAMESPACE="prod")
    def test_temporal_url_includes_workflow_id_when_configured(self):
        task, run, _ = self._create_fixture()
        with patch("products.tasks.backend.api.object_storage.get_presigned_url", return_value=None):
            response = self.client.get(self._url("https://posthog.slack.com/archives/C0ACRAMJUAG/p1779956938619299"))
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        run_payload = body["runs"][0]
        assert run_payload["task_processing_workflow_url"] == (
            f"https://temporal.example.com/namespaces/prod/workflows/task-processing-{task.id}-{run.id}"
        )
        assert run_payload["mention_workflow_url"] == (
            "https://temporal.example.com/namespaces/prod/workflows/posthog-code-mention-T_SLACK:Ev01"
        )

    def test_mention_workflow_id_null_for_old_runs(self):
        self._create_fixture(slack_mention_workflow_id=None)
        with patch("products.tasks.backend.api.object_storage.get_presigned_url", return_value=None):
            response = self.client.get(self._url("https://posthog.slack.com/archives/C0ACRAMJUAG/p1779956938619299"))
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["runs"][0]["mention_workflow_id"] is None
        assert body["runs"][0]["mention_workflow_url"] is None
