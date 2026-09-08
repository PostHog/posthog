from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from django.core.exceptions import ValidationError
from django.utils import timezone

from posthog.models import Team
from posthog.models.scoping import team_scope

from products.experiments.backend.facade.contracts import PulseExperimentLifecycleResult
from products.subscriptions.backend.facade import adoption
from products.subscriptions.backend.facade.outcomes import ProvisionedOutcome
from products.subscriptions.backend.logic import adoption_reconciliation
from products.subscriptions.backend.models import (
    ProactivePreparedArtifact,
    ProactiveRecommendation,
    ProactiveRecommendationRun,
)
from products.subscriptions.backend.tasks import tasks as subscription_tasks
from products.tasks.backend.facade.draft_publication import DraftPublicationLifecycleResult


def test_reconciliation_task_delegates_to_the_bounded_batch(monkeypatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(
        subscription_tasks,
        "reconcile_proactive_artifact_adoptions_batch",
        lambda: calls.append(True),
    )

    subscription_tasks.reconcile_proactive_artifact_adoptions.run()

    assert calls == [True]


def create_artifact(
    team: Team,
    *,
    kind: str = ProactivePreparedArtifact.Kind.EXPERIMENT_DRAFT,
    status: str = ProactivePreparedArtifact.Status.PREPARING,
    task_publication_id: UUID | None = None,
    experiment_id: int | None = None,
    prior_artifact: ProactivePreparedArtifact | None = None,
) -> ProactivePreparedArtifact:
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
        kind=kind,
        status=status,
        artifact_config_hash="c" * 64,
        input_hash="d" * 64,
        task_publication_id=task_publication_id,
        experiment_id=experiment_id,
        prior_artifact=prior_artifact,
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


@pytest.mark.django_db
def test_reconcile_preparing_pr_promotes_an_authoritatively_open_pr(team, monkeypatch) -> None:
    publication_id = uuid4()
    artifact = create_artifact(
        team,
        kind=ProactivePreparedArtifact.Kind.DRAFT_PR,
        task_publication_id=publication_id,
    )
    monkeypatch.setattr(
        adoption,
        "get_draft_publication_lifecycle",
        lambda **_kwargs: DraftPublicationLifecycleResult(
            publication_id=publication_id,
            local_status="published",
            remote_state="open",
            pr_number=1,
            pr_url="https://github.com/example/repository/pull/1",
        ),
    )

    adoption.reconcile_prepared_artifact(team_id=team.id, artifact_id=artifact.id)

    artifact.refresh_from_db()
    assert artifact.status == ProactivePreparedArtifact.Status.PREPARED
    assert artifact.url == "https://github.com/example/repository/pull/1"
    assert artifact.prepared_at is not None
    assert artifact.adoption_source is None
    assert artifact.adopted_at is None


@pytest.mark.django_db
def test_reconcile_merged_pr_preserves_the_first_authoritative_timestamp(team, monkeypatch) -> None:
    publication_id = uuid4()
    artifact = create_artifact(
        team,
        kind=ProactivePreparedArtifact.Kind.DRAFT_PR,
        status=ProactivePreparedArtifact.Status.PREPARED,
        task_publication_id=publication_id,
    )
    merged_at = timezone.now() - timedelta(hours=1)

    monkeypatch.setattr(
        adoption,
        "get_draft_publication_lifecycle",
        lambda **_kwargs: DraftPublicationLifecycleResult(
            publication_id=publication_id,
            local_status="published",
            remote_state="merged",
            pr_number=1,
            pr_url="https://github.com/example/repository/pull/1",
            merged_at=merged_at,
        ),
    )
    adoption.reconcile_prepared_artifact(team_id=team.id, artifact_id=artifact.id)

    later_merged_at = timezone.now()
    monkeypatch.setattr(
        adoption,
        "get_draft_publication_lifecycle",
        lambda **_kwargs: DraftPublicationLifecycleResult(
            publication_id=publication_id,
            local_status="published",
            remote_state="merged",
            pr_number=1,
            pr_url="https://github.com/example/repository/pull/1",
            merged_at=later_merged_at,
        ),
    )
    adoption.reconcile_prepared_artifact(team_id=team.id, artifact_id=artifact.id)

    artifact.refresh_from_db()
    assert artifact.status == ProactivePreparedArtifact.Status.ADOPTED
    assert artifact.adoption_source == ProactivePreparedArtifact.AdoptionSource.DRAFT_PR_MERGED
    assert artifact.adopted_at == merged_at


@pytest.mark.django_db
def test_reconcile_activated_experiment_records_start_date_as_adoption_timestamp(team, monkeypatch) -> None:
    artifact = create_artifact(
        team,
        status=ProactivePreparedArtifact.Status.PREPARED,
        experiment_id=123,
    )
    started_at = timezone.now() - timedelta(minutes=5)
    monkeypatch.setattr(
        adoption,
        "get_pulse_experiment_lifecycle",
        lambda **_kwargs: PulseExperimentLifecycleResult(
            experiment_id=123,
            state="activated",
            start_date=started_at,
        ),
    )

    adoption.reconcile_prepared_artifact(team_id=team.id, artifact_id=artifact.id)

    artifact.refresh_from_db()
    assert artifact.status == ProactivePreparedArtifact.Status.ADOPTED
    assert artifact.adoption_source == ProactivePreparedArtifact.AdoptionSource.EXPERIMENT_ACTIVATED
    assert artifact.adopted_at == started_at


@pytest.mark.django_db
def test_adoption_dispatches_one_new_pending_outcome_only_after_commit(
    team, monkeypatch, django_capture_on_commit_callbacks
) -> None:
    artifact = create_artifact(team, status=ProactivePreparedArtifact.Status.PREPARED, experiment_id=123)
    due_at = datetime(2026, 9, 15, tzinfo=UTC)
    outcome_id = uuid4()
    dispatched: list[tuple[int, UUID, datetime]] = []
    monkeypatch.setattr(
        adoption,
        "get_pulse_experiment_lifecycle",
        lambda **_kwargs: PulseExperimentLifecycleResult(
            experiment_id=123,
            state="activated",
            start_date=timezone.now() - timedelta(minutes=5),
        ),
    )
    monkeypatch.setattr(
        adoption,
        "provision_outcome_for_adopted_artifact",
        lambda **_kwargs: ProvisionedOutcome(outcome_id=outcome_id, status="pending", created=True, due_at=due_at),
    )
    monkeypatch.setattr(
        adoption,
        "start_proactive_outcome_readout",
        lambda *, team_id, outcome_id, due_at: dispatched.append((team_id, outcome_id, due_at)),
    )

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        adoption.reconcile_prepared_artifact(team_id=team.id, artifact_id=artifact.id)
        assert dispatched == []

    assert len(callbacks) == 1
    callbacks[0]()
    adoption.reconcile_prepared_artifact(team_id=team.id, artifact_id=artifact.id)
    assert dispatched == [(team.id, outcome_id, due_at)]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "provisioned",
    [
        ProvisionedOutcome(outcome_id=uuid4(), status="unavailable", created=True, due_at=None),
        ProvisionedOutcome(
            outcome_id=uuid4(), status="pending", created=False, due_at=datetime(2026, 9, 15, tzinfo=UTC)
        ),
    ],
)
def test_adoption_does_not_dispatch_unavailable_or_preexisting_outcomes(
    team, monkeypatch, django_capture_on_commit_callbacks, provisioned: ProvisionedOutcome
) -> None:
    artifact = create_artifact(team, status=ProactivePreparedArtifact.Status.PREPARED, experiment_id=123)
    monkeypatch.setattr(
        adoption,
        "get_pulse_experiment_lifecycle",
        lambda **_kwargs: PulseExperimentLifecycleResult(
            experiment_id=123,
            state="activated",
            start_date=timezone.now() - timedelta(minutes=5),
        ),
    )
    monkeypatch.setattr(adoption, "provision_outcome_for_adopted_artifact", lambda **_kwargs: provisioned)
    dispatched: list[object] = []
    monkeypatch.setattr(adoption, "start_proactive_outcome_readout", lambda **_kwargs: dispatched.append(object()))

    with django_capture_on_commit_callbacks(execute=True):
        adoption.reconcile_prepared_artifact(team_id=team.id, artifact_id=artifact.id)

    assert dispatched == []


