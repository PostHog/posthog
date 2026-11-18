from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.contrib.admin.models import LogEntry

from parameterized import parameterized

from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricsRecalculation,
    ExperimentSavedMetric,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag

# The legacy conversion reads only the count query's series. The fixture names no query kind of another
# product, so test_model_crossing_uses does not count these tests as driving a trends query runner.
LEGACY_TRENDS_METRIC = {
    "kind": "ExperimentTrendsQuery",
    "count_query": {"series": [{"kind": "EventsNode", "event": "$pageview"}]},
}


class TestExperimentsConsole(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="console-flag", name="Flag")
        self.experiment = Experiment.objects.create(
            team=self.team,
            name="Checkout test",
            created_by=self.user,
            feature_flag=flag,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            metrics=[{"kind": "ExperimentMetric", "series": [{"event": "$pageview", "properties": {"$browser": "x"}}]}],
        )

    def _finished_run(self, **fields: object) -> ExperimentMetricsRecalculation:
        return ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=self.experiment,
            status=ExperimentMetricsRecalculation.Status.FAILED,
            total_metrics=1,
            metric_uuids=["m-1"],
            metric_errors={"m-1": {"message": "timeout in ClickHouse"}},
            started_at=datetime(2026, 1, 2, 10, 0, tzinfo=UTC),
            completed_at=datetime(2026, 1, 2, 10, 4, tzinfo=UTC),
            **fields,
        )

    def test_the_team_page_links_to_the_experiments_and_every_page_renders(self) -> None:
        run = self._finished_run()
        saved_metric = ExperimentSavedMetric.objects.create(team=self.team, name="Signups", query=LEGACY_TRENDS_METRIC)
        self.experiment.saved_metrics.add(saved_metric)

        team_page = self.client.get(f"/admin/console/teams/{self.team.pk}/").content.decode()
        assert f"/admin/console/tools/experiments/?team={self.team.pk}" in team_page

        pages = {
            f"/admin/console/tools/experiments/?team={self.team.pk}": "Checkout test",
            f"/admin/console/tools/experiments/?experiment={self.experiment.pk}": "timeout in ClickHouse",
            f"/admin/console/tools/experiments/?saved_metric={saved_metric.pk}": "legacy engine and can be migrated",
            "/admin/console/tools/experiment-recalculations/": str(run.pk),
            f"/admin/console/tools/experiment-recalculations/?run={run.pk}": "timeout in ClickHouse",
            f"/admin/console/tools/experiment-recalculations/live/run-failures/?run={run.pk}": "timeout in ClickHouse",
        }
        for url, expected in pages.items():
            response = self.client.get(url)
            assert response.status_code == 200, url
            assert expected in response.content.decode(), url

        experiment_page = self.client.get(f"/admin/console/tools/experiments/?experiment={self.experiment.pk}")
        content = experiment_page.content.decode()
        # The legacy shared metric blocks the migration, and the dict properties offer the fix.
        assert "Migrate all legacy shared metrics first" in content
        assert "/admin/console/tools/experiments/migrate/" not in content
        assert "/admin/console/tools/experiments/fix-properties/" in content

        removed_flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="removed-flag")
        Experiment.objects.create(
            team=self.team, name="Removed test", created_by=self.user, feature_flag=removed_flag, deleted=True
        )
        team_list = self.client.get(f"/admin/console/tools/experiments/?team={self.team.pk}").content.decode()
        assert "Removed test" not in team_list

    @parameterized.expand(
        [
            ("start_new_run", "start-recalculation", ExperimentMetricsRecalculation.Trigger.MANUAL),
            ("retry_latest_failures", "retry-failures", ExperimentMetricsRecalculation.Trigger.METRIC_CONFIG_CHANGE),
        ]
    )
    @patch("products.experiments.backend.staff_operations.start_metrics_recalculation_workflow")
    def test_starting_a_recalculation_dispatches_the_workflow_and_opens_the_run(
        self, _name: str, operation_key: str, trigger: str, start_workflow: MagicMock
    ) -> None:
        prior = self._finished_run()

        response = self.client.post(
            f"/admin/console/tools/experiments/{operation_key}/?experiment={self.experiment.pk}"
        )

        new_run = ExperimentMetricsRecalculation.objects.filter(experiment=self.experiment).exclude(pk=prior.pk).get()
        assert new_run.trigger == trigger
        start_workflow.assert_called_once()
        assert response.status_code == 302
        assert response["Location"] == f"/admin/console/tools/experiment-recalculations/?run={new_run.pk}"

    def test_migrating_an_experiment_opens_its_new_engine_copy(self) -> None:
        Experiment.objects.filter(pk=self.experiment.pk).update(metrics=[LEGACY_TRENDS_METRIC])

        response = self.client.post(
            f"/admin/console/tools/experiments/migrate/?experiment={self.experiment.pk}", {"reason": "Customer asked"}
        )

        self.experiment.refresh_from_db()
        assert self.experiment.stats_config is not None
        migrated_to = self.experiment.stats_config["migrated_to"]
        assert response["Location"] == f"/admin/console/tools/experiments/?experiment={migrated_to}"
        migrated_metrics = Experiment.objects.get(pk=migrated_to).metrics
        assert migrated_metrics is not None
        assert migrated_metrics[0]["kind"] == "ExperimentMetric"

    @parameterized.expand(
        [
            ("fail_a_stuck_run", "mark-failed", datetime(2026, 1, 2, tzinfo=UTC), 302, "failed", True),
            # Completing a run that never started would make the latest-run endpoint serve zero results.
            ("refuse_to_complete_a_run_that_never_started", "mark-completed", None, 400, "pending", False),
        ]
    )
    @patch("products.experiments.backend.staff_operations.cancel_recalculation_workflow")
    def test_marking_a_run_terminal(
        self,
        _name: str,
        operation_key: str,
        query_to: datetime | None,
        expected_status: int,
        expected_run_status: str,
        expect_cancel: bool,
        cancel_workflow: MagicMock,
    ) -> None:
        run = ExperimentMetricsRecalculation.objects.create(
            team=self.team,
            experiment=self.experiment,
            status=ExperimentMetricsRecalculation.Status.PENDING,
            total_metrics=1,
            metric_uuids=["m-1"],
            query_to=query_to,
        )

        confirm_page = self.client.get(f"/admin/console/tools/experiment-recalculations/{operation_key}/?run={run.pk}")
        assert f"recalculation {run.pk} of experiment {self.experiment.pk}, team {self.team.pk}" in (
            confirm_page.content.decode()
        )

        response = self.client.post(
            f"/admin/console/tools/experiment-recalculations/{operation_key}/?run={run.pk}",
            {"reason": "Workflow stuck after a deploy"},
        )

        assert response.status_code == expected_status
        run.refresh_from_db()
        assert run.status == expected_run_status
        assert cancel_workflow.called == expect_cancel
        history = LogEntry.objects.filter(object_id=str(run.pk)).values_list("user_id", "change_message")
        assert list(history) == (
            [(self.user.pk, "Manually marked failed from PostHog Admin.")] if expect_cancel else []
        )

    @parameterized.expand(
        [
            (
                "experiment_action",
                "experiment",
                "fix-properties/?from=ticket",
                "experiments/?experiment={pk}&from=ticket",
            ),
            ("saved_metric_action", "experimentsavedmetric", "migrate/", "experiments/?saved_metric={pk}"),
            (
                "recalculation_action",
                "experimentmetricsrecalculation",
                "mark-failed/",
                "experiment-recalculations/?run={pk}",
            ),
        ]
    )
    def test_an_old_django_admin_action_url_lands_on_the_console(
        self, _name: str, model: str, old: str, new: str
    ) -> None:
        if model == "experiment":
            pk: object = self.experiment.pk
        elif model == "experimentsavedmetric":
            pk = ExperimentSavedMetric.objects.create(team=self.team, name="Signups", query=LEGACY_TRENDS_METRIC).pk
        else:
            pk = self._finished_run().pk

        response = self.client.get(f"/admin/experiments/{model}/{pk}/{old}")

        assert response.status_code == 302
        assert response["Location"] == "/admin/console/tools/" + new.format(pk=pk)
