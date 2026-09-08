from __future__ import annotations

from uuid import uuid4

import pytest

from products.subscriptions.backend.facade import artifacts
from products.subscriptions.backend.facade.artifacts import (
    PreparedArtifactClaimInput,
    PreparedArtifactFailureInput,
    claim_prepared_artifact,
    mark_prepared_artifact_failed,
)
from products.subscriptions.backend.models import ProactiveRecommendation, ProactiveRecommendationRun


@pytest.mark.django_db
def test_claim_selects_the_first_persisted_experiment_when_an_earlier_code_recommendation_lacks_consent(team) -> None:
    """A code recommendation without frozen consent must not prevent a later experiment draft."""
    run = ProactiveRecommendationRun.objects.for_team(team.id).create(
        team_id=team.id,
        subscription_id=123,
        delivery_id=uuid4(),
        actor_id=456,
        snapshot_hash="a" * 64,
        artifact_config_hash="b" * 64,
        status=ProactiveRecommendationRun.Status.COMPLETED,
    )
    ProactiveRecommendation.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        semantic_key="code-first",
        recommendation={"kind": "product_change"},
        citations=[],
    )
    experiment = ProactiveRecommendation.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        semantic_key="experiment-second",
        recommendation={"kind": "experiment"},
        citations=[],
    )

    claim_input = PreparedArtifactClaimInput(team_id=team.id, run_id=run.id, actor_id=456)
    artifact = claim_prepared_artifact(claim_input)
    replay = claim_prepared_artifact(claim_input)

    assert artifact is not None
    assert artifact.recommendation_id == experiment.id
    assert artifact.kind == "experiment_draft"
    assert artifact.status == "preparing"
    assert replay == artifact


@pytest.mark.django_db
def test_claim_replays_an_experiment_when_earlier_code_authority_is_restored(team, monkeypatch) -> None:
    """A durable experiment claim survives a later authorization change for another recommendation."""
    run = ProactiveRecommendationRun.objects.for_team(team.id).create(
        team_id=team.id,
        subscription_id=123,
        delivery_id=uuid4(),
        actor_id=456,
        snapshot_hash="a" * 64,
        artifact_config_hash="b" * 64,
        repository_binding={
            "repository": "posthog/posthog",
            "base_sha": "c" * 40,
            "base_branch": "master",
            "github_integration_id": 123,
            "github_user_integration_id": str(uuid4()),
            "github_installation_id": "456",
            "grant_version": "current",
        },
        status=ProactiveRecommendationRun.Status.COMPLETED,
    )
    ProactiveRecommendation.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        semantic_key="code-first",
        recommendation={"kind": "product_change"},
        citations=[],
    )
    experiment = ProactiveRecommendation.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        semantic_key="experiment-second",
        recommendation={"kind": "experiment"},
        citations=[],
    )
    has_authority = False
    monkeypatch.setattr(artifacts, "revalidate_staged_repository_binding", lambda **_kwargs: has_authority)
    claim_input = PreparedArtifactClaimInput(team_id=team.id, run_id=run.id, actor_id=456)

    first = claim_prepared_artifact(claim_input)
    has_authority = True
    replay = claim_prepared_artifact(claim_input)

    assert first is not None
    assert first.recommendation_id == experiment.id
    assert replay == first


@pytest.mark.django_db
def test_artifact_failure_does_not_change_the_completed_recommendation_run(team) -> None:
    """Artifact preparation failures are local and must not rewrite report delivery state."""
    run = ProactiveRecommendationRun.objects.for_team(team.id).create(
        team_id=team.id,
        subscription_id=123,
        delivery_id=uuid4(),
        actor_id=456,
        snapshot_hash="a" * 64,
        artifact_config_hash="b" * 64,
        status=ProactiveRecommendationRun.Status.COMPLETED,
    )
    ProactiveRecommendation.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        semantic_key="experiment",
        recommendation={"kind": "experiment"},
        citations=[],
    )
    artifact = claim_prepared_artifact(PreparedArtifactClaimInput(team_id=team.id, run_id=run.id, actor_id=456))
    assert artifact is not None

    failed = mark_prepared_artifact_failed(
        PreparedArtifactFailureInput(team_id=team.id, artifact_id=artifact.id, failure_code="provider_unavailable")
    )

    run.refresh_from_db()
    assert failed.status == "failed"
    assert run.status == ProactiveRecommendationRun.Status.COMPLETED


