from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory

from posthog.api.feature_flag import FeatureFlagSerializer
from posthog.models import FeatureFlag, Team
from posthog.models.action.action import Action
from posthog.models.evaluation_context import EvaluationContext, FeatureFlagEvaluationContext
from posthog.models.team.extensions import get_or_create_team_extension

from products.event_definitions.backend.models.event_definition import EventDefinition
from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentHoldout,
    ExperimentMetricResult,
    ExperimentSavedMetric,
    ExperimentTimeseriesRecalculation,
)
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig


# Note that we use allow_unknown_events here since allowing it was the behavior before validating it
# and to continue allowing it here keeps test setup simple (instead of creating events before)
class TestExperimentService(APIBaseTest):
    def _service(self) -> ExperimentService:
        return ExperimentService(team=self.team, user=self.user)

    def _make_request(self):
        request = APIRequestFactory().post("/fake")
        request.user = self.user
        return request

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
        config = get_or_create_team_extension(self.team, TeamExperimentsConfig)
        config.default_experiment_stats_method = "frequentist"
        config.default_experiment_confidence_level = Decimal("0.90")
        config.save()

        self._create_flag(key="team-defaults")
        service = self._service()

        experiment = service.create_experiment(name="Team Defaults", feature_flag_key="team-defaults")

        assert experiment.stats_config is not None
        assert experiment.stats_config["method"] == "frequentist"
        assert experiment.stats_config["bayesian"]["ci_level"] == 0.90
        assert abs(experiment.stats_config["frequentist"]["alpha"] - 0.10) < 1e-10

    def test_stats_config_preserves_provided_method(self):
        config = get_or_create_team_extension(self.team, TeamExperimentsConfig)
        config.default_experiment_stats_method = "bayesian"
        config.save()

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
        config = get_or_create_team_extension(self.team, TeamExperimentsConfig)
        config.default_experiment_confidence_level = Decimal("0.90")
        config.save()

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
                "metric_type": "mean",
                "uuid": "uuid-1",
                "source": {"kind": "EventsNode", "event": "$pageview"},
            },
        ]

        experiment = service.create_experiment(
            name="Fingerprint Test",
            feature_flag_key="fingerprint-test",
            allow_unknown_events=True,
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
            {
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "uuid": "aaa",
                "source": {"kind": "EventsNode", "event": "$pageview"},
            },
            {
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "uuid": "bbb",
                "source": {"kind": "EventsNode", "event": "$pageleave"},
            },
        ]

        experiment = service.create_experiment(
            name="Ordering Test",
            feature_flag_key="ordering-test",
            allow_unknown_events=True,
            metrics=metrics,
        )

        assert experiment.primary_metrics_ordered_uuids == ["aaa", "bbb"]

    def test_secondary_metric_ordering_synced(self):
        self._create_flag(key="sec-ordering")
        service = self._service()

        metrics_secondary = [
            {
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "uuid": "sec-1",
                "source": {"kind": "EventsNode", "event": "$pageview"},
            },
        ]

        experiment = service.create_experiment(
            name="Secondary Ordering",
            feature_flag_key="sec-ordering",
            allow_unknown_events=True,
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
            query={
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "uuid": "saved-primary",
                "source": {"kind": "EventsNode", "event": "$pageview"},
            },
        )
        saved_metric_secondary = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="Secondary Saved Metric",
            query={
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "uuid": "saved-secondary",
                "source": {"kind": "EventsNode", "event": "$pageview"},
            },
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
            allow_unknown_events=True,
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
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": primary_metric_uuid,
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                }
            ],
            metrics_secondary=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": secondary_metric_uuid,
                    "source": {"kind": "EventsNode", "event": "$pageleave"},
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
            allow_unknown_events=True,
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": "m1",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                }
            ],
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
            allow_unknown_events=True,
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": "m1",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                }
            ],
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
            allow_unknown_events=True,
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": "m1",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": "m2",
                    "source": {"kind": "EventsNode", "event": "$pageleave"},
                },
            ],
            primary_metrics_ordered_uuids=["m1", "m2"],
        )

        updated = service.update_experiment(
            experiment,
            {
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "uuid": "m1",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    },
                ],
            },
            allow_unknown_events=True,
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
        assert experiment.feature_flag.filters["holdout"] == {"id": holdout.id, "exclusion_percentage": 10}
        assert "holdout_groups" not in experiment.feature_flag.filters

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
    # Launch experiment
    # ------------------------------------------------------------------

    _DEFAULT_METRIC = {
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "uuid": "m1",
        "source": {"kind": "EventsNode", "event": "$pageview"},
    }

    def _create_launchable_experiment(
        self,
        name: str = "Launchable",
        feature_flag_key: str = "launchable-flag",
        **kwargs: Any,
    ) -> Experiment:
        kwargs.setdefault("metrics", [self._DEFAULT_METRIC])
        kwargs.setdefault("primary_metrics_ordered_uuids", ["m1"])
        kwargs.setdefault("allow_unknown_events", True)
        return self._service().create_experiment(name=name, feature_flag_key=feature_flag_key, **kwargs)

    def _create_ended_experiment(
        self,
        name: str = "Ended",
        feature_flag_key: str = "ended-flag",
        **kwargs: Any,
    ) -> Experiment:
        experiment = self._create_launchable_experiment(name=name, feature_flag_key=feature_flag_key, **kwargs)
        service = self._service()
        service.launch_experiment(experiment)
        service.update_experiment(experiment, {"end_date": timezone.now()})
        return experiment

    def test_launch_experiment_success(self):
        experiment = self._create_launchable_experiment(name="Launch Test", feature_flag_key="launch-new-flag")

        assert experiment.is_draft
        assert experiment.feature_flag.active is False

        launched = self._service().launch_experiment(experiment)

        assert launched.start_date is not None
        assert not launched.is_draft
        assert launched.status == Experiment.Status.RUNNING
        launched.feature_flag.refresh_from_db()
        assert launched.feature_flag.active is True

    def test_launch_experiment_sets_fingerprints(self):
        self._create_flag(key="fp-launch")
        experiment = self._create_launchable_experiment(name="Fingerprint Launch", feature_flag_key="fp-launch")

        # Draft metrics have fingerprints computed with start_date=None
        assert experiment.metrics is not None
        draft_fingerprint = experiment.metrics[0].get("fingerprint")

        launched = self._service().launch_experiment(experiment)

        # After launch, fingerprints should be recomputed with the new start_date
        assert launched.metrics is not None
        launch_fingerprint = launched.metrics[0].get("fingerprint")
        assert launch_fingerprint is not None
        assert launch_fingerprint != draft_fingerprint

    def test_launch_experiment_already_running_raises(self):
        experiment = self._create_launchable_experiment(name="Already Running", feature_flag_key="already-running-flag")
        service = self._service()
        service.launch_experiment(experiment)

        with self.assertRaises(ValidationError) as ctx:
            service.launch_experiment(experiment)

        assert "already been launched" in str(ctx.exception)

    def test_launch_experiment_already_stopped_raises(self):
        experiment = self._create_launchable_experiment(name="Already Stopped", feature_flag_key="already-stopped-flag")
        service = self._service()
        service.launch_experiment(experiment)
        service.update_experiment(experiment, {"end_date": timezone.now()})

        with self.assertRaises(ValidationError) as ctx:
            service.launch_experiment(experiment)

        assert "already been launched" in str(ctx.exception)

    def test_launch_experiment_without_metrics(self):
        experiment = self._create_launchable_experiment(
            name="No Metrics",
            feature_flag_key="no-metrics-flag",
            metrics=[],
            primary_metrics_ordered_uuids=None,
        )

        launched = self._service().launch_experiment(experiment)

        assert launched.start_date is not None
        assert launched.status == Experiment.Status.RUNNING

    def test_launch_experiment_with_only_secondary_metrics(self):
        self._create_flag(key="secondary-only")
        experiment = self._service().create_experiment(
            name="Secondary Only",
            feature_flag_key="secondary-only",
            allow_unknown_events=True,
            metrics_secondary=[self._DEFAULT_METRIC],
            secondary_metrics_ordered_uuids=["m1"],
        )

        launched = self._service().launch_experiment(experiment)

        assert launched.start_date is not None
        assert launched.status == Experiment.Status.RUNNING

    def test_launch_experiment_with_linked_active_flag(self):
        """Pre-existing flag that is already active (rolled out). Launch should succeed and flag stays active."""
        flag = self._create_flag(key="already-active")
        assert flag.active is True  # FeatureFlag default

        experiment = self._create_launchable_experiment(name="Linked Active Flag", feature_flag_key="already-active")

        launched = self._service().launch_experiment(experiment)

        assert launched.start_date is not None
        assert launched.status == Experiment.Status.RUNNING
        launched.feature_flag.refresh_from_db()
        assert launched.feature_flag.active is True

    def test_launch_experiment_with_linked_inactive_flag(self):
        """Pre-existing flag that is inactive. Launch should activate it."""
        flag = self._create_flag(key="inactive-flag")
        flag.active = False
        flag.save()

        experiment = self._create_launchable_experiment(name="Linked Inactive Flag", feature_flag_key="inactive-flag")

        launched = self._service().launch_experiment(experiment)

        assert launched.start_date is not None
        launched.feature_flag.refresh_from_db()
        assert launched.feature_flag.active is True

    def test_launch_experiment_with_linked_flag_preserves_conditions(self):
        """Pre-existing flag with custom release conditions. Launch should preserve them."""
        flag = self._create_flag(key="custom-conditions")
        flag.filters = {
            "groups": [
                {
                    "properties": [{"key": "country", "value": "US", "type": "person"}],
                    "rollout_percentage": 50,
                },
                {"properties": [], "rollout_percentage": 100},
            ],
            "multivariate": {
                "variants": [
                    {"key": "control", "rollout_percentage": 50},
                    {"key": "test", "rollout_percentage": 50},
                ]
            },
        }
        flag.save()

        experiment = self._create_launchable_experiment(name="Custom Conditions", feature_flag_key="custom-conditions")

        launched = self._service().launch_experiment(experiment)

        launched.feature_flag.refresh_from_db()
        groups = launched.feature_flag.filters["groups"]
        assert len(groups) == 2
        assert groups[0]["properties"] == [{"key": "country", "value": "US", "type": "person"}]
        assert groups[0]["rollout_percentage"] == 50

    def test_launch_experiment_flag_modified_to_invalid_raises(self):
        """Flag modified after experiment creation to remove control variant. Launch should fail."""
        flag = self._create_flag(key="will-break")
        experiment = self._create_launchable_experiment(name="Will Break", feature_flag_key="will-break")

        # Simulate someone modifying the flag to remove "control"
        flag.filters["multivariate"]["variants"] = [
            {"key": "variant_a", "rollout_percentage": 50},
            {"key": "variant_b", "rollout_percentage": 50},
        ]
        flag.save()
        experiment.feature_flag.refresh_from_db()

        with self.assertRaises(ValidationError) as ctx:
            self._service().launch_experiment(experiment)

        assert "control" in str(ctx.exception).lower()

    def test_launch_experiment_flag_reduced_to_single_variant_raises(self):
        """Flag modified to have only 1 variant. Launch should fail."""
        flag = self._create_flag(key="single-variant")
        experiment = self._create_launchable_experiment(name="Single Variant", feature_flag_key="single-variant")

        flag.filters["multivariate"]["variants"] = [
            {"key": "control", "rollout_percentage": 100},
        ]
        flag.save()
        experiment.feature_flag.refresh_from_db()

        with self.assertRaises(ValidationError) as ctx:
            self._service().launch_experiment(experiment)

        assert "at least 2 variants" in str(ctx.exception)

    # ------------------------------------------------------------------
    # Archive
    # ------------------------------------------------------------------

    def test_archive_experiment_success(self):
        experiment = self._create_ended_experiment(name="Archive Test", feature_flag_key="archive-flag")

        archived = self._service().archive_experiment(experiment)

        assert archived.archived is True
        assert archived.status == Experiment.Status.STOPPED

    def test_archive_experiment_already_archived_raises(self):
        experiment = self._create_ended_experiment(name="Already Archived", feature_flag_key="already-archived-flag")
        service = self._service()
        service.archive_experiment(experiment)

        with self.assertRaises(ValidationError) as ctx:
            service.archive_experiment(experiment)

        assert "already archived" in str(ctx.exception)

    @parameterized.expand(
        [
            ("draft", True),
            ("running", False),
        ]
    )
    def test_archive_experiment_not_ended_raises(self, _name: str, is_draft: bool):
        service = self._service()
        experiment = self._create_launchable_experiment(
            name=f"Archive {_name}", feature_flag_key=f"archive-{_name}-flag"
        )
        if not is_draft:
            service.launch_experiment(experiment)

        with self.assertRaises(ValidationError) as ctx:
            service.archive_experiment(experiment)
        assert "must be ended" in str(ctx.exception)

    # ------------------------------------------------------------------
    # End
    # ------------------------------------------------------------------

    def test_end_experiment_success(self):
        experiment = self._create_running_experiment(name="End Test", feature_flag_key="end-flag")

        assert experiment.is_running
        assert experiment.end_date is None

        ended = self._service().end_experiment(experiment)

        ended.refresh_from_db()
        assert ended.is_stopped
        assert ended.end_date is not None

    @parameterized.expand(
        [
            ("active_flag", True),
            ("paused_flag", False),
        ]
    )
    def test_end_experiment_leaves_feature_flag_unchanged(self, _name: str, flag_active: bool):
        experiment = self._create_running_experiment(name=f"End Flag {_name}", feature_flag_key=f"end-flag-{_name}")
        if not flag_active:
            self._service().pause_experiment(experiment)

        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.active is flag_active

        ended = self._service().end_experiment(experiment)

        ended.feature_flag.refresh_from_db()
        assert ended.feature_flag.active is flag_active
        assert ended.feature_flag.filters == experiment.feature_flag.filters

    def test_end_experiment_with_conclusion(self):
        experiment = self._create_running_experiment(name="End Conclusion", feature_flag_key="end-conclusion-flag")

        ended = self._service().end_experiment(
            experiment,
            conclusion="won",
            conclusion_comment="Test variant clearly won",
        )

        ended.refresh_from_db()
        assert ended.is_stopped
        assert ended.conclusion == "won"
        assert ended.conclusion_comment == "Test variant clearly won"

    def test_end_experiment_draft_raises(self):
        experiment = self._create_launchable_experiment(name="End Draft", feature_flag_key="end-draft-flag")

        assert experiment.is_draft

        with self.assertRaises(ValidationError) as ctx:
            self._service().end_experiment(experiment)

        assert "not been launched" in str(ctx.exception)

    def test_end_experiment_already_ended_raises(self):
        experiment = self._create_ended_experiment(name="End Already", feature_flag_key="end-already-flag")

        assert experiment.is_stopped

        with self.assertRaises(ValidationError) as ctx:
            self._service().end_experiment(experiment)

        assert "already ended" in str(ctx.exception)

    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_end_experiment_reports_analytics(self, mock_report_user_action):
        experiment = self._create_running_experiment(name="End Analytics", feature_flag_key="end-analytics-flag")
        mock_request = MagicMock()

        self._service().end_experiment(experiment, request=mock_request)

        assert mock_report_user_action.call_count == 2
        event_names = [call.args[1] for call in mock_report_user_action.call_args_list]
        assert "experiment completed" in event_names
        assert "experiment stopped" in event_names

    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_end_experiment_completed_event_includes_duration(self, mock_report_user_action):
        experiment = self._create_running_experiment(name="End Duration", feature_flag_key="end-duration-flag")
        mock_request = MagicMock()

        self._service().end_experiment(experiment, request=mock_request)

        completed_call = next(
            call for call in mock_report_user_action.call_args_list if call.args[1] == "experiment completed"
        )
        metadata = completed_call.args[2]
        assert "duration" in metadata
        assert isinstance(metadata["duration"], int)
        assert metadata["duration"] >= 0

    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_end_experiment_completed_event_includes_significant_when_results_exist(self, mock_report_user_action):
        experiment = self._create_running_experiment(name="End Significant", feature_flag_key="end-significant-flag")
        assert experiment.metrics is not None
        metric_uuid = experiment.metrics[0]["uuid"]

        assert experiment.start_date is not None
        ExperimentMetricResult.objects.create(
            experiment=experiment,
            metric_uuid=metric_uuid,
            query_from=experiment.start_date,
            query_to=timezone.now(),
            status=ExperimentMetricResult.Status.COMPLETED,
            result={"significant": True, "variants": []},
            completed_at=timezone.now(),
        )

        mock_request = MagicMock()
        self._service().end_experiment(experiment, request=mock_request)

        completed_call = next(
            call for call in mock_report_user_action.call_args_list if call.args[1] == "experiment completed"
        )
        metadata = completed_call.args[2]
        assert metadata["significant"] is True

    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_end_experiment_completed_event_omits_significant_when_no_results(self, mock_report_user_action):
        experiment = self._create_running_experiment(name="End No Results", feature_flag_key="end-no-results-flag")
        mock_request = MagicMock()

        self._service().end_experiment(experiment, request=mock_request)

        completed_call = next(
            call for call in mock_report_user_action.call_args_list if call.args[1] == "experiment completed"
        )
        metadata = completed_call.args[2]
        assert "significant" not in metadata

    # ------------------------------------------------------------------
    # Pause / Resume
    # ------------------------------------------------------------------

    def _create_running_experiment(
        self,
        name: str = "Running",
        feature_flag_key: str = "running-flag",
        **kwargs: Any,
    ) -> Experiment:
        experiment = self._create_launchable_experiment(name=name, feature_flag_key=feature_flag_key, **kwargs)
        self._service().launch_experiment(experiment)
        return experiment

    def test_pause_experiment_success(self):
        experiment = self._create_running_experiment(name="Pause Test", feature_flag_key="pause-flag")

        assert experiment.feature_flag.active is True

        paused = self._service().pause_experiment(experiment)

        paused.feature_flag.refresh_from_db()
        assert paused.feature_flag.active is False
        assert paused.start_date is not None
        assert paused.end_date is None

    def test_resume_experiment_success(self):
        experiment = self._create_running_experiment(name="Resume Test", feature_flag_key="resume-flag")
        service = self._service()
        service.pause_experiment(experiment)

        assert experiment.feature_flag.active is False

        resumed = service.resume_experiment(experiment)

        resumed.feature_flag.refresh_from_db()
        assert resumed.feature_flag.active is True
        assert resumed.start_date is not None
        assert resumed.end_date is None

    def test_pause_experiment_already_paused_raises(self):
        experiment = self._create_running_experiment(name="Already Paused", feature_flag_key="already-paused-flag")
        service = self._service()
        service.pause_experiment(experiment)

        with self.assertRaises(ValidationError) as ctx:
            service.pause_experiment(experiment)

        assert "already paused" in str(ctx.exception)

    def test_resume_experiment_not_paused_raises(self):
        experiment = self._create_running_experiment(name="Not Paused", feature_flag_key="not-paused-flag")

        with self.assertRaises(ValidationError) as ctx:
            self._service().resume_experiment(experiment)

        assert "not paused" in str(ctx.exception)

    @parameterized.expand(
        [
            ("draft",),
            ("ended",),
        ]
    )
    def test_pause_experiment_wrong_state_raises(self, state: str):
        service = self._service()
        if state == "draft":
            experiment = self._create_launchable_experiment(name="Pause Draft", feature_flag_key=f"pause-{state}-flag")
        else:
            experiment = self._create_ended_experiment(name="Pause Ended", feature_flag_key=f"pause-{state}-flag")

        with self.assertRaises(ValidationError):
            service.pause_experiment(experiment)

    @parameterized.expand(
        [
            ("draft",),
            ("ended",),
        ]
    )
    def test_resume_experiment_wrong_state_raises(self, state: str):
        service = self._service()
        if state == "draft":
            experiment = self._create_launchable_experiment(
                name="Resume Draft", feature_flag_key=f"resume-{state}-flag"
            )
        else:
            experiment = self._create_ended_experiment(name="Resume Ended", feature_flag_key=f"resume-{state}-flag")

        with self.assertRaises(ValidationError):
            service.resume_experiment(experiment)

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    @parameterized.expand(
        [
            ("running",),
            ("ended",),
        ]
    )
    def test_reset_experiment_success(self, state: str):
        if state == "running":
            experiment = self._create_running_experiment(name="Reset Running", feature_flag_key=f"reset-{state}-flag")
            assert experiment.is_running
        else:
            experiment = self._create_ended_experiment(name="Reset Ended", feature_flag_key=f"reset-{state}-flag")
            assert experiment.is_stopped

        reset = self._service().reset_experiment(experiment)

        reset.refresh_from_db()
        assert reset.is_draft
        assert reset.start_date is None
        assert reset.end_date is None
        assert reset.archived is False
        assert reset.conclusion is None
        assert reset.conclusion_comment is None

    def test_reset_experiment_leaves_feature_flag_unchanged(self):
        experiment = self._create_running_experiment(name="Reset Flag", feature_flag_key="reset-flag-unchanged")

        assert experiment.feature_flag.active is True

        reset = self._service().reset_experiment(experiment)

        reset.feature_flag.refresh_from_db()
        assert reset.feature_flag.active is True

    def test_reset_draft_experiment_raises(self):
        experiment = self._create_launchable_experiment(name="Reset Draft", feature_flag_key="reset-draft-flag")

        assert experiment.is_draft

        with self.assertRaises(ValidationError) as ctx:
            self._service().reset_experiment(experiment)

        assert "already in draft state" in str(ctx.exception)

    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_reset_experiment_reports_analytics(self, mock_report_user_action):
        experiment = self._create_running_experiment(name="Reset Analytics", feature_flag_key="reset-analytics-flag")
        mock_request = MagicMock()

        self._service().reset_experiment(experiment, request=mock_request)

        mock_report_user_action.assert_called_once()
        assert mock_report_user_action.call_args.args[1] == "experiment reset"

    # ------------------------------------------------------------------
    # Ship variant
    # ------------------------------------------------------------------

    def test_ship_variant_running_experiment(self):
        experiment = self._create_running_experiment(name="Ship Running", feature_flag_key="ship-running-flag")

        assert experiment.is_running
        original_groups = experiment.feature_flag.filters.get("groups", [])

        shipped = self._service().ship_variant(
            experiment, variant_key="test", conclusion="won", request=self._make_request()
        )

        shipped.refresh_from_db()
        shipped.feature_flag.refresh_from_db()

        # Verify experiment is stopped with conclusion
        assert shipped.is_stopped
        assert shipped.end_date is not None
        assert shipped.conclusion == "won"

        # Verify flag filter transformation
        variants = shipped.feature_flag.filters["multivariate"]["variants"]
        assert any(v["key"] == "test" and v["rollout_percentage"] == 100 for v in variants)
        assert any(v["key"] == "control" and v["rollout_percentage"] == 0 for v in variants)

        # Verify catch-all group prepended and original groups preserved
        groups = shipped.feature_flag.filters["groups"]
        assert groups[0]["properties"] == []
        assert groups[0]["rollout_percentage"] == 100
        assert "Added automatically" in groups[0].get("description", "")
        assert groups[1:] == original_groups

    def test_ship_variant_already_stopped_experiment(self):
        experiment = self._create_ended_experiment(name="Ship Stopped", feature_flag_key="ship-stopped-flag")

        assert experiment.is_stopped
        original_end_date = experiment.end_date

        shipped = self._service().ship_variant(
            experiment,
            variant_key="test",
            conclusion="won",
            conclusion_comment="Shipping after end",
            request=self._make_request(),
        )

        shipped.refresh_from_db()
        shipped.feature_flag.refresh_from_db()

        # Experiment stays stopped, end_date unchanged
        assert shipped.is_stopped
        assert shipped.end_date == original_end_date
        assert shipped.conclusion == "won"
        assert shipped.conclusion_comment == "Shipping after end"

        # Flag is still rewritten
        variants = shipped.feature_flag.filters["multivariate"]["variants"]
        assert any(v["key"] == "test" and v["rollout_percentage"] == 100 for v in variants)

    def test_ship_variant_preserves_existing_conclusion_when_not_provided(self):
        experiment = self._create_ended_experiment(
            name="Ship No Conclusion", feature_flag_key="ship-no-conclusion-flag"
        )
        # Set an existing conclusion on the stopped experiment
        experiment.conclusion = "won"
        experiment.conclusion_comment = "Test variant is the clear winner"
        experiment.save()

        shipped = self._service().ship_variant(
            experiment,
            variant_key="test",
            # Deliberately not providing conclusion or conclusion_comment
            request=self._make_request(),
        )

        shipped.refresh_from_db()
        assert shipped.conclusion == "won"
        assert shipped.conclusion_comment == "Test variant is the clear winner"

    def test_ship_variant_preserves_payloads_and_aggregation(self):
        experiment = self._create_running_experiment(name="Ship Payloads", feature_flag_key="ship-payloads-flag")
        # Update the flag via the serializer to match real API behavior.
        # aggregation_group_type_index must be set on each group explicitly —
        # the serializer validator only distributes the top-level value to
        # groups that don't already have the key, and these groups already
        # have it set to None from the initial creation.
        flag = experiment.feature_flag
        updated_filters = {
            **flag.filters,
            "payloads": {"test": '{"color": "blue"}'},
            "aggregation_group_type_index": 1,
            "groups": [{**g, "aggregation_group_type_index": 1} for g in flag.filters.get("groups", [])],
        }
        flag_serializer = FeatureFlagSerializer(
            flag,
            data={"filters": updated_filters},
            partial=True,
            context={
                "request": self._make_request(),
                "team_id": self.team.id,
                "project_id": self.team.project_id,
            },
        )
        flag_serializer.is_valid(raise_exception=True)
        flag_serializer.save()
        flag.refresh_from_db()

        shipped = self._service().ship_variant(experiment, variant_key="test", request=self._make_request())

        shipped.feature_flag.refresh_from_db()
        assert shipped.feature_flag.filters["payloads"] == {"test": '{"color": "blue"}'}
        assert shipped.feature_flag.filters["aggregation_group_type_index"] == 1

    def test_ship_variant_draft_raises(self):
        experiment = self._create_launchable_experiment(name="Ship Draft", feature_flag_key="ship-draft-flag")

        assert experiment.is_draft

        with self.assertRaises(ValidationError) as ctx:
            self._service().ship_variant(experiment, variant_key="test", request=self._make_request())

        assert "not been launched" in str(ctx.exception)

    def test_ship_variant_invalid_variant_key_raises(self):
        experiment = self._create_running_experiment(
            name="Ship Invalid Variant", feature_flag_key="ship-invalid-variant-flag"
        )

        with self.assertRaises(ValidationError) as ctx:
            self._service().ship_variant(experiment, variant_key="nonexistent", request=self._make_request())

        assert "not found" in str(ctx.exception)

    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_ship_variant_running_reports_analytics(self, mock_report_user_action):
        experiment = self._create_running_experiment(
            name="Ship Analytics Running", feature_flag_key="ship-analytics-running-flag"
        )

        self._service().ship_variant(experiment, variant_key="test", request=self._make_request())

        event_names = [call.args[1] for call in mock_report_user_action.call_args_list]
        # Should report variant shipped + end events (completed + stopped)
        assert "experiment variant shipped" in event_names
        assert "experiment completed" in event_names
        assert "experiment stopped" in event_names

        # Verify variant_key in shipped event metadata
        shipped_call = next(
            call for call in mock_report_user_action.call_args_list if call.args[1] == "experiment variant shipped"
        )
        assert shipped_call.args[2]["variant_key"] == "test"

    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_ship_variant_stopped_reports_only_shipped_event(self, mock_report_user_action):
        experiment = self._create_ended_experiment(
            name="Ship Analytics Stopped", feature_flag_key="ship-analytics-stopped-flag"
        )

        self._service().ship_variant(experiment, variant_key="test", request=self._make_request())

        event_names = [call.args[1] for call in mock_report_user_action.call_args_list]
        # Should only report variant shipped, NOT end events (already ended)
        assert "experiment variant shipped" in event_names
        assert "experiment completed" not in event_names
        assert "experiment stopped" not in event_names

    # ------------------------------------------------------------------
    # Transform filters for winning variant
    # ------------------------------------------------------------------

    def test_transform_filters_for_winning_variant(self):
        current_filters = {
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "payloads": {},
            "multivariate": {
                "variants": [
                    {"key": "control", "name": "Control Group", "rollout_percentage": 50},
                    {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
                ]
            },
            "aggregation_group_type_index": None,
        }

        result = ExperimentService._transform_filters_for_winning_variant(current_filters, "test")

        assert result["multivariate"]["variants"] == [
            {"key": "control", "name": "Control Group", "rollout_percentage": 0},
            {"key": "test", "name": "Test Variant", "rollout_percentage": 100},
        ]
        assert result["groups"][0] == {
            "properties": [],
            "rollout_percentage": 100,
            "description": "Added automatically when the experiment was ended to keep only one variant.",
        }
        assert result["groups"][1:] == [{"properties": [], "rollout_percentage": 100}]
        assert result["payloads"] == {}
        assert result["aggregation_group_type_index"] is None

    def test_transform_filters_multiple_variants_with_payloads(self):
        current_filters = {
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "payloads": {
                "test_1": "{key: 'test_1'}",
                "test_2": "{key: 'test_2'}",
                "test_3": "{key: 'test_3'}",
                "control": "{key: 'control'}",
            },
            "multivariate": {
                "variants": [
                    {"key": "control", "name": "This is control", "rollout_percentage": 25},
                    {"key": "test_1", "name": "This is test_1", "rollout_percentage": 25},
                    {"key": "test_2", "name": "This is test_2", "rollout_percentage": 25},
                    {"key": "test_3", "name": "This is test_3", "rollout_percentage": 25},
                ]
            },
            "aggregation_group_type_index": 1,
        }

        result = ExperimentService._transform_filters_for_winning_variant(current_filters, "control")

        assert result["multivariate"]["variants"] == [
            {"key": "control", "name": "This is control", "rollout_percentage": 100},
            {"key": "test_1", "name": "This is test_1", "rollout_percentage": 0},
            {"key": "test_2", "name": "This is test_2", "rollout_percentage": 0},
            {"key": "test_3", "name": "This is test_3", "rollout_percentage": 0},
        ]
        assert result["groups"][0] == {
            "properties": [],
            "rollout_percentage": 100,
            "description": "Added automatically when the experiment was ended to keep only one variant.",
        }
        assert result["groups"][1:] == [{"properties": [], "rollout_percentage": 100}]
        assert result["payloads"] == current_filters["payloads"]
        assert result["aggregation_group_type_index"] == 1

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
    # Eligible feature flags
    # ------------------------------------------------------------------

    def test_get_eligible_feature_flags_only_returns_control_first_multivariate_flags(self) -> None:
        eligible_flag = self._create_flag(key="eligible-flag")
        self._create_flag(
            key="wrong-order-flag",
            variants=[
                {"key": "test", "name": "Test", "rollout_percentage": 50},
                {"key": "control", "name": "Control", "rollout_percentage": 50},
            ],
        )
        self._create_flag(
            key="single-variant-flag",
            variants=[{"key": "control", "name": "Control", "rollout_percentage": 100}],
        )

        result = self._service().get_eligible_feature_flags(order="key")

        assert result["count"] == 1
        assert [flag.key for flag in result["results"]] == [eligible_flag.key]

    def test_get_eligible_feature_flags_applies_search_and_pagination(self) -> None:
        self._create_flag(key="search-alpha")
        self._create_flag(key="search-beta")
        self._create_flag(key="other-flag")

        result = self._service().get_eligible_feature_flags(
            search="search",
            order="key",
            limit=1,
            offset=1,
        )

        assert result["count"] == 2
        assert [flag.key for flag in result["results"]] == ["search-beta"]

    def test_get_eligible_feature_flags_filters_by_evaluation_contexts(self) -> None:
        flag_with_tags = self._create_flag(key="flag-with-tags")
        self._create_flag(key="flag-without-tags")
        evaluation_context = EvaluationContext.objects.create(name="app", team=self.team)
        FeatureFlagEvaluationContext.objects.create(feature_flag=flag_with_tags, evaluation_context=evaluation_context)

        service = self._service()

        flags_with_tags = service.get_eligible_feature_flags(has_evaluation_contexts="true", order="key")
        flags_without_tags = service.get_eligible_feature_flags(has_evaluation_contexts="false", order="key")

        assert [flag.key for flag in flags_with_tags["results"]] == ["flag-with-tags"]
        assert [flag.key for flag in flags_without_tags["results"]] == ["flag-without-tags"]

    # ------------------------------------------------------------------
    # Experiment list/querying
    # ------------------------------------------------------------------

    def test_filter_experiments_queryset_defaults_to_non_archived_non_deleted_for_list(self) -> None:
        service = self._service()
        service.create_experiment(name="Visible", feature_flag_key="list-visible")
        service.create_experiment(name="Archived", feature_flag_key="list-archived", archived=True)
        service.create_experiment(name="Deleted", feature_flag_key="list-deleted", deleted=True)

        queryset = service.filter_experiments_queryset(
            Experiment.objects.filter(team=self.team),
            action="list",
        )

        assert set(queryset.values_list("name", flat=True)) == {"Visible"}

    def test_filter_experiments_queryset_includes_deleted_on_restore_update(self) -> None:
        service = self._service()
        experiment = service.create_experiment(name="Restore Me", feature_flag_key="restore-me", deleted=True)

        default_queryset = service.filter_experiments_queryset(
            Experiment.objects.filter(team=self.team),
            action="update",
        )
        restore_queryset = service.filter_experiments_queryset(
            Experiment.objects.filter(team=self.team),
            action="update",
            request_data={"deleted": "false"},
        )

        assert experiment.id not in default_queryset.values_list("id", flat=True)
        assert experiment.id in restore_queryset.values_list("id", flat=True)

    @parameterized.expand(
        [
            ("draft", {"status": "draft"}, {"Draft"}),
            ("running", {"status": "running"}, {"Running"}),
            ("stopped", {"status": "stopped"}, {"Stopped"}),
            ("complete", {"status": "complete"}, {"Stopped"}),
            ("all", {"status": "all"}, {"Draft", "Running", "Stopped"}),
            ("invalid", {"status": "bogus"}, {"Draft", "Running", "Stopped"}),
        ]
    )
    def test_filter_experiments_queryset_filters_by_status(
        self, _: str, query_params: dict[str, str], expected_names: set[str]
    ) -> None:
        service = self._service()
        now = timezone.now()
        service.create_experiment(name="Draft", feature_flag_key="status-draft")
        service.create_experiment(
            name="Running",
            feature_flag_key="status-running",
            start_date=now - timedelta(days=2),
        )
        service.create_experiment(
            name="Stopped",
            feature_flag_key="status-stopped",
            start_date=now - timedelta(days=4),
            end_date=now - timedelta(days=1),
        )

        queryset = service.filter_experiments_queryset(
            Experiment.objects.filter(team=self.team),
            action="list",
            query_params=query_params,
        )

        assert set(queryset.values_list("name", flat=True)) == expected_names

    @parameterized.expand(
        [
            ("created_by_id", {"created_by_id": None}, {"Creator self", "Search match"}),
            ("archived_true", {"archived": "true"}, {"Archived search"}),
            ("archived_false", {"archived": "false"}, {"Creator self", "Creator other", "Search match"}),
            ("search", {"search": "Search"}, {"Search match"}),
        ]
    )
    def test_filter_experiments_queryset_filters_by_common_query_params(
        self, _: str, query_params: dict[str, str | None], expected_names: set[str]
    ) -> None:
        service = self._service()
        other_user = self._create_user("other-user@example.com")

        service.create_experiment(name="Creator self", feature_flag_key="created-by-self")
        ExperimentService(team=self.team, user=other_user).create_experiment(
            name="Creator other",
            feature_flag_key="created-by-other",
        )
        service.create_experiment(name="Search match", feature_flag_key="search-match")
        service.create_experiment(name="Archived search", feature_flag_key="archived-search", archived=True)

        if "created_by_id" in query_params and query_params["created_by_id"] is None:
            query_params = {**query_params, "created_by_id": str(self.user.id)}

        queryset = service.filter_experiments_queryset(
            Experiment.objects.filter(team=self.team),
            action="list",
            query_params=query_params,
        )

        assert set(queryset.values_list("name", flat=True)) == expected_names

    @parameterized.expand(
        [
            ("ascending", "duration", ["Short", "Long"]),
            ("descending", "-duration", ["Long", "Short"]),
        ]
    )
    def test_filter_experiments_queryset_orders_by_duration(
        self, _: str, order: str, expected_order: list[str]
    ) -> None:
        service = self._service()
        now = timezone.now()
        service.create_experiment(
            name="Short",
            feature_flag_key="short-duration",
            start_date=now - timedelta(days=2),
            end_date=now - timedelta(days=1),
        )
        service.create_experiment(
            name="Long",
            feature_flag_key="long-duration",
            start_date=now - timedelta(days=4),
            end_date=now - timedelta(days=1),
        )

        queryset = service.filter_experiments_queryset(
            Experiment.objects.filter(team=self.team),
            action="list",
            query_params={"order": order},
        )

        assert list(queryset.values_list("name", flat=True)[:2]) == expected_order

    @parameterized.expand(
        [
            ("ascending", "status", ["Draft", "Running", "Stopped"]),
            ("descending", "-status", ["Stopped", "Running", "Draft"]),
        ]
    )
    def test_filter_experiments_queryset_orders_by_status(self, _: str, order: str, expected_order: list[str]) -> None:
        service = self._service()
        now = timezone.now()
        service.create_experiment(name="Draft", feature_flag_key="order-status-draft")
        service.create_experiment(
            name="Running",
            feature_flag_key="order-status-running",
            start_date=now - timedelta(days=2),
        )
        service.create_experiment(
            name="Stopped",
            feature_flag_key="order-status-stopped",
            start_date=now - timedelta(days=4),
            end_date=now - timedelta(days=1),
        )

        queryset = service.filter_experiments_queryset(
            Experiment.objects.filter(team=self.team),
            action="list",
            query_params={"order": order},
        )

        assert list(queryset.values_list("name", flat=True)[:3]) == expected_order

    def test_filter_experiments_queryset_validates_feature_flag_id(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            self._service().filter_experiments_queryset(
                Experiment.objects.filter(team=self.team),
                action="list",
                query_params={"feature_flag_id": "not-an-int"},
            )

        assert "feature_flag_id must be an integer" in str(ctx.exception)

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

    # ------------------------------------------------------------------
    # Legacy metrics update restrictions
    # ------------------------------------------------------------------

    @parameterized.expand(
        [
            ("name", {"name": "Updated Name"}),
            ("description", {"description": "New hypothesis"}),
            ("end_date", {"end_date": timezone.now() + timedelta(days=7)}),
        ]
    )
    def test_update_experiment_with_legacy_metrics_allows_specific_fields(self, field_name: str, update_data: dict):
        """Test that experiments with legacy metrics can update name, description, and end_date."""
        service = self._service()
        flag = self._create_flag(key=f"legacy-flag-{field_name}")

        # Create experiment with legacy inline metrics directly in database
        experiment = Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=flag,
            name="Legacy Experiment",
            metrics=[{"kind": "ExperimentTrendsQuery", "query": {}}],
            start_date=timezone.now(),
        )

        # Should allow update
        updated = service.update_experiment(experiment, update_data)
        if field_name == "name":
            assert updated.name == "Updated Name"
        elif field_name == "description":
            assert updated.description == "New hypothesis"
        elif field_name == "end_date":
            assert updated.end_date is not None

    @parameterized.expand(
        [
            ("metrics", {"metrics": []}, "metrics"),
            ("metrics_secondary", {"metrics_secondary": []}, "metrics_secondary"),
            ("parameters", {"parameters": {"foo": "bar"}}, "parameters"),
            ("filters", {"filters": {"foo": "bar"}}, "filters"),
            ("exposure_criteria", {"exposure_criteria": {"foo": "bar"}}, "exposure_criteria"),
            ("stats_config", {"stats_config": {"foo": "bar"}}, "stats_config"),
            ("scheduling_config", {"scheduling_config": {"foo": "bar"}}, "scheduling_config"),
            ("start_date", {"start_date": timezone.now()}, "start_date"),
            ("archived", {"archived": True}, "archived"),
            ("conclusion", {"conclusion": "won"}, "conclusion"),
        ]
    )
    def test_update_experiment_with_legacy_metrics_blocks_disallowed_fields(
        self, field_name: str, update_data: dict, expected_field_in_error: str
    ):
        """Test that experiments with legacy metrics cannot update disallowed fields."""
        service = self._service()
        flag = self._create_flag(key=f"legacy-block-{field_name}")

        # Create experiment with legacy inline metrics
        experiment = Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=flag,
            name="Legacy Experiment",
            metrics=[{"kind": "ExperimentTrendsQuery", "query": {}}],
            start_date=timezone.now(),
        )

        # Should block update
        with self.assertRaises(ValidationError) as cm:
            service.update_experiment(experiment, update_data)
        self.assertIn("legacy metric formats", str(cm.exception))
        self.assertIn(f"Cannot update: {expected_field_in_error}", str(cm.exception))

    @parameterized.expand(
        [
            ("inline_trends", {"kind": "ExperimentTrendsQuery", "query": {}}, None),
            ("inline_funnels", {"kind": "ExperimentFunnelsQuery", "funnels_query": {}}, None),
            (
                "saved_trends",
                None,
                {"kind": "ExperimentTrendsQuery", "query": {}},
            ),
            (
                "saved_funnels",
                None,
                {"kind": "ExperimentFunnelsQuery", "funnels_query": {}},
            ),
        ]
    )
    def test_update_experiment_detects_various_legacy_metric_types(
        self, test_name: str, inline_metric: dict | None, saved_metric_query: dict | None
    ):
        """Test that legacy detection works for both inline and saved metrics, Trends and Funnels."""
        from products.experiments.backend.models.experiment import ExperimentToSavedMetric

        service = self._service()
        flag = self._create_flag(key=f"legacy-detect-{test_name}")

        if inline_metric:
            # Create with inline legacy metric
            experiment = Experiment.objects.create(
                team=self.team,
                created_by=self.user,
                feature_flag=flag,
                name="Legacy Experiment",
                metrics=[inline_metric],
                start_date=timezone.now(),
            )
        else:
            # Create with saved legacy metric
            saved_metric = ExperimentSavedMetric.objects.create(
                team=self.team,
                created_by=self.user,
                name="Legacy Saved Metric",
                query=saved_metric_query,
            )

            experiment = Experiment.objects.create(
                team=self.team,
                created_by=self.user,
                feature_flag=flag,
                name="Legacy Saved Experiment",
                start_date=timezone.now(),
            )

            ExperimentToSavedMetric.objects.create(
                experiment=experiment,
                saved_metric=saved_metric,
                metadata={"type": "primary"},
            )

        # All should be detected as legacy and block disallowed updates
        with self.assertRaises(ValidationError) as cm:
            service.update_experiment(experiment, {"metrics": []})
        self.assertIn("legacy metric formats", str(cm.exception))

    def test_update_experiment_without_legacy_metrics_allows_all_updates(self):
        """Test that experiments without legacy metrics can be updated normally."""
        service = self._service()
        self._create_flag(key="normal-flag")

        # Create experiment with new ExperimentMetric format
        experiment = service.create_experiment(
            name="Normal Experiment",
            feature_flag_key="normal-flag",
            allow_unknown_events=True,
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "test_event"},
                }
            ],
            start_date=timezone.now(),
        )

        # Should allow updating metrics
        new_metrics = [
            {
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "EventsNode", "event": "another_event"},
            }
        ]
        updated = service.update_experiment(experiment, {"metrics": new_metrics}, allow_unknown_events=True)
        assert updated.metrics
        assert updated.metrics[0]["source"]["event"] == "another_event"

        # Should allow updating parameters (when draft)
        experiment.start_date = None
        experiment.save()
        updated = service.update_experiment(experiment, {"parameters": {"minimum_detectable_effect": 0.05}})
        assert updated.parameters == {"minimum_detectable_effect": 0.05}

    # ------------------------------------------------------------------
    # Validation hardening
    # ------------------------------------------------------------------

    def test_variant_missing_key_raises_validation_error(self):
        """Variant without 'key' should return 400, not 500 KeyError."""
        service = self._service()
        with self.assertRaises(ValidationError):
            service.create_experiment(
                name="Bad Variants",
                feature_flag_key="bad-variant-flag",
                parameters={
                    "feature_flag_variants": [
                        {"name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            )

    def test_variant_not_a_dict_raises_validation_error(self):
        """Variant that is not a dict should return 400."""
        service = self._service()
        with self.assertRaises(ValidationError):
            service.create_experiment(
                name="Bad Variants",
                feature_flag_key="bad-variant-flag-2",
                parameters={"feature_flag_variants": ["control", "test"]},
            )

    def test_duplicate_metric_uuids_raises_validation_error(self):
        """Metrics with duplicate UUIDs should be rejected."""
        service = self._service()
        with self.assertRaises(ValidationError):
            service.create_experiment(
                name="Dup UUIDs",
                feature_flag_key="dup-uuid-flag",
                allow_unknown_events=True,
                metrics=[
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "uuid": "11bfb66a-51f5-48d0-a87e-bde2b4c958a6",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    },
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "uuid": "11bfb66a-51f5-48d0-a87e-bde2b4c958a6",
                        "source": {"kind": "EventsNode", "event": "other_event"},
                    },
                ],
            )

    def test_duplicate_metric_uuids_across_primary_and_secondary_raises(self):
        """Duplicate UUIDs across primary and secondary metrics should also be rejected."""
        service = self._service()
        with self.assertRaises(ValidationError):
            service.create_experiment(
                name="Dup UUIDs Cross",
                feature_flag_key="dup-uuid-cross-flag",
                allow_unknown_events=True,
                metrics=[
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "uuid": "11bfb66a-51f5-48d0-a87e-bde2b4c958a6",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    },
                ],
                metrics_secondary=[
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "uuid": "11bfb66a-51f5-48d0-a87e-bde2b4c958a6",
                        "source": {"kind": "EventsNode", "event": "other_event"},
                    },
                ],
            )

    def test_metrics_without_uuids_get_auto_assigned(self):
        """Metrics with no UUID should get unique auto-generated UUIDs on create."""
        service = self._service()
        experiment = service.create_experiment(
            name="Auto UUID",
            feature_flag_key="auto-uuid-flag",
            allow_unknown_events=True,
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "other_event"},
                },
            ],
        )
        assert experiment.metrics is not None
        assert len(experiment.metrics) == 2
        uuid_0 = experiment.metrics[0].get("uuid")
        uuid_1 = experiment.metrics[1].get("uuid")
        assert uuid_0 is not None
        assert uuid_1 is not None
        UUID(uuid_0)  # raises ValueError if not a valid UUID
        UUID(uuid_1)
        assert uuid_0 != uuid_1

    def test_metrics_with_empty_string_uuid_get_auto_assigned(self):
        """Metrics with empty string UUID should get auto-generated UUIDs on create."""
        service = self._service()
        experiment = service.create_experiment(
            name="Empty UUID",
            feature_flag_key="empty-uuid-flag",
            allow_unknown_events=True,
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": "",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            ],
        )
        assert experiment.metrics is not None
        assert len(experiment.metrics) == 1
        uuid = experiment.metrics[0].get("uuid")
        assert uuid is not None
        assert uuid != ""
        UUID(uuid)  # raises ValueError if not a valid UUID

    def test_duplicate_empty_string_uuids_do_not_clash(self):
        """Two metrics with empty string UUIDs should both get unique auto-generated UUIDs."""
        service = self._service()
        experiment = service.create_experiment(
            name="Empty UUID Dup",
            feature_flag_key="empty-uuid-dup-flag",
            allow_unknown_events=True,
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": "",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": "",
                    "source": {"kind": "EventsNode", "event": "other_event"},
                },
            ],
        )
        assert experiment.metrics is not None
        assert len(experiment.metrics) == 2
        uuid_0 = experiment.metrics[0].get("uuid")
        uuid_1 = experiment.metrics[1].get("uuid")
        assert uuid_0 is not None
        assert uuid_1 is not None
        UUID(uuid_0)  # raises ValueError if not a valid UUID
        UUID(uuid_1)
        assert uuid_0 != uuid_1

    def _base_queryset(self):
        return Experiment.objects.filter(team=self.team)

    def test_order_by_invalid_field_raises_validation_error(self):
        """Ordering by a non-allowlisted field should be rejected."""
        service = self._service()
        with self.assertRaises(ValidationError):
            service.filter_experiments_queryset(
                self._base_queryset(), action="list", query_params={"order": "feature_flag__key"}
            )

    @parameterized.expand(
        [
            ("created_at",),
            ("-created_at",),
            ("name",),
            ("-name",),
            ("start_date",),
            ("-start_date",),
            ("end_date",),
            ("-end_date",),
            ("updated_at",),
            ("-updated_at",),
            ("duration",),
            ("-duration",),
            ("status",),
            ("-status",),
        ]
    )
    def test_order_by_valid_fields_works(self, order: str):
        service = self._service()
        qs = service.filter_experiments_queryset(self._base_queryset(), action="list", query_params={"order": order})
        assert qs is not None

    def test_eligible_flags_order_by_invalid_field_raises(self):
        """Ordering eligible flags by a non-allowlisted field should be rejected."""
        service = self._service()
        with self.assertRaises(ValidationError):
            service.get_eligible_feature_flags(order="team__organization__name")

    def test_launch_with_deleted_flag_raises(self):
        """Launching an experiment whose flag is soft-deleted should fail."""
        experiment = self._create_launchable_experiment(
            name="Deleted Flag Launch",
            feature_flag_key="deleted-flag-launch",
        )
        experiment.feature_flag.deleted = True
        experiment.feature_flag.save()

        service = self._service()
        with self.assertRaises(ValidationError) as ctx:
            service.launch_experiment(experiment)
        assert "deleted" in str(ctx.exception.detail).lower()

    @parameterized.expand(
        [
            ("empty_string", {"method": ""}),
            ("garbage", {"method": "garbage"}),
            ("numeric", {"method": 42}),
        ]
    )
    def test_invalid_stats_config_method_raises(self, _name: str, stats_config: dict):
        """Invalid stats_config method values should be rejected."""
        service = self._service()
        with self.assertRaises(ValidationError):
            service.create_experiment(
                name="Bad Stats",
                feature_flag_key=f"bad-stats-flag-{_name}",
                stats_config=stats_config,
            )

    @parameterized.expand(
        [
            ("bayesian",),
            ("frequentist",),
        ]
    )
    def test_valid_stats_config_methods_work(self, method: str):
        service = self._service()
        experiment = service.create_experiment(
            name=f"Stats {method}",
            feature_flag_key=f"stats-{method}-flag",
            stats_config={"method": method},
        )
        assert experiment.stats_config is not None
        assert experiment.stats_config["method"] == method

    # ------------------------------------------------------------------
    # Action ID validation (hard error)
    # ------------------------------------------------------------------

    def test_metric_with_nonexistent_action_id_raises(self):
        service = self._service()
        with self.assertRaises(ValidationError) as ctx:
            service.create_experiment(
                name="Bad Action",
                feature_flag_key="bad-action-flag",
                metrics=[
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "ActionsNode", "id": 999999},
                    },
                ],
            )
        assert "999999" in str(ctx.exception.detail)

    def test_metric_with_action_belonging_to_other_team_raises(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        action = Action.objects.create(team=other_team, name="other team action")
        service = self._service()
        with self.assertRaises(ValidationError):
            service.create_experiment(
                name="Wrong Team Action",
                feature_flag_key="wrong-team-action-flag",
                metrics=[
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "ActionsNode", "id": action.id},
                    },
                ],
            )

    def test_metric_with_deleted_action_raises(self):
        action = Action.objects.create(team=self.team, name="deleted action", deleted=True)
        service = self._service()
        with self.assertRaises(ValidationError):
            service.create_experiment(
                name="Deleted Action",
                feature_flag_key="deleted-action-flag",
                metrics=[
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "ActionsNode", "id": action.id},
                    },
                ],
            )

    def test_metric_with_valid_action_id_passes(self):
        action = Action.objects.create(team=self.team, name="valid action")
        service = self._service()
        experiment = service.create_experiment(
            name="Valid Action",
            feature_flag_key="valid-action-flag",
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "ActionsNode", "id": action.id},
                },
            ],
        )
        assert experiment.metrics is not None and len(experiment.metrics) == 1

    def test_funnel_metric_with_nonexistent_action_in_series_raises(self):
        action = Action.objects.create(team=self.team, name="real action")
        service = self._service()
        with self.assertRaises(ValidationError):
            service.create_experiment(
                name="Bad Funnel Action",
                feature_flag_key="bad-funnel-action-flag",
                metrics=[
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [
                            {"kind": "ActionsNode", "id": action.id},
                            {"kind": "ActionsNode", "id": 999999},
                        ],
                    },
                ],
            )

    def test_ratio_metric_with_nonexistent_action_raises(self):
        service = self._service()
        with self.assertRaises(ValidationError):
            service.create_experiment(
                name="Bad Ratio Action",
                feature_flag_key="bad-ratio-action-flag",
                metrics=[
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "ratio",
                        "numerator": {"kind": "EventsNode", "event": "$pageview"},
                        "denominator": {"kind": "ActionsNode", "id": 999999},
                    },
                ],
            )

    def test_retention_metric_with_nonexistent_action_raises(self):
        service = self._service()
        with self.assertRaises(ValidationError):
            service.create_experiment(
                name="Bad Retention Action",
                feature_flag_key="bad-retention-action-flag",
                metrics=[
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "retention",
                        "start_event": {"kind": "EventsNode", "event": "$pageview"},
                        "completion_event": {"kind": "ActionsNode", "id": 999999},
                        "retention_window_start": 0,
                        "retention_window_end": 7,
                        "retention_window_unit": "day",
                        "start_handling": "strict",
                    },
                ],
            )

    def test_action_validation_in_secondary_metrics(self):
        service = self._service()
        with self.assertRaises(ValidationError):
            service.create_experiment(
                name="Bad Secondary Action",
                feature_flag_key="bad-secondary-action-flag",
                metrics_secondary=[
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "ActionsNode", "id": 999999},
                    },
                ],
            )

    # ------------------------------------------------------------------
    # Event name validation (hard error by default)
    # ------------------------------------------------------------------

    def test_metric_with_unknown_event_raises(self):
        service = self._service()
        with self.assertRaises(ValidationError) as ctx:
            service.create_experiment(
                name="Unknown Event",
                feature_flag_key="unknown-event-flag",
                metrics=[
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$unknown_event"},
                    },
                ],
            )
        assert "$unknown_event" in str(ctx.exception.detail)

    def test_metric_with_known_event_passes(self):
        EventDefinition.objects.create(team=self.team, name="$pageview")
        service = self._service()
        experiment = service.create_experiment(
            name="Known Event",
            feature_flag_key="known-event-flag",
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            ],
        )
        assert experiment.metrics is not None and len(experiment.metrics) == 1

    def test_unknown_event_in_secondary_metrics_raises(self):
        EventDefinition.objects.create(team=self.team, name="$pageview")
        service = self._service()
        with self.assertRaises(ValidationError) as ctx:
            service.create_experiment(
                name="Bad Secondary Event",
                feature_flag_key="bad-secondary-event-flag",
                metrics=[
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    },
                ],
                metrics_secondary=[
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "totally_fake"},
                    },
                ],
            )
        assert "totally_fake" in str(ctx.exception.detail)

    def test_funnel_series_with_unknown_event_raises(self):
        EventDefinition.objects.create(team=self.team, name="step_one")
        service = self._service()
        with self.assertRaises(ValidationError) as ctx:
            # step_one exists (created above), step_two_typo does not
            service.create_experiment(
                name="Funnel Unknown Event",
                feature_flag_key="funnel-unknown-event-flag",
                metrics=[
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [
                            {"kind": "EventsNode", "event": "step_one"},
                            {"kind": "EventsNode", "event": "step_two_typo"},
                        ],
                    },
                ],
            )
        assert "step_two_typo" in str(ctx.exception.detail)

    def test_null_event_name_passes_validation(self):
        service = self._service()
        experiment = service.create_experiment(
            name="Null Event",
            feature_flag_key="null-event-flag",
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": None},
                },
            ],
        )
        assert experiment.metrics is not None and len(experiment.metrics) == 1

    def test_no_metrics_passes_validation(self):
        service = self._service()
        experiment = service.create_experiment(
            name="No Metrics",
            feature_flag_key="no-metrics-flag",
        )
        assert experiment.metrics == []

    def test_action_nodes_not_checked_for_event_existence(self):
        action = Action.objects.create(team=self.team, name="valid action for event test")
        service = self._service()
        experiment = service.create_experiment(
            name="Action No Event Check",
            feature_flag_key="action-no-event-check-flag",
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "ActionsNode", "id": action.id},
                },
            ],
        )
        assert experiment.metrics is not None and len(experiment.metrics) == 1

    # ------------------------------------------------------------------
    # allow_unknown_events opt-in
    # ------------------------------------------------------------------

    def test_allow_unknown_events_bypasses_event_validation(self):
        service = self._service()
        experiment = service.create_experiment(
            name="Allow Unknown",
            feature_flag_key="allow-unknown-flag",
            allow_unknown_events=True,
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "not_yet_deployed"},
                },
            ],
        )
        assert experiment.metrics is not None and len(experiment.metrics) == 1

    def test_allow_unknown_events_still_validates_actions(self):
        service = self._service()
        with self.assertRaises(ValidationError):
            service.create_experiment(
                name="Allow Unknown But Bad Action",
                feature_flag_key="allow-unknown-bad-action-flag",
                allow_unknown_events=True,
                metrics=[
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "ActionsNode", "id": 999999},
                    },
                ],
            )

    def test_explicit_allow_unknown_events_false_raises(self):
        service = self._service()
        with self.assertRaises(ValidationError) as ctx:
            service.create_experiment(
                name="Explicit False",
                feature_flag_key="explicit-false-flag",
                allow_unknown_events=False,
                metrics=[
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "nonexistent_event"},
                    },
                ],
            )
        assert "nonexistent_event" in str(ctx.exception.detail)

    # ------------------------------------------------------------------
    # Event/action validation on update_experiment
    # ------------------------------------------------------------------

    def test_update_experiment_with_unknown_event_raises(self):
        EventDefinition.objects.create(team=self.team, name="$pageview")
        service = self._service()
        experiment = service.create_experiment(
            name="Update Event Error",
            feature_flag_key="update-event-error-flag",
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            ],
        )

        with self.assertRaises(ValidationError):
            service.update_experiment(
                experiment,
                {
                    "metrics": [
                        {
                            "kind": "ExperimentMetric",
                            "metric_type": "mean",
                            "source": {"kind": "EventsNode", "event": "nonexistent_event"},
                        },
                    ],
                },
            )

    def test_update_experiment_with_nonexistent_action_raises(self):
        service = self._service()
        experiment = service.create_experiment(
            name="Update Action Error",
            feature_flag_key="update-action-error-flag",
        )
        with self.assertRaises(ValidationError):
            service.update_experiment(
                experiment,
                {
                    "metrics": [
                        {
                            "kind": "ExperimentMetric",
                            "metric_type": "mean",
                            "source": {"kind": "ActionsNode", "id": 999999},
                        },
                    ],
                },
            )
