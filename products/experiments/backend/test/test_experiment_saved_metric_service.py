from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.models import Team

from products.experiments.backend.experiment_saved_metric_service import ExperimentSavedMetricService
from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.models.experiment import ExperimentSavedMetric, ExperimentToSavedMetric


class TestExperimentSavedMetricService(APIBaseTest):
    def _service(self) -> ExperimentSavedMetricService:
        return ExperimentSavedMetricService(team=self.team, user=self.user)

    def _valid_trends_query(self) -> dict:
        return {
            "kind": "ExperimentTrendsQuery",
            "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
        }

    def test_create_saved_metric_with_minimum_fields(self) -> None:
        original_query = self._valid_trends_query()
        saved_metric = self._service().create_saved_metric(
            name="Service saved metric",
            description="Created through the service",
            query=original_query,
        )

        assert saved_metric.team_id == self.team.id
        assert saved_metric.created_by_id == self.user.id
        assert saved_metric.name == "Service saved metric"
        assert saved_metric.description == "Created through the service"
        assert saved_metric.query["uuid"]
        assert {key: value for key, value in saved_metric.query.items() if key != "uuid"} == original_query

    @parameterized.expand(
        [
            ("missing_query", None, "Query is required to create a saved metric"),
            (
                "invalid_kind",
                {"kind": "not-ExperimentTrendsQuery"},
                "Metric query kind must be 'ExperimentMetric', 'ExperimentTrendsQuery' or 'ExperimentFunnelsQuery'",
            ),
            (
                "missing_metric_type",
                {"kind": "ExperimentMetric"},
                "ExperimentMetric requires a metric_type",
            ),
            (
                "invalid_metric_type",
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "invalid",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
                "ExperimentMetric metric_type must be 'mean', 'funnel', 'ratio', or 'retention'",
            ),
        ]
    )
    def test_create_saved_metric_validates_query(
        self,
        _: str,
        query: dict | None,
        expected_error: str,
    ) -> None:
        with self.assertRaises(ValidationError) as ctx:
            self._service().create_saved_metric(name="Invalid saved metric", query=query)  # type: ignore[arg-type]

        assert expected_error in str(ctx.exception)

    def test_update_saved_metric_updates_fields(self) -> None:
        saved_metric = ExperimentSavedMetric.objects.create(
            team=self.team,
            created_by=self.user,
            name="Original saved metric",
            description="Original description",
            query=self._valid_trends_query(),
        )

        updated = self._service().update_saved_metric(
            saved_metric,
            {
                "name": "Updated saved metric",
                "description": "Updated description",
            },
        )

        assert updated.name == "Updated saved metric"
        assert updated.description == "Updated description"

    def test_update_saved_metric_skips_save_for_empty_update(self) -> None:
        saved_metric = ExperimentSavedMetric.objects.create(
            team=self.team,
            created_by=self.user,
            name="Original saved metric",
            description="Original description",
            query=self._valid_trends_query(),
        )

        with patch("products.experiments.backend.models.experiment.ExperimentSavedMetric.save") as save_mock:
            updated = self._service().update_saved_metric(saved_metric, {})

        assert updated == saved_metric
        save_mock.assert_not_called()

    def test_update_saved_metric_validates_query_before_mutation(self) -> None:
        saved_metric = ExperimentSavedMetric.objects.create(
            team=self.team,
            created_by=self.user,
            name="Original name",
            description="Original description",
            query=self._valid_trends_query(),
        )

        with self.assertRaises(ValidationError) as ctx:
            self._service().update_saved_metric(
                saved_metric,
                {
                    "name": "Updated name",
                    "query": {},
                },
            )

        assert "Query is required to create a saved metric" in str(ctx.exception)
        saved_metric.refresh_from_db()
        assert saved_metric.name == "Original name"
        assert saved_metric.query == self._valid_trends_query()

    def test_update_saved_metric_query_preserves_existing_uuid(self) -> None:
        saved_metric = self._service().create_saved_metric(
            name="Saved metric with generated UUID",
            query=self._valid_trends_query(),
        )
        original_uuid = saved_metric.query["uuid"]

        updated = self._service().update_saved_metric(
            saved_metric,
            {
                "query": {
                    "kind": "ExperimentTrendsQuery",
                    "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageleave"}]},
                }
            },
        )

        assert updated.query["uuid"] == original_uuid
        assert updated.query["count_query"]["series"][0]["event"] == "$pageleave"

    def test_update_saved_metric_rejects_uuid_changes(self) -> None:
        saved_metric = self._service().create_saved_metric(
            name="Saved metric with stable UUID",
            query=self._valid_trends_query(),
        )

        with self.assertRaises(ValidationError) as ctx:
            self._service().update_saved_metric(
                saved_metric,
                {
                    "query": {
                        **saved_metric.query,
                        "uuid": "different-uuid",
                    }
                },
            )

        assert "Saved metric UUID cannot be changed" in str(ctx.exception)

    def test_update_saved_metric_rejects_unknown_keys(self) -> None:
        saved_metric = ExperimentSavedMetric.objects.create(
            team=self.team,
            created_by=self.user,
            name="Original saved metric",
            query=self._valid_trends_query(),
        )

        with self.assertRaises(ValidationError) as ctx:
            self._service().update_saved_metric(saved_metric, {"metadata": {"type": "primary"}})

        assert "Can't update keys: metadata on ExperimentSavedMetric" in str(ctx.exception)

    def test_update_saved_metric_rejects_metric_from_another_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        saved_metric = ExperimentSavedMetric.objects.create(
            team=other_team,
            created_by=self.user,
            name="Other team saved metric",
            query=self._valid_trends_query(),
        )

        with self.assertRaises(ValidationError) as ctx:
            self._service().update_saved_metric(saved_metric, {"name": "Updated name"})

        assert "Saved metric does not exist or does not belong to this project" in str(ctx.exception)

    def test_delete_saved_metric_removes_experiment_links(self) -> None:
        saved_metric = ExperimentSavedMetric.objects.create(
            team=self.team,
            created_by=self.user,
            name="Linked saved metric",
            query={
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "EventsNode", "event": "$pageview"},
            },
        )

        experiment_service = ExperimentService(team=self.team, user=self.user)
        experiment = experiment_service.create_experiment(
            name="Experiment with saved metric",
            feature_flag_key="saved-metric-service-delete",
            saved_metrics_ids=[{"id": saved_metric.id, "metadata": {"type": "primary"}}],
        )

        assert experiment.experimenttosavedmetric_set.count() == 1

        self._service().delete_saved_metric(saved_metric)

        assert not ExperimentSavedMetric.objects.filter(id=saved_metric.id).exists()
        assert ExperimentToSavedMetric.objects.filter(experiment_id=experiment.id).count() == 0

    def test_update_saved_metric_does_not_delete_links_on_validation_error(self) -> None:
        saved_metric = ExperimentSavedMetric.objects.create(
            team=self.team,
            created_by=self.user,
            name="Protected saved metric",
            query=self._valid_trends_query(),
        )

        with (
            patch("products.experiments.backend.models.experiment.ExperimentSavedMetric.save") as save_mock,
            self.assertRaises(ValidationError),
        ):
            self._service().update_saved_metric(saved_metric, {"query": {}})

        save_mock.assert_not_called()
