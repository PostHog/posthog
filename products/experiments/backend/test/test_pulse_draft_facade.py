from __future__ import annotations

from uuid import uuid4

import pytest

from rest_framework.exceptions import PermissionDenied

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.facade import PulseExperimentDraftInput, create_pulse_experiment_draft
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag


@pytest.mark.django_db
def test_create_pulse_experiment_draft_is_inert_and_replays_exactly(team, user, monkeypatch) -> None:
    artifact_id = uuid4()
    input = PulseExperimentDraftInput(
        team_id=team.id,
        actor_id=user.id,
        artifact_id=artifact_id,
        title="Improve checkout completion",
        target="The checkout flow",
        metric_direction="increase",
        expected_metric_movement="completed purchases",
    )

    def launch_experiment(*_args, **_kwargs) -> None:
        raise AssertionError("Pulse must not launch an experiment")

    monkeypatch.setattr(ExperimentService, "launch_experiment", launch_experiment)
    created = create_pulse_experiment_draft(input)
    replayed = create_pulse_experiment_draft(input)

    experiment = Experiment.objects.get(id=created.experiment_id)
    flag = FeatureFlag.objects.get(id=created.feature_flag_id)
    assert replayed == created
    assert FeatureFlag.objects.filter(team_id=team.id).count() == 1
    assert Experiment.objects.filter(team_id=team.id).count() == 1
    assert flag.key == f"pulse-experiment-{artifact_id.hex}"
    assert flag.active is False
    assert flag.filters == {
        "aggregation_group_type_index": None,
        "groups": [{"properties": [], "rollout_percentage": 0, "aggregation_group_type_index": None}],
        "holdout": None,
        "multivariate": {"variants": flag.variants},
    }
    assert flag.variants == [
        {"key": "control", "name": "Control Group", "rollout_percentage": 50},
        {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
    ]
    assert experiment.start_date is None
    assert experiment.metrics == []
    assert experiment.metrics_secondary == []
    assert experiment.parameters == {
        "pulse_draft": {"artifact_id": str(artifact_id), "state": "draft", "team_id": team.id}
    }
    assert experiment.description == (
        "Hypothesis: For The checkout flow, the expected metric movement is increase: completed purchases."
    )


@pytest.mark.django_db
def test_create_pulse_experiment_draft_rejects_a_matching_key_with_drifted_provenance(team, user) -> None:
    artifact_id = uuid4()
    input = PulseExperimentDraftInput(
        team_id=team.id,
        actor_id=user.id,
        artifact_id=artifact_id,
        title="Improve checkout completion",
        target="The checkout flow",
        metric_direction="increase",
        expected_metric_movement="completed purchases",
    )
    created = create_pulse_experiment_draft(input)
    Experiment.objects.filter(id=created.experiment_id).update(parameters={"pulse_draft": {"state": "draft"}})

    with pytest.raises(ValueError, match="does not match"):
        create_pulse_experiment_draft(input)

    assert FeatureFlag.objects.filter(team_id=team.id).count() == 1
    assert Experiment.objects.filter(team_id=team.id).count() == 1


@pytest.mark.django_db
def test_create_pulse_experiment_draft_rejects_a_drifted_feature_flag(team, user) -> None:
    artifact_id = uuid4()
    input = PulseExperimentDraftInput(
        team_id=team.id,
        actor_id=user.id,
        artifact_id=artifact_id,
        title="Improve checkout completion",
        target="The checkout flow",
        metric_direction="increase",
        expected_metric_movement="completed purchases",
    )
    created = create_pulse_experiment_draft(input)
    FeatureFlag.objects.filter(id=created.feature_flag_id).update(
        filters={
            "aggregation_group_type_index": None,
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "multivariate": {
                "variants": [
                    {"key": "control", "name": "Control Group", "rollout_percentage": 50},
                    {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
                ]
            },
        }
    )

    with pytest.raises(ValueError, match="does not match"):
        create_pulse_experiment_draft(input)


@pytest.mark.django_db
def test_create_pulse_experiment_draft_rejects_a_tombstoned_key(team, user) -> None:
    artifact_id = uuid4()
    input = PulseExperimentDraftInput(
        team_id=team.id,
        actor_id=user.id,
        artifact_id=artifact_id,
        title="Improve checkout completion",
        target="The checkout flow",
        metric_direction="increase",
        expected_metric_movement="completed purchases",
    )
    created = create_pulse_experiment_draft(input)
    FeatureFlag.objects_including_soft_deleted.filter(id=created.feature_flag_id).update(
        deleted=True, key=f"pulse-experiment-{artifact_id.hex}:deleted:{created.feature_flag_id}"
    )

    with pytest.raises(ValueError, match="collides"):
        create_pulse_experiment_draft(input)

    assert FeatureFlag.objects_including_soft_deleted.filter(team_id=team.id).count() == 1


@pytest.mark.django_db
def test_create_pulse_experiment_draft_revalidates_an_active_actor(team, user) -> None:
    input = PulseExperimentDraftInput(
        team_id=team.id,
        actor_id=user.id,
        artifact_id=uuid4(),
        title="Improve checkout completion",
        target="The checkout flow",
        metric_direction="increase",
        expected_metric_movement="completed purchases",
    )
    user.is_active = False
    user.save(update_fields=["is_active"])

    with pytest.raises(PermissionDenied, match="access"):
        create_pulse_experiment_draft(input)

    assert FeatureFlag.objects.filter(team_id=team.id).count() == 0
