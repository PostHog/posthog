from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import BaseTest

from django.core.exceptions import FieldDoesNotExist

from posthog.models.team import Team

from products.experiments.backend.facade import testing
from products.experiments.backend.models.experiment import Experiment, ExperimentToSavedMetric
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestFacadeTesting(BaseTest):
    def test_seed_helpers_write_team_scoped_rows_and_relations(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="seeded-flag", created_by=self.user)
        holdout_id = testing.create_holdout(
            team_id=self.team.id, name="Holdout", filters=[{"properties": [], "rollout_percentage": 10}]
        )
        start_date = datetime(2026, 1, 1, tzinfo=UTC)
        experiment_id = testing.create_experiment(
            team_id=self.team.id,
            feature_flag_id=flag.id,
            created_by_id=self.user.id,
            start_date=start_date,
            end_date=start_date + timedelta(days=1),
            holdout_id=holdout_id,
            metrics=[{"kind": "ExperimentMetric", "metric_type": "mean"}],
            updated_at=start_date,
        )
        saved_metric_id = testing.create_saved_metric(
            team_id=self.team.id,
            name="Shared metric",
            description="Counts checkouts.",
            query={"kind": "ExperimentMetric", "metric_type": "funnel"},
        )
        testing.link_saved_metric(
            experiment_id=experiment_id, saved_metric_id=saved_metric_id, metadata={"type": "secondary"}
        )
        testing.set_team_experiments_config(team_id=self.team.id, default_cuped_enabled=True)
        testing.set_team_experiments_config(team_id=self.team.id, experiment_precomputation_enabled=True)

        experiment = Experiment.objects.get(id=experiment_id)
        assert experiment.team_id == self.team.id
        assert experiment.feature_flag_id == flag.id
        assert experiment.created_by_id == self.user.id
        assert experiment.holdout is not None and experiment.holdout.team_id == self.team.id
        assert experiment.status == Experiment.Status.STOPPED
        assert experiment.metrics == [{"kind": "ExperimentMetric", "metric_type": "mean"}]
        assert experiment.exposure_criteria == {}
        assert experiment.updated_at == start_date
        link = ExperimentToSavedMetric.objects.get(experiment_id=experiment_id)
        assert (link.saved_metric_id, link.metadata) == (saved_metric_id, {"type": "secondary"})
        assert (link.saved_metric.team_id, link.saved_metric.description) == (self.team.id, "Counts checkouts.")
        config = TeamExperimentsConfig.objects.get(team_id=self.team.id)
        assert (config.default_cuped_enabled, config.experiment_precomputation_enabled) == (True, True)

        other_team = Team.objects.create(organization=self.organization, name="Other team")
        with pytest.raises(Experiment.DoesNotExist):
            testing.update_experiment(team_id=other_team.id, experiment_id=experiment_id, deleted=True)
        with pytest.raises(Experiment.DoesNotExist):
            testing.delete_experiment(team_id=other_team.id, experiment_id=experiment_id)
        with pytest.raises(FieldDoesNotExist):
            testing.update_experiment(team_id=self.team.id, experiment_id=experiment_id, delted=True)

        testing.update_experiment(team_id=self.team.id, experiment_id=experiment_id, deleted=True, holdout_id=None)
        experiment.refresh_from_db()
        assert (experiment.deleted, experiment.holdout_id) == (True, None)
        testing.delete_experiment(team_id=self.team.id, experiment_id=experiment_id)
        assert not Experiment.objects.filter(id=experiment_id).exists()