@pytest.mark.django_db
def test_claim_keeps_the_first_persisted_code_recommendation_when_its_frozen_binding_revalidates(
    team, monkeypatch
) -> None:
    """Persisted order decides between eligible artifact kinds, rather than a new model decision."""
    run = ProactiveRecommendationRun.objects.for_team(team.id).create(
        team_id=team.id,
        subscription_id=123,
        delivery_id=uuid4(),
        actor_id=456,
        snapshot_hash="a" * 64,
        artifact_config_hash="b" * 64,
        repository_binding={
            "repository": "posthog/posthog",
            "base_sha": "c" * 40,
            "base_branch": "master",
            "github_integration_id": 123,
            "github_user_integration_id": str(uuid4()),
            "github_installation_id": "456",
            "grant_version": "current",
        },
        status=ProactiveRecommendationRun.Status.COMPLETED,
    )
    code = ProactiveRecommendation.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        semantic_key="code-first",
        recommendation={"kind": "instrumentation"},
        citations=[],
    )
    ProactiveRecommendation.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        semantic_key="experiment-second",
        recommendation={"kind": "experiment"},
        citations=[],
    )
    monkeypatch.setattr(artifacts, "revalidate_staged_repository_binding", lambda **_kwargs: True)

    artifact = claim_prepared_artifact(PreparedArtifactClaimInput(team_id=team.id, run_id=run.id, actor_id=456))

    assert artifact is not None
    assert artifact.recommendation_id == code.id
    assert artifact.kind == "draft_pr"


@pytest.mark.django_db
def test_claim_replay_rejects_changed_frozen_config_hash(team) -> None:
    """A changed analysis snapshot cannot reuse an at-most-once artifact claim."""
    run = ProactiveRecommendationRun.objects.for_team(team.id).create(
        team_id=team.id,
        subscription_id=123,
        delivery_id=uuid4(),
        actor_id=456,
        snapshot_hash="a" * 64,
        artifact_config_hash="b" * 64,
        status=ProactiveRecommendationRun.Status.COMPLETED,
    )
    ProactiveRecommendation.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        semantic_key="experiment",
        recommendation={"kind": "experiment"},
        citations=[],
    )
    claim_input = PreparedArtifactClaimInput(team_id=team.id, run_id=run.id, actor_id=456)
    assert claim_prepared_artifact(claim_input) is not None
    ProactiveRecommendationRun.objects.for_team(team.id).filter(id=run.id).update(artifact_config_hash="c" * 64)

    with pytest.raises(ValueError, match="does not match"):
        claim_prepared_artifact(claim_input)


@pytest.mark.django_db
def test_claim_does_not_create_an_artifact_for_investigation_recommendations(team) -> None:
    """Investigations have no executable artifact kind in this narrow aggregate."""
    run = ProactiveRecommendationRun.objects.for_team(team.id).create(
        team_id=team.id,
        subscription_id=123,
        delivery_id=uuid4(),
        actor_id=456,
        snapshot_hash="a" * 64,
        artifact_config_hash="b" * 64,
        status=ProactiveRecommendationRun.Status.COMPLETED,
    )
    ProactiveRecommendation.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        semantic_key="investigate",
        recommendation={"kind": "investigation"},
        citations=[],
    )

    artifact = claim_prepared_artifact(PreparedArtifactClaimInput(team_id=team.id, run_id=run.id, actor_id=456))

    assert artifact is None


@pytest.mark.django_db
def test_claim_rejects_a_malformed_frozen_repository_binding(team, monkeypatch) -> None:
    """A binding with a non-integer integration ID cannot authorize a draft PR."""
    run = ProactiveRecommendationRun.objects.for_team(team.id).create(
        team_id=team.id,
        subscription_id=123,
        delivery_id=uuid4(),
        actor_id=456,
        snapshot_hash="a" * 64,
        artifact_config_hash="b" * 64,
        repository_binding={
            "repository": "posthog/posthog",
            "base_sha": "c" * 40,
            "base_branch": "master",
            "github_integration_id": True,
            "github_user_integration_id": str(uuid4()),
            "github_installation_id": "456",
            "grant_version": "current",
        },
        status=ProactiveRecommendationRun.Status.COMPLETED,
    )
    ProactiveRecommendation.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        semantic_key="code-first",
        recommendation={"kind": "product_change"},
        citations=[],
    )
    experiment = ProactiveRecommendation.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        semantic_key="experiment-second",
        recommendation={"kind": "experiment"},
        citations=[],
    )
    monkeypatch.setattr(artifacts, "revalidate_staged_repository_binding", lambda **_kwargs: True)

    artifact = claim_prepared_artifact(PreparedArtifactClaimInput(team_id=team.id, run_id=run.id, actor_id=456))

    assert artifact is not None
    assert artifact.recommendation_id == experiment.id