@pytest.mark.django_db
def test_rolled_back_adoption_does_not_dispatch_outcome(team, monkeypatch, django_capture_on_commit_callbacks) -> None:
    artifact = create_artifact(team, status=ProactivePreparedArtifact.Status.PREPARED, experiment_id=123)
    monkeypatch.setattr(
        adoption,
        "get_pulse_experiment_lifecycle",
        lambda **_kwargs: PulseExperimentLifecycleResult(
            experiment_id=123,
            state="activated",
            start_date=timezone.now() - timedelta(minutes=5),
        ),
    )
    monkeypatch.setattr(
        adoption,
        "provision_outcome_for_adopted_artifact",
        lambda **_kwargs: ProvisionedOutcome(
            outcome_id=uuid4(), status="pending", created=True, due_at=datetime(2026, 9, 15, tzinfo=UTC)
        ),
    )
    dispatched: list[object] = []
    monkeypatch.setattr(adoption, "start_proactive_outcome_readout", lambda **_kwargs: dispatched.append(object()))

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        with pytest.raises(RuntimeError, match="rollback"):
            with adoption.transaction.atomic():
                adoption.reconcile_prepared_artifact(team_id=team.id, artifact_id=artifact.id)
                raise RuntimeError("rollback")

    assert callbacks == []
    assert dispatched == []


