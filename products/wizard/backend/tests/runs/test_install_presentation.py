from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import PersonalAPIKey
from posthog.models.integration import Integration
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.utils import absolute_uri

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import CreatePullRequestArtifactInput, UpdateWizardRunTaskInput
from products.wizard.backend.facade.enums import WizardRunStatus, WizardTaskStatus
from products.wizard.backend.models import WizardRun

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

REPOSITORY_ACCESS = "products.wizard.backend.logic.runs.repository_access.repo_selection"


@override_settings(WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID="wizard-client-id")
class TestWizardInstallViewSet(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.integration = Integration.objects.create(team=self.team, kind="github", config={})
        self.resolve_integration = patch(
            f"{REPOSITORY_ACCESS}.resolve_team_github_integration_id", return_value=self.integration.id
        )
        self.repository_accessible = patch(
            f"{REPOSITORY_ACCESS}.repository_accessible_via_integration", return_value=True
        )
        self.resolve_integration.start()
        self.accessible = self.repository_accessible.start()
        self.addCleanup(patch.stopall)

    def _url(self, run_id: str = "") -> str:
        return f"/api/projects/{self.team.id}/wizard/installs/{run_id}"

    def _authenticate_oauth(self, scope: str) -> None:
        application = OAuthApplication.objects.create(
            name="Chat client",
            user=self.user,
            organization=self.organization,
            client_type=OAuthApplication.CLIENT_PUBLIC,
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

    def _authenticate_personal_api_key(self) -> None:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Install test key", user=self.user, secure_value=hash_key_value(token), scopes=["*"]
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def _start(self, **payload: str) -> "_MonkeyPatchedResponse":
        return self.client.post(self._url(), {"repository": "posthog/posthog", **payload}, format="json")

    @parameterized.expand(
        [
            ("session", None, status.HTTP_201_CREATED),
            ("oauth_task_write", "task:write", status.HTTP_201_CREATED),
            ("oauth_task_read_only", "task:read", status.HTTP_403_FORBIDDEN),
            ("oauth_other_scope", "insight:write", status.HTTP_403_FORBIDDEN),
            ("personal_api_key", "personal_api_key", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_start_accepts_sessions_and_oauth_tokens_with_task_write(
        self, _name: str, credential: str | None, expected_status: int
    ) -> None:
        if credential == "personal_api_key":
            self._authenticate_personal_api_key()
        elif credential is not None:
            self._authenticate_oauth(credential)

        response = self._start(idempotency_key="auth-check")

        self.assertEqual(response.status_code, expected_status, response.content)
        self.assertEqual(WizardRun.objects.for_team(self.team.id).exists(), expected_status == status.HTTP_201_CREATED)
        if expected_status == status.HTTP_201_CREATED:
            run = WizardRun.objects.for_team(self.team.id).get()
            self.assertEqual(
                response.json(),
                {
                    "run_id": str(run.id),
                    "status": "created",
                    "url": absolute_uri(f"/project/{self.team.id}/wizard/runs"),
                },
            )
            self.assertEqual(run.program["id"], "posthog-integration")
            self.assertEqual(run.environment, "cloud")

    def test_status_reads_with_task_read(self) -> None:
        run_id = self._start(idempotency_key="status-scope").json()["run_id"]
        self._authenticate_oauth("task:read")

        response = self.client.get(self._url(run_id))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

    def test_disabled_cloud_execution_hides_both_endpoints(self) -> None:
        run_id = self._start(idempotency_key="before-cloud-off").json()["run_id"]

        with override_settings(WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID=""):
            start = self._start(idempotency_key="cloud-off")
            status_response = self.client.get(self._url(run_id))

        self.assertEqual(start.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(status_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(WizardRun.objects.for_team(self.team.id).count(), 1)

    @parameterized.expand([("pending", False), ("legacy", None)])
    def test_start_allows_users_without_a_verified_email(self, _name: str, is_email_verified: bool | None) -> None:
        self.user.is_email_verified = is_email_verified
        self.user.save()

        response = self._start(idempotency_key=f"unverified-{_name}")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)

    def test_start_refuses_a_second_active_run_for_the_same_user(self) -> None:
        self._start(idempotency_key="first-run")

        response = self._start(idempotency_key="second-run")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.json()["code"], "run_already_active")
        self.assertEqual(WizardRun.objects.for_team(self.team.id).count(), 1)

    def test_idempotency_key_reuse_for_another_repository_conflicts(self) -> None:
        self._start(idempotency_key="reused")

        response = self._start(idempotency_key="reused", repository="posthog/posthog-js")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.json()["code"], "idempotency_conflict")

    def test_start_records_the_branch(self) -> None:
        response = self._start(idempotency_key="branch", branch="release/next")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        run = WizardRun.objects.for_team(self.team.id).get()
        self.assertEqual(run.workspace, {"repository": "posthog/posthog", "branch": "release/next"})

    @parameterized.expand([("leading_dash", "-x"), ("dot_dot", "a..b"), ("space", "my branch"), ("lock", "main.lock")])
    def test_start_rejects_invalid_branches(self, _name: str, branch: str) -> None:
        response = self._start(idempotency_key="bad-branch", branch=branch)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "branch")

    def test_unreachable_repository_refreshes_the_repository_cache_once(self) -> None:
        self.accessible.side_effect = [False, True]

        with patch("posthog.models.integration.GitHubIntegration.sync_repository_cache") as sync:
            response = self._start(idempotency_key="fresh-install")
            self.accessible.side_effect = None
            self.accessible.return_value = False
            missing = self._start(idempotency_key="missing-repository", repository="posthog/missing")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        self.assertEqual(missing.json()["code"], "repository_not_accessible")
        sync.assert_called_once_with(min_refresh_interval_seconds=60)

    @parameterized.expand(
        [
            ("not_connected", None, "github_not_connected"),
            ("not_accessible", True, "repository_not_accessible"),
        ]
    )
    def test_start_explains_missing_repository_access(self, _name: str, connected: bool | None, code: str) -> None:
        self.accessible.return_value = False
        if connected is None:
            patch(f"{REPOSITORY_ACCESS}.resolve_team_github_integration_id", return_value=None).start()

        with patch("posthog.models.integration.GitHubIntegration.sync_repository_cache"):
            response = self._start(idempotency_key=f"access-{_name}")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], code)
        self.assertFalse(WizardRun.objects.for_team(self.team.id).exists())

    def test_status_reports_tasks_pull_request_and_next_step(self) -> None:
        run_id = self._start(idempotency_key="status").json()["run_id"]
        run = WizardRun.objects.for_team(self.team.id).get()
        wizard_facade.update_run_task_list(
            self.team.id,
            run.id,
            (UpdateWizardRunTaskInput(title="Install the SDK", status=WizardTaskStatus.COMPLETED),),
        )
        WizardRun.objects.for_team(self.team.id).filter(id=run.id).update(
            status=WizardRunStatus.COMPLETED.value, stage=None
        )
        wizard_facade.create_pull_request_artifact(
            CreatePullRequestArtifactInput(
                team_id=self.team.id,
                run_id=run.id,
                url="https://github.com/posthog/posthog/pull/1",
                number=1,
                repository="posthog/posthog",
                head_branch="posthog/wizard-1",
                base_branch="main",
            )
        )

        response = self.client.get(self._url(run_id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "status": "completed",
                "stage": None,
                "error_code": None,
                "error_message": None,
                "pull_request_url": "https://github.com/posthog/posthog/pull/1",
                "tasks": [{"name": "Install the SDK", "status": "completed"}],
                "next_step": (
                    "The setup agent opened a pull request. Share the link with the user so they can review and merge it."
                ),
            },
        )

    def test_status_does_not_disclose_another_projects_run(self) -> None:
        run_id = self._start(idempotency_key="other-project").json()["run_id"]
        other_team = self.create_team_with_organization(organization=self.organization)

        response = self.client.get(f"/api/projects/{other_team.id}/wizard/installs/{run_id}")
        malformed = self.client.get(self._url("-" * 36))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(malformed.status_code, status.HTTP_404_NOT_FOUND)
