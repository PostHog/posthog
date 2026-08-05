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

    Each push fully replaces `report` / `error` / `task_run_id` — the row always
    reflects the latest detection run for the (repository, kind) key. Concurrent
    POSTs for a brand-new key can race the unique constraint and surface as a
    500; the client's normal HTTP retry handles that on the next attempt.
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
