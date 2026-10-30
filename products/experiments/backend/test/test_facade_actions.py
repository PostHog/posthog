from typing import Any

from posthog.test.base import BaseTest

from posthog.models import Team

from products.experiments.backend.experiment_creator import to_experiment_creator
from products.experiments.backend.facade.actions import (
    count_experiments_referencing_actions,
    experiments_referencing_action,
)
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag

ACTION_ID = 101
OTHER_ACTION_ID = 102


def _action_metric(action_id: int) -> list[dict[str, Any]]:
    return [{"kind": "ExperimentMetric", "metric_type": "mean", "source": {"kind": "ActionsNode", "id": action_id}}]


class TestActionReferencesFacade(BaseTest):
    def _experiment(self, name: str, *, team: Team | None = None, **fields: Any) -> None:
        team = team or self.team
        flag = FeatureFlag.objects.create(team=team, key=f"flag-{name}", created_by=self.user)
        Experiment.objects.create(team=team, name=name, feature_flag=flag, created_by=self.user, **fields)

    def test_finds_the_live_team_experiments_that_reference_each_action(self) -> None:
        self._experiment("Metric", metrics=_action_metric(ACTION_ID))
        self._experiment("Legacy filter", filters={"actions": [{"id": str(ACTION_ID), "type": "actions"}]})
        self._experiment("Other action", metrics_secondary=_action_metric(OTHER_ACTION_ID))
        self._experiment("Deleted", deleted=True, metrics=_action_metric(ACTION_ID))
        self._experiment(
            "Other team",
            team=Team.objects.create(organization=self.organization, name="other"),
            metrics=_action_metric(ACTION_ID),
        )

        references = experiments_referencing_action(self.team.id, ACTION_ID, limit=10)

        assert sorted(reference.name for reference in references) == ["Legacy filter", "Metric"]
        assert [reference.created_by for reference in references] == [to_experiment_creator(self.user)] * 2
        assert len(experiments_referencing_action(self.team.id, ACTION_ID, limit=1)) == 1
        assert count_experiments_referencing_actions(self.team.id, [ACTION_ID, OTHER_ACTION_ID, 103]) == {
            ACTION_ID: 2,
            OTHER_ACTION_ID: 1,
        }
