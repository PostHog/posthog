from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest import mock

from parameterized import parameterized
from rest_framework import status

from products.experiments.backend.hogql_queries.experiment_metric_fingerprint import compute_metric_fingerprint
from products.experiments.backend.hogql_queries.utils import get_experiment_stats_method
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
)
from products.experiments.backend.temporal.recalc_fingerprint import compute_recalc_fingerprint
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _mean_metric(uuid: str) -> dict:
    return {
        "uuid": uuid,
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "source": {"kind": "EventsNode", "event": "purchase"},
    }


class TestMetricsRecalculationAPI(APIBaseTest):
    def _flag(self, key: str) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=key,
            name=f"Flag for {key}",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
        )

    def _launched_experiment(self, flag_key: str = "api-flag") -> Experiment:
        exp = Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=self._flag(flag_key),
            name="exp",
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        exp.metrics = [_mean_metric("m1")]
        exp.save()
        return exp

    def _post_url(self, exp_id: int) -> str:
        return f"/api/projects/{self.team.id}/experiments/{exp_id}/metrics_recalculation/"

    def _latest_url(self, exp_id: int) -> str:
        return f"/api/projects/{self.team.id}/experiments/{exp_id}/metrics_recalculation/latest/"

    def _by_id_url(self, exp_id: int, recalc_id: str) -> str:
        return f"/api/projects/{self.team.id}/experiments/{exp_id}/metrics_recalculation/{recalc_id}/"

    # ------------------------------------------------------------------
    # POST /metrics_recalculation/
    # ------------------------------------------------------------------

    @mock.patch("products.experiments.backend.presentation.views.sync_connect")
    @mock.patch("products.experiments.backend.presentation.views.asyncio.run")
    def test_post_creates_and_starts_workflow(self, mock_run, mock_connect):
        exp = self._launched_experiment()
        resp = self.client.post(self._post_url(exp.id), {"trigger": "manual"}, format="json")
        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        body = resp.json()
        assert body["status"] == "pending"
        assert body["trigger"] == "manual"
        assert ExperimentMetricsRecalculation.objects.filter(experiment=exp).count() == 1
        assert mock_run.called

    @mock.patch("products.experiments.backend.presentation.views.sync_connect")
    @mock.patch("products.experiments.backend.presentation.views.asyncio.run")
    def test_post_is_idempotent_returns_200(self, mock_run, mock_connect):
        exp = self._launched_experiment()
        first = self.client.post(self._post_url(exp.id), {"trigger": "manual"}, format="json")
        assert first.status_code == status.HTTP_201_CREATED
        second = self.client.post(self._post_url(exp.id), {"trigger": "manual"}, format="json")
        assert second.status_code == status.HTTP_200_OK
        assert second.json()["id"] == first.json()["id"]
        assert ExperimentMetricsRecalculation.objects.filter(experiment=exp).count() == 1

    @mock.patch("products.experiments.backend.presentation.views.sync_connect")
    @mock.patch("products.experiments.backend.presentation.views.asyncio.run")
    def test_post_rejects_unlaunched_experiment(self, mock_run, mock_connect):
        exp = Experiment.objects.create(
            team=self.team, created_by=self.user, feature_flag=self._flag("unlaunched"), name="draft"
        )
        resp = self.client.post(self._post_url(exp.id), {"trigger": "manual"}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @mock.patch(
        "products.experiments.backend.presentation.views.sync_connect", side_effect=RuntimeError("temporal down")
    )
    @mock.patch("products.experiments.backend.presentation.views.asyncio.run")
    def test_post_marks_failed_when_workflow_start_errors(self, mock_run, mock_connect):
        # When the workflow start fails, the view marks the freshly-created row FAILED then re-raises.
        # The DRF test client converts the exception into a 500 response rather than propagating it.
        exp = self._launched_experiment()
        resp = self.client.post(self._post_url(exp.id), {"trigger": "manual"}, format="json")
        assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        row = ExperimentMetricsRecalculation.objects.get(experiment=exp)
        assert row.status == ExperimentMetricsRecalculation.Status.FAILED

    # ------------------------------------------------------------------
    # GET /metrics_recalculation/latest/
    # ------------------------------------------------------------------

    def test_get_latest_404_when_no_completed_run(self):
        exp = self._launched_experiment()
        ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp, status="pending")
        resp = self.client.get(self._latest_url(exp.id))
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_get_latest_returns_most_recent_completed_with_results(self):
        exp = self._launched_experiment()
        recalc = ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=exp,
            metric_uuids=["m1"],
            status="completed",
            query_to=datetime(2026, 6, 1, tzinfo=UTC),
        )
        # Narrow nullable fields populated above. _launched_experiment always sets metrics + start_date,
        # and we just set query_to on the recalc above.
        assert exp.metrics and exp.start_date is not None
        assert recalc.query_to is not None
        config_fp = compute_metric_fingerprint(
            exp.metrics[0],
            exp.start_date,
            get_experiment_stats_method(exp),
            exp.exposure_criteria,
            only_count_matured_users=exp.only_count_matured_users,
        )
        recalc_fp = compute_recalc_fingerprint(config_fp)
        ExperimentMetricResult.objects.create(
            experiment=exp,
            metric_uuid="m1",
            fingerprint=recalc_fp,
            query_from=exp.start_date,
            query_to=recalc.query_to,
            status="completed",
            result={"ok": True},
        )

        resp = self.client.get(self._latest_url(exp.id))
        assert resp.status_code == status.HTTP_200_OK, resp.content
        body = resp.json()
        assert body["id"] == str(recalc.id)
        assert body["status"] == "completed"
        assert len(body["results"]) == 1
        assert body["results"][0]["metric_uuid"] == "m1"
        assert body["results"][0]["result"] == {"ok": True}

    # ------------------------------------------------------------------
    # GET /metrics_recalculation/{id}/
    # ------------------------------------------------------------------

    @parameterized.expand(
        [
            ("pending", "pending"),
            ("in_progress", "in_progress"),
            ("completed", "completed"),
            ("failed", "failed"),
        ]
    )
    def test_get_by_id_returns_run_of_any_status(self, name: str, run_status: str):
        exp = self._launched_experiment(flag_key=f"by-id-{name}")
        row = ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp, status=run_status)
        resp = self.client.get(self._by_id_url(exp.id, str(row.id)))
        assert resp.status_code == status.HTTP_200_OK, resp.content
        assert resp.json()["status"] == run_status
        assert resp.json()["id"] == str(row.id)

    def test_get_by_id_404_for_unknown_id(self):
        exp = self._launched_experiment()
        resp = self.client.get(self._by_id_url(exp.id, "00000000-0000-0000-0000-000000000001"))
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_get_by_id_404_for_other_experiment_id(self):
        exp = self._launched_experiment(flag_key="by-id-mine")
        other = self._launched_experiment(flag_key="by-id-other")
        row = ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=other, status="completed")
        resp = self.client.get(self._by_id_url(exp.id, str(row.id)))
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    # ------------------------------------------------------------------
    # GET /metrics_recalculation/latest/ — timeseries cold-start fallback
    # ------------------------------------------------------------------

    def _store_timeseries_point(self, exp: Experiment, metric_uuid: str, query_to: datetime) -> None:
        assert exp.metrics and exp.start_date is not None
        metric_dict = next(m for m in exp.metrics if m["uuid"] == metric_uuid)
        config_fp = compute_metric_fingerprint(
            metric_dict,
            exp.start_date,
            get_experiment_stats_method(exp),
            exp.exposure_criteria,
            only_count_matured_users=exp.only_count_matured_users,
        )
        ExperimentMetricResult.objects.create(
            experiment=exp,
            metric_uuid=metric_uuid,
            fingerprint=config_fp,
            query_from=exp.start_date,
            query_to=query_to,
            status="completed",
            result={"ok": True},
        )

    def test_get_latest_returns_timeseries_fallback_on_cold_start(self):
        # No real recalc row, but a completed timeseries point exists → 200 with source=timeseries_fallback.
        exp = self._launched_experiment(flag_key="ts-fallback")
        self._store_timeseries_point(exp, "m1", datetime(2026, 2, 2, tzinfo=UTC))

        resp = self.client.get(self._latest_url(exp.id))
        assert resp.status_code == status.HTTP_200_OK, resp.content
        body = resp.json()
        assert body["result_source"] == "timeseries_fallback"
        assert body["status"] == "completed"
        assert len(body["results"]) == 1
        assert body["results"][0]["result"] == {"ok": True}

    def test_get_latest_still_404_when_no_recalc_and_no_timeseries(self):
        exp = self._launched_experiment(flag_key="ts-empty")
        resp = self.client.get(self._latest_url(exp.id))
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    @mock.patch("products.experiments.backend.presentation.views.sync_connect")
    def test_get_latest_fallback_does_not_start_a_workflow(self, mock_connect):
        # GET stays a pure read: the fallback path must never connect to Temporal.
        exp = self._launched_experiment(flag_key="ts-pure-read")
        self._store_timeseries_point(exp, "m1", datetime(2026, 2, 2, tzinfo=UTC))

        resp = self.client.get(self._latest_url(exp.id))
        assert resp.status_code == status.HTTP_200_OK
        assert not mock_connect.called
