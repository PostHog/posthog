from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from django.utils import timezone

from products.subscriptions.backend.facade import artifacts
from products.subscriptions.backend.facade.artifacts import (
    PreparedArtifactClaimInput,
    PreparedArtifactFailureInput,
    PrepareDraftPRInput,
    PrepareExperimentDraftInput,
    claim_prepared_artifact,
    mark_prepared_artifact_failed,
    prepare_draft_pr,
    prepare_experiment_draft,
)
from products.subscriptions.backend.models import (
    ProactivePreparedArtifact,
    ProactiveRecommendation,
    ProactiveRecommendationRun,
)
from products.tasks.backend.facade.staged_execution import AdvancedStagedTask
from products.tasks.backend.models import Task, TaskDraftPublication, TaskRun, TaskStagedRun


@pytest.fixture(autouse=True)
def enable_artifact_preparation(settings) -> None:
    settings.PULSE_ARTIFACT_PREPARATION_ENABLED = True


@pytest.mark.django_db
def test_prepare_experiment_draft_completes_the_claim_once(team, user) -> None:
    run = ProactiveRecommendationRun.objects.for_team(team.id).create(
        team_id=team.id,
        subscription_id=123,
        delivery_id=uuid4(),
        actor_id=user.id,
        snapshot_hash="a" * 64,
        artifact_config_hash="b" * 64,
        status=ProactiveRecommendationRun.Status.COMPLETED,
    )
    ProactiveRecommendation.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        semantic_key="experiment",
        recommendation={
            "kind": "experiment",
            "title": "Improve checkout completion",
            "target": "The checkout flow",
            "metric_direction": "increase",
            "expected_metric_movement": "completed purchases",
        },
        citations=[],
    )
    claimed = claim_prepared_artifact(PreparedArtifactClaimInput(team_id=team.id, run_id=run.id, actor_id=user.id))
    assert claimed is not None

    prepared = prepare_experiment_draft(
        PrepareExperimentDraftInput(team_id=team.id, artifact_id=claimed.id, actor_id=user.id)
    )
    replayed = prepare_experiment_draft(
        PrepareExperimentDraftInput(team_id=team.id, artifact_id=claimed.id, actor_id=user.id)
    )

    claimed_row = ProactivePreparedArtifact.objects.for_team(team.id).get(id=claimed.id)
    assert replayed == prepared
    assert claimed_row.status == ProactivePreparedArtifact.Status.PREPARED
    assert claimed_row.experiment_id == prepared.experiment_id
    assert claimed_row.feature_flag_id == prepared.feature_flag_id
    assert claimed_row.url == f"/project/{team.id}/experiments/{prepared.experiment_id}"
    assert claimed_row.prepared_at == prepared.prepared_at
    assert claimed_row.prepared_at is not None

    failed = mark_prepared_artifact_failed(
        PreparedArtifactFailureInput(team_id=team.id, artifact_id=claimed.id, failure_code="provider_unavailable")
    )
    assert failed.status == "prepared"


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