@pytest.mark.django_db
def test_reconcile_linked_prior_pr_adopts_from_the_prior_exact_lifecycle(team, monkeypatch) -> None:
    prior = create_artifact(
        team,
        kind=ProactivePreparedArtifact.Kind.DRAFT_PR,
        status=ProactivePreparedArtifact.Status.PREPARED,
        task_publication_id=uuid4(),
    )
    linked = create_artifact(
        team,
        kind=ProactivePreparedArtifact.Kind.DRAFT_PR,
        status=ProactivePreparedArtifact.Status.PREPARED,
        prior_artifact=prior,
    )
    merged_at = timezone.now() - timedelta(minutes=5)

    def lifecycle(*, team_id: int, caller_id: UUID, publication_id: UUID) -> DraftPublicationLifecycleResult:
        assert team_id == team.id
        assert caller_id == prior.run.delivery_id
        assert publication_id == prior.task_publication_id
        return DraftPublicationLifecycleResult(
            publication_id=publication_id,
            local_status="published",
            remote_state="merged",
            pr_number=1,
            pr_url="https://github.com/example/repository/pull/1",
            merged_at=merged_at,
        )

    monkeypatch.setattr(adoption, "get_draft_publication_lifecycle", lifecycle)

    adoption.reconcile_prepared_artifact(team_id=team.id, artifact_id=linked.id)

    linked.refresh_from_db()
    assert linked.status == ProactivePreparedArtifact.Status.ADOPTED
    assert linked.adoption_source == ProactivePreparedArtifact.AdoptionSource.DRAFT_PR_MERGED
    assert linked.adopted_at == merged_at


