import uuid

import pytest
from posthog.test.base import BaseTest

from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric
from products.experiments.backend.temporal.metric_resolution import find_metric_dict, iter_metric_dicts
from products.feature_flags.backend.models.feature_flag import FeatureFlag


@pytest.mark.django_db(transaction=True)
class TestMetricResolution(BaseTest):
    def _experiment(self, metrics: list[dict] | None = None, metrics_secondary: list[dict] | None = None) -> Experiment:
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=f"flag-{uuid.uuid4().hex[:8]}",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        return Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=flag,
            name="exp",
            metrics=metrics or [],
            metrics_secondary=metrics_secondary or [],
        )

    def _attach_saved(self, experiment: Experiment, query: dict, metadata: dict | None = None) -> None:
        saved = ExperimentSavedMetric.objects.create(team=self.team, name="saved", query=query)
        ExperimentToSavedMetric.objects.create(experiment=experiment, saved_metric=saved, metadata=metadata or {})

    def test_inline_metric_takes_precedence_over_saved_with_same_uuid(self):
        shared_uuid = str(uuid.uuid4())
        inline = {"uuid": shared_uuid, "metric_type": "funnel", "source": "inline"}
        experiment = self._experiment(metrics=[inline])
        self._attach_saved(experiment, {"uuid": shared_uuid, "metric_type": "funnel", "source": "saved"})

        resolved = find_metric_dict(experiment, shared_uuid)
        assert resolved is not None
        assert resolved["source"] == "inline"

    def test_resolution_order_is_primary_secondary_saved(self):
        primary, secondary = {"uuid": str(uuid.uuid4())}, {"uuid": str(uuid.uuid4())}
        experiment = self._experiment(metrics=[primary], metrics_secondary=[secondary])
        saved_uuid = str(uuid.uuid4())
        self._attach_saved(experiment, {"uuid": saved_uuid, "metric_type": "mean"})

        assert [m["uuid"] for m in iter_metric_dicts(experiment)] == [
            primary["uuid"],
            secondary["uuid"],
            saved_uuid,
        ]

    def test_saved_metric_breakdowns_merged_from_link_metadata(self):
        experiment = self._experiment()
        saved_uuid = str(uuid.uuid4())
        breakdowns = [{"property": "$browser", "type": "event"}]
        self._attach_saved(
            experiment,
            {"uuid": saved_uuid, "metric_type": "funnel", "breakdownFilter": {"breakdown_limit": 5}},
            metadata={"breakdowns": breakdowns},
        )

        resolved = find_metric_dict(experiment, saved_uuid)
        assert resolved is not None
        assert resolved["breakdownFilter"] == {"breakdown_limit": 5, "breakdowns": breakdowns}

    def test_saved_metric_without_metadata_gets_empty_breakdowns(self):
        experiment = self._experiment()
        saved_uuid = str(uuid.uuid4())
        self._attach_saved(experiment, {"uuid": saved_uuid, "metric_type": "funnel"})

        resolved = find_metric_dict(experiment, saved_uuid)
        assert resolved is not None
        assert resolved["breakdownFilter"] == {"breakdowns": []}

    def test_metrics_without_uuid_are_excluded(self):
        experiment = self._experiment(metrics=[{"metric_type": "funnel"}])
        self._attach_saved(experiment, {"metric_type": "funnel"})
        assert iter_metric_dicts(experiment) == []
