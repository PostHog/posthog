import pytest

from products.wizard.backend.facade.contracts import GitRepositoryWorkspace, LocalFolderWorkspace
from products.wizard.backend.facade.enums import WizardRunEnvironment
from products.wizard.backend.presentation.runs.serializers import (
    UpdateWizardRunTaskListSerializer,
    WizardRunCreateRequestSerializer,
)


@pytest.mark.parametrize(
    "tasks",
    (
        [{"name": "Install SDK"}],
        [{"name": "Install SDK", "status": "unknown"}],
        [{"name": "Install SDK", "status": "created"}, {"name": "Install SDK", "status": "running"}],
        [{"name": " ", "status": "created"}],
        [{"name": str(i), "status": "created"} for i in range(101)],
    ),
)
def test_task_snapshot_rejects_invalid_tasks(tasks: list[dict[str, str]]) -> None:
    serializer = UpdateWizardRunTaskListSerializer(data={"tasks": tasks})
    assert not serializer.is_valid()
    assert "tasks" in serializer.errors


@pytest.mark.parametrize(
    "payload, expected_environment, expected_workspace",
    (
        (
            {
                "program_id": "posthog-integration",
                "environment": "local",
                "workspace": {"type": "local_folder", "project_name": "example-project"},
            },
            WizardRunEnvironment.LOCAL,
            LocalFolderWorkspace(project_name="example-project"),
        ),
        (
            {
                "program_id": "posthog-integration",
                "environment": "cloud",
                "idempotency_key": "serialize-cloud-run",
                "workspace": {"type": "git_repository", "repository": "posthog/posthog"},
            },
            WizardRunEnvironment.CLOUD,
            GitRepositoryWorkspace(repository="posthog/posthog"),
        ),
    ),
)
def test_create_request_discriminates_workspace(
    payload: dict[str, object],
    expected_environment: WizardRunEnvironment,
    expected_workspace: LocalFolderWorkspace | GitRepositoryWorkspace,
) -> None:
    serializer = WizardRunCreateRequestSerializer(data=payload)

    assert serializer.is_valid(), serializer.errors
    assert serializer.to_contract(team_id=123, created_by_id=456).program_id == "posthog-integration"
    assert serializer.to_contract(team_id=123, created_by_id=456).environment == expected_environment
    assert serializer.to_contract(team_id=123, created_by_id=456).workspace == expected_workspace


@pytest.mark.parametrize(
    "workspace",
    (
        {},
        {"type": "unknown"},
        {"type": "local_folder"},
        {"type": "git_repository"},
    ),
)
def test_create_request_rejects_invalid_workspace(workspace: dict[str, object]) -> None:
    serializer = WizardRunCreateRequestSerializer(
        data={"program_id": "posthog-integration", "environment": "local", "workspace": workspace}
    )

    assert not serializer.is_valid()
    assert "workspace" in serializer.errors


@pytest.mark.parametrize("repository", ("posthog", "/posthog", "posthog/", "posthog/posthog/extra"))
def test_create_request_rejects_invalid_repository(repository: str) -> None:
    serializer = WizardRunCreateRequestSerializer(
        data={
            "program_id": "posthog-integration",
            "environment": "cloud",
            "workspace": {"type": "git_repository", "repository": repository},
        }
    )

    assert not serializer.is_valid()
    assert "workspace" in serializer.errors
