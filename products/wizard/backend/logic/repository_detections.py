"""
Business logic for repository detections.
"""

from django.db import transaction

from products.wizard.backend.facade.contracts import UpsertWizardRepositoryDetectionInput, WizardRepositoryDetectionDTO
from products.wizard.backend.models import WizardRepositoryDetection


def upsert_wizard_repository_detection(
    params: UpsertWizardRepositoryDetectionInput,
) -> tuple[WizardRepositoryDetectionDTO, bool]:
    """Upsert a detection row and return (dto, created).

    Each push fully replaces `report` / `error` / `task_run_id`. Concurrent POSTs for a
    brand-new key can race the unique constraint into a 500; the client's HTTP retry covers it.
    """
    with transaction.atomic():
        defaults = {
            "report": params.report,
            "error": params.error,
            "task_run_id": params.task_run_id,
        }
        # created_by only in create_defaults so a later push for the same key can't reattribute it.
        instance, created = WizardRepositoryDetection.objects.update_or_create(
            team_id=params.team_id,
            repository=params.repository,
            kind=params.kind,
            defaults=defaults,
            create_defaults={**defaults, "created_by_id": params.created_by_id},
        )
    return _to_dto(instance), created


def record_wizard_repository_detection_run(
    *,
    team_id: int,
    repository: str,
    kind: str,
    task_run_id: str,
    created_by_id: int | None,
) -> WizardRepositoryDetectionDTO:
    """Stamp a freshly triggered cloud scan onto the (repository, kind) row.

    Only `task_run_id` changes, so the previous `report`/`error` stay readable while the scan
    runs. A row created here has both `report` and `error` null: no scan has completed yet.

    `for_team` because the trigger endpoint runs outside ambient team scope.
    """
    with transaction.atomic():
        instance, _ = WizardRepositoryDetection.objects.for_team(team_id).update_or_create(
            team_id=team_id,
            repository=repository,
            kind=kind,
            defaults={"task_run_id": task_run_id},
            create_defaults={"task_run_id": task_run_id, "created_by_id": created_by_id},
        )
    return _to_dto(instance)


def list_wizard_repository_detections(
    team_id: int, *, kind: str | None = None, limit: int = 200
) -> list[WizardRepositoryDetectionDTO]:
    """The team's detection rows, most recently updated first.

    `for_team` because the listing endpoint runs outside ambient team scope.
    """
    queryset = WizardRepositoryDetection.objects.for_team(team_id)
    if kind is not None:
        queryset = queryset.filter(kind=kind)
    return [_to_dto(instance) for instance in queryset.order_by("-updated_at")[:limit]]


def _to_dto(instance: WizardRepositoryDetection) -> WizardRepositoryDetectionDTO:
    return WizardRepositoryDetectionDTO(
        id=str(instance.id),
        team_id=instance.team_id,
        repository=instance.repository,
        kind=instance.kind,
        report=instance.report,
        error=instance.error,
        task_run_id=str(instance.task_run_id) if instance.task_run_id else None,
        created_at=instance.created_at,
        updated_at=instance.updated_at,
    )