@pytest.mark.django_db
def test_prepare_draft_pr_links_an_exact_open_prior_artifact_without_execution(team, monkeypatch) -> None:
    prior_publication_id = uuid4()
    prior_run = ProactiveRecommendationRun.objects.for_team(team.id).create(
        team_id=team.id,
        subscription_id=123,
        delivery_id=uuid4(),
        actor_id=456,
        snapshot_hash="a" * 64,
        artifact_config_hash="b" * 64,
        status=ProactiveRecommendationRun.Status.COMPLETED,
    )
    prior_recommendation = ProactiveRecommendation.objects.for_team(team.id).create(
        team_id=team.id,
        run=prior_run,
        semantic_key="same-recommendation",
        recommendation={"kind": "product_change"},
        citations=[],
    )
    prior = ProactivePreparedArtifact.objects.for_team(team.id).create(
        team_id=team.id,
        run=prior_run,
        recommendation=prior_recommendation,
        kind=ProactivePreparedArtifact.Kind.DRAFT_PR,
        artifact_config_hash="b" * 64,
        input_hash="c" * 64,
        task_publication_id=prior_publication_id,
    )
    run = ProactiveRecommendationRun.objects.for_team(team.id).create(
        team_id=team.id,
        subscription_id=123,
        delivery_id=uuid4(),
        actor_id=456,
        snapshot_hash="d" * 64,
        artifact_config_hash="e" * 64,
        status=ProactiveRecommendationRun.Status.COMPLETED,
    )
    recommendation = ProactiveRecommendation.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        semantic_key="same-recommendation",
        recommendation={"kind": "product_change"},
        citations=[],
    )
    current = ProactivePreparedArtifact.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        recommendation=recommendation,
        kind=ProactivePreparedArtifact.Kind.DRAFT_PR,
        artifact_config_hash="e" * 64,
        input_hash="f" * 64,
    )
    monkeypatch.setattr(
        artifacts,
        "get_draft_publication_lifecycle",
        lambda **_kwargs: artifacts.DraftPublicationLifecycleResult(
            publication_id=prior_publication_id,
            local_status="published",
            remote_state="open",
            pr_number=17,
            pr_url="https://github.com/example/repository/pull/17",
        ),
    )
    monkeypatch.setattr(artifacts, "_matches_durable_replay", lambda **_kwargs: True)
    advance = monkeypatch.setattr(artifacts, "advance_staged_task", lambda _input: pytest.fail("must not advance"))
    assert advance is None

    result = prepare_draft_pr(PrepareDraftPRInput(team_id=team.id, artifact_id=current.id, actor_id=456))

    current.refresh_from_db()
    prior.refresh_from_db()
    assert result.prior_artifact_id == prior.id
    assert current.prior_artifact_id == prior.id
    assert current.status == ProactivePreparedArtifact.Status.PREPARED
    assert current.url == "https://github.com/example/repository/pull/17"
    assert prior.prepared_at is None


@pytest.mark.django_db
def test_artifact_writes_are_disabled_by_default(team, settings) -> None:
    settings.PULSE_ARTIFACT_PREPARATION_ENABLED = False
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

    assert claim_prepared_artifact(PreparedArtifactClaimInput(team_id=team.id, run_id=run.id, actor_id=456)) is None
    assert not ProactivePreparedArtifact.objects.for_team(team.id).exists()