@pytest.mark.django_db
@pytest.mark.parametrize("relation", ["cross_team", "self"])
def test_reconcile_corrupt_prior_pr_relation_confers_no_authority(team, monkeypatch, relation) -> None:
    linked = create_artifact(
        team,
        kind=ProactivePreparedArtifact.Kind.DRAFT_PR,
        status=ProactivePreparedArtifact.Status.PREPARED,
    )
    if relation == "cross_team":
        other_team = Team.objects.create(organization=team.organization, name="Other team")
        prior = create_artifact(
            other_team,
            kind=ProactivePreparedArtifact.Kind.DRAFT_PR,
            status=ProactivePreparedArtifact.Status.PREPARED,
            task_publication_id=uuid4(),
        )
        prior_id = prior.id
    else:
        prior_id = linked.id
    ProactivePreparedArtifact.objects.for_team(team.id).filter(id=linked.id).update(prior_artifact_id=prior_id)
    monkeypatch.setattr(
        adoption,
        "get_draft_publication_lifecycle",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("corrupt relation must not read lifecycle")),
    )

    adoption.reconcile_prepared_artifact(team_id=team.id, artifact_id=linked.id)

    linked.refresh_from_db()
    assert linked.status == ProactivePreparedArtifact.Status.PREPARED
    assert linked.adopted_at is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("remote_state", "merged_at"),
    [
        ("unknown", None),
        ("closed", None),
        ("merged", None),
    ],
)
def test_reconcile_non_adoption_pr_lifecycle_is_a_noop(team, monkeypatch, remote_state, merged_at) -> None:
    publication_id = uuid4()
    artifact = create_artifact(
        team,
        kind=ProactivePreparedArtifact.Kind.DRAFT_PR,
        status=ProactivePreparedArtifact.Status.PREPARED,
        task_publication_id=publication_id,
    )
    monkeypatch.setattr(
        adoption,
        "get_draft_publication_lifecycle",
        lambda **_kwargs: DraftPublicationLifecycleResult(
            publication_id=publication_id,
            local_status="published",
            remote_state=remote_state,
            pr_number=1,
            pr_url="https://github.com/example/repository/pull/1",
            merged_at=merged_at,
        ),
    )

    adoption.reconcile_prepared_artifact(team_id=team.id, artifact_id=artifact.id)

    artifact.refresh_from_db()
    assert artifact.status == ProactivePreparedArtifact.Status.PREPARED
    assert artifact.adoption_source is None
    assert artifact.adopted_at is None


@pytest.mark.django_db
def test_reconciliation_task_rotates_a_bounded_cross_team_batch(team, monkeypatch) -> None:
    other_team = Team.objects.create(organization=team.organization, name="Other team")
    created: list[ProactivePreparedArtifact] = []
    for index in range(adoption_reconciliation._ADOPTION_RECONCILIATION_BATCH_SIZE + 1):
        owner = team if index % 2 == 0 else other_team
        artifact = create_artifact(
            owner,
            status=ProactivePreparedArtifact.Status.PREPARED,
            experiment_id=index + 1,
        )
        ProactivePreparedArtifact.objects.for_team(owner.id).filter(id=artifact.id).update(
            updated_at=timezone.now()
            - timedelta(seconds=adoption_reconciliation._ADOPTION_RECONCILIATION_BATCH_SIZE - index)
        )
        created.append(artifact)

    seen: list[tuple[int, UUID]] = []
    monkeypatch.setattr(
        adoption_reconciliation,
        "reconcile_prepared_artifact",
        lambda *, team_id, artifact_id: seen.append((team_id, artifact_id)),
    )

    adoption_reconciliation.reconcile_proactive_artifact_adoptions_batch()

    assert seen == [(artifact.team_id, artifact.id) for artifact in created[:-1]]
    assert {team_id for team_id, _artifact_id in seen} == {team.id, other_team.id}

    seen.clear()
    subscription_tasks.reconcile_proactive_artifact_adoptions.run()

    assert seen[0] == (created[-1].team_id, created[-1].id)


@pytest.mark.django_db
def test_reconciliation_task_continues_after_one_artifact_failure(team, monkeypatch) -> None:
    first = create_artifact(team, status=ProactivePreparedArtifact.Status.PREPARED, experiment_id=1)
    second = create_artifact(team, status=ProactivePreparedArtifact.Status.PREPARED, experiment_id=2)
    first_updated_at = timezone.now() - timedelta(minutes=2)
    ProactivePreparedArtifact.objects.for_team(team.id).filter(id=first.id).update(updated_at=first_updated_at)
    ProactivePreparedArtifact.objects.for_team(team.id).filter(id=second.id).update(
        updated_at=first_updated_at + timedelta(seconds=1)
    )
    seen: list[UUID] = []

    def reconcile(*, team_id: int, artifact_id: UUID) -> None:
        if artifact_id == first.id:
            raise RuntimeError("transient lifecycle read failure")
        assert team_id == team.id
        seen.append(artifact_id)

    monkeypatch.setattr(adoption_reconciliation, "reconcile_prepared_artifact", reconcile)

    adoption_reconciliation.reconcile_proactive_artifact_adoptions_batch()

    assert seen == [second.id]
    first.refresh_from_db()
    assert first.updated_at > first_updated_at
