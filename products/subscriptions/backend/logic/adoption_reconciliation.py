"""Bounded reconciliation for prepared proactive artifacts."""

from __future__ import annotations

from uuid import UUID

from django.db.models import Q
from django.utils import timezone

import structlog

from products.subscriptions.backend.facade.adoption import reconcile_prepared_artifact
from products.subscriptions.backend.models import ProactivePreparedArtifact

logger = structlog.get_logger(__name__)

_ADOPTION_RECONCILIATION_BATCH_SIZE = 20


def reconcile_proactive_artifact_adoptions_batch() -> None:
    """Reconcile a stable batch, re-scoping every cross-team candidate before use."""
    candidates: list[tuple[int, UUID]] = list(
        ProactivePreparedArtifact.objects.unscoped()  # nosemgrep: idor-lookup-without-team (bounded system reconciler; each candidate is re-scoped before use)
        .filter(adopted_at__isnull=True)
        .filter(
            Q(
                kind=ProactivePreparedArtifact.Kind.DRAFT_PR,
                status__in=[
                    ProactivePreparedArtifact.Status.PREPARING,
                    ProactivePreparedArtifact.Status.PREPARED,
                ],
            )
            & (
                Q(task_publication_id__isnull=False)
                | Q(
                    status=ProactivePreparedArtifact.Status.PREPARED,
                    prior_artifact_id__isnull=False,
                )
            )
            | Q(
                kind=ProactivePreparedArtifact.Kind.EXPERIMENT_DRAFT,
                status=ProactivePreparedArtifact.Status.PREPARED,
                experiment_id__isnull=False,
            )
        )
        .order_by("updated_at", "id")
        .values_list("team_id", "id")[:_ADOPTION_RECONCILIATION_BATCH_SIZE]
    )
    for team_id, artifact_id in candidates:
        try:
            reconcile_prepared_artifact(team_id=team_id, artifact_id=artifact_id)
        except Exception:
            logger.exception(
                "proactive_artifact_adoption_reconciliation_failed",
                team_id=team_id,
                artifact_id=str(artifact_id),
            )
        finally:
            ProactivePreparedArtifact.objects.for_team(team_id).filter(id=artifact_id).update(updated_at=timezone.now())
