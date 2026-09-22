from uuid import uuid4

from rest_framework import status

from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from ee.api.test.base import APILicensedTest

LEGACY_TRENDS_METRIC = {
    "kind": "ExperimentTrendsQuery",
    "count_query": {"series": [{"kind": "EventsNode", "event": "$pageview"}]},
}
LEGACY_FUNNEL_QUERY = {
    "kind": "ExperimentFunnelsQuery",
    "funnels_query": {"series": [{"kind": "EventsNode", "event": "signed_up", "name": "x"}]},
}


class TestExperimentMigrateEndpoint(APILicensedTest):
    def setUp(self) -> None:
        super().setUp()
        self.experiment = Experiment.objects.create(
            team=self.team,
            name="Legacy experiment",
            created_by=self.user,
            feature_flag=FeatureFlag.objects.create(team=self.team, key="legacy-flag", created_by=self.user),
            metrics=[LEGACY_TRENDS_METRIC],
        )
        self.shared_metric = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="Legacy shared metric",
            created_by=self.user,
            query=LEGACY_FUNNEL_QUERY,
        )
        ExperimentToSavedMetric.objects.create(
            experiment=self.experiment, saved_metric=self.shared_metric, metadata={"type": "secondary"}
        )

    def _migrate(self):
        return self.client.post(f"/api/projects/{self.team.id}/experiments/{self.experiment.id}/migrate")

    def test_migrates_the_experiment_and_its_legacy_shared_metric(self) -> None:
        response = self._migrate()
        assert response.status_code == status.HTTP_200_OK, response.json()

        migrated = Experiment.objects.get(pk=response.json()["id"])
        assert migrated.id != self.experiment.id
        assert migrated.metrics is not None
        [migrated_metric] = migrated.metrics
        assert migrated_metric["kind"] == "ExperimentMetric"
        assert migrated_metric["metric_type"] == "mean"
        assert migrated_metric["source"] == {"kind": "EventsNode", "event": "$pageview"}
        assert migrated.feature_flag_id == self.experiment.feature_flag_id

        self.experiment.refresh_from_db()
        assert self.experiment.stats_config is not None
        assert migrated.stats_config is not None
        assert self.experiment.stats_config["migrated_to"] == migrated.id
        assert migrated.stats_config["migrated_from"] == self.experiment.id

        link = ExperimentToSavedMetric.objects.get(experiment=migrated)
        assert link.metadata == {"type": "secondary"}
        assert link.saved_metric_id != self.shared_metric.id
        assert link.saved_metric.query["kind"] == "ExperimentMetric"

        self.shared_metric.refresh_from_db()
        assert self.shared_metric.metadata is not None
        assert self.shared_metric.metadata["migrated_to"] == link.saved_metric_id

    def test_migrated_metrics_are_reachable_through_the_ordering_arrays(self) -> None:
        # The UI renders only what the ordering arrays list, so a metric missing from them is invisible.
        migrated = Experiment.objects.get(pk=self._migrate().json()["id"])
        link = ExperimentToSavedMetric.objects.get(experiment=migrated)

        assert migrated.metrics is not None
        assert migrated.primary_metrics_ordered_uuids == [migrated.metrics[0]["uuid"]]
        assert migrated.secondary_metrics_ordered_uuids == [link.saved_metric.query["uuid"]]
        assert migrated.metrics[0]["fingerprint"]

    def test_the_copy_starts_unlinked_from_the_source_flag_rule(self) -> None:
        rule_id = uuid4()
        Experiment.objects.filter(pk=self.experiment.pk).update(
            feature_flag_rule_id=rule_id, feature_flag_rule_snapshot={"variants": []}
        )

        migrated = Experiment.objects.get(pk=self._migrate().json()["id"])

        assert migrated.feature_flag_rule_id is None
        assert migrated.feature_flag_rule_snapshot is None

    def test_migrates_again_when_the_earlier_copy_was_deleted(self) -> None:
        first = Experiment.objects.get(pk=self._migrate().json()["id"])
        first_id = first.id
        ExperimentSavedMetric.objects.get(
            pk=ExperimentToSavedMetric.objects.get(experiment=first).saved_metric_id
        ).delete()
        first.delete()

        response = self._migrate()

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["id"] != first_id
        second = Experiment.objects.get(pk=response.json()["id"])
        assert ExperimentToSavedMetric.objects.get(experiment=second).saved_metric.query["kind"] == "ExperimentMetric"

    def test_migrating_twice_returns_the_first_copy(self) -> None:
        first = self._migrate().json()["id"]
        second = self._migrate()

        assert second.status_code == status.HTTP_200_OK
        assert second.json()["id"] == first
        assert Experiment.objects.filter(team=self.team).count() == 2
        assert ExperimentSavedMetric.objects.filter(team=self.team).count() == 2

    def test_rejects_an_experiment_that_is_already_on_the_new_engine(self) -> None:
        Experiment.objects.filter(pk=self.experiment.pk).update(metrics=[])
        ExperimentToSavedMetric.objects.filter(experiment=self.experiment).delete()

        response = self._migrate()

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Experiment.objects.filter(team=self.team).count() == 1
