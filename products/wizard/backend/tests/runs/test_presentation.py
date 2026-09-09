from hashlib import sha256
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models import PersonalAPIKey, Team, User
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.config import DEFAULT_WIZARD_VERSION
from products.wizard.backend.facade.contracts import (
    CreatePullRequestArtifactInput,
    CreateWizardRunInput,
    LocalFolderWorkspace,
)
from products.wizard.backend.facade.enums import WizardRunEnvironment, WizardRunStatus
from products.wizard.backend.models import WizardRun, WizardRunArtifact


@override_settings(WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID="wizard-client-id")
class TestWizardRunViewSet(APIBaseTest):
    def _url(self, run_id: str = "") -> str:
        return f"/api/projects/{self.team.id}/wizard/runs/{run_id}"

    def _authenticate_personal_api_key(self, scopes: list[str]) -> None:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Wizard run test key",
            user=self.user,
            secure_value=hash_key_value(token),
            scopes=scopes,
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def _cloud_payload(self, *, repository: str = "posthog/posthog", idempotency_key: str | None = None) -> dict:
        payload = {
            "program_id": "posthog-integration",
            "environment": "cloud",
            "workspace": {"type": "git_repository", "repository": repository},
        }
        if idempotency_key is not None:
            payload["idempotency_key"] = idempotency_key
        return payload

    def test_create_local_run(self) -> None:
        response = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "example-project"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.json(),
            {
                "id": response.json()["id"],
                "team_id": self.team.id,
                "created_by_id": self.user.id,
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "example-project"},
                "program": {
                    "id": "posthog-integration",
                    "name": "PostHog integration",
                    "description": "Set up PostHog SDK integration",
                    "wizard_version": DEFAULT_WIZARD_VERSION,
                    "command": [],
                    "tags": [],
                    "required_programs": [],
                    "supported_environments": ["local", "cloud"],
                },
                "status": "running",
                "error_code": None,
                "error_message": None,
                "stage": None,
                "created_at": response.json()["created_at"],
                "updated_at": response.json()["updated_at"],
                "started_at": response.json()["started_at"],
                "finished_at": None,
                "deadline_at": None,
            },
        )

    @override_settings(WIZARD_RUN_CREATE_THROTTLE_RATE="1/hour")
    def test_create_is_rate_limited_per_user(self) -> None:
        cache.clear()

        first = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "rate-limit-project"},
            },
            format="json",
        )
        second = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "rate-limit-project-two"},
            },
            format="json",
        )

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    @override_settings(WIZARD_RUN_READ_THROTTLE_RATE="1/minute")
    def test_list_is_rate_limited_per_user(self) -> None:
        cache.clear()

        first = self.client.get(self._url())
        second = self.client.get(self._url())

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_create_requires_program_id(self) -> None:
        response = self.client.post(
            self._url(),
            {
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "example-project"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "program_id")
        self.assertEqual(response.json()["code"], "required")

    def test_create_accepts_explicit_wizard_version(self) -> None:
        response = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "wizard_version": "latest",
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "example-project"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["program"]["wizard_version"], "latest")

    def test_create_rejects_invalid_wizard_version(self) -> None:
        response = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "wizard_version": "next",
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "example-project"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "wizard_version")

    def test_create_rejects_unavailable_program(self) -> None:
        with patch("posthoganalytics.get_feature_flag_payload", return_value={"version": 1, "programs": []}):
            response = self.client.post(
                self._url(),
                {
                    "program_id": "unavailable-program",
                    "environment": "local",
                    "workspace": {"type": "local_folder", "project_name": "example-project"},
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Choose an available Wizard program.")
        self.assertFalse(WizardRun.objects.for_team(self.team.id).exists())

    def test_retrieve_run(self) -> None:
        created = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "example-project"},
            },
            format="json",
        ).json()

        response = self.client.get(self._url(created["id"]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), created)

    def test_retrieve_does_not_disclose_another_teams_run(self) -> None:
        other_team = Team.objects.create(
            organization=self.team.organization,
            project=self.team.project,
            name="Other environment",
        )
        other_run = wizard_facade.create_run(
            CreateWizardRunInput(
                team_id=other_team.id,
                created_by_id=self.user.id,
                program_id="posthog-integration",
                environment=WizardRunEnvironment.LOCAL,
                workspace=LocalFolderWorkspace(project_name="other-project"),
            )
        )

        response = self.client.get(self._url(str(other_run.id)))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_rejects_unknown_workspace_without_writing(self) -> None:
        response = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "environment": "local",
                "workspace": {"type": "unknown"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(WizardRun.objects.unscoped().filter(team_id=self.team.id).exists())

    def test_create_rejects_environment_workspace_mismatch(self) -> None:
        response = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "environment": "local",
                "workspace": {"type": "git_repository", "repository": "posthog/posthog"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Choose a workspace supported by this run environment.")

    @parameterized.expand(("missing_integration", "inaccessible_repository"))
    def test_cloud_repository_admission_has_one_public_error(self, scenario: str) -> None:
        integration_id = None if scenario == "missing_integration" else 123
        with (
            patch(
                "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id",
                return_value=integration_id,
            ),
            patch(
                "products.wizard.backend.logic.runs.repository_access.repo_selection.repository_accessible_via_integration",
                return_value=False,
            ),
        ):
            response = self.client.post(
                self._url(),
                {
                    "program_id": "posthog-integration",
                    "environment": "cloud",
                    "idempotency_key": f"repository-admission-{scenario}",
                    "workspace": {"type": "git_repository", "repository": "posthog/posthog"},
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Connect GitHub with access to this repository, then try again.")

    @patch(
        "products.wizard.backend.logic.runs.repository_access.repo_selection.repository_accessible_via_integration",
        return_value=True,
    )
    @patch(
        "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id",
        return_value=123,
    )
    def test_cloud_run_rejects_a_second_active_run(self, _resolve_integration, _repository_accessible) -> None:
        first = self.client.post(self._url(), self._cloud_payload(idempotency_key="first-run"), format="json")

        response = self.client.post(self._url(), self._cloud_payload(idempotency_key="second-run"), format="json")

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(
            response.json()["detail"],
            "A cloud Wizard run is already active. Wait for it to finish or cancel it before starting another.",
        )

    @patch(
        "products.wizard.backend.logic.runs.repository_access.repo_selection.repository_accessible_via_integration",
        return_value=True,
    )
    @patch(
        "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id",
        return_value=123,
    )
    @override_settings(WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID="")
    def test_cloud_run_rejects_disabled_cloud_execution(self, _resolve_integration, _repository_accessible) -> None:
        response = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "environment": "cloud",
                "idempotency_key": "disabled-cloud-execution",
                "workspace": {"type": "git_repository", "repository": "posthog/posthog"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(WizardRun.objects.for_team(self.team.id).exists())

    def test_personal_api_key_cannot_access_wizard_runs(self) -> None:
        run = wizard_facade.create_run(
            CreateWizardRunInput(
                team_id=self.team.id,
                created_by_id=self.user.id,
                program_id="posthog-integration",
                environment=WizardRunEnvironment.LOCAL,
                workspace=LocalFolderWorkspace(project_name="example-project"),
            )
        )

        self._authenticate_personal_api_key(["wizard_session:read", "wizard_session:write"])

        for url in (
            self._url(),
            self._url(str(run.id)),
            self._url(f"{run.id}/artifacts/"),
            self._url(f"{run.id}/artifacts/00000000-0000-0000-0000-000000000000/content/"),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        response = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "another-project"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(WizardRun.objects.for_team(self.team.id).count(), 1)

    @patch(
        "products.wizard.backend.logic.runs.repository_access.repo_selection.repository_accessible_via_integration",
        return_value=True,
    )
    @patch(
        "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id",
        return_value=123,
    )
    def test_cloud_run_requires_idempotency_key(self, _resolve_integration, _repository_accessible) -> None:
        response = self.client.post(self._url(), self._cloud_payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "idempotency_key")
        self.assertFalse(WizardRun.objects.for_team(self.team.id).exists())

    @patch(
        "products.wizard.backend.logic.runs.repository_access.repo_selection.repository_accessible_via_integration",
        return_value=True,
    )
    @patch(
        "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id",
        return_value=123,
    )
    def test_cloud_run_replays_matching_idempotent_request(self, _resolve_integration, _repository_accessible) -> None:
        payload = self._cloud_payload(idempotency_key="create-posthog-run")

        first = self.client.post(self._url(), payload, format="json")
        replay = self.client.post(self._url(), payload, format="json")

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(replay.status_code, status.HTTP_200_OK)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(WizardRun.objects.for_team(self.team.id).count(), 1)

    @patch(
        "products.wizard.backend.logic.runs.repository_access.repo_selection.repository_accessible_via_integration",
        return_value=True,
    )
    @patch(
        "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id",
        return_value=123,
    )
    def test_cloud_run_rejects_reused_idempotency_key_for_different_request(
        self, _resolve_integration, _repository_accessible
    ) -> None:
        first = self.client.post(
            self._url(),
            self._cloud_payload(idempotency_key="create-posthog-run"),
            format="json",
        )
        replay = self.client.post(
            self._url(),
            self._cloud_payload(repository="posthog/posthog-js", idempotency_key="create-posthog-run"),
            format="json",
        )

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(replay.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(replay.json()["code"], "idempotency_conflict")
        self.assertEqual(WizardRun.objects.for_team(self.team.id).count(), 1)

    @patch(
        "products.wizard.backend.logic.runs.repository_access.repo_selection.repository_accessible_via_integration",
        return_value=True,
    )
    @patch(
        "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id",
        return_value=123,
    )
    def test_cloud_run_can_be_cancelled(self, _resolve_integration, _repository_accessible) -> None:
        created = self.client.post(
            self._url(),
            self._cloud_payload(idempotency_key="cancel-posthog-run"),
            format="json",
        ).json()
        WizardRun.objects.for_team(self.team.id).filter(id=created["id"]).update(workflow_id="wizard-workflow")

        with patch(
            "products.wizard.backend.temporal.client.cancel_wizard_run_workflow",
            create=True,
        ) as cancel_workflow:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.patch(self._url(created["id"]), {"status": "cancelled"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "cancelled")
        cancel_workflow.assert_called_once_with(UUID(created["id"]))

    @patch("products.wizard.backend.logic.artifacts.service.object_storage.write")
    def test_list_run_artifacts(self, _write) -> None:
        created = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "example-project"},
            },
            format="json",
        ).json()
        wizard_facade.create_git_diff_artifact(self.team.id, UUID(created["id"]), b"diff")

        response = self.client.get(self._url(f"{created['id']}/artifacts/"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["run_id"], created["id"])
        self.assertEqual(response.json()["results"][0]["artifact_type"], "git_diff")

    def test_get_git_diff_content(self) -> None:
        created = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "example-project"},
            },
            format="json",
        ).json()
        diff = b"diff --git a/app.py b/app.py\n-old\n+new\n"

        with (
            patch("products.wizard.backend.logic.artifacts.service.object_storage.write"),
            patch(
                "products.wizard.backend.logic.artifacts.service.object_storage.read_bytes", return_value=diff
            ) as read_bytes,
        ):
            artifact = wizard_facade.create_git_diff_artifact(self.team.id, UUID(created["id"]), diff)
            assert artifact is not None

            response = self.client.get(self._url(f"{created['id']}/artifacts/{artifact.id}/content/"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, diff)
        self.assertEqual(response["Content-Type"], "text/x-diff; charset=utf-8")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        read_bytes.assert_called_once_with(
            f"projects/{self.team.id}/wizard-runs/{created['id']}/artifacts/git-diff-{sha256(diff).hexdigest()}.patch",
            bucket=settings.WIZARD_RUN_ARTIFACTS_S3_BUCKET,
            missing_ok=True,
        )

    def test_get_git_diff_content_rejects_oversized_artifact_before_download(self) -> None:
        created = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "example-project"},
            },
            format="json",
        ).json()

        with patch("products.wizard.backend.logic.artifacts.service.object_storage.write"):
            artifact = wizard_facade.create_git_diff_artifact(self.team.id, UUID(created["id"]), b"diff")
        assert artifact is not None
        WizardRunArtifact.objects.for_team(self.team.id).filter(id=artifact.id).update(size_bytes=2 * 1024 * 1024 + 1)

        with patch("products.wizard.backend.logic.artifacts.service.object_storage.read_bytes") as read_bytes:
            response = self.client.get(self._url(f"{created['id']}/artifacts/{artifact.id}/content/"))

        self.assertEqual(response.status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        read_bytes.assert_not_called()

    def test_get_git_diff_content_is_scoped_to_nested_run(self) -> None:
        first = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "first-project"},
            },
            format="json",
        ).json()
        second = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "second-project"},
            },
            format="json",
        ).json()

        with (
            patch("products.wizard.backend.logic.artifacts.service.object_storage.write"),
            patch("products.wizard.backend.logic.artifacts.service.object_storage.read_bytes") as read_bytes,
        ):
            artifact = wizard_facade.create_git_diff_artifact(self.team.id, UUID(first["id"]), b"diff")
            assert artifact is not None

            response = self.client.get(self._url(f"{second['id']}/artifacts/{artifact.id}/content/"))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        read_bytes.assert_not_called()

    def test_list_pull_request_artifact(self) -> None:
        created = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "example-project"},
            },
            format="json",
        ).json()
        wizard_facade.create_pull_request_artifact(
            CreatePullRequestArtifactInput(
                team_id=self.team.id,
                run_id=UUID(created["id"]),
                url="https://github.com/posthog/posthog/pull/123",
                number=123,
                repository="posthog/posthog",
                head_branch="posthog/wizard-123",
                base_branch="master",
            )
        )

        response = self.client.get(self._url(f"{created['id']}/artifacts/"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        artifact = response.json()["results"][0]
        self.assertEqual(
            response.json(),
            {
                "count": 1,
                "next": None,
                "previous": None,
                "results": [
                    {
                        "id": artifact["id"],
                        "team_id": self.team.id,
                        "run_id": created["id"],
                        "artifact_type": "pull_request",
                        "url": "https://github.com/posthog/posthog/pull/123",
                        "number": 123,
                        "repository": "posthog/posthog",
                        "head_branch": "posthog/wizard-123",
                        "base_branch": "master",
                        "created_at": artifact["created_at"],
                    }
                ],
            },
        )

    @parameterized.expand(
        (
            ({"status": "completed"}, WizardRunStatus.COMPLETED, None),
            ({"status": "failed", "error_code": "timeout"}, WizardRunStatus.FAILED, "timeout"),
            (
                {"status": "failed", "error_code": "PHW_DETECT_NO_POSTHOG_SDK"},
                WizardRunStatus.FAILED,
                "PHW_DETECT_NO_POSTHOG_SDK",
            ),
            ({"status": "cancelled"}, WizardRunStatus.CANCELLED, None),
        )
    )
    def test_transition_local_run(
        self,
        payload: dict[str, str],
        expected_status: WizardRunStatus,
        expected_error_code: str | None,
    ) -> None:
        created = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "example-project"},
            },
            format="json",
        ).json()

        response = self.client.patch(self._url(created["id"]), payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], expected_status.value)
        self.assertEqual(response.json()["error_code"], expected_error_code)

    def test_transition_rejects_invalid_error_code(self) -> None:
        created = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "example-project"},
            },
            format="json",
        ).json()

        response = self.client.patch(
            self._url(created["id"]),
            {"status": "failed", "error_code": "arbitrary-error"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_transition_rejects_terminal_run(self) -> None:
        created = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "example-project"},
            },
            format="json",
        ).json()
        self.client.patch(self._url(created["id"]), {"status": "completed"}, format="json")

        response = self.client.patch(self._url(created["id"]), {"status": "cancelled"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.json()["code"], "invalid_transition")

    def test_transition_rejects_another_user(self) -> None:
        created = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "example-project"},
            },
            format="json",
        ).json()
        other_user = User.objects.create_and_join(self.organization, "teammate@example.com", None)
        self.client.force_login(other_user)

        response = self.client.patch(self._url(created["id"]), {"status": "completed"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(wizard_facade.get_run(self.team.id, UUID(created["id"])).status, WizardRunStatus.RUNNING)

    @patch(
        "products.wizard.backend.logic.runs.repository_access.repo_selection.repository_accessible_via_integration",
        return_value=True,
    )
    @patch(
        "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id",
        return_value=123,
    )
    def test_cloud_run_rejects_non_cancellation_transition(self, _resolve_integration, _repository_accessible) -> None:
        created = self.client.post(
            self._url(),
            {
                "program_id": "posthog-integration",
                "environment": "cloud",
                "idempotency_key": "reject-cloud-completion",
                "workspace": {"type": "git_repository", "repository": "posthog/posthog"},
            },
            format="json",
        ).json()

        response = self.client.patch(self._url(created["id"]), {"status": "completed"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.json()["code"], "cloud_run_managed")
        self.assertEqual(wizard_facade.get_run(self.team.id, UUID(created["id"])).status, WizardRunStatus.CREATED)

    def test_transition_does_not_disclose_another_teams_run(self) -> None:
        other_team = Team.objects.create(
            organization=self.team.organization,
            project=self.team.project,
            name="Other environment",
        )
        other_run = wizard_facade.create_run(
            CreateWizardRunInput(
                team_id=other_team.id,
                created_by_id=self.user.id,
                program_id="posthog-integration",
                environment=WizardRunEnvironment.LOCAL,
                workspace=LocalFolderWorkspace(project_name="other-project"),
            )
        )

        response = self.client.patch(self._url(str(other_run.id)), {"status": "completed"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(wizard_facade.get_run(other_team.id, other_run.id).status, WizardRunStatus.RUNNING)
