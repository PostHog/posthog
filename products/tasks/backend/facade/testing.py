from uuid import UUID

from products.tasks.backend.models import TaskArtifact


def create_task_artifact(*, team_id: int, task_id: UUID, task_run_id: UUID, name: str) -> UUID:
    return (
        TaskArtifact.objects.for_team(team_id)
        .create(
            team_id=team_id,
            task_id=task_id,
            task_run_id=task_run_id,
            name=name,
            artifact_type=TaskArtifact.ArtifactType.DOCUMENT,
            adapter=TaskArtifact.Adapter.DOCUMENT_CONNECTOR,
        )
        .id
    )
