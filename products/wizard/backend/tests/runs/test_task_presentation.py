from datetime import timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team, User
from posthog.models.oauth import OAuthAccessToken, OAuthApplication

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import CreateWizardRunInput, LocalFolderWorkspace
from products.wizard.backend.facade.enums import WizardRunEnvironment


class TestWizardRunTasks(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.wizard_run = wizard_facade.create_run(
            CreateWizardRunInput(
                team_id=self.team.id,
                created_by_id=self.user.id,
                program_id="posthog-integration",
                environment=WizardRunEnvironment.LOCAL,
                workspace=LocalFolderWorkspace(project_name="example-project"),
            )
        )
        self.url = f"/api/projects/{self.team.id}/wizard/runs/{self.wizard_run.id}/tasks/"

    def _authenticate_agent(self, scope: str = "wizard_run:read wizard_run:write") -> None:
        application = OAuthApplication.objects.create(
            name="Wizard",
            user=self.user,
            organization=self.organization,
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
        )
        token = f"pha_{uuid4().hex}"
        OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token=token,
            expires=timezone.now() + timedelta(hours=1),
            scope=scope,
            scoped_teams=[self.team.id],
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_snapshot_write_read_and_validation(self) -> None:
        self._authenticate_agent()
        response = self.client.put(self.url, {"tasks": [{"name": "Install SDK"}]}, format="json")
        assert response.status_code == 400

        with (
            patch("products.wizard.backend.logic.runs.pubsub.get_client") as redis,
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.put(
                self.url, {"tasks": [{"name": "Install SDK", "status": "running"}]}, format="json"
            )
            assert response.status_code == 204
            assert not response.content
            redis.return_value.publish.assert_not_called()
        assert redis.return_value.publish.call_args.args == (
            f"wizard_runs:team:{self.team.id}:run:{self.wizard_run.id}",
            b"{}",
        )

        data = self.client.get(self.url).json()
        assert set(data) == {"tasks"}
        assert data["tasks"] == [
            {
                "name": "Install SDK",
                "status": "running",
                "created_at": data["tasks"][0]["created_at"],
                "started_at": data["tasks"][0]["created_at"],
                "completed_at": None,
                "failed_at": None,
                "error_message": None,
            }
        ]
        response = self.client.put(self.url, {"tasks": []}, format="json")
        assert response.status_code == 204
        assert self.client.get(self.url).json() == {"tasks": []}

    @parameterized.expand([("session", 403), ("read_scope", 403), ("other_owner", 403), ("other_team", 404)])
    def test_task_write_permissions(self, case: str, expected: int) -> None:
        if case != "session":
            self._authenticate_agent("wizard_run:read" if case == "read_scope" else "wizard_run:write")
        if case in ("other_owner", "other_team"):
            owner = User.objects.create_and_join(self.organization, "other@example.com", None)
            team = self.team if case == "other_owner" else Team.objects.create(organization=self.organization)
            run = wizard_facade.create_run(
                CreateWizardRunInput(
                    team_id=team.id,
                    created_by_id=owner.id,
                    program_id="posthog-integration",
                    environment=WizardRunEnvironment.LOCAL,
                    workspace=LocalFolderWorkspace(project_name="another-project"),
                )
            )
            self.url = f"/api/projects/{self.team.id}/wizard/runs/{run.id}/tasks/"
        response = self.client.put(self.url, {"tasks": []}, format="json")
        assert response.status_code == expected

    def test_agent_can_create_and_complete_local_run(self) -> None:
        self._authenticate_agent()
        response = self.client.post(
            f"/api/projects/{self.team.id}/wizard/runs/",
            {
                "program_id": "posthog-integration",
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "another-project"},
            },
            format="json",
        )
        assert response.status_code == 201
        response = self.client.patch(
            f"/api/projects/{self.team.id}/wizard/runs/{response.json()['id']}/",
            {"status": "completed"},
            format="json",
        )
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

    def test_run_stream_honors_killswitch(self) -> None:
        with patch(
            "products.wizard.backend.presentation.runs.views._wizard_sync_killswitch_enabled", return_value=True
        ):
            response = self.client.get(
                f"/api/projects/{self.team.id}/wizard/runs/{self.wizard_run.id}/stream/",
                HTTP_ACCEPT="text/event-stream",
            )
        assert response.status_code == 204
