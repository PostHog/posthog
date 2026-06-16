from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from products.experiments.backend.hogql_queries.experiment_metric_fingerprint import compute_metric_fingerprint
from products.experiments.backend.hogql_queries.utils import get_experiment_stats_method
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
)
from products.experiments.backend.recalculation import (
    get_latest_recalculation,
    get_recalculation_by_id,
    get_run_results,
    request_recalculation,
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


@pytest.mark.django_db(transaction=True)
class TestRecalculationService(BaseTest):
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

    def _launched_experiment(self, flag_key: str = "svc-flag") -> Experiment:
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

    def test_request_recalculation_creates_pending(self):
        exp = self._launched_experiment()
        result = request_recalculation(exp, self.user, "manual")
        assert result["status"] == "pending"
        assert result["is_existing"] is False
        assert ExperimentMetricsRecalculation.objects.filter(experiment=exp).count() == 1

    def test_request_recalculation_is_idempotent(self):
        exp = self._launched_experiment()
        first = request_recalculation(exp, self.user, "manual")
        second = request_recalculation(exp, self.user, "manual")
        assert second["is_existing"] is True
        assert second["id"] == first["id"]
        # Only one job row was created across both calls.
        assert ExperimentMetricsRecalculation.objects.filter(experiment=exp).count() == 1

    @parameterized.expand(
        [
            # (name, status, stale_field) — both lifecycle anchors must release the experiment when their
            # respective timestamp is past the staleness threshold. Without this, a Temporal-connect failure
            # that also lost its rollback UPDATE permanently locks the experiment out of recalculations.
            ("pending_stale_by_created_at", "pending", "created_at"),
            ("in_progress_stale_by_started_at", "in_progress", "started_at"),
        ]
    )
    def test_request_recalculation_recovers_from_stale_active_row(self, name: str, status: str, stale_field: str):
        exp = self._launched_experiment(flag_key=f"stale-{name}")
        long_ago = timezone.now() - timedelta(hours=2)
        stale_kwargs: dict = {"team": self.team, "experiment": exp, "status": status}
        if stale_field == "created_at":
            # created_at uses auto_now_add so we have to update after create.
            stale_row = ExperimentMetricsRecalculation.objects.create(**stale_kwargs)
            ExperimentMetricsRecalculation.objects.filter(id=stale_row.id).update(created_at=long_ago)
        else:
            stale_row = ExperimentMetricsRecalculation.objects.create(**stale_kwargs, started_at=long_ago)

        result = request_recalculation(exp, self.user, "manual")

        # A fresh row was created (NOT the stale one) and the stale row was marked FAILED.
        assert result["is_existing"] is False
        assert result["id"] != str(stale_row.id)
        stale_row.refresh_from_db()
        assert stale_row.status == "failed"

    def test_request_recalculation_does_not_recover_recent_active_row(self):
        # Defensive: a row created N minutes ago (well under the threshold) must still block, no matter the
        # status. This pins the threshold is doing real work and we aren't accidentally short-circuiting it.
        exp = self._launched_experiment(flag_key="recent-pending")
        recent_row = ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp, status="pending")
        result = request_recalculation(exp, self.user, "manual")
        assert result["is_existing"] is True
        assert result["id"] == str(recent_row.id)

    def test_request_recalculation_rejects_unlaunched(self):
        exp = Experiment.objects.create(
            team=self.team, created_by=self.user, feature_flag=self._flag("unlaunched"), name="draft"
        )
        with pytest.raises(ValidationError):
            request_recalculation(exp, self.user, "manual")

    @parameterized.expand(
        [
            ("manual",),
            ("experiment_launch",),
            ("experiment_stop",),
            ("experiment_update",),
        ]
    )
    def test_request_recalculation_persists_trigger(self, trigger: str):
        exp = self._launched_experiment(flag_key=f"trigger-{trigger}")
        result = request_recalculation(exp, self.user, trigger)
        assert result["trigger"] == trigger
        row = ExperimentMetricsRecalculation.objects.get(id=result["id"])
        assert row.trigger == trigger

    def test_get_latest_recalculation_returns_most_recent_completed(self):
        # get_latest_recalculation filters to status='completed' (powers GET /metrics_recalculation/latest).
        exp = self._launched_experiment()
        first_done = ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp, status="completed")
        ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp, status="failed")
        second_done = ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp, status="completed")
        # A pending run created AFTER the latest completed one must NOT be returned.
        ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp, status="pending")
        latest = get_latest_recalculation(exp)
        assert latest is not None
        assert latest.id == second_done.id
        assert latest.id != first_done.id

    @parameterized.expand(
        [
            ("never_ran", []),
            ("only_pending", ["pending"]),
            ("only_failed", ["failed"]),
            ("only_in_progress", ["in_progress"]),
        ]
    )
    def test_get_latest_recalculation_none_when_no_completed(self, name: str, statuses: list[str]):
        exp = self._launched_experiment(flag_key=f"latest-{name}")
        for status in statuses:
            ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp, status=status)
        assert get_latest_recalculation(exp) is None

    def test_get_recalculation_by_id_returns_row(self):
        exp = self._launched_experiment()
        row = ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp, status="in_progress")
        result = get_recalculation_by_id(exp, str(row.id))
        assert result is not None
        assert result.id == row.id

    def test_get_recalculation_by_id_none_for_unknown_id(self):
        exp = self._launched_experiment()
        # Valid UUID format but no such row exists.
        assert get_recalculation_by_id(exp, "00000000-0000-0000-0000-000000000001") is None

    def test_get_recalculation_by_id_none_for_other_experiment(self):
        # ID belongs to a different experiment in the same team — must NOT cross experiments.
        exp = self._launched_experiment(flag_key="by-id-mine")
        other = self._launched_experiment(flag_key="by-id-other")
        row = ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=other, status="completed")
        assert get_recalculation_by_id(exp, str(row.id)) is None

    def test_get_run_results_scopes_by_recalc_fingerprint(self):
        exp = self._launched_experiment()
        recalc = ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=exp,
            metric_uuids=["m1"],
            status="completed",
            query_to=timezone.now(),
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
        recalc_fp = compute_recalc_fingerprint(config_fp, str(recalc.id))

        # The row from THIS run (recalc-fingerprinted) — must be returned.
        ExperimentMetricResult.objects.create(
            experiment=exp,
            metric_uuid="m1",
            fingerprint=recalc_fp,
            query_from=exp.start_date,
            query_to=recalc.query_to,
            status="completed",
            result={"ok": True},
        )
        # A stale row from another run / different fingerprint — must NOT be returned.
        ExperimentMetricResult.objects.create(
            experiment=exp,
            metric_uuid="m1",
            fingerprint="some-other-fingerprint",
            query_from=exp.start_date,
            query_to=datetime(2026, 4, 1, tzinfo=UTC),
            status="completed",
            result={"stale": True},
        )

        results = get_run_results(recalc)
        assert len(results) == 1
        assert results[0]["metric_uuid"] == "m1"
        assert results[0]["status"] == "completed"
        assert results[0]["result"] == {"ok": True}
        assert results[0]["error_message"] is None

    def test_get_run_results_strips_step_sessions(self):
        # step_sessions carries per-step person IDs, session IDs, and event UUIDs. It powers the frontend's
        # "view sessions per step" affordance off a separate per-metric query, so it does not belong in the
        # recalc results payload. Mirrors the same stripping the timeseries-results path applies.
        exp = self._launched_experiment()
        recalc = ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=exp,
            metric_uuids=["m1"],
            status="completed",
            query_to=timezone.now(),
        )
        assert exp.metrics and exp.start_date is not None
        assert recalc.query_to is not None
        config_fp = compute_metric_fingerprint(
            exp.metrics[0],
            exp.start_date,
            get_experiment_stats_method(exp),
            exp.exposure_criteria,
            only_count_matured_users=exp.only_count_matured_users,
        )
        recalc_fp = compute_recalc_fingerprint(config_fp, str(recalc.id))
        ExperimentMetricResult.objects.create(
            experiment=exp,
            metric_uuid="m1",
            fingerprint=recalc_fp,
            query_from=exp.start_date,
            query_to=recalc.query_to,
            status="completed",
            result={
                "step_sessions": [["top-level-leak"]],
                "baseline": {
                    "step_sessions": [["baseline-leak"]],
                    "count": 42,
                },
                "variant_results": [
                    {
                        "key": "test",
                        "step_sessions": [["variant-leak"]],
                        "count": 7,
                    },
                ],
            },
        )

        results = get_run_results(recalc)

        assert len(results) == 1
        result = results[0]["result"]
        assert "step_sessions" not in result
        assert "step_sessions" not in result["baseline"]
        assert result["baseline"]["count"] == 42
        assert "step_sessions" not in result["variant_results"][0]
        assert result["variant_results"][0]["count"] == 7
        assert result["variant_results"][0]["key"] == "test"

    def test_get_run_results_returns_empty_when_no_rows_yet(self):
        exp = self._launched_experiment()
        recalc = ExperimentMetricsRecalculation.objects.create(
            team=self.team, experiment=exp, metric_uuids=["m1"], status="in_progress"
        )
        assert get_run_results(recalc) == []

    def test_get_run_results_returns_empty_when_no_metrics_persisted(self):
        # Discovery hasn't yet persisted metric_uuids onto the job.
        exp = self._launched_experiment()
        recalc = ExperimentMetricsRecalculation.objects.create(team=self.team, experiment=exp, status="pending")
        assert get_run_results(recalc) == []
