from io import StringIO

from posthog.test.base import APIBaseTest

from django.core.management import call_command
from django.utils import timezone

from parameterized import parameterized

from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestDedupeExperimentMetricUuids(APIBaseTest):
    def _create_flag(self, key: str) -> FeatureFlag:
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

    def _create_experiment(self, key: str, **fields) -> Experiment:
        flag = self._create_flag(key)
        return Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=flag,
            name=f"Experiment {key}",
            start_date=timezone.now(),
            **fields,
        )

    def _metric(self, uuid: str, event: str = "purchase") -> dict:
        return {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "source": {"kind": "EventsNode", "event": event, "math": "total"},
            "uuid": uuid,
        }

    def _run(self, *args) -> str:
        out = StringIO()
        call_command("dedupe_experiment_metric_uuids", *args, stdout=out)
        return out.getvalue()

    def _uuids(self, metrics: list[dict] | None) -> list[str]:
        return [m["uuid"] for m in (metrics or [])]

    def test_no_experiments_to_dedupe_reports_nothing(self):
        self._create_experiment(
            "clean",
            metrics=[self._metric("aaaaaaaa-0000-0000-0000-000000000001")],
            primary_metrics_ordered_uuids=["aaaaaaaa-0000-0000-0000-000000000001"],
        )

        output = self._run()

        assert "No experiments to dedupe." in output

    @parameterized.expand(
        [
            ("primary", "metrics", "primary_metrics_ordered_uuids"),
            ("secondary", "metrics_secondary", "secondary_metrics_ordered_uuids"),
        ]
    )
    def test_dedupes_duplicate_uuid_within_a_single_metric_list(self, _name, metrics_field, ordering_field):
        dup = "aaaaaaaa-0000-0000-0000-000000000001"
        experiment = self._create_experiment(
            f"inline-dup-{metrics_field}",
            **{
                metrics_field: [self._metric(dup, "first"), self._metric(dup, "second")],
                ordering_field: [dup],
            },
        )

        self._run()
        experiment.refresh_from_db()

        metrics = getattr(experiment, metrics_field)
        ordering = getattr(experiment, ordering_field)
        uuids = self._uuids(metrics)
        # First occurrence keeps the original uuid; the second is regenerated.
        assert uuids[0] == dup
        assert uuids[1] != dup
        assert len(set(uuids)) == 2
        # The regenerated uuid is appended to the ordering; the incumbent stays.
        assert ordering == [dup, uuids[1]]
        # The order of the metrics themselves and their events is preserved.
        assert metrics[0]["source"]["event"] == "first"
        assert metrics[1]["source"]["event"] == "second"

    def test_dedupes_duplicate_uuid_across_primary_and_secondary(self):
        dup = "bbbbbbbb-0000-0000-0000-000000000001"
        experiment = self._create_experiment(
            "cross-list-dup",
            metrics=[self._metric(dup, "primary")],
            metrics_secondary=[self._metric(dup, "secondary")],
            primary_metrics_ordered_uuids=[dup],
            secondary_metrics_ordered_uuids=[dup],
        )

        self._run()
        experiment.refresh_from_db()

        assert experiment.metrics is not None
        assert experiment.metrics_secondary is not None
        primary_uuid = experiment.metrics[0]["uuid"]
        secondary_uuid = experiment.metrics_secondary[0]["uuid"]
        # Primary keeps the incumbent; the secondary collision is regenerated.
        assert primary_uuid == dup
        assert secondary_uuid != dup
        assert experiment.primary_metrics_ordered_uuids == [dup]
        # The secondary ordering's pre-dedup `dup` is now an orphan (it points at
        # no surviving secondary metric) so it is dropped and the new uuid replaces it.
        assert experiment.secondary_metrics_ordered_uuids == [secondary_uuid]

    def test_inline_metric_colliding_with_saved_metric_uuid_is_regenerated(self):
        shared = "cccccccc-0000-0000-0000-000000000001"
        saved_metric = ExperimentSavedMetric.objects.create(
            team=self.team,
            created_by=self.user,
            name="Saved",
            query={"kind": "ExperimentMetric", "metric_type": "mean", "uuid": shared},
        )
        experiment = self._create_experiment(
            "saved-collision",
            metrics=[self._metric(shared, "inline")],
            primary_metrics_ordered_uuids=[shared],
        )
        ExperimentToSavedMetric.objects.create(
            experiment=experiment,
            saved_metric=saved_metric,
            metadata={"type": "primary"},
        )

        self._run()
        experiment.refresh_from_db()

        assert experiment.metrics is not None
        inline_uuid = experiment.metrics[0]["uuid"]
        # The saved-metric uuid is treated as a fixed point; the inline copy moves.
        assert inline_uuid != shared
        # The saved-metric uuid stays in the ordering, the regenerated inline uuid is appended.
        assert experiment.primary_metrics_ordered_uuids == [shared, inline_uuid]

    def test_dry_run_reports_but_does_not_write(self):
        dup = "dddddddd-0000-0000-0000-000000000001"
        experiment = self._create_experiment(
            "dry-run",
            metrics=[self._metric(dup, "first"), self._metric(dup, "second")],
            primary_metrics_ordered_uuids=[dup],
        )

        output = self._run("--dry-run")
        experiment.refresh_from_db()

        assert "[DRY RUN]" in output
        assert "Would update 1 experiments" in output
        # Nothing was written: the duplicate uuid is still present.
        assert self._uuids(experiment.metrics) == [dup, dup]
        assert experiment.primary_metrics_ordered_uuids == [dup]

    def test_preserves_null_secondary_metrics(self):
        dup = "eeeeeeee-0000-0000-0000-000000000001"
        experiment = self._create_experiment(
            "null-secondary",
            metrics=[self._metric(dup, "first"), self._metric(dup, "second")],
            metrics_secondary=None,
            primary_metrics_ordered_uuids=[dup],
            secondary_metrics_ordered_uuids=None,
        )

        self._run()
        experiment.refresh_from_db()

        # Primary was deduped, but the null secondary column is left untouched
        # rather than normalized to an empty list.
        assert len(set(self._uuids(experiment.metrics))) == 2
        assert experiment.metrics_secondary is None
        assert experiment.secondary_metrics_ordered_uuids is None

    def test_saved_metric_only_duplication_is_skipped(self):
        shared = "ffffffff-0000-0000-0000-000000000001"
        saved_primary = ExperimentSavedMetric.objects.create(
            team=self.team,
            created_by=self.user,
            name="Saved primary",
            query={"kind": "ExperimentMetric", "metric_type": "mean", "uuid": shared},
        )
        saved_secondary = ExperimentSavedMetric.objects.create(
            team=self.team,
            created_by=self.user,
            name="Saved secondary",
            query={"kind": "ExperimentMetric", "metric_type": "mean", "uuid": shared},
        )
        experiment = self._create_experiment(
            "saved-only-dup",
            metrics=[],
            primary_metrics_ordered_uuids=[shared],
        )
        ExperimentToSavedMetric.objects.create(
            experiment=experiment, saved_metric=saved_primary, metadata={"type": "primary"}
        )
        ExperimentToSavedMetric.objects.create(
            experiment=experiment, saved_metric=saved_secondary, metadata={"type": "secondary"}
        )

        output = self._run()
        experiment.refresh_from_db()

        # The command can only rewrite inline metrics, so a duplicate that exists
        # solely across two saved metrics is surfaced as skipped, not silently
        # left looking unprocessed.
        assert "1 skipped" in output
        assert experiment.metrics == []

    def test_is_restart_safe_after_a_full_run(self):
        dup = "33333333-0000-0000-0000-000000000001"
        experiment = self._create_experiment(
            "restart-safe",
            metrics=[self._metric(dup, "a"), self._metric(dup, "b")],
            primary_metrics_ordered_uuids=[dup],
        )

        self._run()
        first_pass_uuids = self._uuids(Experiment.objects.get(id=experiment.id).metrics)

        # A second run finds nothing left to fix and is a no-op.
        output = self._run()
        assert "No experiments to dedupe." in output
        assert self._uuids(Experiment.objects.get(id=experiment.id).metrics) == first_pass_uuids
