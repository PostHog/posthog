from decimal import Decimal

from posthog.test.base import APIBaseTest

from rest_framework.exceptions import ValidationError

from posthog.models import FeatureFlag
from posthog.models.experiment import ExperimentSavedMetric

from products.experiments.backend.experiment_service import ExperimentService


class TestExperimentService(APIBaseTest):
    def _service(self) -> ExperimentService:
        return ExperimentService(team=self.team, user=self.user)

    def _create_flag(
        self,
        key: str = "test-flag",
        variants: list[dict] | None = None,
    ) -> FeatureFlag:
        if variants is None:
            variants = [
                {"key": "control", "name": "Control", "rollout_percentage": 50},
                {"key": "test", "name": "Test", "rollout_percentage": 50},
            ]
        return FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=key,
            name=f"Flag for {key}",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {"variants": variants},
            },
        )

    # ------------------------------------------------------------------
    # Basic creation
    # ------------------------------------------------------------------

    def test_create_draft_experiment_with_existing_flag(self):
        self._create_flag(key="my-flag")
        service = self._service()

        experiment = service.create_experiment(name="My Experiment", feature_flag_key="my-flag")

        assert experiment.name == "My Experiment"
        assert experiment.feature_flag.key == "my-flag"
        assert experiment.is_draft
        assert experiment.metrics == []
        assert experiment.metrics_secondary == []
        assert experiment.filters == {}

    def test_create_experiment_creates_new_flag(self):
        service = self._service()

        experiment = service.create_experiment(
            name="New Flag Experiment",
            feature_flag_key="brand-new-flag",
        )

        flag = experiment.feature_flag
        assert flag.key == "brand-new-flag"
        assert flag.name == "Feature Flag for Experiment New Flag Experiment"
        variants = flag.filters["multivariate"]["variants"]
        assert len(variants) == 2
        assert variants[0]["key"] == "control"
        assert variants[1]["key"] == "test"
        assert flag.active is False  # draft → flag inactive

    def test_create_launched_experiment_activates_flag(self):
        from django.utils import timezone

        service = self._service()
        now = timezone.now()

        experiment = service.create_experiment(
            name="Launched Experiment",
            feature_flag_key="launched-flag",
            start_date=now,
        )

        assert experiment.start_date == now
        assert not experiment.is_draft
        assert experiment.feature_flag.active is True

    # ------------------------------------------------------------------
    # Stats config defaults
    # ------------------------------------------------------------------

    def test_stats_config_defaults_bayesian(self):
        self._create_flag(key="stats-test")
        service = self._service()

        experiment = service.create_experiment(name="Stats Test", feature_flag_key="stats-test")

        assert experiment.stats_config is not None
        assert experiment.stats_config["method"] == "bayesian"

    def test_stats_config_defaults_from_team(self):
        self.team.default_experiment_stats_method = "frequentist"
        self.team.default_experiment_confidence_level = Decimal("0.90")
        self.team.save()

        self._create_flag(key="team-defaults")
        service = self._service()

        experiment = service.create_experiment(name="Team Defaults", feature_flag_key="team-defaults")

        assert experiment.stats_config is not None
        assert experiment.stats_config["method"] == "frequentist"
        assert experiment.stats_config["bayesian"]["ci_level"] == 0.90
        assert abs(experiment.stats_config["frequentist"]["alpha"] - 0.10) < 1e-10

    def test_stats_config_preserves_provided_method(self):
        self.team.default_experiment_stats_method = "bayesian"
        self.team.save()

        self._create_flag(key="preserve-method")
        service = self._service()

        experiment = service.create_experiment(
            name="Preserve Method",
            feature_flag_key="preserve-method",
            stats_config={"method": "frequentist"},
        )

        assert experiment.stats_config is not None
        assert experiment.stats_config["method"] == "frequentist"

    def test_stats_config_preserves_provided_confidence(self):
        self.team.default_experiment_confidence_level = Decimal("0.90")
        self.team.save()

        self._create_flag(key="preserve-confidence")
        service = self._service()

        experiment = service.create_experiment(
            name="Preserve Confidence",
            feature_flag_key="preserve-confidence",
            stats_config={"method": "bayesian", "bayesian": {"ci_level": 0.99}},
        )

        assert experiment.stats_config is not None
        assert experiment.stats_config["bayesian"]["ci_level"] == 0.99

    # ------------------------------------------------------------------
    # Metric fingerprints
    # ------------------------------------------------------------------

    def test_metric_fingerprints_computed(self):
        self._create_flag(key="fingerprint-test")
        service = self._service()

        metrics = [
            {
                "kind": "ExperimentMetric",
                "metric_type": "count",
                "uuid": "uuid-1",
                "event": "$pageview",
            },
        ]

        experiment = service.create_experiment(
            name="Fingerprint Test",
            feature_flag_key="fingerprint-test",
            metrics=metrics,
        )

        assert experiment.metrics is not None
        assert len(experiment.metrics) == 1
        assert "fingerprint" in experiment.metrics[0]
        assert isinstance(experiment.metrics[0]["fingerprint"], str)
        assert len(experiment.metrics[0]["fingerprint"]) == 64  # SHA256 hex

    def test_no_fingerprints_when_no_metrics(self):
        self._create_flag(key="no-metrics")
        service = self._service()

        experiment = service.create_experiment(name="No Metrics", feature_flag_key="no-metrics")

        assert experiment.metrics == []

    # ------------------------------------------------------------------
    # Metric ordering
    # ------------------------------------------------------------------

    def test_metric_ordering_synced(self):
        self._create_flag(key="ordering-test")
        service = self._service()

        metrics = [
            {"kind": "ExperimentMetric", "metric_type": "count", "uuid": "aaa", "event": "$pageview"},
            {"kind": "ExperimentMetric", "metric_type": "count", "uuid": "bbb", "event": "$pageleave"},
        ]

        experiment = service.create_experiment(
            name="Ordering Test",
            feature_flag_key="ordering-test",
            metrics=metrics,
        )

        assert experiment.primary_metrics_ordered_uuids == ["aaa", "bbb"]

    def test_secondary_metric_ordering_synced(self):
        self._create_flag(key="sec-ordering")
        service = self._service()

        metrics_secondary = [
            {"kind": "ExperimentMetric", "metric_type": "count", "uuid": "sec-1", "event": "$pageview"},
        ]

        experiment = service.create_experiment(
            name="Secondary Ordering",
            feature_flag_key="sec-ordering",
            metrics_secondary=metrics_secondary,
        )

        assert experiment.secondary_metrics_ordered_uuids == ["sec-1"]

    # ------------------------------------------------------------------
    # Web experiment variants
    # ------------------------------------------------------------------

    def test_web_experiment_gets_variants(self):
        self._create_flag(
            key="web-flag",
            variants=[
                {"key": "control", "name": "Control", "rollout_percentage": 50},
                {"key": "test", "name": "Test", "rollout_percentage": 50},
            ],
        )
        service = self._service()

        experiment = service.create_experiment(
            name="Web Experiment",
            feature_flag_key="web-flag",
            type="web",
        )

        assert experiment.variants == {
            "control": {"rollout_percentage": 50},
            "test": {"rollout_percentage": 50},
        }

    # ------------------------------------------------------------------
    # Flag validation errors
    # ------------------------------------------------------------------

    def test_existing_flag_without_control_raises(self):
        self._create_flag(
            key="no-control",
            variants=[
                {"key": "baseline", "name": "Baseline", "rollout_percentage": 50},
                {"key": "test", "name": "Test", "rollout_percentage": 50},
            ],
        )
        service = self._service()

        with self.assertRaises(ValidationError) as ctx:
            service.create_experiment(name="Bad Flag", feature_flag_key="no-control")

        assert "control" in str(ctx.exception)

    def test_existing_flag_with_one_variant_raises(self):
        self._create_flag(
            key="one-variant",
            variants=[{"key": "control", "name": "Control", "rollout_percentage": 100}],
        )
        service = self._service()

        with self.assertRaises(ValidationError) as ctx:
            service.create_experiment(name="One Variant", feature_flag_key="one-variant")

        assert "at least 2 variants" in str(ctx.exception)

    # ------------------------------------------------------------------
    # Saved metrics
    # ------------------------------------------------------------------

    def test_saved_metrics_linked(self):
        self._create_flag(key="saved-metrics-test")
        saved_metric = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="My Saved Metric",
            query={"kind": "ExperimentMetric", "metric_type": "count", "uuid": "sm-uuid", "event": "$pageview"},
        )

        service = self._service()
        experiment = service.create_experiment(
            name="Saved Metrics Test",
            feature_flag_key="saved-metrics-test",
            saved_metrics_ids=[{"id": saved_metric.id, "metadata": {"type": "primary"}}],
        )

        links = list(experiment.experimenttosavedmetric_set.all())
        assert len(links) == 1
        assert links[0].saved_metric_id == saved_metric.id
        assert experiment.primary_metrics_ordered_uuids == ["sm-uuid"]

    # ------------------------------------------------------------------
    # Pass-through fields
    # ------------------------------------------------------------------

    def test_description_and_type_passed_through(self):
        self._create_flag(key="passthrough")
        service = self._service()

        experiment = service.create_experiment(
            name="Passthrough Test",
            feature_flag_key="passthrough",
            description="A description",
            type="web",
        )

        assert experiment.description == "A description"
        assert experiment.type == "web"

    def test_parameters_passed_through(self):
        self._create_flag(key="params-test")
        service = self._service()

        params = {
            "feature_flag_variants": [
                {"key": "control", "name": "Control", "rollout_percentage": 50},
                {"key": "test", "name": "Test", "rollout_percentage": 50},
            ],
            "minimum_detectable_effect": 30,
        }

        experiment = service.create_experiment(
            name="Params Test",
            feature_flag_key="params-test",
            parameters=params,
        )

        assert experiment.parameters == params
