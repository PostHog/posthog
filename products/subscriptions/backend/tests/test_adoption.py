from __future__ import annotations

from uuid import uuid4

import pytest

from django.core.exceptions import ValidationError
from django.utils import timezone

from posthog.models.scoping import team_scope

from products.subscriptions.backend.models import (
    ProactivePreparedArtifact,
    ProactiveRecommendation,
    ProactiveRecommendationRun,
)


def create_artifact(team) -> ProactivePreparedArtifact:
    run = ProactiveRecommendationRun.objects.for_team(team.id).create(
        team_id=team.id,
        subscription_id=123,
        delivery_id=uuid4(),
        actor_id=456,
        snapshot_hash="a" * 64,
        artifact_config_hash="b" * 64,
        status=ProactiveRecommendationRun.Status.COMPLETED,
    )
    recommendation = ProactiveRecommendation.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        semantic_key="experiment",
        recommendation={"kind": "experiment"},
        citations=[],
    )
    return ProactivePreparedArtifact.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        recommendation=recommendation,
        kind=ProactivePreparedArtifact.Kind.EXPERIMENT_DRAFT,
        artifact_config_hash="c" * 64,
        input_hash="d" * 64,
    )


@pytest.mark.django_db
def test_artifact_adoption_fields_default_to_unset_and_persist_closed_source(team) -> None:
    artifact = create_artifact(team)
    adopted_at = timezone.now()

    assert artifact.status == ProactivePreparedArtifact.Status.PREPARING
    assert artifact.adoption_source is None
    assert artifact.adopted_at is None

    artifact.status = ProactivePreparedArtifact.Status.ADOPTED
    artifact.adoption_source = ProactivePreparedArtifact.AdoptionSource.EXPERIMENT_ACTIVATED
    artifact.adopted_at = adopted_at
    with team_scope(team.id):
        artifact.full_clean()
    artifact.save()

    persisted = ProactivePreparedArtifact.objects.for_team(team.id).get(id=artifact.id)
    assert persisted.status == ProactivePreparedArtifact.Status.ADOPTED
    assert persisted.adoption_source == ProactivePreparedArtifact.AdoptionSource.EXPERIMENT_ACTIVATED
    assert persisted.adopted_at == adopted_at


@pytest.mark.django_db
def test_artifact_adoption_source_rejects_unknown_value(team) -> None:
    artifact = create_artifact(team)
    artifact.status = ProactivePreparedArtifact.Status.ADOPTED
    artifact.adoption_source = "manual_override"

    with pytest.raises(ValidationError, match="not a valid choice"):
        with team_scope(team.id):
            artifact.full_clean()