@pytest.mark.django_db
def test_prepare_draft_pr_replays_its_own_exact_tasks_reservation_before_new_prior_links(
    team, user, monkeypatch
) -> None:
    task = Task.objects.create(
        team=team,
        created_by=user,
        title="Prepare recommendation",
        description="Prepare a draft recommendation change.",
        origin_product="pulse",
    )
    analysis_run = TaskRun.objects.create(task=task, team=team, status=TaskRun.Status.COMPLETED)
    execution_run = TaskRun.objects.create(task=task, team=team, status=TaskRun.Status.IN_PROGRESS)
    staged_run = TaskStagedRun.objects.for_team(team.id).create(
        team=team,
        caller_id=uuid4(),
        task=task,
        analysis_run=analysis_run,
        execution_run=execution_run,
        repository="example/repository",
        base_sha="a" * 40,
        base_branch="main",
        github_integration_id=1,
        github_user_integration_id=uuid4(),
        github_installation_id="installation-1",
        grant_version="v1",
        analysis_manifest={"version": 1, "phase": "analysis", "mcp_scope_preset": "read_only", "disabled_tools": []},
        execution_manifest={"version": 1, "phase": "execution", "mcp_scope_preset": "read_only", "disabled_tools": []},
        create_idempotency_key="create-key",
        advance_idempotency_key="advance-key",
    )
    run = ProactiveRecommendationRun.objects.for_team(team.id).create(
        team_id=team.id,
        subscription_id=123,
        delivery_id=staged_run.caller_id,
        actor_id=user.id,
        snapshot_hash="b" * 64,
        artifact_config_hash="c" * 64,
        staged_run_id=staged_run.id,
        repository_binding={
            "repository": "example/repository",
            "base_sha": "a" * 40,
            "base_branch": "main",
            "github_integration_id": 1,
            "github_user_integration_id": str(staged_run.github_user_integration_id),
            "github_installation_id": "installation-1",
            "grant_version": "v1",
        },
        status=ProactiveRecommendationRun.Status.COMPLETED,
    )
    recommendation = ProactiveRecommendation.objects.for_team(team.id).create(
        team_id=team.id,
        run=run,
        semantic_key="exact-replay",
        recommendation={
            "kind": "product_change",
            "title": "Add a safe check",
            "target": "The recommendation flow",
            "rationale": "Protect exact retries",
        },
        citations=[],
    )
    monkeypatch.setattr(artifacts, "revalidate_staged_repository_binding", lambda **_kwargs: True)
    claimed = claim_prepared_artifact(PreparedArtifactClaimInput(team_id=team.id, run_id=run.id, actor_id=user.id))
    assert claimed is not None
    ProactivePreparedArtifact.objects.for_team(team.id).filter(id=claimed.id).update(
        created_at=timezone.now() - timedelta(hours=2)
    )

    advance_calls: list[object] = []

    def advance(input: object) -> AdvancedStagedTask:
        advance_calls.append(input)
        return AdvancedStagedTask(
            staged_run_id=staged_run.id,
            task_id=task.id,
            analysis_run_id=analysis_run.id,
            execution_run_id=execution_run.id,
        )

    monkeypatch.setattr(artifacts, "advance_staged_task", advance)

    first = prepare_draft_pr(PrepareDraftPRInput(team_id=team.id, artifact_id=claimed.id, actor_id=user.id))
    prior_run = ProactiveRecommendationRun.objects.for_team(team.id).create(
        team_id=team.id,
        subscription_id=run.subscription_id,
        delivery_id=uuid4(),
        actor_id=user.id,
        snapshot_hash="d" * 64,
        artifact_config_hash="e" * 64,
        status=ProactiveRecommendationRun.Status.COMPLETED,
    )
    prior_recommendation = ProactiveRecommendation.objects.for_team(team.id).create(
        team_id=team.id,
        run=prior_run,
        semantic_key=recommendation.semantic_key,
        recommendation={"kind": "product_change"},
        citations=[],
    )
    assert prior_run.artifact_config_hash is not None
    ProactivePreparedArtifact.objects.for_team(team.id).create(
        team_id=team.id,
        run=prior_run,
        recommendation=prior_recommendation,
        kind=ProactivePreparedArtifact.Kind.DRAFT_PR,
        artifact_config_hash=prior_run.artifact_config_hash,
        input_hash="f" * 64,
        task_publication_id=uuid4(),
    )
    monkeypatch.setattr(artifacts, "get_draft_publication_lifecycle", lambda **_kwargs: pytest.fail("must not relink"))
    execution_run.status = TaskRun.Status.COMPLETED
    execution_run.save(update_fields=["status"])

    second = prepare_draft_pr(PrepareDraftPRInput(team_id=team.id, artifact_id=claimed.id, actor_id=user.id))

    claimed_row = ProactivePreparedArtifact.objects.for_team(team.id).get(id=claimed.id)
    publications = TaskDraftPublication.objects.for_team(team.id).filter(staged_run_id=staged_run.id)
    assert first == second
    assert first.publication_id == claimed_row.task_publication_id
    assert first.staged_run_id == staged_run.id
    assert claimed_row.status == ProactivePreparedArtifact.Status.PREPARING
    assert claimed_row.prior_artifact_id is None
    assert publications.count() == 1
    publication = publications.get()
    assert publication.starts_before > timezone.now()
    assert publication.starts_before <= timezone.now() + timedelta(hours=1)
    assert len(advance_calls) == 1


@pytest.mark.django_db
def test_transient_artifact_preparation_failure_remains_retryable(team, monkeypatch) -> None:
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
    monkeypatch.setattr(artifacts, "prepare_experiment_draft", lambda _input: (_ for _ in ()).throw(RuntimeError()))

    with pytest.raises(RuntimeError):
        artifacts.prepare_proactive_artifact_for_run(team_id=team.id, run_id=run.id)

    artifact = ProactivePreparedArtifact.objects.for_team(team.id).get(run=run)
    assert artifact.status == ProactivePreparedArtifact.Status.PREPARING
