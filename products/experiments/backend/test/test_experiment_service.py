from datetime import timedelta
from decimal import Decimal

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.models import FeatureFlag, Team
from posthog.models.experiment import (
    Experiment,
    ExperimentHoldout,
    ExperimentMetricResult,
    ExperimentSavedMetric,
    ExperimentTimeseriesRecalculation,
)

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

    def test_create_experiment_with_minimum_fields_uses_defaults(self):
        self._create_flag(key="minimum-flag")
        service = self._service()

        experiment = service.create_experiment(name="Minimum Experiment", feature_flag_key="minimum-flag")

        assert experiment.name == "Minimum Experiment"
        assert experiment.feature_flag.key == "minimum-flag"
        assert experiment.is_draft
        assert experiment.description == ""
        assert experiment.type == "product"
        assert experiment.parameters is None
        assert experiment.metrics == []
        assert experiment.metrics_secondary == []
        assert experiment.secondary_metrics == []
        assert experiment.filters == {}
        assert experiment.scheduling_config is None
        assert experiment.exposure_preaggregation_enabled is False
        assert experiment.archived is False
        assert experiment.deleted is False
        assert experiment.conclusion is None
        assert experiment.conclusion_comment is None
        assert experiment.primary_metrics_ordered_uuids is None
        assert experiment.secondary_metrics_ordered_uuids is None
        assert experiment.stats_config is not None
        assert experiment.stats_config["method"] == "bayesian"
        assert experiment.exposure_criteria == {"filterTestAccounts": True}

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

    @parameterized.expand(
        [
            ("not_list", {"id": 1}, "Saved metrics must be a list"),
            ("missing_id", [{"metadata": {"type": "primary"}}], "Saved metric must have an id"),
            ("non_object", [[1]], "Saved metric must be an object"),
            ("metadata_not_object", [{"id": 1, "metadata": "primary"}], "Metadata must be an object"),
            ("metadata_missing_type", [{"id": 1, "metadata": {"xxx": "primary"}}], "Metadata must have a type key"),
        ]
    )
    def test_create_experiment_validates_saved_metrics_payload(
        self, _: str, saved_metrics_ids: object, expected_error: str
    ) -> None:
        self._create_flag(key="saved-metrics-invalid")
        service = self._service()

        with self.assertRaises(ValidationError) as ctx:
            service.create_experiment(
                name="Saved Metrics Invalid",
                feature_flag_key="saved-metrics-invalid",
                saved_metrics_ids=saved_metrics_ids,  # type: ignore[arg-type]
            )

        assert expected_error in str(ctx.exception)

    def test_create_experiment_rejects_saved_metrics_from_another_team(self) -> None:
        self._create_flag(key="saved-metrics-team-check")
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        saved_metric = ExperimentSavedMetric.objects.create(
            team=other_team,
            name="Other Team Metric",
            query={"kind": "ExperimentMetric", "metric_type": "count", "uuid": "other-uuid", "event": "$pageview"},
        )
        service = self._service()

        with self.assertRaises(ValidationError) as ctx:
            service.create_experiment(
                name="Wrong Team Metric",
                feature_flag_key="saved-metrics-team-check",
                saved_metrics_ids=[{"id": saved_metric.id, "metadata": {"type": "primary"}}],
            )

        assert "Saved metric does not exist or does not belong to this project" in str(ctx.exception)

    # ------------------------------------------------------------------
    # Service contract fields
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

    def test_create_experiment_with_all_fields(self):
        service = self._service()
        now = timezone.now()

        holdout = ExperimentHoldout.objects.create(
            team=self.team,
            created_by=self.user,
            name="All Fields Holdout",
            filters=[{"properties": [], "rollout_percentage": 10}],
        )
        saved_metric_primary = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="Primary Saved Metric",
            query={"kind": "ExperimentMetric", "metric_type": "count", "uuid": "saved-primary", "event": "$pageview"},
        )
        saved_metric_secondary = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="Secondary Saved Metric",
            query={"kind": "ExperimentMetric", "metric_type": "count", "uuid": "saved-secondary", "event": "$pageview"},
        )

        primary_metric_uuid = "inline-primary"
        secondary_metric_uuid = "inline-secondary"

        secondary_metrics = [
            {
                "name": "Legacy secondary metric",
                "filters": {"events": [{"id": "$pageview", "name": "$pageview", "order": 0, "type": "events"}]},
            },
        ]

        experiment = service.create_experiment(
            name="All Fields Experiment",
            feature_flag_key="all-fields-flag",
            description="All optional fields set",
            type="web",
            parameters={
                "feature_flag_variants": [
                    {"key": "control", "name": "Control", "rollout_percentage": 34},
                    {"key": "variant-a", "name": "Variant A", "rollout_percentage": 33},
                    {"key": "variant-b", "name": "Variant B", "rollout_percentage": 33},
                ],
                "rollout_percentage": 80,
                "minimum_detectable_effect": 20,
            },
            metrics=[
                {"kind": "ExperimentMetric", "metric_type": "count", "uuid": primary_metric_uuid, "event": "$pageview"}
            ],
            metrics_secondary=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "count",
                    "uuid": secondary_metric_uuid,
                    "event": "$pageleave",
                }
            ],
            secondary_metrics=secondary_metrics,
            stats_config={"method": "frequentist", "frequentist": {"alpha": 0.08}},
            exposure_criteria={"filterTestAccounts": True},
            holdout=holdout,
            saved_metrics_ids=[
                {"id": saved_metric_primary.id, "metadata": {"type": "primary"}},
                {"id": saved_metric_secondary.id, "metadata": {"type": "secondary"}},
            ],
            start_date=now,
            end_date=now + timedelta(days=14),
            primary_metrics_ordered_uuids=["manual-primary"],
            secondary_metrics_ordered_uuids=["manual-secondary"],
            create_in_folder="Test/Experiments",
            filters={"events": [], "actions": [], "properties": []},
            scheduling_config={"timeseries": True},
            exposure_preaggregation_enabled=True,
            archived=True,
            deleted=True,
            conclusion="won",
            conclusion_comment="Shipped to 100%",
        )

        assert experiment.name == "All Fields Experiment"
        assert experiment.description == "All optional fields set"
        assert experiment.type == "web"
        assert experiment.feature_flag.key == "all-fields-flag"
        assert experiment.feature_flag.active is True
        assert experiment.holdout_id == holdout.id
        assert experiment.secondary_metrics == secondary_metrics
        assert experiment.exposure_preaggregation_enabled is True
        assert experiment.archived is True
        assert experiment.deleted is True
        assert experiment.conclusion == "won"
        assert experiment.conclusion_comment == "Shipped to 100%"
        assert experiment.filters == {"events": [], "actions": [], "properties": []}
        assert experiment.scheduling_config == {"timeseries": True}

        assert experiment.metrics is not None
        assert len(experiment.metrics) == 1
        assert experiment.metrics[0]["uuid"] == primary_metric_uuid
        assert "fingerprint" in experiment.metrics[0]

        assert experiment.metrics_secondary is not None
        assert len(experiment.metrics_secondary) == 1
        assert experiment.metrics_secondary[0]["uuid"] == secondary_metric_uuid
        assert "fingerprint" in experiment.metrics_secondary[0]

        assert experiment.variants == {
            "control": {"rollout_percentage": 34},
            "variant-a": {"rollout_percentage": 33},
            "variant-b": {"rollout_percentage": 33},
        }

        assert set(experiment.primary_metrics_ordered_uuids or []) == {
            "manual-primary",
            primary_metric_uuid,
            "saved-primary",
        }
        assert set(experiment.secondary_metrics_ordered_uuids or []) == {
            "manual-secondary",
            secondary_metric_uuid,
            "saved-secondary",
        }

    def test_create_experiment_rolls_back_when_late_validation_fails(self):
        service = self._service()

        with (
            patch.object(
                ExperimentService,
                "_validate_metric_ordering_on_create",
                side_effect=ValidationError("ordering invalid"),
            ),
            self.assertRaises(ValidationError),
        ):
            service.create_experiment(
                name="Rollback Create",
                feature_flag_key="rollback-create-flag",
            )

        assert not Experiment.objects.filter(name="Rollback Create").exists()
        assert not FeatureFlag.objects.filter(team=self.team, key="rollback-create-flag").exists()

    # ------------------------------------------------------------------
    # Status field
    # ------------------------------------------------------------------

    @parameterized.expand(
        [
            ("draft", None, None),
            ("running", timezone.now(), None),
            ("stopped", timezone.now(), timezone.now() + timedelta(days=7)),
        ]
    )
    def test_create_experiment_sets_correct_status(self, expected_status, start_date, end_date):
        service = self._service()

        experiment = service.create_experiment(
            name=f"Status {expected_status}",
            feature_flag_key=f"status-{expected_status}",
            start_date=start_date,
            end_date=end_date,
        )

        assert experiment.status == expected_status

    def test_partial_save_with_update_fields_still_persists_status(self):
        service = self._service()

        experiment = service.create_experiment(
            name="Partial Save",
            feature_flag_key="partial-save-flag",
        )
        assert experiment.status == "draft"

        experiment.start_date = timezone.now()
        experiment.save(update_fields=["start_date"])

        experiment.refresh_from_db()
        assert experiment.status == "running"

    def test_create_experiment_with_unknown_field_raises_type_error(self):
        self._create_flag(key="unknown-key-flag")
        service = self._service()

        with self.assertRaises(TypeError) as ctx:
            service.create_experiment(
                name="Unknown Key",
                feature_flag_key="unknown-key-flag",
                unknown_field="boom",  # type: ignore[call-arg]
            )

        assert "unexpected keyword argument 'unknown_field'" in str(ctx.exception)

    # ------------------------------------------------------------------
    # Update experiment
    # ------------------------------------------------------------------

    def _create_draft_experiment(self, name: str = "Draft Experiment", flag_key: str = "draft-flag") -> Experiment:
        self._create_flag(key=flag_key)
        service = self._service()
        return service.create_experiment(
            name=name,
            feature_flag_key=flag_key,
            metrics=[{"kind": "ExperimentMetric", "metric_type": "count", "uuid": "m1", "event": "$pageview"}],
            primary_metrics_ordered_uuids=["m1"],
        )

    def test_update_experiment_basic_fields(self):
        experiment = self._create_draft_experiment()
        service = self._service()

        updated = service.update_experiment(
            experiment,
            {
                "name": "Updated Name",
                "description": "Updated description",
            },
        )

        assert updated.name == "Updated Name"
        assert updated.description == "Updated description"

    def test_update_experiment_rejects_extra_keys(self):
        experiment = self._create_draft_experiment()
        service = self._service()

        with self.assertRaises(ValidationError) as ctx:
            service.update_experiment(experiment, {"unknown_key": "value"})

        assert "Can't update keys" in str(ctx.exception)

    def test_update_experiment_allows_matching_feature_flag_key(self):
        experiment = self._create_draft_experiment()
        service = self._service()

        updated = service.update_experiment(
            experiment,
            {
                "name": "Same Key OK",
                "get_feature_flag_key": experiment.feature_flag.key,
            },
        )

        assert updated.name == "Same Key OK"
        assert updated.get_feature_flag_key() == experiment.feature_flag.key

    def test_update_experiment_rejects_different_feature_flag_key(self):
        experiment = self._create_draft_experiment()
        service = self._service()

        with self.assertRaises(ValidationError) as ctx:
            service.update_experiment(
                experiment,
                {
                    "get_feature_flag_key": "different-key",
                },
            )

        assert "Can't update keys" in str(ctx.exception)

    def test_update_experiment_launches_by_setting_start_date(self):
        service = self._service()
        # Create experiment with a new flag (service creates flag as inactive for drafts)
        experiment = service.create_experiment(
            name="Launch Test",
            feature_flag_key="launch-test-flag",
            metrics=[{"kind": "ExperimentMetric", "metric_type": "count", "uuid": "m1", "event": "$pageview"}],
            primary_metrics_ordered_uuids=["m1"],
        )
        assert experiment.is_draft
        assert experiment.feature_flag.active is False

        now = timezone.now()
        updated = service.update_experiment(experiment, {"start_date": now})

        assert updated.start_date == now
        updated.feature_flag.refresh_from_db()
        assert updated.feature_flag.active is True

    def test_update_experiment_rejects_variants_change_after_launch(self):
        experiment = self._create_draft_experiment()
        service = self._service()
        service.update_experiment(experiment, {"start_date": timezone.now()})

        with self.assertRaises(ValidationError) as ctx:
            service.update_experiment(
                experiment,
                {
                    "parameters": {
                        "feature_flag_variants": [
                            {"key": "control", "name": "Control", "rollout_percentage": 34},
                            {"key": "test", "name": "Test", "rollout_percentage": 33},
                            {"key": "new_variant", "name": "New", "rollout_percentage": 33},
                        ]
                    }
                },
            )

        assert "Can't update feature_flag_variants" in str(ctx.exception)

    def test_update_experiment_rejects_holdout_change_after_launch(self):
        holdout = ExperimentHoldout.objects.create(
            team=self.team,
            created_by=self.user,
            name="Holdout",
            filters=[{"properties": [], "rollout_percentage": 10}],
        )
        experiment = self._create_draft_experiment()
        service = self._service()
        service.update_experiment(experiment, {"start_date": timezone.now()})

        with self.assertRaises(ValidationError) as ctx:
            service.update_experiment(experiment, {"holdout": holdout})

        assert "Can't update holdout" in str(ctx.exception)

    def test_update_experiment_rejects_global_filter_properties(self):
        experiment = self._create_draft_experiment()
        service = self._service()

        with self.assertRaises(ValidationError) as ctx:
            service.update_experiment(experiment, {"filters": {"properties": [{"key": "country", "value": "US"}]}})

        assert "global filter properties" in str(ctx.exception)

    def test_update_experiment_syncs_feature_flag_variants_for_draft(self):
        experiment = self._create_draft_experiment()
        service = self._service()

        service.update_experiment(
            experiment,
            {
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 34},
                        {"key": "test", "name": "Test", "rollout_percentage": 33},
                        {"key": "variant-b", "name": "Variant B", "rollout_percentage": 33},
                    ],
                }
            },
        )

        experiment.feature_flag.refresh_from_db()
        variants = experiment.feature_flag.filters["multivariate"]["variants"]
        assert len(variants) == 3
        assert variants[2]["key"] == "variant-b"

    def test_update_experiment_recalculates_fingerprints(self):
        experiment = self._create_draft_experiment()
        assert experiment.metrics is not None
        original_fingerprint = experiment.metrics[0]["fingerprint"]

        service = self._service()
        updated = service.update_experiment(experiment, {"start_date": timezone.now()})

        assert updated.metrics is not None
        assert updated.metrics[0]["fingerprint"] != original_fingerprint

    def test_update_experiment_syncs_ordering_on_metric_add(self):
        experiment = self._create_draft_experiment()
        service = self._service()

        updated = service.update_experiment(
            experiment,
            {
                "metrics": [
                    {"kind": "ExperimentMetric", "metric_type": "count", "uuid": "m1", "event": "$pageview"},
                    {"kind": "ExperimentMetric", "metric_type": "count", "uuid": "m2", "event": "$pageleave"},
                ],
            },
        )

        assert updated.primary_metrics_ordered_uuids is not None
        assert "m1" in updated.primary_metrics_ordered_uuids
        assert "m2" in updated.primary_metrics_ordered_uuids

    def test_update_experiment_syncs_ordering_on_metric_remove(self):
        self._create_flag(key="remove-test")
        service = self._service()
        experiment = service.create_experiment(
            name="Remove Test",
            feature_flag_key="remove-test",
            metrics=[
                {"kind": "ExperimentMetric", "metric_type": "count", "uuid": "m1", "event": "$pageview"},
                {"kind": "ExperimentMetric", "metric_type": "count", "uuid": "m2", "event": "$pageleave"},
            ],
            primary_metrics_ordered_uuids=["m1", "m2"],
        )

        updated = service.update_experiment(
            experiment,
            {
                "metrics": [
                    {"kind": "ExperimentMetric", "metric_type": "count", "uuid": "m1", "event": "$pageview"},
                ],
            },
        )

        assert updated.primary_metrics_ordered_uuids == ["m1"]

    def test_update_experiment_replaces_saved_metrics(self):
        experiment = self._create_draft_experiment()
        sm1 = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="SM1",
            query={"kind": "ExperimentMetric", "metric_type": "count", "uuid": "sm-1", "event": "$pageview"},
        )
        sm2 = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="SM2",
            query={"kind": "ExperimentMetric", "metric_type": "count", "uuid": "sm-2", "event": "$pageleave"},
        )

        service = self._service()
        service.update_experiment(
            experiment,
            {
                "saved_metrics_ids": [{"id": sm1.id, "metadata": {"type": "primary"}}],
            },
        )

        assert experiment.experimenttosavedmetric_set.count() == 1
        first_link = experiment.experimenttosavedmetric_set.first()
        assert first_link is not None
        assert first_link.saved_metric_id == sm1.id

        service.update_experiment(
            experiment,
            {
                "saved_metrics_ids": [{"id": sm2.id, "metadata": {"type": "secondary"}}],
            },
        )

        assert experiment.experimenttosavedmetric_set.count() == 1
        second_link = experiment.experimenttosavedmetric_set.first()
        assert second_link is not None
        assert second_link.saved_metric_id == sm2.id

    def test_update_experiment_rolls_back_saved_metric_changes_on_validation_error(self):
        self._create_flag(key="rollback-update")
        sm1 = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="SM1",
            query={"kind": "ExperimentMetric", "metric_type": "count", "uuid": "sm-1", "event": "$pageview"},
        )
        sm2 = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="SM2",
            query={"kind": "ExperimentMetric", "metric_type": "count", "uuid": "sm-2", "event": "$pageleave"},
        )
        service = self._service()
        experiment = service.create_experiment(
            name="Rollback Update",
            feature_flag_key="rollback-update",
            saved_metrics_ids=[{"id": sm1.id, "metadata": {"type": "primary"}}],
        )

        with self.assertRaises(ValidationError) as ctx:
            service.update_experiment(
                experiment,
                {
                    "saved_metrics_ids": [{"id": sm2.id, "metadata": {"type": "secondary"}}],
                    "unknown_key": "value",
                },
            )

        assert "Can't update keys" in str(ctx.exception)

        link_ids = list(
            Experiment.objects.get(id=experiment.id).experimenttosavedmetric_set.values_list(
                "saved_metric_id", flat=True
            )
        )
        assert link_ids == [sm1.id]

        fresh_experiment = Experiment.objects.get(id=experiment.id)
        assert fresh_experiment.primary_metrics_ordered_uuids == ["sm-1"]
        assert fresh_experiment.secondary_metrics_ordered_uuids == []

    def test_update_experiment_validates_saved_metrics_before_mutation(self) -> None:
        self._create_flag(key="saved-metrics-update-validate")
        sm1 = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="SM1",
            query={"kind": "ExperimentMetric", "metric_type": "count", "uuid": "sm-1", "event": "$pageview"},
        )
        service = self._service()
        experiment = service.create_experiment(
            name="Update Validation",
            feature_flag_key="saved-metrics-update-validate",
            saved_metrics_ids=[{"id": sm1.id, "metadata": {"type": "primary"}}],
        )

        with (
            patch("django.db.models.query.QuerySet.delete") as delete_mock,
            self.assertRaises(ValidationError) as ctx,
        ):
            service.update_experiment(
                experiment,
                {
                    "saved_metrics_ids": [[sm1.id]],
                },
            )

        assert "Saved metric must be an object" in str(ctx.exception)
        delete_mock.assert_not_called()

    def test_update_experiment_validates_unknown_keys_before_saved_metric_mutation(self):
        self._create_flag(key="validate-before-mutate")
        sm1 = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="SM1",
            query={"kind": "ExperimentMetric", "metric_type": "count", "uuid": "sm-1", "event": "$pageview"},
        )
        sm2 = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="SM2",
            query={"kind": "ExperimentMetric", "metric_type": "count", "uuid": "sm-2", "event": "$pageleave"},
        )
        service = self._service()
        experiment = service.create_experiment(
            name="Validate Before Mutate",
            feature_flag_key="validate-before-mutate",
            saved_metrics_ids=[{"id": sm1.id, "metadata": {"type": "primary"}}],
        )

        with (
            patch("django.db.models.query.QuerySet.delete") as delete_mock,
            self.assertRaises(ValidationError) as ctx,
        ):
            service.update_experiment(
                experiment,
                {
                    "saved_metrics_ids": [{"id": sm2.id, "metadata": {"type": "secondary"}}],
                    "unknown_key": "value",
                },
            )

        assert "Can't update keys" in str(ctx.exception)
        delete_mock.assert_not_called()

    def test_update_experiment_restore_with_deleted_flag_raises(self):
        experiment = self._create_draft_experiment()
        service = self._service()
        experiment.deleted = True
        experiment.save()
        experiment.feature_flag.deleted = True
        experiment.feature_flag.save()

        with self.assertRaises(ValidationError) as ctx:
            service.update_experiment(experiment, {"deleted": False})

        assert "linked feature flag has been deleted" in str(ctx.exception)

    def test_update_experiment_updates_holdout_on_draft(self):
        holdout = ExperimentHoldout.objects.create(
            team=self.team,
            created_by=self.user,
            name="H",
            filters=[{"properties": [], "rollout_percentage": 10}],
        )
        experiment = self._create_draft_experiment()
        service = self._service()

        service.update_experiment(experiment, {"holdout": holdout})

        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.filters["holdout_groups"] == holdout.filters

    # ------------------------------------------------------------------
    # Duplicate experiment
    # ------------------------------------------------------------------

    def test_duplicate_experiment_creates_draft_copy(self):
        self._create_flag(key="dup-source")
        service = self._service()
        source = service.create_experiment(
            name="Original",
            feature_flag_key="dup-source",
            description="Original desc",
            start_date=timezone.now(),
        )

        dup = service.duplicate_experiment(source)

        assert dup.name == "Original (Copy)"
        assert dup.description == "Original desc"
        assert dup.is_draft
        assert dup.start_date is None
        assert dup.end_date is None
        assert dup.archived is False
        assert dup.deleted is False
        assert dup.id != source.id
        # Same flag key → reuses the existing flag
        assert dup.feature_flag.id == source.feature_flag.id

    def test_duplicate_experiment_generates_unique_name(self):
        self._create_flag(key="dup-unique-1")
        service = self._service()
        source = service.create_experiment(name="Test", feature_flag_key="dup-unique-1")

        dup1 = service.duplicate_experiment(source)
        assert dup1.name == "Test (Copy)"

        dup2 = service.duplicate_experiment(source)
        assert dup2.name == "Test (Copy) 1"

    def test_duplicate_experiment_with_custom_flag_key(self):
        self._create_flag(key="dup-custom-source")
        self._create_flag(
            key="dup-custom-target",
            variants=[
                {"key": "control", "name": "Control", "rollout_percentage": 34},
                {"key": "test", "name": "Test", "rollout_percentage": 33},
                {"key": "extra", "name": "Extra", "rollout_percentage": 33},
            ],
        )
        service = self._service()
        source = service.create_experiment(
            name="Custom Key",
            feature_flag_key="dup-custom-source",
        )

        dup = service.duplicate_experiment(source, feature_flag_key="dup-custom-target")

        assert dup.feature_flag.key == "dup-custom-target"
        flag_variants = dup.feature_flag.filters["multivariate"]["variants"]
        assert len(flag_variants) == 3

    def test_duplicate_experiment_revalidates_source_parameters(self):
        self._create_flag(key="dup-invalid-source")
        service = self._service()
        source = service.create_experiment(
            name="Invalid Source",
            feature_flag_key="dup-invalid-source",
        )
        Experiment.objects.filter(id=source.id).update(
            parameters={
                "feature_flag_variants": [
                    {"key": "test", "name": "Test", "rollout_percentage": 100},
                ]
            }
        )
        source.refresh_from_db()

        with self.assertRaises(ValidationError) as ctx:
            service.duplicate_experiment(source)

        assert "at least 2 variants" in str(ctx.exception)

    def test_duplicate_experiment_copies_saved_metrics(self):
        self._create_flag(key="dup-saved")
        sm = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="SM",
            query={"kind": "ExperimentMetric", "metric_type": "count", "uuid": "sm-uuid", "event": "$pageview"},
        )
        service = self._service()
        source = service.create_experiment(
            name="With Saved",
            feature_flag_key="dup-saved",
            saved_metrics_ids=[{"id": sm.id, "metadata": {"type": "primary"}}],
        )

        dup = service.duplicate_experiment(source)

        links = list(dup.experimenttosavedmetric_set.all())
        assert len(links) == 1
        assert links[0].saved_metric_id == sm.id

    # ------------------------------------------------------------------
    # Exposure cohort
    # ------------------------------------------------------------------

    def test_create_exposure_cohort(self):
        self._create_flag(key="cohort-flag")
        service = self._service()
        experiment = service.create_experiment(
            name="Cohort Test",
            feature_flag_key="cohort-flag",
            start_date=timezone.now(),
        )

        cohort = service.create_exposure_cohort(experiment)

        assert cohort.name == 'Users exposed to experiment "Cohort Test"'
        assert cohort.is_static is False
        experiment.refresh_from_db()
        assert experiment.exposure_cohort_id == cohort.id

    def test_create_exposure_cohort_without_start_date_raises(self):
        self._create_flag(key="cohort-no-start")
        service = self._service()
        experiment = service.create_experiment(name="No Start", feature_flag_key="cohort-no-start")

        with self.assertRaises(ValidationError) as ctx:
            service.create_exposure_cohort(experiment)

        assert "does not have a start date" in str(ctx.exception)

    def test_create_exposure_cohort_duplicate_raises(self):
        from posthog.models.cohort import Cohort

        self._create_flag(key="cohort-dup")
        service = self._service()
        experiment = service.create_experiment(
            name="Dup Cohort",
            feature_flag_key="cohort-dup",
            start_date=timezone.now(),
        )
        cohort = Cohort.objects.create(team=self.team, name="Existing")
        experiment.exposure_cohort = cohort
        experiment.save(update_fields=["exposure_cohort"])

        with self.assertRaises(ValidationError) as ctx:
            service.create_exposure_cohort(experiment)

        assert "already has an exposure cohort" in str(ctx.exception)

    # ------------------------------------------------------------------
    # Timeseries results
    # ------------------------------------------------------------------

    def test_get_timeseries_results_no_start_date_raises(self):
        self._create_flag(key="ts-no-start")
        service = self._service()
        experiment = service.create_experiment(name="No Start", feature_flag_key="ts-no-start")

        with self.assertRaises(ValidationError) as ctx:
            service.get_timeseries_results(experiment, metric_uuid="m1", fingerprint="fp1")

        assert "not been started" in str(ctx.exception)

    def test_get_timeseries_results_pending_when_no_records(self):
        self._create_flag(key="ts-pending")
        service = self._service()
        experiment = service.create_experiment(
            name="Pending",
            feature_flag_key="ts-pending",
            start_date=timezone.now() - timedelta(days=2),
            end_date=timezone.now(),
        )

        result = service.get_timeseries_results(experiment, metric_uuid="m1", fingerprint="fp1")

        assert result["status"] == "pending"
        assert result["experiment_id"] == experiment.id
        assert result["metric_uuid"] == "m1"
        assert len(result["timeseries"]) == 3

    def test_get_timeseries_results_completed(self):
        self._create_flag(key="ts-completed")
        service = self._service()
        now = timezone.now()
        # Use midnight-aligned dates so query_to boundaries map correctly
        start_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        end_midnight = start_midnight + timedelta(days=1)
        experiment = service.create_experiment(
            name="Completed",
            feature_flag_key="ts-completed",
            start_date=start_midnight,
            end_date=end_midnight,
        )

        # Create results whose query_to is midnight (exclusive end of each day)
        for day_offset in range(2):
            ExperimentMetricResult.objects.create(
                experiment=experiment,
                metric_uuid="m1",
                fingerprint="fp1",
                query_from=start_midnight + timedelta(days=day_offset),
                query_to=start_midnight + timedelta(days=day_offset + 1),
                status="completed",
                result={"variant_control": {"count": 100}},
                completed_at=now,
            )

        result = service.get_timeseries_results(experiment, metric_uuid="m1", fingerprint="fp1")

        assert result["status"] == "completed"
        assert result["computed_at"] is not None

    # ------------------------------------------------------------------
    # Timeseries recalculation
    # ------------------------------------------------------------------

    def test_request_timeseries_recalculation(self):
        self._create_flag(key="ts-recalc")
        service = self._service()
        experiment = service.create_experiment(
            name="Recalc",
            feature_flag_key="ts-recalc",
            start_date=timezone.now(),
        )

        result = service.request_timeseries_recalculation(
            experiment, metric={"uuid": "m1", "kind": "ExperimentMetric"}, fingerprint="fp1"
        )

        assert result["experiment_id"] == experiment.id
        assert result["metric_uuid"] == "m1"
        assert result["status"] == ExperimentTimeseriesRecalculation.Status.PENDING
        assert result["is_existing"] is False

    def test_request_timeseries_recalculation_idempotent(self):
        self._create_flag(key="ts-idempotent")
        service = self._service()
        experiment = service.create_experiment(
            name="Idempotent",
            feature_flag_key="ts-idempotent",
            start_date=timezone.now(),
        )

        result1 = service.request_timeseries_recalculation(experiment, metric={"uuid": "m1"}, fingerprint="fp1")
        result2 = service.request_timeseries_recalculation(experiment, metric={"uuid": "m1"}, fingerprint="fp1")

        assert result1["id"] == result2["id"]
        assert result2["is_existing"] is True

    def test_request_timeseries_recalculation_not_started_raises(self):
        self._create_flag(key="ts-not-started")
        service = self._service()
        experiment = service.create_experiment(name="Not Started", feature_flag_key="ts-not-started")

        with self.assertRaises(ValidationError) as ctx:
            service.request_timeseries_recalculation(experiment, metric={"uuid": "m1"}, fingerprint="fp1")

        assert "hasn't started" in str(ctx.exception)

    def test_request_timeseries_recalculation_deletes_old_results(self):
        self._create_flag(key="ts-delete-old")
        service = self._service()
        now = timezone.now()
        experiment = service.create_experiment(
            name="Delete Old",
            feature_flag_key="ts-delete-old",
            start_date=now,
        )

        ExperimentMetricResult.objects.create(
            experiment=experiment,
            metric_uuid="m1",
            fingerprint="fp1",
            query_from=now,
            query_to=now + timedelta(days=1),
            status="completed",
            result={"data": True},
            completed_at=now,
        )
        assert ExperimentMetricResult.objects.filter(experiment=experiment, metric_uuid="m1").count() == 1

        service.request_timeseries_recalculation(experiment, metric={"uuid": "m1"}, fingerprint="fp1")

        assert ExperimentMetricResult.objects.filter(experiment=experiment, metric_uuid="m1").count() == 0

    # ------------------------------------------------------------------
    # Velocity stats
    # ------------------------------------------------------------------

    def test_get_velocity_stats_empty(self):
        service = self._service()
        result = service.get_velocity_stats()

        assert result["launched_last_30d"] == 0
        assert result["launched_previous_30d"] == 0
        assert result["percent_change"] == 0.0
        assert result["active_experiments"] == 0
        assert result["completed_last_30d"] == 0

    def test_get_velocity_stats_with_experiments(self):
        service = self._service()
        now = timezone.now()

        self._create_flag(key="stats-active")
        service.create_experiment(
            name="Active",
            feature_flag_key="stats-active",
            start_date=now - timedelta(days=5),
        )

        self._create_flag(key="stats-completed")
        service.create_experiment(
            name="Completed",
            feature_flag_key="stats-completed",
            start_date=now - timedelta(days=10),
            end_date=now - timedelta(days=3),
        )

        result = service.get_velocity_stats()

        assert result["launched_last_30d"] == 2
        assert result["active_experiments"] == 1
        assert result["completed_last_30d"] == 1

    def test_get_velocity_stats_percent_change(self):
        service = self._service()
        now = timezone.now()

        for i in range(3):
            key = f"stats-prev-{i}"
            self._create_flag(key=key)
            exp = service.create_experiment(name=f"Prev {i}", feature_flag_key=key)
            Experiment.objects.filter(id=exp.id).update(
                start_date=now - timedelta(days=45),
                end_date=now - timedelta(days=35),
            )

        self._create_flag(key="stats-recent")
        service.create_experiment(
            name="Recent",
            feature_flag_key="stats-recent",
            start_date=now - timedelta(days=5),
        )

        result = service.get_velocity_stats()

        assert result["launched_last_30d"] == 1
        assert result["launched_previous_30d"] == 3
        expected_change = round(((1 - 3) / 3) * 100, 1)
        assert result["percent_change"] == expected_change
