"""One-way reconciliation of prepared Pulse artifacts with authoritative lifecycle facts."""

from __future__ import annotations

from datetime import datetime
from functools import partial
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from products.experiments.backend.facade import get_pulse_experiment_lifecycle
from products.subscriptions.backend.facade.outcomes import provision_outcome_for_adopted_artifact
from products.subscriptions.backend.models import ProactivePreparedArtifact
from products.subscriptions.backend.temporal.client import start_proactive_outcome_readout
from products.tasks.backend.facade.draft_publication import get_draft_publication_lifecycle


def reconcile_prepared_artifact(*, team_id: int, artifact_id: UUID) -> None:
    """Record one authoritative adoption fact, if the exact artifact is still eligible.

    Lifecycle reads deliberately happen before the conditional local update. This keeps
    network-backed authority outside a transaction and lets concurrent replays preserve
    the first observed source and timestamp.
    """
    artifact = ProactivePreparedArtifact.objects.for_team(team_id).select_related("run").filter(id=artifact_id).first()
    if artifact is None or artifact.adopted_at is not None:
        return

    if artifact.kind == ProactivePreparedArtifact.Kind.DRAFT_PR:
        _reconcile_draft_pr(artifact=artifact)
    elif artifact.kind == ProactivePreparedArtifact.Kind.EXPERIMENT_DRAFT:
        _reconcile_experiment_draft(artifact=artifact)


def _reconcile_draft_pr(*, artifact: ProactivePreparedArtifact) -> None:
    binding = _draft_publication_binding(artifact=artifact)
    if binding is None:
        return

    lifecycle = get_draft_publication_lifecycle(
        team_id=artifact.team_id,
        caller_id=binding.caller_id,
        publication_id=binding.publication_id,
    )
    if lifecycle.remote_state == "merged" and lifecycle.merged_at is not None:
        _adopt_artifact(
            team_id=artifact.team_id,
            artifact_id=artifact.id,
            kind=ProactivePreparedArtifact.Kind.DRAFT_PR,
            adoption_source=ProactivePreparedArtifact.AdoptionSource.DRAFT_PR_MERGED,
            adopted_at=lifecycle.merged_at,
        )
    elif binding.is_own_publication and lifecycle.remote_state == "open":
        ProactivePreparedArtifact.objects.for_team(artifact.team_id).filter(
            id=artifact.id,
            kind=ProactivePreparedArtifact.Kind.DRAFT_PR,
            status=ProactivePreparedArtifact.Status.PREPARING,
            adopted_at__isnull=True,
        ).update(
            status=ProactivePreparedArtifact.Status.PREPARED,
            url=lifecycle.pr_url,
            prepared_at=timezone.now(),
            updated_at=timezone.now(),
        )


def _reconcile_experiment_draft(*, artifact: ProactivePreparedArtifact) -> None:
    if artifact.experiment_id is None:
        return

    lifecycle = get_pulse_experiment_lifecycle(team_id=artifact.team_id, experiment_id=artifact.experiment_id)
    if lifecycle.state != "activated" or lifecycle.start_date is None:
        return

    _adopt_artifact(
        team_id=artifact.team_id,
        artifact_id=artifact.id,
        kind=ProactivePreparedArtifact.Kind.EXPERIMENT_DRAFT,
        adoption_source=ProactivePreparedArtifact.AdoptionSource.EXPERIMENT_ACTIVATED,
        adopted_at=lifecycle.start_date,
    )


def _adopt_artifact(
    *,
    team_id: int,
    artifact_id: UUID,
    kind: str,
    adoption_source: str,
    adopted_at: datetime,
) -> None:
    """Record adoption and schedule a new eligible readout after the local commit.

    The external lifecycle was deliberately read by the caller before entering this
    transaction. A process crash after commit but before the Temporal start can miss
    this alpha readout; no second delivery ledger or recovery loop is introduced here.
    """
    with transaction.atomic():
        artifact = (
            ProactivePreparedArtifact.objects.for_team(team_id)
            .select_for_update()
            .filter(
                id=artifact_id,
                kind=kind,
                status__in=[
                    ProactivePreparedArtifact.Status.PREPARING,
                    ProactivePreparedArtifact.Status.PREPARED,
                ],
                adopted_at__isnull=True,
            )
            .first()
        )
        if artifact is None:
            return
        updated = (
            ProactivePreparedArtifact.objects.for_team(team_id)
            .filter(
                id=artifact.id,
                kind=kind,
                status__in=[
                    ProactivePreparedArtifact.Status.PREPARING,
                    ProactivePreparedArtifact.Status.PREPARED,
                ],
                adopted_at__isnull=True,
            )
            .update(
                status=ProactivePreparedArtifact.Status.ADOPTED,
                adoption_source=adoption_source,
                adopted_at=adopted_at,
                updated_at=timezone.now(),
            )
        )
        if updated != 1:
            return
        provisioned = provision_outcome_for_adopted_artifact(team_id=team_id, artifact_id=artifact.id)
        if (
            provisioned is not None
            and provisioned.created
            and provisioned.status == "pending"
            and provisioned.due_at is not None
        ):
            transaction.on_commit(
                partial(
                    start_proactive_outcome_readout,
                    team_id=team_id,
                    outcome_id=provisioned.outcome_id,
                    due_at=provisioned.due_at,
                )
            )


class _DraftPublicationBinding:
    def __init__(self, *, publication_id: UUID, caller_id: UUID, is_own_publication: bool) -> None:
        self.publication_id = publication_id
        self.caller_id = caller_id
        self.is_own_publication = is_own_publication


def _draft_publication_binding(*, artifact: ProactivePreparedArtifact) -> _DraftPublicationBinding | None:
    if artifact.task_publication_id is not None:
        return _DraftPublicationBinding(
            publication_id=artifact.task_publication_id,
            caller_id=artifact.run.delivery_id,
            is_own_publication=True,
        )
    if artifact.prior_artifact_id is None:
        return None

    prior = (
        ProactivePreparedArtifact.objects.for_team(artifact.team_id)
        .select_related("run")
        .filter(
            id=artifact.prior_artifact_id,
            kind=ProactivePreparedArtifact.Kind.DRAFT_PR,
            task_publication_id__isnull=False,
        )
        .first()
    )
    if prior is None or prior.id == artifact.id or prior.created_at >= artifact.created_at:
        return None
    assert prior.task_publication_id is not None
    return _DraftPublicationBinding(
        publication_id=prior.task_publication_id,
        caller_id=prior.run.delivery_id,
        is_own_publication=False,
    )
