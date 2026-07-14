import json
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, PropertyMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

import pydantic
from parameterized import parameterized
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIRequestFactory

from posthog.schema import EventsNode, ExperimentMetric

from posthog.constants import AvailableFeature
from posthog.event_usage import EventSource
from posthog.exceptions import (
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.models import OrganizationMembership, Team, User
from posthog.models.team.extensions import get_or_create_team_extension

from products.actions.backend.models.action import Action
from products.approvals.backend.models import ApprovalPolicy, ChangeRequest
from products.cohorts.backend.models.cohort import Cohort
from products.event_definitions.backend.models.event_definition import EventDefinition
from products.experiments.backend.experiment_service import (
    ExperimentService,
    _deprecated_fields_in_request,
    _deprecated_parameters_keys_in_request,
)
from products.experiments.backend.models.experiment import (
    EXPOSURE_FROZEN_COHORT_KEY,
    EXPOSURE_FROZEN_GROUP_KEY,
    EXPOSURE_FROZEN_GROUP_MARKER,
    Experiment,
    ExperimentHoldout,
    ExperimentMetricResult,
    ExperimentSavedMetric,
    ExperimentTimeseriesRecalculation,
)
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.feature_flags.backend.api.feature_flag import FeatureFlagSerializer
from products.feature_flags.backend.models.evaluation_context import EvaluationContext, FeatureFlagEvaluationContext
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

from ee.models.rbac.access_control import AccessControl


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
        assert experiment.archived is False
        assert experiment.deleted is False
        assert experiment.conclusion is None
        assert experiment.conclusion_comment is None
        assert experiment.primary_metrics_ordered_uuids is None
        assert experiment.secondary_metrics_ordered_uuids is None
        assert experiment.stats_config is not None
        assert experiment.stats_config["method"] == "bayesian"
        assert experiment.exposure_criteria == {"filterTestAccounts": True}

    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_create_experiment_defers_analytics_until_after_commit(self, mock_report_user_action):
        # The capture must be deferred to on_commit, not run inside the transaction.
        service = self._service()

        registered_callbacks: list[Any] = []
        with patch("django.db.transaction.on_commit", side_effect=registered_callbacks.append):
            service.create_experiment(
                name="Deferred Analytics",
                feature_flag_key="deferred-flag",
                event_source=EventSource.API,
            )

        # Nothing captured yet — it's deferred, not run inside the transaction.
        mock_report_user_action.assert_not_called()
        assert registered_callbacks, "expected create_experiment to register an on_commit callback"

        for callback in registered_callbacks:
            callback()

        mock_report_user_action.assert_called_once()
        assert mock_report_user_action.call_args.args[1] == "experiment created"

    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_create_experiment_survives_post_commit_analytics_failure(self, mock_report_user_action):
        # A post-commit capture failure must not roll back or fail the create — experiment still exists.
        mock_report_user_action.side_effect = RuntimeError("analytics down")
        service = self._service()

        with patch("django.db.transaction.on_commit", side_effect=lambda func: func()):
            experiment = service.create_experiment(
                name="Resilient Analytics",
                feature_flag_key="resilient-flag",
                event_source=EventSource.API,
            )

        mock_report_user_action.assert_called_once()
        assert Experiment.objects.filter(pk=experiment.pk).exists()

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
    # Only count matured users defaults
    # ------------------------------------------------------------------

    def test_only_count_matured_users_defaults_from_team(self):
        config = get_or_create_team_extension(self.team, TeamExperimentsConfig)
        config.default_only_count_matured_users = True
        config.save()

        self._create_flag(key="matured-default")
        service = self._service()

        experiment = service.create_experiment(name="Matured Default", feature_flag_key="matured-default")

        assert experiment.only_count_matured_users is True

    def test_only_count_matured_users_explicit_override(self):
        config = get_or_create_team_extension(self.team, TeamExperimentsConfig)
        config.default_only_count_matured_users = True
        config.save()

        self._create_flag(key="matured-override")
        service = self._service()

        experiment = service.create_experiment(
            name="Matured Override",
            feature_flag_key="matured-override",
            only_count_matured_users=False,
        )

        assert experiment.only_count_matured_users is False

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

    @parameterized.expand(
        [
            (
                "not_a_dict",
                "not-a-dict",
                "exposure_criteria must be an object, got str",
            ),
            (
                "falsy_empty_list",
                [],
                "exposure_criteria must be an object, got list",
            ),
            (
                "falsy_empty_string",
                "",
                "exposure_criteria must be an object, got str",
            ),
            (
                "falsy_false",
                False,
                "exposure_criteria must be an object, got bool",
            ),
            (
                "filter_test_accounts_string",
                {"filterTestAccounts": "true"},
                "exposure_criteria.filterTestAccounts must be a boolean, got str: 'true'",
            ),
            (
                "filter_test_accounts_int",
                {"filterTestAccounts": 1},
                "exposure_criteria.filterTestAccounts must be a boolean, got int: 1",
            ),
            (
                "exposure_config_not_a_dict",
                {"exposure_config": "ActionsNode"},
                "exposure_criteria.exposure_config must be an object, got str",
            ),
            (
                "exposure_config_unknown_kind",
                {"exposure_config": {"kind": "EventsNode", "event": "$pageview"}},
                "exposure_criteria.exposure_config.kind must be one of "
                "['ExperimentEventExposureConfig', 'ActionsNode'], got 'EventsNode'",
            ),
            (
                "exposure_config_event_kind_missing_event",
                {"exposure_config": {"kind": "ExperimentEventExposureConfig", "properties": []}},
                "Invalid exposure_criteria.exposure_config (kind='ExperimentEventExposureConfig')",
            ),
            (
                "exposure_config_actions_kind_missing_id",
                {"exposure_config": {"kind": "ActionsNode"}},
                "Invalid exposure_criteria.exposure_config (kind='ActionsNode')",
            ),
        ]
    )
    def test_validate_experiment_exposure_criteria_rejects_invalid_payloads(
        self, _: str, exposure_criteria: object, expected_error_fragment: str
    ) -> None:
        with self.assertRaises(ValidationError) as ctx:
            ExperimentService.validate_experiment_exposure_criteria(exposure_criteria)

        assert expected_error_fragment in str(ctx.exception), (
            f"Expected fragment {expected_error_fragment!r} in error: {ctx.exception}"
        )

    @parameterized.expand(
        [
            ("none", None),
            ("empty_dict", {}),
            (
                "event_payload",
                {
                    "filterTestAccounts": True,
                    "exposure_config": {
                        "kind": "ExperimentEventExposureConfig",
                        "event": "$feature_flag_called",
                        "properties": [],
                    },
                },
            ),
            (
                "action_payload",
                {
                    "filterTestAccounts": False,
                    "exposure_config": {"kind": "ActionsNode", "id": 1},
                },
            ),
            (
                "event_payload_without_explicit_kind",
                {"exposure_config": {"event": "$pageview", "properties": []}},
            ),
        ]
    )
    def test_validate_experiment_exposure_criteria_accepts_valid_payloads(
        self, _: str, exposure_criteria: object
    ) -> None:
        ExperimentService.validate_experiment_exposure_criteria(exposure_criteria)

    def test_validate_experiment_exposure_criteria_hint_is_actionable(self) -> None:
        """The error hint should name both supported kinds so the LLM can self-correct."""
        with self.assertRaises(ValidationError) as ctx:
            ExperimentService.validate_experiment_exposure_criteria({"exposure_config": {"kind": "FunnelsQuery"}})
        message = str(ctx.exception)
        assert "ExperimentEventExposureConfig" in message
        assert "ActionsNode" in message

    def test_validate_experiment_exposure_criteria_truncates_large_user_values(self) -> None:
        """A large user-supplied value must not bloat the error message reflected back."""
        huge_kind = "x" * 10_000
        with self.assertRaises(ValidationError) as ctx:
            ExperimentService.validate_experiment_exposure_criteria({"exposure_config": {"kind": huge_kind}})
        message = str(ctx.exception)
        assert "...(truncated)" in message
        assert len(message) < 1_000, f"Error message length was {len(message)}, expected to be bounded"

    # ------------------------------------------------------------------
    # validate_experiment_metrics — preserves existing rejection contract
    # ------------------------------------------------------------------

    def test_validate_experiment_metrics_accepts_none(self) -> None:
        ExperimentService.validate_experiment_metrics(None)

    def test_validate_experiment_metrics_accepts_empty_list(self) -> None:
        ExperimentService.validate_experiment_metrics([])

    @parameterized.expand(
        [
            (
                "valid_mean_with_event",
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            ),
            (
                "valid_mean_with_action",
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "ActionsNode", "id": 1},
                },
            ),
            (
                "valid_funnel_with_one_step",
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "funnel",
                    "series": [{"kind": "EventsNode", "event": "$pageview"}],
                },
            ),
            (
                "valid_ratio",
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "ratio",
                    "numerator": {"kind": "EventsNode", "event": "purchase"},
                    "denominator": {"kind": "EventsNode", "event": "$pageview"},
                },
            ),
            (
                "valid_retention",
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "retention",
                    "start_event": {"kind": "EventsNode", "event": "$pageview"},
                    "completion_event": {"kind": "EventsNode", "event": "purchase"},
                    "retention_window_start": 0,
                    "retention_window_end": 7,
                    "retention_window_unit": "day",
                    "start_handling": "first_seen",
                },
            ),
        ]
    )
    def test_validate_experiment_metrics_accepts_valid_payloads(self, _: str, metric: dict) -> None:
        ExperimentService.validate_experiment_metrics([metric])

    @parameterized.expand(
        [
            ("not_a_list", "not-a-list", "Metrics must be a list"),
            ("metric_not_a_dict", ["not-a-dict"], "Invalid metric at index 0: must be a dict"),
            (
                "legacy_kind",
                [{"kind": "ExperimentTrendsQuery"}],
                "legacy metric kind 'ExperimentTrendsQuery' is no longer supported",
            ),
            (
                "wrong_kind",
                [{"kind": "FunnelsQuery"}],
                "metric kind must be 'ExperimentMetric'",
            ),
            (
                "funnel_with_no_series",
                [{"kind": "ExperimentMetric", "metric_type": "funnel", "series": []}],
                "funnel metrics require at least one step",
            ),
        ]
    )
    def test_validate_experiment_metrics_rejects_invalid_payloads(
        self, _: str, metrics: object, expected_fragment: str
    ) -> None:
        with self.assertRaises(ValidationError) as ctx:
            ExperimentService.validate_experiment_metrics(metrics)  # type: ignore[arg-type]
        assert expected_fragment in str(ctx.exception), (
            f"Expected fragment {expected_fragment!r} in error: {ctx.exception}"
        )

    # ------------------------------------------------------------------
    # validate_experiment_metrics — threshold / math-type compatibility
    # ------------------------------------------------------------------

    @parameterized.expand(
        [
            ("threshold_on_sum", "sum"),
            ("threshold_on_total_count", "total"),
        ]
    )
    def test_validate_experiment_metrics_accepts_threshold_on_summed_math(self, _: str, math: str) -> None:
        ExperimentService.validate_experiment_metrics(
            [
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview", "math": math, "math_property": "amount"},
                    "threshold": 100,
                }
            ]
        )

    @parameterized.expand(
        [
            ("threshold_on_unique_session", "unique_session"),
            ("threshold_on_dau", "dau"),
            ("threshold_on_hogql", "hogql"),
        ]
    )
    def test_validate_experiment_metrics_rejects_threshold_on_unsupported_math(self, _: str, math: str) -> None:
        with self.assertRaises(ValidationError) as ctx:
            ExperimentService.validate_experiment_metrics(
                [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageview", "math": math},
                        "threshold": 100,
                    }
                ]
            )
        assert "threshold" in str(ctx.exception), f"Expected 'threshold' in error: {ctx.exception}"

    @parameterized.expand(
        [
            ("zero", 0),
            ("negative", -5),
        ]
    )
    def test_validate_experiment_metrics_rejects_non_positive_threshold(self, _: str, threshold: int) -> None:
        # A non-positive threshold is always satisfied, yielding a meaningless 100% proportion.
        with self.assertRaises(ValidationError) as ctx:
            ExperimentService.validate_experiment_metrics(
                [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {
                            "kind": "EventsNode",
                            "event": "$pageview",
                            "math": "sum",
                            "math_property": "amount",
                        },
                        "threshold": threshold,
                    }
                ]
            )
        assert "threshold" in str(ctx.exception), f"Expected 'threshold' in error: {ctx.exception}"

    @parameterized.expand(
        [
            ("lower_bound", {"lower_bound_percentile": 0.01}),
            ("upper_bound", {"upper_bound_percentile": 0.99}),
        ]
    )
    def test_validate_experiment_metrics_rejects_threshold_with_winsorization(self, _: str, bounds: dict) -> None:
        # Winsorization caps continuous outliers, which is meaningless once the metric
        # collapses to a binary threshold outcome — reject the combination.
        with self.assertRaises(ValidationError) as ctx:
            ExperimentService.validate_experiment_metrics(
                [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {
                            "kind": "EventsNode",
                            "event": "$pageview",
                            "math": "sum",
                            "math_property": "amount",
                        },
                        "threshold": 100,
                        **bounds,
                    }
                ]
            )
        assert "threshold" in str(ctx.exception), f"Expected 'threshold' in error: {ctx.exception}"

    # ------------------------------------------------------------------
    # validate_experiment_metrics — improved pydantic error messages
    # ------------------------------------------------------------------

    _INVALID_METRIC_EVENTS_NODE_ID = {
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "source": {"kind": "EventsNode", "event": "$pageview", "id": None},
    }

    def test_validate_experiment_metrics_does_not_leak_user_input_into_message(self) -> None:
        """User-supplied data must not be echoed back into error messages reflected to the caller."""
        sensitive_value = "secret-payload-12345-do-not-leak"
        metric = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "source": {
                "kind": "EventsNode",
                "event": "$pageview",
                "id": sensitive_value,
            },
        }
        with self.assertRaises(ValidationError) as ctx:
            ExperimentService.validate_experiment_metrics([metric])
        message = str(ctx.exception)
        assert sensitive_value not in message, f"Sensitive user value leaked into error message: {message}"

    def test_validate_experiment_metrics_strips_pydantic_url_field(self) -> None:
        """Pydantic URLs like https://errors.pydantic.dev/... add noise — strip them."""
        with self.assertRaises(ValidationError) as ctx:
            ExperimentService.validate_experiment_metrics([self._INVALID_METRIC_EVENTS_NODE_ID])
        message = str(ctx.exception)
        assert "errors.pydantic.dev" not in message
        assert "'url':" not in message

    def test_validate_experiment_metrics_preserves_loc_and_type_in_message(self) -> None:
        """Field location and error type stay so callers can self-correct."""
        with self.assertRaises(ValidationError) as ctx:
            ExperimentService.validate_experiment_metrics([self._INVALID_METRIC_EVENTS_NODE_ID])
        message = str(ctx.exception)
        assert "extra_forbidden" in message
        assert "id" in message

    def test_validate_experiment_metrics_preserves_index_prefix(self) -> None:
        """The 'Invalid metric at index <i>:' prefix identifies which metric failed."""
        with self.assertRaises(ValidationError) as ctx:
            ExperimentService.validate_experiment_metrics([self._INVALID_METRIC_EVENTS_NODE_ID])
        assert "Invalid metric at index 0:" in str(ctx.exception)

    def test_metric_type_to_class_mapping_matches_schema(self) -> None:
        """Drift guard: every variant of the ExperimentMetric union must have an entry in
        _METRIC_TYPE_TO_CLASS. If a new metric_type is added to the schema, this fails so
        the mapping (used to filter pydantic errors to the matching variant) stays accurate."""
        root_annotation = ExperimentMetric.model_fields["root"].annotation
        assert root_annotation is not None, "ExperimentMetric.root has no annotation — schema is malformed"
        union_variants = root_annotation.__args__
        schema_pairs = {}
        for variant in union_variants:
            metric_type_annotation = variant.model_fields["metric_type"].annotation
            assert metric_type_annotation is not None, (
                f"{variant.__name__}.metric_type has no annotation — schema is malformed"
            )
            schema_pairs[metric_type_annotation.__args__[0]] = variant.__name__
        assert ExperimentService._METRIC_TYPE_TO_CLASS == schema_pairs, (
            "ExperimentMetric union changed — update ExperimentService._METRIC_TYPE_TO_CLASS. "
            f"Expected {schema_pairs}, got {ExperimentService._METRIC_TYPE_TO_CLASS}"
        )

    @parameterized.expand(
        [
            (
                "matches_events_node_id",
                {"type": "extra_forbidden", "loc": ("ExperimentMeanMetric", "source", "EventsNode", "id")},
                True,
            ),
            (
                "ignores_wrong_error_type",
                {"type": "missing", "loc": ("ExperimentMeanMetric", "source", "EventsNode", "id")},
                False,
            ),
            (
                "ignores_extra_forbidden_on_other_field",
                {"type": "extra_forbidden", "loc": ("ExperimentMeanMetric", "source", "EventsNode", "foo")},
                False,
            ),
            (
                "ignores_extra_forbidden_not_on_events_node",
                {"type": "extra_forbidden", "loc": ("ExperimentMeanMetric", "source", "ActionsNode", "event")},
                False,
            ),
            ("ignores_empty_loc", {"type": "extra_forbidden", "loc": ()}, False),
            ("ignores_missing_loc", {"type": "extra_forbidden"}, False),
        ]
    )
    def test_is_events_node_actions_node_confusion_predicate(self, _: str, err: dict, expected: bool) -> None:
        assert ExperimentService._is_events_node_actions_node_confusion(err) is expected

    def test_pydantic_extra_forbidden_error_code_is_still_in_use(self) -> None:
        """Canary: the EventsNode.id hint matches on the pydantic error type slug
        'extra_forbidden'. Pydantic publishes these slugs as stable public API, but they
        live in an external dependency — fail loudly if a future pydantic upgrade renames
        the slug so the hint stops silently matching."""
        try:
            EventsNode.model_validate({"event": "x", "totally_made_up_field_does_not_exist": 1})
        except pydantic.ValidationError as e:
            error_types = {err["type"] for err in e.errors()}
            assert "extra_forbidden" in error_types, (
                f"pydantic no longer emits 'extra_forbidden' for unknown fields — "
                f"got {error_types}. Update ExperimentService._build_metric_validation_hint."
            )
        else:
            raise AssertionError("pydantic did not reject an unknown field on EventsNode")

    def test_validate_experiment_metrics_events_node_id_hint(self) -> None:
        """Passing `id` on an EventsNode yields a hint mentioning both EventsNode and ActionsNode."""
        with self.assertRaises(ValidationError) as ctx:
            ExperimentService.validate_experiment_metrics([self._INVALID_METRIC_EVENTS_NODE_ID])
        message = str(ctx.exception)
        assert "EventsNode" in message
        assert "ActionsNode" in message

    def test_validate_experiment_metrics_does_not_echo_large_user_values(self) -> None:
        """A large user-supplied value (e.g. enormous event name) must not bloat the message."""
        huge_value = "x" * 10_000
        metric = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "source": {"kind": "EventsNode", "event": "$pageview", "id": huge_value},
        }
        with self.assertRaises(ValidationError) as ctx:
            ExperimentService.validate_experiment_metrics([metric])
        message = str(ctx.exception)
        assert huge_value not in message
        # The message size must scale with the metric schema (bounded), not with user input.
        # Even with a 10KB user value, the message stays small relative to the input.
        assert len(message) < len(huge_value), (
            f"Error message length {len(message)} must not grow with user input ({len(huge_value)})"
        )

    def test_validate_experiment_metrics_caps_reported_errors_for_huge_payloads(self) -> None:
        """A funnel with many bad steps must not produce an unbounded error list."""
        # 100 invalid funnel steps — each one will trigger union-variant errors.
        bad_step = {"kind": "EventsNode", "event": "$pageview", "id": None}
        metric = {
            "kind": "ExperimentMetric",
            "metric_type": "funnel",
            "series": [bad_step] * 100,
        }
        with self.assertRaises(ValidationError) as ctx:
            ExperimentService.validate_experiment_metrics([metric])
        message = str(ctx.exception)
        # The truncation marker key from the implementation should appear when the cap is hit.
        assert "truncated" in message
        # And the message size remains bounded even with 100 bad steps.
        assert len(message) < 10_000, f"Error message length {len(message)} exceeded bound"

    def test_validate_experiment_metrics_reports_index_for_second_metric(self) -> None:
        """Multi-metric payloads must report which index failed."""
        valid = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "source": {"kind": "EventsNode", "event": "$pageview"},
        }
        with self.assertRaises(ValidationError) as ctx:
            ExperimentService.validate_experiment_metrics([valid, self._INVALID_METRIC_EVENTS_NODE_ID])
        assert "Invalid metric at index 1:" in str(ctx.exception)

    # ------------------------------------------------------------------
    # Service contract fields
    # ------------------------------------------------------------------

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
                "minimum_detectable_effect": 20,
            },
            feature_flag_config={
                "filters": {
                    "multivariate": {
                        "variants": [
                            {"key": "control", "name": "Control", "rollout_percentage": 34},
                            {"key": "variant-a", "name": "Variant A", "rollout_percentage": 33},
                            {"key": "variant-b", "name": "Variant B", "rollout_percentage": 33},
                        ]
                    },
                    "groups": [{"properties": [], "rollout_percentage": 80}],
                },
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

    def test_get_feature_flag_key_strips_tombstone_for_deleted_flag(self):
        experiment = self._create_draft_experiment(flag_key="tombstone-key-flag")
        flag = experiment.feature_flag

        flag.deleted = True
        flag.key = flag.tombstoned_key()
        flag.save()
        experiment.refresh_from_db()

        # The serializer (feature_flag_key) and analytics read through this method, so it
        # must surface the original key rather than leaking the ":deleted:<id>" tombstone.
        assert experiment.get_feature_flag_key() == "tombstone-key-flag"

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
                {},
                feature_flag_config={
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "control", "name": "Control", "rollout_percentage": 34},
                                {"key": "test", "name": "Test", "rollout_percentage": 33},
                                {"key": "new_variant", "name": "New", "rollout_percentage": 33},
                            ]
                        }
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

    @parameterized.expand([("regex",), ("not_regex",)])
    def test_update_experiment_allows_existing_invalid_regex_in_flag_filters(self, operator):
        experiment = self._create_draft_experiment()
        flag = experiment.feature_flag
        flag.filters["groups"][0]["properties"] = [
            {"key": "email", "value": "[unclosed", "operator": operator, "type": "person"}
        ]
        flag.save(update_fields=["filters"])

        service = self._service()
        service.update_experiment(
            experiment,
            {},
            feature_flag_config={
                "filters": {
                    "multivariate": {
                        "variants": [
                            {"key": "control", "name": "Control", "rollout_percentage": 50},
                            {"key": "test", "name": "Test", "rollout_percentage": 50},
                        ]
                    },
                },
            },
        )

        flag.refresh_from_db()
        assert flag.filters["groups"][0]["properties"][0]["value"] == "[unclosed"
        assert flag.filters["groups"][0]["properties"][0]["operator"] == operator

    def test_update_experiment_syncs_feature_flag_variants_for_draft(self):
        experiment = self._create_draft_experiment()
        service = self._service()

        service.update_experiment(
            experiment,
            {},
            feature_flag_config={
                "filters": {
                    "multivariate": {
                        "variants": [
                            {"key": "control", "name": "Control", "rollout_percentage": 34},
                            {"key": "test", "name": "Test", "rollout_percentage": 33},
                            {"key": "variant-b", "name": "Variant B", "rollout_percentage": 33},
                        ]
                    },
                }
            },
        )

        experiment.feature_flag.refresh_from_db()
        variants = experiment.feature_flag.filters["multivariate"]["variants"]
        assert len(variants) == 3
        assert variants[2]["key"] == "variant-b"

    def test_update_running_experiment_syncs_flag_when_update_feature_flag_params_true(self):
        experiment = self._create_running_experiment()
        assert experiment.feature_flag.filters["multivariate"]["variants"][0]["rollout_percentage"] == 50
        assert experiment.feature_flag.filters["groups"][0]["rollout_percentage"] == 100

        self._service().update_experiment(
            experiment,
            {"update_feature_flag_params": True},
            feature_flag_config={
                "filters": {
                    "multivariate": {
                        "variants": [
                            {"key": "control", "name": "Control", "rollout_percentage": 75},
                            {"key": "test", "name": "Test", "rollout_percentage": 25},
                        ]
                    },
                    "groups": [{"properties": [], "rollout_percentage": 50}],
                },
            },
        )

        experiment.feature_flag.refresh_from_db()
        variants = experiment.feature_flag.filters["multivariate"]["variants"]
        assert variants[0]["rollout_percentage"] == 75
        assert variants[1]["rollout_percentage"] == 25
        assert experiment.feature_flag.filters["groups"][0]["rollout_percentage"] == 50

    @parameterized.expand(
        [
            ("absent", {}),
            ("false", {"update_feature_flag_params": False}),
        ]
    )
    def test_update_running_experiment_does_not_sync_flag(self, _name: str, extra: dict):
        experiment = self._create_running_experiment()
        assert experiment.feature_flag.filters["multivariate"]["variants"][0]["rollout_percentage"] == 50

        self._service().update_experiment(
            experiment,
            {**extra},
            feature_flag_config={
                "filters": {
                    "multivariate": {
                        "variants": [
                            {"key": "control", "name": "Control", "rollout_percentage": 75},
                            {"key": "test", "name": "Test", "rollout_percentage": 25},
                        ]
                    },
                },
            },
        )

        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.filters["multivariate"]["variants"][0]["rollout_percentage"] == 50

    def test_update_running_experiment_with_flag_preserves_single_group_with_custom_conditions(self):
        """A flag with one group targeting a cohort at 57% — variant split change must not touch the group."""
        experiment = self._create_running_experiment()

        cohort = Cohort.objects.create(team=self.team, name="Internal / Test users")
        flag = experiment.feature_flag
        flag.filters["groups"] = [
            {
                "properties": [{"key": "id", "value": cohort.id, "type": "cohort"}],
                "rollout_percentage": 57,
            },
        ]
        flag.save()

        self._service().update_experiment(
            experiment,
            {"update_feature_flag_params": True},
            feature_flag_config={
                "filters": {
                    "multivariate": {
                        "variants": [
                            {"key": "control", "name": "Control", "rollout_percentage": 70},
                            {"key": "test", "name": "Test", "rollout_percentage": 30},
                        ]
                    },
                },
            },
        )

        flag.refresh_from_db()
        assert len(flag.filters["groups"]) == 1
        assert flag.filters["groups"][0]["properties"] == [{"key": "id", "value": cohort.id, "type": "cohort"}]
        assert flag.filters["groups"][0]["rollout_percentage"] == 57
        assert flag.filters["multivariate"]["variants"][0]["rollout_percentage"] == 70
        assert flag.filters["multivariate"]["variants"][1]["rollout_percentage"] == 30

    def test_update_running_experiment_with_flag_preserves_multiple_groups(self):
        experiment = self._create_running_experiment()

        cohort = Cohort.objects.create(team=self.team, name="Internal / Test users")
        flag = experiment.feature_flag
        flag.filters["groups"] = [
            {
                "properties": [{"key": "id", "value": cohort.id, "type": "cohort"}],
                "rollout_percentage": 57,
            },
            {
                "properties": [{"key": "country", "value": "US", "type": "person"}],
                "rollout_percentage": 100,
            },
        ]
        flag.save()

        self._service().update_experiment(
            experiment,
            {"update_feature_flag_params": True},
            feature_flag_config={
                "filters": {
                    "multivariate": {
                        "variants": [
                            {"key": "control", "name": "Control", "rollout_percentage": 70},
                            {"key": "test", "name": "Test", "rollout_percentage": 30},
                        ]
                    },
                },
            },
        )

        flag.refresh_from_db()
        assert len(flag.filters["groups"]) == 2
        assert flag.filters["groups"][0]["properties"] == [{"key": "id", "value": cohort.id, "type": "cohort"}]
        assert flag.filters["groups"][0]["rollout_percentage"] == 57
        assert flag.filters["groups"][1]["properties"] == [{"key": "country", "value": "US", "type": "person"}]
        assert flag.filters["groups"][1]["rollout_percentage"] == 100
        assert flag.filters["multivariate"]["variants"][0]["rollout_percentage"] == 70
        assert flag.filters["multivariate"]["variants"][1]["rollout_percentage"] == 30

    def test_update_running_experiment_with_flag_still_rejects_adding_variants(self):
        experiment = self._create_running_experiment()

        with self.assertRaises(ValidationError) as ctx:
            self._service().update_experiment(
                experiment,
                {"update_feature_flag_params": True},
                feature_flag_config={
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "control", "name": "Control", "rollout_percentage": 34},
                                {"key": "test", "name": "Test", "rollout_percentage": 33},
                                {"key": "new_variant", "name": "New", "rollout_percentage": 33},
                            ]
                        }
                    },
                },
            )

        assert "Can't update feature_flag_variants" in str(ctx.exception)

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
            },
            allow_unknown_events=True,
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

    @parameterized.expand(
        [
            ("primary", "metrics", "primary_metrics_ordered_uuids"),
            ("secondary", "metrics_secondary", "secondary_metrics_ordered_uuids"),
        ]
    )
    def test_update_experiment_auto_generates_uuids(self, _name, field, ordering_attr):
        experiment = self._create_draft_experiment()
        service = self._service()

        updated = service.update_experiment(
            experiment,
            {
                field: [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    }
                ],
            },
            allow_unknown_events=True,
        )

        metrics = getattr(updated, field)
        assert len(metrics) == 1
        generated_uuid = metrics[0].get("uuid")
        assert generated_uuid, "UUID should be auto-generated for metrics without one"
        assert getattr(updated, ordering_attr) == [generated_uuid]

    @parameterized.expand(
        [
            ("primary", "metrics", "primary_metrics_ordered_uuids"),
            ("secondary", "metrics_secondary", "secondary_metrics_ordered_uuids"),
        ]
    )
    def test_update_experiment_preserves_provided_metric_uuids(self, _name, field, ordering_attr):
        experiment = self._create_draft_experiment()
        service = self._service()

        updated = service.update_experiment(
            experiment,
            {
                field: [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "uuid": "explicit-uuid",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    }
                ],
            },
            allow_unknown_events=True,
        )

        metrics = getattr(updated, field)
        assert metrics[0]["uuid"] == "explicit-uuid"
        assert "explicit-uuid" in (getattr(updated, ordering_attr) or [])

    @parameterized.expand(
        [
            ("primary", "metrics"),
            ("secondary", "metrics_secondary"),
        ]
    )
    def test_create_experiment_does_not_mutate_input_metrics(self, _name, field):
        self._create_flag(key=f"no-mutate-create-flag-{_name}")
        service = self._service()

        input_metrics = [
            {
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "EventsNode", "event": "$pageview"},
            }
        ]
        snapshot = deepcopy(input_metrics)
        metric_kwargs: dict[str, Any] = {field: input_metrics}

        service.create_experiment(
            name=f"No Mutate Create {_name}",
            feature_flag_key=f"no-mutate-create-flag-{_name}",
            allow_unknown_events=True,
            **metric_kwargs,
        )

        assert input_metrics == snapshot

    @parameterized.expand(
        [
            ("primary", "metrics"),
            ("secondary", "metrics_secondary"),
        ]
    )
    def test_update_experiment_does_not_mutate_input_metrics(self, _name, field):
        experiment = self._create_draft_experiment()
        service = self._service()

        input_metrics = [
            {
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "EventsNode", "event": "$pageview"},
            }
        ]
        snapshot = deepcopy(input_metrics)

        service.update_experiment(experiment, {field: input_metrics}, allow_unknown_events=True)

        assert input_metrics == snapshot

    def test_update_experiment_does_not_mutate_flag_filters_in_place(self):
        experiment = self._create_draft_experiment()
        service = self._service()

        original_filters = experiment.feature_flag.filters
        snapshot = deepcopy(original_filters)

        service.update_experiment(
            experiment,
            {
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ],
                    "rollout_percentage": 75,
                }
            },
        )

        assert original_filters == snapshot

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

    def _updated_events(self, mock_report_user_action):
        return [c for c in mock_report_user_action.call_args_list if c.args[1] == "experiment updated"]

    def _changed_fields(self, mock_report_user_action):
        events = self._updated_events(mock_report_user_action)
        assert len(events) == 1, f"expected exactly one 'experiment updated' event, got {len(events)}"
        return events[0].args[2]["changed_fields"]

    def _make_saved_metric(self, name: str, event: str = "$pageview") -> ExperimentSavedMetric:
        return ExperimentSavedMetric.objects.create(
            team=self.team,
            name=name,
            query={"kind": "ExperimentMetric", "metric_type": "mean", "source": {"kind": "EventsNode", "event": event}},
        )

    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_update_reports_updated_with_metric_composition(self, mock_report_user_action):
        experiment = self._create_draft_experiment()
        saved_metric = self._make_saved_metric("Shared SM")
        service = self._service()
        service.update_experiment(
            experiment,
            {"saved_metrics_ids": [{"id": saved_metric.id, "metadata": {"type": "primary"}}]},
            serializer_context=service._build_serializer_context(),
        )

        metadata = self._updated_events(mock_report_user_action)[0].args[2]
        assert metadata["saved_metrics_count"] == 1
        # _create_draft_experiment seeds one inline primary metric and no secondary
        assert metadata["metrics_count"] == 1
        assert metadata["secondary_metrics_count"] == 0
        assert "saved_metrics" in metadata["changed_fields"]
        assert mock_report_user_action.call_args_list[-1].kwargs["team"] == self.team
        assert mock_report_user_action.call_args_list[-1].kwargs["request"] is not None

    @parameterized.expand(
        [
            ("name", {"name": "Renamed experiment"}, "name"),
            ("description", {"description": "A brand new hypothesis"}, "description"),
        ]
    )
    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_update_changed_fields_scalar_edit(self, _name, update_data, expected_field, mock_report_user_action):
        experiment = self._create_draft_experiment()
        service = self._service()
        service.update_experiment(experiment, update_data, serializer_context=service._build_serializer_context())

        changed = self._changed_fields(mock_report_user_action)
        assert expected_field in changed
        # A scalar edit must not falsely report metric (re)configuration even though the
        # update pipeline internally re-touches existing inline metrics.
        assert "metrics" not in changed
        assert "saved_metrics" not in changed

    @parameterized.expand(
        [
            (
                "primary",
                {
                    "metrics": [
                        {
                            "kind": "ExperimentMetric",
                            "metric_type": "mean",
                            "uuid": "m-new",
                            "source": {"kind": "EventsNode", "event": "checkout_completed"},
                        }
                    ]
                },
                "metrics",
            ),
            (
                "secondary",
                {
                    "metrics_secondary": [
                        {
                            "kind": "ExperimentMetric",
                            "metric_type": "funnel",
                            "uuid": "s-new",
                            "series": [
                                {"kind": "EventsNode", "event": "$pageview"},
                                {"kind": "EventsNode", "event": "signed_up"},
                            ],
                        }
                    ]
                },
                "metrics_secondary",
            ),
        ]
    )
    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_update_changed_fields_inline_metric(self, _name, update_data, expected_field, mock_report_user_action):
        experiment = self._create_draft_experiment()
        service = self._service()
        service.update_experiment(
            experiment, update_data, serializer_context=service._build_serializer_context(), allow_unknown_events=True
        )

        changed = self._changed_fields(mock_report_user_action)
        assert expected_field in changed
        assert "saved_metrics" not in changed

    @parameterized.expand(
        [
            # (initial role attached, role sent in the measured update, expect a real change)
            ("attach", None, "primary", True),
            ("detach", "primary", None, True),
            ("retype", "primary", "secondary", True),
            ("resend_identical", "primary", "primary", False),
        ]
    )
    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_saved_metric_change_detection(self, _name, initial_type, new_type, expect_change, mock_report_user_action):
        experiment = self._create_draft_experiment()
        saved_metric = self._make_saved_metric("Reusable conversion")
        service = self._service()
        ctx = service._build_serializer_context()

        # fresh payload per call — update_experiment mutates update_data in place
        def attach(metric_type: str) -> dict:
            return {"saved_metrics_ids": [{"id": saved_metric.id, "metadata": {"type": metric_type}}]}

        if initial_type is not None:
            service.update_experiment(experiment, attach(initial_type), serializer_context=ctx)
        mock_report_user_action.reset_mock()

        update_data = {"saved_metrics_ids": []} if new_type is None else attach(new_type)
        service.update_experiment(experiment, update_data, serializer_context=ctx)

        if expect_change:
            changed = self._changed_fields(mock_report_user_action)
            assert "saved_metrics" in changed
            # the write-side payload key must not leak; inline metrics were untouched
            assert "saved_metrics_ids" not in changed
            assert "metrics" not in changed
        else:
            assert self._updated_events(mock_report_user_action) == []

    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_update_with_no_real_change_does_not_report(self, mock_report_user_action):
        experiment = self._create_draft_experiment(name="Stable name")
        service = self._service()
        service.update_experiment(
            experiment, {"name": "Stable name"}, serializer_context=service._build_serializer_context()
        )

        assert self._updated_events(mock_report_user_action) == []

    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_update_changed_fields_multiple_at_once(self, mock_report_user_action):
        experiment = self._create_draft_experiment()
        saved_metric = self._make_saved_metric("Reusable conversion")
        service = self._service()
        service.update_experiment(
            experiment,
            {
                "name": "Renamed and remetered",
                "saved_metrics_ids": [{"id": saved_metric.id, "metadata": {"type": "primary"}}],
            },
            serializer_context=service._build_serializer_context(),
        )

        changed = self._changed_fields(mock_report_user_action)
        assert "name" in changed
        assert "saved_metrics" in changed

    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_update_with_event_source_and_no_request_reports_with_source(self, mock_report_user_action):
        # Parity with create_experiment: a non-HTTP caller (e.g. an AI/Max tool) that passes
        # event_source must still emit, attributed to that channel, even without a request.
        experiment = self._create_draft_experiment()
        service = self._service()
        service.update_experiment(experiment, {"name": "Renamed by AI"}, event_source=EventSource.POSTHOG_AI)

        event = self._updated_events(mock_report_user_action)[0]
        assert event.args[2]["source"] == EventSource.POSTHOG_AI
        assert "name" in event.args[2]["changed_fields"]
        assert event.kwargs["request"] is None

    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_update_without_request_or_event_source_is_silent(self, mock_report_user_action):
        # Internal callers that supply neither a request nor an event_source stay invisible.
        experiment = self._create_draft_experiment()
        service = self._service()
        service.update_experiment(experiment, {"name": "Renamed internally"})

        assert self._updated_events(mock_report_user_action) == []

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

    def test_duplicate_experiment_uses_flag_variants_over_stale_parameters(self):
        self._create_flag(key="dup-stale-source")
        service = self._service()
        source = service.create_experiment(
            name="Stale Source",
            feature_flag_key="dup-stale-source",
        )
        # Drift the stored parameters to an invalid single-variant set. The linked flag
        # stays the source of truth (control + test), so duplication must ignore the stale
        # copy and build the new flag from the flag's variants rather than revalidate them.
        Experiment.objects.filter(id=source.id).update(
            parameters={
                "feature_flag_variants": [
                    {"key": "test", "name": "Test", "rollout_percentage": 100},
                ]
            }
        )
        source.refresh_from_db()

        dup = service.duplicate_experiment(source, feature_flag_key="dup-stale-target")

        assert dup.feature_flag.key == "dup-stale-target"
        assert [v["key"] for v in dup.feature_flag.variants] == ["control", "test"]

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

    # index 0 is the truthiness edge case: a `if index:` guard would wrongly drop it.
    @parameterized.expand([("index_zero", 0), ("index_one", 1)])
    def test_duplicate_experiment_preserves_group_aggregation(self, _name: str, group_index: int):
        flag = self._create_flag(key="dup-group-source")
        flag.filters = {**flag.filters, "aggregation_group_type_index": group_index}
        flag.save()
        service = self._service()
        source = service.create_experiment(name="Group Source", feature_flag_key="dup-group-source")

        # New key forces a fresh flag through _ensure_feature_flag rather than reusing the source.
        dup = service.duplicate_experiment(source, feature_flag_key="dup-group-target")

        assert dup.feature_flag.id != source.feature_flag.id
        assert dup.feature_flag.aggregation_group_type_index == group_index

    # Only groups[0]'s rollout percentage clones; property targeting and extra groups do not, matching
    # the experiment input surface that restricts groups to a single empty-properties entry.
    @parameterized.expand(
        [
            ("single_group", [{"properties": [], "rollout_percentage": 20}]),
            (
                "targeting_and_extra_groups_dropped",
                [
                    {
                        "properties": [{"key": "email", "type": "person", "value": "a@b.com", "operator": "exact"}],
                        "rollout_percentage": 20,
                    },
                    {"properties": [], "rollout_percentage": 55},
                ],
            ),
        ]
    )
    def test_duplicate_experiment_inherits_rollout_percentage(self, _name: str, source_groups: list[dict]):
        flag = self._create_flag(key="dup-rollout-source")
        flag.filters = {**flag.filters, "groups": source_groups}
        flag.save()
        service = self._service()
        source = service.create_experiment(name="Rollout Source", feature_flag_key="dup-rollout-source")

        # New key forces a fresh flag through _ensure_feature_flag rather than reusing the source.
        dup = service.duplicate_experiment(source, feature_flag_key="dup-rollout-target")

        assert dup.feature_flag.id != source.feature_flag.id
        clone_groups = dup.feature_flag.filters["groups"]
        # Inherits groups[0]'s percentage but nothing else: one group, no property targeting.
        assert len(clone_groups) == 1
        assert clone_groups[0]["rollout_percentage"] == 20
        assert clone_groups[0]["properties"] == []

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

    def test_archive_experiment_archives_disabled_flag(self):
        experiment = self._create_ended_experiment(name="Archive Flag", feature_flag_key="archive-linked-flag")
        experiment.feature_flag.active = False
        experiment.feature_flag.save()

        self._service().archive_experiment(experiment)

        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.archived is True

    def test_archive_experiment_keeps_enabled_flag_unarchived(self):
        # An enabled flag may still be serving traffic (e.g. rolling out the winning
        # variant), so archiving the experiment must not archive it.
        experiment = self._create_ended_experiment(name="Archive Active Flag", feature_flag_key="still-active-flag")
        assert experiment.feature_flag.active is True

        self._service().archive_experiment(experiment)

        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.archived is False

    def test_archive_experiment_disables_and_archives_enabled_flag_when_opted_in(self):
        experiment = self._create_ended_experiment(name="Disable On Archive", feature_flag_key="disable-on-archive")
        assert experiment.feature_flag.active is True

        self._service().archive_experiment(experiment, disable_feature_flag=True)

        experiment.refresh_from_db()
        flag = FeatureFlag.objects.get(pk=experiment.feature_flag_id)
        assert flag.active is False
        assert flag.archived is True
        assert experiment.feature_flag_auto_archived is True

    def test_archive_experiment_denies_disabling_flag_without_editor_access(self):
        # A user who can archive the experiment but lacks editor access to the flag must not
        # be able to disable it via disable_feature_flag — and the experiment archive rolls back.
        experiment = self._create_ended_experiment(name="No Flag Access", feature_flag_key="no-flag-access")
        service = self._service()

        with patch.object(service, "_user_can_edit_flag", return_value=False):
            with self.assertRaises(PermissionDenied):
                service.archive_experiment(experiment, disable_feature_flag=True)

        experiment.refresh_from_db()
        assert experiment.archived is False
        flag = FeatureFlag.objects.get(pk=experiment.feature_flag_id)
        assert flag.active is True
        assert flag.archived is False

    def test_archive_experiment_denies_disabling_flag_for_user_without_real_access(self):
        # Exercises the real _user_can_edit_flag check (no patching): a user with no access to
        # the flag is refused, so an inverted/broken access check would fail this test.
        experiment = self._create_ended_experiment(name="Real No Access", feature_flag_key="real-no-access-flag")
        outsider = User.objects.create_user("outsider@example.com", None, "Outsider")
        service = ExperimentService(team=self.team, user=outsider)

        with self.assertRaises(PermissionDenied):
            service.archive_experiment(experiment, disable_feature_flag=True)

        experiment.refresh_from_db()
        assert experiment.archived is False
        flag = FeatureFlag.objects.get(pk=experiment.feature_flag_id)
        assert flag.active is True
        assert flag.archived is False

    def test_archive_experiment_denies_disabling_active_flag_without_feature_flag_write_scope(self):
        # An experiment-only token must not be able to disable an active flag via disable_feature_flag.
        experiment = self._create_ended_experiment(
            name="No FF Scope Active", feature_flag_key="no-ff-scope-active-flag"
        )

        with self.assertRaises(PermissionDenied):
            self._service().archive_experiment(experiment, disable_feature_flag=True, can_write_feature_flag=False)

        experiment.refresh_from_db()
        assert experiment.archived is False
        flag = FeatureFlag.objects.get(pk=experiment.feature_flag_id)
        assert flag.active is True
        assert flag.archived is False

    def test_archive_experiment_skips_flag_cleanup_without_feature_flag_write_scope(self):
        # A token scoped only to experiments must not archive the linked flag as a side effect.
        experiment = self._create_ended_experiment(name="No FF Scope", feature_flag_key="no-ff-scope-flag")
        experiment.feature_flag.active = False
        experiment.feature_flag.save()

        self._service().archive_experiment(experiment, can_write_feature_flag=False)

        experiment.refresh_from_db()
        assert experiment.archived is True
        flag = FeatureFlag.objects.get(pk=experiment.feature_flag_id)
        assert flag.archived is False
        assert experiment.feature_flag_auto_archived is False

    def test_unarchive_experiment_skips_flag_without_feature_flag_write_scope(self):
        # Unarchiving the flag is a feature_flag write — skipped (flag stays archived, bookkeeping
        # intact) for an experiment-only token, recoverable on a later unarchive with the scope.
        experiment = self._create_ended_experiment(name="Unarchive No Scope", feature_flag_key="unarchive-no-scope")
        experiment.feature_flag.active = False
        experiment.feature_flag.save()
        service = self._service()
        service.archive_experiment(experiment)
        experiment.refresh_from_db()
        assert experiment.feature_flag_auto_archived is True

        service.unarchive_experiment(experiment, can_write_feature_flag=False)

        experiment.refresh_from_db()
        assert experiment.archived is False
        flag = FeatureFlag.objects.get(pk=experiment.feature_flag_id)
        assert flag.archived is True
        assert experiment.feature_flag_auto_archived is True

    def test_archive_experiment_denies_disabling_flag_when_approval_required(self):
        experiment = self._create_ended_experiment(name="Approval Gated", feature_flag_key="approval-gated-flag")
        service = self._service()

        with (
            patch.object(service, "_user_can_edit_flag", return_value=True),
            patch.object(service, "_flag_disable_requires_approval", return_value=True),
        ):
            with self.assertRaises(PermissionDenied):
                service.archive_experiment(experiment, disable_feature_flag=True)

        experiment.refresh_from_db()
        assert experiment.archived is False
        flag = FeatureFlag.objects.get(pk=experiment.feature_flag_id)
        assert flag.active is True
        assert flag.archived is False

    def test_archive_experiment_denies_disabling_flag_with_dependents(self):
        # Mirror the feature flag API: disabling a flag other active flags depend on is rejected.
        experiment = self._create_ended_experiment(name="Has Dependents", feature_flag_key="depended-on-flag")
        FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="dependent-flag",
            active=True,
            filters={
                "groups": [{"properties": [{"type": "flag", "key": str(experiment.feature_flag_id), "value": "true"}]}]
            },
        )

        with self.assertRaises(ValidationError):
            self._service().archive_experiment(experiment, disable_feature_flag=True)

        experiment.refresh_from_db()
        assert experiment.archived is False
        flag = FeatureFlag.objects.get(pk=experiment.feature_flag_id)
        assert flag.active is True
        assert flag.archived is False

    def test_archive_experiment_skips_flag_cleanup_without_editor_access(self):
        # The implicit archive-only cleanup of an already-disabled flag is skipped (not an error)
        # when the caller can't edit the flag — the experiment still archives.
        experiment = self._create_ended_experiment(name="Skip Cleanup", feature_flag_key="skip-cleanup-flag")
        experiment.feature_flag.active = False
        experiment.feature_flag.save()
        service = self._service()

        with patch.object(service, "_user_can_edit_flag", return_value=False):
            service.archive_experiment(experiment)

        experiment.refresh_from_db()
        assert experiment.archived is True
        flag = FeatureFlag.objects.get(pk=experiment.feature_flag_id)
        assert flag.archived is False
        assert experiment.feature_flag_auto_archived is False

    def test_archive_experiment_keeps_flag_shared_with_live_experiment(self):
        experiment = self._create_ended_experiment(name="Shared Flag", feature_flag_key="shared-flag")
        experiment.feature_flag.active = False
        experiment.feature_flag.save()
        Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Other experiment on same flag",
            feature_flag=experiment.feature_flag,
        )

        self._service().archive_experiment(experiment)

        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.archived is False

    def test_archive_experiment_keeps_shared_flag_even_when_opted_in(self):
        # Opting in to disable the flag must still never touch a flag a live experiment relies on.
        experiment = self._create_ended_experiment(name="Shared Opt In", feature_flag_key="shared-opt-in-flag")
        Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Other experiment on same flag",
            feature_flag=experiment.feature_flag,
        )

        self._service().archive_experiment(experiment, disable_feature_flag=True)

        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.active is True
        assert experiment.feature_flag.archived is False

    def test_unarchive_experiment_keeps_opted_in_flag_disabled(self):
        # When archiving disabled an enabled flag, unarchiving un-archives it but leaves it
        # disabled — re-enabling stays an explicit user decision.
        experiment = self._create_ended_experiment(name="Unarchive Opt In", feature_flag_key="unarchive-opt-in-flag")
        service = self._service()
        service.archive_experiment(experiment, disable_feature_flag=True)
        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.archived is True

        service.unarchive_experiment(experiment)

        experiment.refresh_from_db()
        flag = FeatureFlag.objects.get(pk=experiment.feature_flag_id)
        assert flag.archived is False
        assert flag.active is False
        assert experiment.feature_flag_auto_archived is False

    def test_unarchive_experiment_unarchives_flag(self):
        experiment = self._create_ended_experiment(name="Unarchive Flag", feature_flag_key="unarchive-linked-flag")
        experiment.feature_flag.active = False
        experiment.feature_flag.save()
        service = self._service()
        service.archive_experiment(experiment)
        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.archived is True
        assert experiment.feature_flag_auto_archived is True

        service.unarchive_experiment(experiment)

        refreshed = Experiment.objects.get(pk=experiment.id)
        flag = FeatureFlag.objects.get(pk=experiment.feature_flag_id)
        assert flag.archived is False
        assert refreshed.feature_flag_auto_archived is False
        # The flag stays disabled — re-enabling is an explicit user decision
        assert flag.active is False

    def test_unarchive_experiment_keeps_manually_archived_flag(self):
        # The user archived the flag themselves, so unarchiving the experiment must not undo it.
        experiment = self._create_ended_experiment(name="Manual Archive", feature_flag_key="manually-archived-flag")
        experiment.feature_flag.active = False
        experiment.feature_flag.archived = True
        experiment.feature_flag.save()
        service = self._service()
        service.archive_experiment(experiment)
        assert experiment.feature_flag_auto_archived is False

        service.unarchive_experiment(experiment)

        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.archived is True

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
    # Unarchive
    # ------------------------------------------------------------------

    def test_unarchive_experiment_success(self):
        experiment = self._create_ended_experiment(name="Unarchive Test", feature_flag_key="unarchive-flag")
        service = self._service()
        service.archive_experiment(experiment)

        unarchived = service.unarchive_experiment(experiment)

        assert unarchived.archived is False
        assert unarchived.status == Experiment.Status.STOPPED

    def test_unarchive_experiment_not_archived_raises(self):
        experiment = self._create_ended_experiment(name="Not Archived", feature_flag_key="not-archived-flag")

        with self.assertRaises(ValidationError) as ctx:
            self._service().unarchive_experiment(experiment)

        assert "not archived" in str(ctx.exception)

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

    @patch("products.experiments.backend.experiment_service.create_notification")
    def test_end_experiment_dispatches_realtime_to_creator(self, mock_create_notification):
        creator = self._create_user("creator-end@test.com")
        experiment = self._create_running_experiment(name="End Notify", feature_flag_key="end-notify-flag")
        experiment.created_by = creator
        experiment.save()

        self._service().end_experiment(experiment, request=self._make_request())

        assert mock_create_notification.call_count == 1
        data = mock_create_notification.call_args.args[0]
        assert data.notification_type.value == "experiment_concluded"
        assert data.target_id == str(creator.id)
        assert data.team_id == self.team.id
        assert data.resource_type == "experiment"
        assert data.resource_id == str(experiment.id)

    @patch("products.experiments.backend.experiment_service.create_notification")
    def test_ship_variant_running_dispatches_realtime(self, mock_create_notification):
        creator = self._create_user("creator-ship@test.com")
        experiment = self._create_running_experiment(name="Ship Notify", feature_flag_key="ship-notify-flag")
        experiment.created_by = creator
        experiment.save()

        self._service().ship_variant(experiment, variant_key="control", request=self._make_request())

        assert mock_create_notification.call_count == 1
        data = mock_create_notification.call_args.args[0]
        assert data.notification_type.value == "experiment_concluded"

    @patch("products.experiments.backend.experiment_service.create_notification")
    def test_no_dispatch_when_actor_is_creator(self, mock_create_notification):
        # If the user ending the experiment is the creator, skip the self-notification.
        experiment = self._create_running_experiment(name="Self End", feature_flag_key="self-end-flag")
        assert experiment.created_by_id == self.user.id

        self._service().end_experiment(experiment, request=self._make_request())

        mock_create_notification.assert_not_called()

    @patch("products.experiments.backend.experiment_service.create_notification")
    def test_ship_variant_already_stopped_does_not_dispatch(self, mock_create_notification):
        experiment = self._create_ended_experiment(
            name="Ship Stopped Notify", feature_flag_key="ship-stopped-notify-flag"
        )

        self._service().ship_variant(experiment, variant_key="control", request=self._make_request())

        mock_create_notification.assert_not_called()

    @patch("products.experiments.backend.experiment_service.create_notification")
    def test_no_dispatch_when_experiment_has_no_creator(self, mock_create_notification):
        experiment = self._create_running_experiment(name="No Creator", feature_flag_key="no-creator-flag")
        experiment.created_by = None
        experiment.save()

        self._service().end_experiment(experiment, request=self._make_request())

        mock_create_notification.assert_not_called()

    @patch(
        "products.experiments.backend.experiment_service.create_notification",
        side_effect=RuntimeError("kafka down"),
    )
    def test_realtime_failure_does_not_block_end_experiment(self, _mock_create_notification):
        creator = self._create_user("creator-failure@test.com")
        experiment = self._create_running_experiment(name="Notify Failure", feature_flag_key="notify-failure-flag")
        experiment.created_by = creator
        experiment.save()

        # Must not raise.
        self._service().end_experiment(experiment, request=self._make_request())

        experiment.refresh_from_db()
        assert experiment.end_date is not None

    @parameterized.expand(
        [
            ("significant", {"significant": True, "variants": []}, "Primary metric: significant"),
            ("inconclusive", {"significant": False, "variants": []}, "Primary metric: inconclusive"),
            ("no_result", None, ""),
        ]
    )
    @patch("products.experiments.backend.experiment_service.create_notification")
    def test_end_experiment_body_reflects_primary_metric_outcome(
        self,
        _name: str,
        metric_result: dict | None,
        expected_body: str,
        mock_create_notification: MagicMock,
    ) -> None:
        creator = self._create_user(f"creator-body-{_name}@test.com")
        experiment = self._create_running_experiment(
            name=f"End Body {_name}", feature_flag_key=f"end-body-{_name.replace('_', '-')}-flag"
        )
        experiment.created_by = creator
        experiment.save()
        if metric_result is not None:
            assert experiment.metrics is not None
            assert experiment.start_date is not None
            ExperimentMetricResult.objects.create(
                experiment=experiment,
                metric_uuid=experiment.metrics[0]["uuid"],
                query_from=experiment.start_date,
                query_to=timezone.now(),
                status=ExperimentMetricResult.Status.COMPLETED,
                result=metric_result,
                completed_at=timezone.now(),
            )

        self._service().end_experiment(experiment, request=self._make_request())

        assert mock_create_notification.call_count == 1
        data = mock_create_notification.call_args.args[0]
        assert data.body == expected_body

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

    def test_is_paused_false_for_draft_with_inactive_flag(self) -> None:
        # Inactive flag alone does not make an experiment paused — must also be running.
        draft = self._create_launchable_experiment(name="Draft Inactive", feature_flag_key="draft-inactive-flag")
        draft.feature_flag.active = False
        draft.feature_flag.save()
        assert draft.is_paused is False

    def test_is_paused_false_for_stopped_with_inactive_flag(self) -> None:
        # Inactive flag alone does not make an experiment paused — must also be running.
        stopped = self._create_running_experiment(name="Stopped Inactive", feature_flag_key="stopped-inactive-flag")
        self._service().end_experiment(stopped, request=MagicMock())
        stopped.feature_flag.active = False
        stopped.feature_flag.save()
        stopped.refresh_from_db()
        assert stopped.is_paused is False

    def test_pause_experiment_success(self):
        experiment = self._create_running_experiment(name="Pause Test", feature_flag_key="pause-flag")

        assert experiment.feature_flag.active is True
        assert experiment.is_paused is False

        paused = self._service().pause_experiment(experiment)

        paused.feature_flag.refresh_from_db()
        assert paused.feature_flag.active is False
        assert paused.start_date is not None
        assert paused.end_date is None
        assert paused.is_paused is True
        assert paused.is_running is True  # status remains running while paused

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

    @parameterized.expand(
        [
            (
                "launched",
                "experiment launched",
                lambda self: self._create_launchable_experiment(name="Ev L", feature_flag_key="ev-launched-flag"),
                lambda service, experiment, request: service.launch_experiment(experiment, request=request),
            ),
            (
                "paused",
                "experiment paused",
                lambda self: self._create_running_experiment(name="Ev P", feature_flag_key="ev-paused-flag"),
                lambda service, experiment, request: service.pause_experiment(experiment, request=request),
            ),
            (
                "resumed",
                "experiment resumed",
                lambda self: self._create_running_experiment(name="Ev R", feature_flag_key="ev-resumed-flag"),
                # pause first (no request -> no report), then resume with the request under assertion
                lambda service, experiment, request: (
                    service.pause_experiment(experiment),
                    service.resume_experiment(experiment, request=request),
                ),
            ),
            (
                "archived",
                "experiment archived",
                lambda self: self._create_ended_experiment(name="Ev A", feature_flag_key="ev-archived-flag"),
                lambda service, experiment, request: service.archive_experiment(experiment, request=request),
            ),
            (
                "unarchived",
                "experiment unarchived",
                lambda self: self._create_ended_experiment(name="Ev U", feature_flag_key="ev-unarchived-flag"),
                # archive first (no request -> no report), then unarchive with the request under assertion
                lambda service, experiment, request: (
                    service.archive_experiment(experiment),
                    service.unarchive_experiment(experiment, request=request),
                ),
            ),
        ]
    )
    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_lifecycle_action_emits_exact_event_name(self, _name, event_name, build, act, mock_report_user_action):
        # These five event strings are asserted nowhere else. After the per-action report methods were
        # collapsed into one _report_lifecycle_event(event_name) call, a typo'd string at any call site
        # would silently break the analytics event without this guard.
        experiment = build(self)
        mock_report_user_action.reset_mock()

        act(self._service(), experiment, self._make_request())

        mock_report_user_action.assert_called_once()
        assert mock_report_user_action.call_args.args[1] == event_name

    # ------------------------------------------------------------------
    # Freeze exposure
    # ------------------------------------------------------------------

    def _stamp_exposure_frozen_marker(self, flag: FeatureFlag) -> None:
        filters = deepcopy(flag.filters)
        for group in filters.get("groups", []):
            group[EXPOSURE_FROZEN_GROUP_KEY] = True
            group["description"] = EXPOSURE_FROZEN_GROUP_MARKER
        flag.filters = filters
        flag.save()

    def _update_flag_filters(self, flag: FeatureFlag, filters: dict) -> None:
        serializer = FeatureFlagSerializer(
            flag,
            data={"filters": filters},
            partial=True,
            context={"request": self._make_request(), "team_id": self.team.id, "project_id": self.team.project_id},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        flag.refresh_from_db()

    @contextmanager
    def _stub_freeze_population(self, exposed_uuids: list[str] | None = None):
        uuids = exposed_uuids if exposed_uuids is not None else ["00000000-0000-0000-0000-000000000001"]
        with (
            patch.object(ExperimentService, "_fetch_exposed_person_uuids", return_value=uuids),
            # The stubbed uuids have no real persons behind them; treat them all as resolvable so
            # the personless guard doesn't reject these unrelated scenarios.
            patch(
                "products.experiments.backend.experiment_service.get_person_ids_and_uuids_by_uuids",
                new=lambda team_id, uuids: [(index + 1, person_uuid) for index, person_uuid in enumerate(uuids)],
            ),
            patch(
                "products.cohorts.backend.models.cohort.Cohort.insert_users_list_by_id_uuid_pairs_skip_validation",
                return_value=0,
            ) as mock_insert,
        ):
            yield mock_insert

    @parameterized.expand(
        [
            ("running_with_marker", "running", True, True),
            ("running_without_marker", "running", False, False),
            ("draft_with_marker", "draft", True, False),
            ("stopped_with_marker", "stopped", True, False),
            # Paused takes precedence: a deactivated flag serves no one, so "frozen" would
            # misdescribe the experiment and hide the pause/resume lifecycle in the UI.
            ("paused_with_marker", "paused", True, False),
        ]
    )
    def test_is_exposure_frozen_property(self, _name: str, state: str, marker: bool, expected: bool) -> None:
        if state == "draft":
            experiment = self._create_launchable_experiment(name="Exp Frozen Draft", feature_flag_key=f"ef-{_name}")
        elif state == "stopped":
            experiment = self._create_ended_experiment(name="Exp Frozen Stopped", feature_flag_key=f"ef-{_name}")
        else:
            experiment = self._create_running_experiment(name="Exp Frozen Running", feature_flag_key=f"ef-{_name}")

        if state == "paused":
            flag = experiment.feature_flag
            flag.active = False
            flag.save()

        if marker:
            self._stamp_exposure_frozen_marker(experiment.feature_flag)

        experiment.refresh_from_db()
        assert experiment.is_exposure_frozen is expected

    def test_freeze_exposure_success(self):
        experiment = self._create_running_experiment(name="Freeze Exposure", feature_flag_key="freeze-exposure-flag")
        original_variants = deepcopy(experiment.feature_flag.filters["multivariate"])

        with self._stub_freeze_population() as mock_insert:
            frozen = self._service().freeze_exposure(experiment, request=self._make_request())

        frozen.feature_flag.refresh_from_db()

        # A static snapshot cohort was created and populated synchronously from the exposed set,
        # fed the (person_id, uuid) pairs already resolved by the personless guard — the freeze
        # must not fetch the persons from personhog a second time.
        cohort = Cohort.objects.get(team=self.team, name='Exposure snapshot for experiment "Freeze Exposure"')
        assert cohort.is_static is True
        mock_insert.assert_called_once_with(
            [(1, "00000000-0000-0000-0000-000000000001")], team_id=self.team.id, raise_on_error=True
        )

        # The cohort condition + freeze key + marker note were AND'd into every release group.
        groups = frozen.feature_flag.filters["groups"]
        assert len(groups) >= 1
        for group in groups:
            assert {"key": "id", "type": "cohort", "value": cohort.id, "operator": "in"} in group["properties"]
            assert group[EXPOSURE_FROZEN_GROUP_KEY] is True
            assert group[EXPOSURE_FROZEN_COHORT_KEY] == cohort.id
            assert EXPOSURE_FROZEN_GROUP_MARKER in group["description"]

        # Variants left byte-for-byte unchanged so enrolled users keep their variant.
        assert frozen.feature_flag.filters["multivariate"] == original_variants

        # Metrics keep flowing — not ended.
        assert frozen.end_date is None
        assert frozen.is_running is True
        assert frozen.is_exposure_frozen is True

    def test_freeze_exposure_multi_group_flag(self):
        experiment = self._create_running_experiment(name="Freeze Multi", feature_flag_key="freeze-multi-flag")
        flag = experiment.feature_flag

        # A catch-all group plus an internal test-user group (heterogeneous, like real experiment flags).
        catch_all = {"properties": [], "rollout_percentage": 100}
        internal_group = {
            "properties": [{"key": "email", "value": "@posthog.com", "operator": "icontains", "type": "person"}],
            "rollout_percentage": 100,
            "description": "Internal test users",
        }
        self._update_flag_filters(flag, {**flag.filters, "groups": [catch_all, internal_group]})

        with self._stub_freeze_population():
            frozen = self._service().freeze_exposure(experiment, request=self._make_request())
        frozen.feature_flag.refresh_from_db()
        cohort = Cohort.objects.get(team=self.team, name='Exposure snapshot for experiment "Freeze Multi"')

        groups = frozen.feature_flag.filters["groups"]
        assert len(groups) == 2
        cohort_condition = {"key": "id", "type": "cohort", "value": cohort.id, "operator": "in"}

        # Catch-all group: only the cohort condition added; description is just the marker note.
        assert groups[0]["properties"] == [cohort_condition]
        assert groups[0]["rollout_percentage"] == 100
        assert groups[0][EXPOSURE_FROZEN_GROUP_KEY] is True
        assert groups[0]["description"] == EXPOSURE_FROZEN_GROUP_MARKER

        # Internal group: original property preserved, cohort condition appended last, and the
        # user-authored description survives with the marker note prepended.
        assert len(groups[1]["properties"]) == 2
        assert groups[1]["properties"][-1] == cohort_condition
        assert groups[1]["properties"][0]["key"] == "email"
        assert groups[1]["rollout_percentage"] == 100
        assert groups[1][EXPOSURE_FROZEN_GROUP_KEY] is True
        assert groups[1]["description"] == f"{EXPOSURE_FROZEN_GROUP_MARKER} Internal test users"

    @parameterized.expand(
        [
            ("draft", "not been launched"),
            ("stopped", "already ended"),
            ("paused", "freeze a paused"),
            ("already_frozen", "already frozen"),
            ("group_aggregated", "Group-aggregated"),
            ("deleted_flag", "has been deleted"),
            ("no_groups", "no release conditions"),
            # Holdout assignment and early-access enrollment (super_groups) are evaluated by the
            # flag matcher before release conditions, so narrowing the release groups to a cohort
            # cannot stop enrollment through them — freezing must be rejected, not silently partial.
            ("holdout_linked", "holdout"),
            ("flag_holdout", "holdout"),
            ("flag_holdout_groups_legacy", "holdout"),
            ("flag_super_groups", "early access"),
        ]
    )
    def test_freeze_exposure_guards_raise(self, state: str, expected_error: str):
        service = self._service()
        if state == "draft":
            experiment = self._create_launchable_experiment(name="FE Draft", feature_flag_key=f"fe-{state}-flag")
        elif state == "stopped":
            experiment = self._create_ended_experiment(name="FE Stopped", feature_flag_key=f"fe-{state}-flag")
        else:
            experiment = self._create_running_experiment(name="FE Running", feature_flag_key=f"fe-{state}-flag")

        if state == "paused":
            # Paused = running with the flag deactivated; freezing must be rejected.
            flag = experiment.feature_flag
            flag.active = False
            flag.save()
            experiment.refresh_from_db()
        elif state == "already_frozen":
            self._stamp_exposure_frozen_marker(experiment.feature_flag)
            experiment.refresh_from_db()
        elif state == "group_aggregated":
            flag = experiment.feature_flag
            flag.filters = {**flag.filters, "aggregation_group_type_index": 0}
            flag.save()
            experiment.refresh_from_db()
        elif state == "deleted_flag":
            flag = experiment.feature_flag
            flag.deleted = True
            flag.save()
            experiment.refresh_from_db()
        elif state == "no_groups":
            flag = experiment.feature_flag
            flag.filters = {**flag.filters, "groups": []}
            flag.save()
            experiment.refresh_from_db()
        elif state == "holdout_linked":
            holdout = ExperimentHoldout.objects.create(
                team=self.team,
                name="FE Holdout",
                filters=[{"properties": [], "rollout_percentage": 10, "variant": "holdout"}],
                created_by=self.user,
            )
            experiment.holdout = holdout
            experiment.save()
        elif state == "flag_holdout":
            flag = experiment.feature_flag
            flag.filters = {**flag.filters, "holdout": {"id": 123, "exclusion_percentage": 10}}
            flag.save()
            experiment.refresh_from_db()
        elif state == "flag_holdout_groups_legacy":
            flag = experiment.feature_flag
            flag.filters = {**flag.filters, "holdout_groups": [{"properties": [], "rollout_percentage": 10}]}
            flag.save()
            experiment.refresh_from_db()
        elif state == "flag_super_groups":
            flag = experiment.feature_flag
            flag.filters = {**flag.filters, "super_groups": [{"properties": [], "rollout_percentage": 100}]}
            flag.save()
            experiment.refresh_from_db()

        # Population stubbed so any state that (wrongly) passes the guards would freeze successfully
        # instead of failing later for an unrelated reason like an empty exposed set.
        with self._stub_freeze_population():
            with self.assertRaises(ValidationError) as ctx:
                service.freeze_exposure(experiment, request=self._make_request())
        assert expected_error.lower() in str(ctx.exception).lower()

    def test_flag_update_after_freeze_preserves_frozen_state(self):
        experiment = self._create_running_experiment(name="Freeze Then Edit", feature_flag_key="freeze-edit-flag")
        with self._stub_freeze_population():
            frozen = self._service().freeze_exposure(experiment, request=self._make_request())
        flag = frozen.feature_flag
        flag.refresh_from_db()

        # The frozen state rides on a non-schema group key, so it only survives as long as flag
        # validation keeps passing unknown group keys through. Pin that contract: an unrelated
        # flag edit sent the way the flag UI sends it — full filters payload included — must not
        # strip the freeze key. If this fails, someone added group-key whitelisting to
        # FeatureFlagSerializer and freezing needs a schema-level home for its state.
        edited_filters = deepcopy(flag.filters)
        edited_filters["groups"][0]["rollout_percentage"] = 50
        self._update_flag_filters(flag, edited_filters)

        frozen.refresh_from_db()
        assert flag.filters["groups"][0][EXPOSURE_FROZEN_GROUP_KEY] is True
        assert frozen.is_exposure_frozen is True

    def test_flag_update_adding_unstamped_group_reopens_exposure(self):
        experiment = self._create_running_experiment(name="Freeze Then Add Group", feature_flag_key="freeze-add-flag")
        with self._stub_freeze_population():
            frozen = self._service().freeze_exposure(experiment, request=self._make_request())
        flag = frozen.feature_flag
        flag.refresh_from_db()

        # Release groups are OR'd, so a manually-added group without the freeze stamp (and without the
        # snapshot-cohort condition) lets new users enroll again. Freezing stamps every group, so the
        # experiment must report unfrozen the moment one unstamped group exists — otherwise the badge
        # keeps saying "exposure frozen" while enrollment is actually open.
        edited_filters = deepcopy(flag.filters)
        edited_filters["groups"].append({"properties": [], "rollout_percentage": 100})
        self._update_flag_filters(flag, edited_filters)

        frozen.refresh_from_db()
        # The original group keeps its stamp — only the freshly added group is unstamped.
        assert flag.filters["groups"][0][EXPOSURE_FROZEN_GROUP_KEY] is True
        assert EXPOSURE_FROZEN_GROUP_KEY not in flag.filters["groups"][1]
        assert frozen.is_exposure_frozen is False

    @parameterized.expand(
        [
            ("timeout", ClickHouseQueryTimeOut),
            ("memory_limit", ClickHouseQueryMemoryLimitExceeded),
            ("estimated_too_long", ClickHouseEstimatedQueryExecutionTimeTooLong),
        ]
    )
    def test_freeze_exposure_rejects_when_scan_is_too_big(self, _name: str, exception_class: type[Exception]):
        experiment = self._create_running_experiment(
            name=f"Freeze {_name}", feature_flag_key=f"freeze-{_name}-flag".replace("_", "-")
        )
        original_filters = deepcopy(experiment.feature_flag.filters)

        # All three "scan too big" ClickHouse errors must map to a friendly 400, not a 500.
        with patch(
            "products.experiments.backend.experiment_service.execute_hogql_query",
            side_effect=exception_class(),
        ):
            with self.assertRaises(ValidationError) as ctx:
                self._service().freeze_exposure(experiment, request=self._make_request())
        assert "too much exposure data" in str(ctx.exception)

        # Nothing was created or changed when the exposed-set scan times out.
        assert not Cohort.objects.filter(team=self.team, is_static=True).exists()
        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.filters == original_filters
        assert experiment.is_exposure_frozen is False

    @patch("products.experiments.backend.experiment_service.FREEZE_EXPOSURE_MAX_EXPOSED_USERS", 2)
    def test_freeze_exposure_rejects_when_too_many_exposed_users(self):
        experiment = self._create_running_experiment(name="Freeze Toobig", feature_flag_key="freeze-toobig-flag")
        original_filters = deepcopy(experiment.feature_flag.filters)

        # Cap patched to 2; the scan returns 3 distinct persons → rejected before any cohort is created.
        with patch(
            "products.experiments.backend.experiment_service.execute_hogql_query",
            return_value=MagicMock(results=[["a"], ["b"], ["c"]]),
        ):
            with self.assertRaises(ValidationError) as ctx:
                self._service().freeze_exposure(experiment, request=self._make_request())
        assert "too many exposed users" in str(ctx.exception)

        assert not Cohort.objects.filter(team=self.team, is_static=True).exists()
        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.filters == original_filters
        assert experiment.is_exposure_frozen is False

    def test_freeze_exposure_deletes_orphan_cohort_on_flag_save_failure(self):
        experiment = self._create_running_experiment(name="Freeze Failure", feature_flag_key="freeze-failure-flag")
        original_filters = deepcopy(experiment.feature_flag.filters)
        static_cohorts_before = Cohort.objects.filter(team=self.team, is_static=True).count()

        # Any failure persisting the narrowed flag must not leave the snapshot cohort behind.
        with self._stub_freeze_population():
            with patch.object(FeatureFlagSerializer, "save", side_effect=ValidationError("boom")):
                with self.assertRaises(ValidationError):
                    self._service().freeze_exposure(experiment, request=self._make_request())

        # The orphaned snapshot cohort was cleaned up; the flag and experiment are untouched.
        assert Cohort.objects.filter(team=self.team, is_static=True).count() == static_cohorts_before
        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.filters == original_filters
        assert experiment.is_exposure_frozen is False

    def test_freeze_exposure_rejects_when_no_users_exposed(self):
        experiment = self._create_running_experiment(name="Freeze Empty", feature_flag_key="freeze-empty-flag")
        original_filters = deepcopy(experiment.feature_flag.filters)

        # An empty snapshot cohort ANDed into every release group would un-enroll every user with a
        # 200 response — the freeze must reject instead.
        with patch.object(ExperimentService, "_fetch_exposed_person_uuids", return_value=[]):
            with self.assertRaises(ValidationError) as ctx:
                self._service().freeze_exposure(experiment, request=self._make_request())
        assert "no users have been exposed" in str(ctx.exception).lower()

        assert not Cohort.objects.filter(team=self.team, is_static=True).exists()
        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.filters == original_filters
        assert experiment.is_exposure_frozen is False

    @parameterized.expand(
        [
            # 4 of 100 unresolvable: within the deletion-noise tolerance, the freeze proceeds.
            ("under_threshold", 4, False),
            # 6 of 100 unresolvable: a material personless share, the freeze must fail closed.
            ("over_threshold", 6, True),
        ]
    )
    def test_freeze_exposure_personless_share_guard(self, _name: str, unresolved: int, expect_rejection: bool):
        experiment = self._create_running_experiment(
            name=f"Freeze Personless {_name}", feature_flag_key=f"freeze-personless-{_name}"
        )
        uuids = [f"00000000-0000-0000-0000-{i:012d}" for i in range(100)]

        # Anonymous (personless) users have exposure events with a person_id but no person row, so
        # they can never match the snapshot cohort: a freeze whose exposed set is materially
        # personless would silently drop those users' variants and must be rejected instead.
        with (
            patch.object(ExperimentService, "_fetch_exposed_person_uuids", return_value=uuids),
            patch(
                "products.experiments.backend.experiment_service.get_person_ids_and_uuids_by_uuids",
                new=lambda team_id, batch: [
                    (index + 1, person_uuid) for index, person_uuid in enumerate(batch[unresolved:])
                ],
            ),
            patch(
                "products.cohorts.backend.models.cohort.Cohort.insert_users_list_by_id_uuid_pairs_skip_validation",
                return_value=0,
            ),
        ):
            if expect_rejection:
                with self.assertRaises(ValidationError) as ctx:
                    self._service().freeze_exposure(experiment, request=self._make_request())
                assert "anonymous or deleted" in str(ctx.exception)
                # Rejected before any snapshot was built: no cohort to clean up, flag untouched.
                assert not Cohort.objects.filter(team=self.team, is_static=True).exists()
                experiment.feature_flag.refresh_from_db()
                assert experiment.is_exposure_frozen is False
            else:
                frozen = self._service().freeze_exposure(experiment, request=self._make_request())
                assert frozen.is_exposure_frozen is True

    def test_freeze_exposure_fails_and_cleans_up_when_cohort_population_fails(self):
        experiment = self._create_running_experiment(name="Freeze Insert Fail", feature_flag_key="freeze-insert-flag")
        original_filters = deepcopy(experiment.feature_flag.filters)

        # A transient store failure mid-insert is swallowed by the cohort batching helper unless the
        # caller opts into raise_on_error. Fail the innermost batch write (not the public method) so
        # the real swallow path runs: the freeze must surface the failure and leave nothing behind,
        # never narrow the flag to a partially populated snapshot.
        with (
            patch.object(
                ExperimentService,
                "_fetch_exposed_person_uuids",
                return_value=["00000000-0000-0000-0000-000000000001"],
            ),
            patch(
                "products.experiments.backend.experiment_service.get_person_ids_and_uuids_by_uuids",
                new=lambda team_id, uuids: [(index + 1, person_uuid) for index, person_uuid in enumerate(uuids)],
            ),
            patch(
                "products.cohorts.backend.models.cohort.Cohort._insert_resolved_batch",
                side_effect=RuntimeError("clickhouse insert failed"),
            ),
        ):
            with self.assertRaises(RuntimeError):
                self._service().freeze_exposure(experiment, request=self._make_request())

        # The partially populated snapshot cohort was cleaned up; the flag and experiment are untouched.
        assert not Cohort.objects.filter(team=self.team, is_static=True).exists()
        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.filters == original_filters
        assert experiment.is_exposure_frozen is False

    def test_freeze_exposure_not_blocked_by_flag_approval_policy(self):
        experiment = self._create_running_experiment(name="Freeze Policy", feature_flag_key="freeze-policy-flag")

        # Flag approval policies are intentionally scoped to active/rollout_percentage changes.
        # Freezing exposure only edits group properties, so a flag-update approval policy must NOT
        # gate it — the freeze applies directly and no change request is raised.
        self.organization.available_product_features = [
            {"key": AvailableFeature.APPROVALS, "name": AvailableFeature.APPROVALS}
        ]
        self.organization.save()
        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.update",
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

        with self._stub_freeze_population():
            frozen = self._service().freeze_exposure(experiment, request=self._make_request())

        assert ChangeRequest.objects.filter(team=self.team).count() == 0
        frozen.feature_flag.refresh_from_db()
        assert frozen.is_exposure_frozen is True

    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_freeze_exposure_reports_analytics(self, mock_report: MagicMock):
        experiment = self._create_running_experiment(name="Freeze Analytics", feature_flag_key="freeze-analytics-flag")

        with self._stub_freeze_population():
            self._service().freeze_exposure(experiment, request=self._make_request())

        assert any(call.args[1] == "experiment exposure frozen" for call in mock_report.call_args_list)

    def test_pause_and_resume_frozen_experiment(self):
        experiment = self._create_running_experiment(name="Freeze Pause", feature_flag_key="freeze-pause-flag")
        with self._stub_freeze_population():
            frozen = self._service().freeze_exposure(experiment, request=self._make_request())
        assert frozen.status_label == "exposure_frozen"

        # Pausing a frozen experiment must not wedge it: with the flag deactivated nothing is
        # served, so "paused" (with a working Resume) is the truthful state — a sticky "frozen"
        # label would hide the Resume action and leave Pause 400-ing with "already paused".
        paused = self._service().pause_experiment(frozen, request=self._make_request())
        assert paused.is_exposure_frozen is False
        assert paused.status_label == "paused"

        # The freeze stamps survive the roundtrip: resuming lands back in frozen, not running.
        resumed = self._service().resume_experiment(paused, request=self._make_request())
        assert resumed.is_exposure_frozen is True
        assert resumed.status_label == "exposure_frozen"

    def test_freeze_exposure_retains_cohort_and_second_freeze_raises(self):
        experiment = self._create_running_experiment(name="Freeze Retain", feature_flag_key="freeze-retain-flag")

        with self._stub_freeze_population():
            self._service().freeze_exposure(experiment, request=self._make_request())
            experiment.refresh_from_db()

            cohort = Cohort.objects.get(team=self.team, name='Exposure snapshot for experiment "Freeze Retain"')
            filters_after_first = deepcopy(experiment.feature_flag.filters)

            with self.assertRaises(ValidationError) as ctx:
                self._service().freeze_exposure(experiment, request=self._make_request())
            assert "already frozen" in str(ctx.exception)

        # The snapshot cohort and frozen flag state are left intact (non-destructive).
        assert Cohort.objects.filter(pk=cohort.pk).exists()
        experiment.feature_flag.refresh_from_db()
        assert experiment.feature_flag.filters == filters_after_first

    @parameterized.expand(
        [
            ("concurrently_frozen", "already frozen"),
            ("flag_deleted", "has been deleted"),
            ("experiment_ended", "already ended"),
        ]
    )
    def test_freeze_exposure_rechecks_state_under_lock_and_cleans_up(self, race: str, expected_error: str):
        experiment = self._create_running_experiment(name=f"Freeze Race {race}", feature_flag_key=f"fr-{race}-flag")
        flag_id = experiment.feature_flag_id

        # The exposure scan + cohort build take long enough for another request to land in between.
        # Simulate that writer committing mid-scan: the guards must be re-run against the fresh rows
        # under the flag lock, and a failed freeze must clean up its own snapshot cohort.
        def concurrent_change_then_return(_experiment: Experiment) -> list[str]:
            if race == "concurrently_frozen":
                self._stamp_exposure_frozen_marker(FeatureFlag.objects.get(pk=flag_id))
            elif race == "flag_deleted":
                FeatureFlag.objects.filter(pk=flag_id).update(deleted=True)
            else:
                Experiment.objects.filter(pk=experiment.pk).update(end_date=timezone.now())
            return ["00000000-0000-0000-0000-000000000001"]

        with (
            patch.object(ExperimentService, "_fetch_exposed_person_uuids", side_effect=concurrent_change_then_return),
            patch(
                "products.experiments.backend.experiment_service.get_person_ids_and_uuids_by_uuids",
                new=lambda team_id, uuids: [(index + 1, person_uuid) for index, person_uuid in enumerate(uuids)],
            ),
            patch(
                "products.cohorts.backend.models.cohort.Cohort.insert_users_list_by_id_uuid_pairs_skip_validation",
                return_value=0,
            ),
        ):
            with self.assertRaises(ValidationError) as ctx:
                self._service().freeze_exposure(experiment, request=self._make_request())
        assert expected_error in str(ctx.exception)

        # The orphaned snapshot cohort was cleaned up and the flag was never narrowed to it.
        assert not Cohort.objects.filter(team=self.team, is_static=True).exists()
        flag = FeatureFlag.objects_including_soft_deleted.get(pk=flag_id)
        for group in flag.filters.get("groups", []):
            assert EXPOSURE_FROZEN_COHORT_KEY not in group

    def test_freeze_exposure_applies_to_filters_edited_during_snapshot_build(self):
        experiment = self._create_running_experiment(name="Freeze Race Edit", feature_flag_key="freeze-race-edit-flag")
        flag = experiment.feature_flag
        edited_filters = deepcopy(flag.filters)
        edited_filters["groups"] = [
            {
                "properties": [{"key": "email", "value": "@posthog.com", "operator": "icontains", "type": "person"}],
                "rollout_percentage": 50,
            }
        ]

        # A flag edit committing while the (slow) exposure scan runs must not be clobbered by a
        # transform computed from the pre-scan filters — the freeze must narrow the fresh groups.
        def concurrent_edit_then_return(_experiment: Experiment) -> list[str]:
            FeatureFlag.objects.filter(pk=flag.pk).update(filters=edited_filters)
            return ["00000000-0000-0000-0000-000000000001"]

        with (
            patch.object(ExperimentService, "_fetch_exposed_person_uuids", side_effect=concurrent_edit_then_return),
            patch(
                "products.experiments.backend.experiment_service.get_person_ids_and_uuids_by_uuids",
                new=lambda team_id, uuids: [(index + 1, person_uuid) for index, person_uuid in enumerate(uuids)],
            ),
            patch(
                "products.cohorts.backend.models.cohort.Cohort.insert_users_list_by_id_uuid_pairs_skip_validation",
                return_value=0,
            ),
        ):
            frozen = self._service().freeze_exposure(experiment, request=self._make_request())

        cohort = Cohort.objects.get(team=self.team, name='Exposure snapshot for experiment "Freeze Race Edit"')
        frozen.feature_flag.refresh_from_db()
        groups = frozen.feature_flag.filters["groups"]
        assert len(groups) == 1
        # The concurrent edit's condition and rollout survive, with the freeze ANDed on top.
        assert groups[0]["rollout_percentage"] == 50
        assert {"key": "email", "value": "@posthog.com", "operator": "icontains", "type": "person"} in groups[0][
            "properties"
        ]
        assert {"key": "id", "type": "cohort", "value": cohort.id, "operator": "in"} in groups[0]["properties"]
        assert groups[0][EXPOSURE_FROZEN_GROUP_KEY] is True

    # ------------------------------------------------------------------
    # Unfreeze exposure
    # ------------------------------------------------------------------

    def test_unfreeze_exposure_restores_original_filters(self) -> None:
        experiment = self._create_running_experiment(name="Unfreeze Test", feature_flag_key="unfreeze-flag")
        flag = experiment.feature_flag

        # Heterogeneous groups: one with a user-authored description, one bare.
        catch_all = {"properties": [], "rollout_percentage": 100}
        internal_group = {
            "properties": [{"key": "email", "value": "@posthog.com", "operator": "icontains", "type": "person"}],
            "rollout_percentage": 100,
            "description": "Internal test users",
        }
        self._update_flag_filters(flag, {**flag.filters, "groups": [catch_all, internal_group]})
        original_filters = deepcopy(flag.filters)

        with self._stub_freeze_population():
            frozen = self._service().freeze_exposure(experiment, request=self._make_request())
        frozen.feature_flag.refresh_from_db()
        cohort = Cohort.objects.get(team=self.team, name='Exposure snapshot for experiment "Unfreeze Test"')

        unfrozen = self._service().unfreeze_exposure(frozen, request=self._make_request())
        unfrozen.feature_flag.refresh_from_db()

        # The flag is byte-for-byte back to its pre-freeze state: cohort condition, freeze keys,
        # and marker note all removed; the user-authored description restored exactly.
        assert unfrozen.feature_flag.filters == original_filters
        assert unfrozen.is_exposure_frozen is False
        assert unfrozen.is_running is True
        assert unfrozen.end_date is None

        # The snapshot cohort is soft-deleted, not left as clutter.
        cohort.refresh_from_db()
        assert cohort.deleted is True

    def test_unfreeze_exposure_keeps_user_edits_made_while_frozen(self) -> None:
        experiment = self._create_running_experiment(name="Unfreeze Edits", feature_flag_key="unfreeze-edits-flag")

        with self._stub_freeze_population():
            frozen = self._service().freeze_exposure(experiment, request=self._make_request())
        flag = frozen.feature_flag
        flag.refresh_from_db()

        # While frozen, a user adds their own condition to the frozen group. The group keeps its
        # freeze stamp, so the experiment stays frozen and can still be unfrozen. (Adding a brand-new
        # unstamped group instead reopens enrollment and reverts the experiment to "running" — see
        # test_flag_update_adding_unstamped_group_reopens_exposure.)
        edited = deepcopy(flag.filters)
        user_condition = {"key": "email", "value": "@posthog.com", "operator": "icontains", "type": "person"}
        edited["groups"][0]["properties"].append(user_condition)
        self._update_flag_filters(flag, edited)

        unfrozen = self._service().unfreeze_exposure(frozen, request=self._make_request())
        unfrozen.feature_flag.refresh_from_db()

        groups = unfrozen.feature_flag.filters["groups"]
        assert len(groups) == 1
        # Only the snapshot-cohort condition was removed from the frozen group — the user's stays.
        assert groups[0]["properties"] == [user_condition]
        assert EXPOSURE_FROZEN_GROUP_KEY not in groups[0]

    def test_unfreeze_exposure_when_not_frozen_raises(self) -> None:
        experiment = self._create_running_experiment(name="UF Not Frozen", feature_flag_key="uf-not-frozen-flag")

        with self.assertRaises(ValidationError) as ctx:
            self._service().unfreeze_exposure(experiment, request=self._make_request())
        assert "not frozen" in str(ctx.exception)

    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_unfreeze_exposure_reports_analytics(self, mock_report: MagicMock) -> None:
        experiment = self._create_running_experiment(name="Unfreeze Analytics", feature_flag_key="uf-analytics-flag")

        with self._stub_freeze_population():
            frozen = self._service().freeze_exposure(experiment, request=self._make_request())
        self._service().unfreeze_exposure(frozen, request=self._make_request())

        assert any(call.args[1] == "experiment exposure unfrozen" for call in mock_report.call_args_list)

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

    @parameterized.expand(
        [
            ("running_frozen",),
            ("stopped_frozen",),
        ]
    )
    def test_reset_experiment_clears_freeze(self, state: str):
        experiment = self._create_running_experiment(name=f"Reset {state}", feature_flag_key=f"reset-{state}-flag")
        original_groups = deepcopy(experiment.feature_flag.filters["groups"])

        with self._stub_freeze_population():
            frozen = self._service().freeze_exposure(experiment, request=self._make_request())
        cohort = Cohort.objects.get(team=self.team, name=f'Exposure snapshot for experiment "Reset {state}"')
        if state == "stopped_frozen":
            # Ending intentionally leaves the flag untouched, so the stamps are still on the
            # groups even though the stopped experiment no longer reports exposure_frozen —
            # reset must strip them regardless, or the relaunch is born frozen.
            self._service().end_experiment(frozen, request=self._make_request())

        reset = self._service().reset_experiment(frozen, request=self._make_request())

        # A re-launched experiment must start fresh: left frozen against the stale snapshot,
        # it could never enroll anyone.
        assert reset.is_draft
        reset.feature_flag.refresh_from_db()
        assert reset.feature_flag.filters["groups"] == original_groups
        cohort.refresh_from_db()
        assert cohort.deleted is True

    @parameterized.expand(
        [
            ("referenced_by_another_flag", 'Exposure snapshot for experiment "Victim"'),
            ("not_a_snapshot_name", "Payment-tier customers"),
        ]
    )
    def test_reset_does_not_delete_stamped_foreign_cohorts(self, case: str, victim_name: str):
        experiment = self._create_running_experiment(name=f"Reset Stamp {case}", feature_flag_key=f"rs-{case}-flag")
        with self._stub_freeze_population():
            frozen = self._service().freeze_exposure(experiment, request=self._make_request())

        # The freeze stamps round-trip through the flag API, so a flag editor can point them at
        # any cohort. Cleanup must verify ownership instead of deleting whatever id is stamped.
        victim = Cohort.objects.create(team=self.team, name=victim_name, is_static=True, created_by=self.user)
        if case == "referenced_by_another_flag":
            FeatureFlag.objects.create(
                team=self.team,
                key=f"other-flag-{case}",
                created_by=self.user,
                active=True,
                filters={
                    "groups": [
                        {
                            "properties": [{"key": "id", "type": "cohort", "value": victim.pk, "operator": "in"}],
                            "rollout_percentage": 100,
                        }
                    ]
                },
            )
        flag = frozen.feature_flag
        tampered = deepcopy(flag.filters)
        tampered["groups"][0][EXPOSURE_FROZEN_COHORT_KEY] = victim.pk
        flag.filters = tampered
        flag.save()

        self._service().reset_experiment(frozen, request=self._make_request())

        victim.refresh_from_db()
        assert victim.deleted is False

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

    def test_ship_variant_running_experiment_default_preserves_groups(self):
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

        # Verify variant distribution flipped
        variants = shipped.feature_flag.filters["multivariate"]["variants"]
        assert any(v["key"] == "test" and v["rollout_percentage"] == 100 for v in variants)
        assert any(v["key"] == "control" and v["rollout_percentage"] == 0 for v in variants)

        # Default mode: existing groups preserved untouched, no catch-all prepended
        assert shipped.feature_flag.filters["groups"] == original_groups

    def test_ship_variant_running_experiment_release_to_everyone_prepends_catch_all(self):
        experiment = self._create_running_experiment(
            name="Ship Running Everyone", feature_flag_key="ship-running-everyone-flag"
        )

        assert experiment.is_running
        original_groups = experiment.feature_flag.filters.get("groups", [])

        shipped = self._service().ship_variant(
            experiment,
            variant_key="test",
            release_to_everyone=True,
            conclusion="won",
            request=self._make_request(),
        )

        shipped.refresh_from_db()
        shipped.feature_flag.refresh_from_db()

        assert shipped.is_stopped
        assert shipped.conclusion == "won"

        variants = shipped.feature_flag.filters["multivariate"]["variants"]
        assert any(v["key"] == "test" and v["rollout_percentage"] == 100 for v in variants)
        assert any(v["key"] == "control" and v["rollout_percentage"] == 0 for v in variants)

        # release_to_everyone: catch-all prepended; original groups preserved after it
        groups = shipped.feature_flag.filters["groups"]
        assert groups[0]["properties"] == []
        assert groups[0]["rollout_percentage"] == 100
        assert "Added automatically" in groups[0].get("description", "")
        assert groups[1:] == original_groups

    @parameterized.expand(
        [
            ("preserve_targeting", False),
            ("release_to_everyone", True),
        ]
    )
    def test_ship_variant_on_frozen_experiment_strips_freeze(self, _name: str, release_to_everyone: bool):
        experiment = self._create_running_experiment(
            name=f"Ship Frozen {_name}", feature_flag_key=f"ship-frozen-{_name}-flag"
        )
        flag = experiment.feature_flag

        # Heterogeneous groups (like real experiment flags) so the round-trip below proves the
        # freeze's cohort condition, structured keys, and description marker are all stripped
        # while user-authored properties and descriptions survive.
        catch_all = {"properties": [], "rollout_percentage": 100}
        internal_group = {
            "properties": [{"key": "email", "value": "@posthog.com", "operator": "icontains", "type": "person"}],
            "rollout_percentage": 100,
            "description": "Internal test users",
        }
        self._update_flag_filters(flag, {**flag.filters, "groups": [catch_all, internal_group]})
        original_groups = deepcopy(flag.filters["groups"])

        with self._stub_freeze_population():
            frozen = self._service().freeze_exposure(experiment, request=self._make_request())
        cohort = Cohort.objects.get(team=self.team, name=f'Exposure snapshot for experiment "Ship Frozen {_name}"')

        shipped = self._service().ship_variant(
            frozen,
            variant_key="test",
            release_to_everyone=release_to_everyone,
            request=self._make_request(),
        )
        shipped.feature_flag.refresh_from_db()

        groups = shipped.feature_flag.filters["groups"]
        if release_to_everyone:
            assert groups[0]["properties"] == []
            assert groups[0]["rollout_percentage"] == 100
            # The frozen snapshot condition below the catch-all is stripped, not left as dead weight.
            assert groups[1:] == original_groups
        else:
            # Shipping ends the enrollment freeze: the winner reaches the original audience, not
            # just the stale snapshot cohort.
            assert groups == original_groups

        # The snapshot cohort is no longer referenced by anything the freeze created — cleaned up.
        cohort.refresh_from_db()
        assert cohort.deleted is True

    def test_ship_variant_on_frozen_experiment_keeps_cohort_when_flag_save_fails(self):
        experiment = self._create_running_experiment(name="Ship Frozen Fail", feature_flag_key="ship-frozen-fail-flag")
        with self._stub_freeze_population():
            frozen = self._service().freeze_exposure(experiment, request=self._make_request())
        cohort = Cohort.objects.get(team=self.team, name='Exposure snapshot for experiment "Ship Frozen Fail"')
        filters_when_frozen = deepcopy(frozen.feature_flag.filters)

        # If persisting the shipped flag fails (e.g. ApprovalRequired surfacing as a 409), the flag
        # is still frozen and serving from the snapshot — the cohort must not be deleted from under it.
        with patch.object(FeatureFlagSerializer, "save", side_effect=ValidationError("boom")):
            with self.assertRaises(ValidationError):
                self._service().ship_variant(frozen, variant_key="test", request=self._make_request())

        cohort.refresh_from_db()
        assert cohort.deleted is not True
        frozen.feature_flag.refresh_from_db()
        assert frozen.feature_flag.filters == filters_when_frozen
        assert frozen.is_exposure_frozen is True

    def test_ship_variant_default_preserves_scoped_release_condition(self):
        experiment = self._create_running_experiment(name="Ship Scoped", feature_flag_key="ship-scoped-flag")

        # Replace flag groups with a scoped release condition (e.g. only EU users)
        flag = experiment.feature_flag
        scoped_group = {
            "properties": [{"key": "country", "value": "EU", "operator": "exact", "type": "person"}],
            "rollout_percentage": 100,
        }
        updated_filters = {**flag.filters, "groups": [scoped_group]}
        serializer = FeatureFlagSerializer(
            flag,
            data={"filters": updated_filters},
            partial=True,
            context={
                "request": self._make_request(),
                "team_id": self.team.id,
                "project_id": self.team.project_id,
            },
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        flag.refresh_from_db()
        original_groups = flag.filters["groups"]

        shipped = self._service().ship_variant(experiment, variant_key="test", request=self._make_request())
        shipped.feature_flag.refresh_from_db()

        # Scoping is preserved exactly — no catch-all destroys it
        assert shipped.feature_flag.filters["groups"] == original_groups

    def test_ship_variant_default_preserves_variant_override(self):
        experiment = self._create_running_experiment(name="Ship Override", feature_flag_key="ship-override-flag")

        # Add a release condition with a variant override (force a cohort to "control")
        flag = experiment.feature_flag
        override_group = {
            "properties": [{"key": "email", "value": "qa@example.com", "operator": "exact", "type": "person"}],
            "rollout_percentage": 100,
            "variant": "control",
        }
        existing_groups = flag.filters.get("groups", [])
        updated_filters = {**flag.filters, "groups": [override_group, *existing_groups]}
        serializer = FeatureFlagSerializer(
            flag,
            data={"filters": updated_filters},
            partial=True,
            context={
                "request": self._make_request(),
                "team_id": self.team.id,
                "project_id": self.team.project_id,
            },
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        flag.refresh_from_db()
        original_groups = flag.filters["groups"]

        # Ship "test" without release_to_everyone — the QA override to "control" must survive
        shipped = self._service().ship_variant(experiment, variant_key="test", request=self._make_request())
        shipped.feature_flag.refresh_from_db()

        groups = shipped.feature_flag.filters["groups"]
        assert groups == original_groups
        assert groups[0]["variant"] == "control"

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

        # Verify variant_key and release_to_everyone in shipped event metadata
        shipped_call = next(
            call for call in mock_report_user_action.call_args_list if call.args[1] == "experiment variant shipped"
        )
        assert shipped_call.args[2]["variant_key"] == "test"
        # Default behavior: release_to_everyone is False
        assert shipped_call.args[2]["release_to_everyone"] is False

    @patch("products.experiments.backend.experiment_service.report_user_action")
    def test_ship_variant_release_to_everyone_recorded_in_analytics(self, mock_report_user_action):
        experiment = self._create_running_experiment(
            name="Ship Analytics Everyone", feature_flag_key="ship-analytics-everyone-flag"
        )

        self._service().ship_variant(
            experiment, variant_key="test", release_to_everyone=True, request=self._make_request()
        )

        shipped_call = next(
            call for call in mock_report_user_action.call_args_list if call.args[1] == "experiment variant shipped"
        )
        assert shipped_call.args[2]["release_to_everyone"] is True

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

    def test_transform_filters_default_preserves_groups(self):
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

        # Variant distribution flipped
        assert result["multivariate"]["variants"] == [
            {"key": "control", "name": "Control Group", "rollout_percentage": 0},
            {"key": "test", "name": "Test Variant", "rollout_percentage": 100},
        ]
        # Groups preserved exactly — no catch-all prepended in default mode
        assert result["groups"] == current_filters["groups"]
        assert result["payloads"] == {}
        assert result["aggregation_group_type_index"] is None

    def test_transform_filters_release_to_everyone_prepends_catch_all(self):
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

        result = ExperimentService._transform_filters_for_winning_variant(
            current_filters, "test", release_to_everyone=True
        )

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

    def test_transform_filters_default_does_not_mutate_input(self):
        """Defensive: ensure the function returns a new groups list without mutating caller's filters."""
        original_groups = [{"properties": [], "rollout_percentage": 50}]
        current_filters = {
            "groups": original_groups,
            "multivariate": {
                "variants": [
                    {"key": "control", "rollout_percentage": 50},
                    {"key": "test", "rollout_percentage": 50},
                ]
            },
        }

        result = ExperimentService._transform_filters_for_winning_variant(current_filters, "test")

        # Caller's list reference is untouched
        assert current_filters["groups"] is original_groups
        # Result's groups equals original by value but is a distinct list object
        assert result["groups"] == original_groups
        assert result["groups"] is not original_groups

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

        result = ExperimentService._transform_filters_for_winning_variant(
            current_filters, "control", release_to_everyone=True
        )

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
        from products.cohorts.backend.models.cohort import Cohort

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

    def test_get_timeseries_results_strips_step_sessions_and_emits_formatted_results(self):
        self._create_flag(key="ts-strip")
        service = self._service()
        now = timezone.now()
        start_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        end_midnight = start_midnight + timedelta(days=1)
        experiment = service.create_experiment(
            name="Strip",
            feature_flag_key="ts-strip",
            start_date=start_midnight,
            end_date=end_midnight,
        )

        session = {"event_uuid": "u", "person_id": "p", "session_id": "s", "timestamp": "t"}
        stored_payload = {
            "baseline": {
                "key": "control",
                "number_of_samples": 100,
                "sum": 5,
                "sum_squares": 5,
                "step_sessions": [[session]],
            },
            "variant_results": [
                {
                    "key": "test",
                    "method": "bayesian",
                    "number_of_samples": 110,
                    "sum": 8,
                    "sum_squares": 8,
                    "chance_to_win": 0.9,
                    "credible_interval": [0.01, 0.05],
                    "significant": True,
                    "step_sessions": [[session, session]],
                }
            ],
        }
        for day_offset in range(2):
            ExperimentMetricResult.objects.create(
                experiment=experiment,
                metric_uuid="m1",
                fingerprint="fp1",
                query_from=start_midnight + timedelta(days=day_offset),
                query_to=start_midnight + timedelta(days=day_offset + 1),
                status="completed",
                result=stored_payload,
                completed_at=now,
            )

        result = service.get_timeseries_results(experiment, metric_uuid="m1", fingerprint="fp1")

        for day_payload in result["timeseries"].values():
            if day_payload is None:
                continue
            assert "step_sessions" not in day_payload["baseline"]
            for variant in day_payload["variant_results"]:
                assert "step_sessions" not in variant

        # Stored row is untouched — stripping happens on read.
        stored = ExperimentMetricResult.objects.first()
        assert stored is not None
        assert stored.result is not None
        assert "step_sessions" in stored.result["baseline"]

        formatted = result["formatted_results"]
        assert "Method: bayesian" in formatted
        assert "Variants: control (baseline), test" in formatted
        assert "step_sessions" not in formatted

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
            ("paused", {"status": "paused"}, {"Paused"}),
            ("stopped", {"status": "stopped"}, {"Stopped"}),
            ("complete", {"status": "complete"}, {"Stopped"}),
            ("all", {"status": "all"}, {"Draft", "Running", "Paused", "Stopped"}),
            ("invalid", {"status": "bogus"}, {"Draft", "Running", "Paused", "Stopped"}),
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
        paused = service.create_experiment(
            name="Paused",
            feature_flag_key="status-paused",
            start_date=now - timedelta(days=2),
        )
        paused.feature_flag.active = False
        paused.feature_flag.save()
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
            # (name, format_filter, expected_names)
            ("json_list", lambda ids: json.dumps([ids[0], ids[1]]), {"Creator self", "Creator other"}),
            ("comma_separated", lambda ids: f"{ids[0]},{ids[2]}", {"Creator self", "Creator third"}),
            ("single_id", lambda ids: str(ids[1]), {"Creator other"}),
            ("no_match", lambda ids: json.dumps([ids[3]]), set()),
        ]
    )
    def test_filter_experiments_queryset_filters_by_multiple_created_by_ids(
        self, _name, format_filter, expected_names
    ) -> None:
        service = self._service()
        other_user = self._create_user("other-user@example.com")
        third_user = self._create_user("third-user@example.com")
        unrelated_user = self._create_user("unrelated-user@example.com")

        service.create_experiment(name="Creator self", feature_flag_key="created-by-self")
        ExperimentService(team=self.team, user=other_user).create_experiment(
            name="Creator other",
            feature_flag_key="created-by-other",
        )
        ExperimentService(team=self.team, user=third_user).create_experiment(
            name="Creator third",
            feature_flag_key="created-by-third",
        )

        ids = [self.user.id, other_user.id, third_user.id, unrelated_user.id]
        queryset = service.filter_experiments_queryset(
            Experiment.objects.filter(team=self.team),
            action="list",
            query_params={"created_by_id": format_filter(ids)},
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
            ("deleted", {"deleted": True}),
        ]
    )
    def test_update_experiment_with_legacy_metrics_allows_specific_fields(self, field_name: str, update_data: dict):
        """Test that experiments with legacy metrics can update name, description, end_date, and deleted."""
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
        elif field_name == "deleted":
            assert updated.deleted is True

    def test_update_experiment_with_legacy_metrics_restore_with_deleted_flag_raises(self):
        service = self._service()
        flag = self._create_flag(key="legacy-restore-flag")

        experiment = Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=flag,
            name="Legacy Experiment",
            metrics=[{"kind": "ExperimentTrendsQuery", "query": {}}],
            start_date=timezone.now(),
            deleted=True,
        )
        flag.deleted = True
        flag.save()

        with self.assertRaises(ValidationError) as ctx:
            service.update_experiment(experiment, {"deleted": False})

        assert "linked feature flag has been deleted" in str(ctx.exception)

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

    def test_create_with_rollout_only_variants_succeeds(self):
        """Variants carrying rollout_percentage (the flag's native shape) build the flag as-is."""
        service = self._service()
        experiment = service.create_experiment(
            name="Rollout only",
            feature_flag_key="rollout-only-flag",
            feature_flag_config={
                "filters": {
                    "multivariate": {
                        "variants": [
                            {"key": "control", "rollout_percentage": 50},
                            {"key": "test", "rollout_percentage": 50},
                        ]
                    }
                }
            },
        )
        assert [v["key"] for v in experiment.feature_flag.variants] == ["control", "test"]

    def test_duplicate_metric_uuids_within_list_are_regenerated(self):
        """Duplicate metric UUIDs within one list should be silently regenerated.

        First occurrence keeps the supplied uuid; later occurrences get fresh ones,
        and the ordering array is rewritten to match.
        """
        shared_uuid = "11bfb66a-51f5-48d0-a87e-bde2b4c958a6"
        service = self._service()
        experiment = service.create_experiment(
            name="Dup UUIDs",
            feature_flag_key="dup-uuid-flag",
            allow_unknown_events=True,
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": shared_uuid,
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": shared_uuid,
                    "source": {"kind": "EventsNode", "event": "other_event"},
                },
            ],
        )
        assert experiment.metrics is not None
        uuid_0 = experiment.metrics[0]["uuid"]
        uuid_1 = experiment.metrics[1]["uuid"]
        assert uuid_0 == shared_uuid
        assert uuid_1 != shared_uuid
        UUID(uuid_1)
        assert experiment.primary_metrics_ordered_uuids is not None
        assert set(experiment.primary_metrics_ordered_uuids) == {uuid_0, uuid_1}

    def test_duplicate_metric_uuids_across_primary_and_secondary_are_regenerated(self):
        """Cross-list collisions are deduped — secondary gets a fresh uuid."""
        shared_uuid = "11bfb66a-51f5-48d0-a87e-bde2b4c958a6"
        service = self._service()
        experiment = service.create_experiment(
            name="Dup UUIDs Cross",
            feature_flag_key="dup-uuid-cross-flag",
            allow_unknown_events=True,
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": shared_uuid,
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            ],
            metrics_secondary=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": shared_uuid,
                    "source": {"kind": "EventsNode", "event": "other_event"},
                },
            ],
        )
        assert experiment.metrics is not None
        assert experiment.metrics_secondary is not None
        primary_uuid = experiment.metrics[0]["uuid"]
        secondary_uuid = experiment.metrics_secondary[0]["uuid"]
        assert primary_uuid == shared_uuid
        assert secondary_uuid != shared_uuid
        UUID(secondary_uuid)

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

    def test_update_dedupes_metric_uuids_on_input(self):
        """Updating an experiment with duplicate uuids in the payload should regenerate the dups."""
        self._create_flag(key="dup-update-flag")
        service = self._service()
        experiment = service.create_experiment(
            name="To dedupe",
            feature_flag_key="dup-update-flag",
            allow_unknown_events=True,
        )
        shared_uuid = "11bfb66a-51f5-48d0-a87e-bde2b4c958a6"
        updated = service.update_experiment(
            experiment,
            {
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "uuid": shared_uuid,
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    },
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "uuid": shared_uuid,
                        "source": {"kind": "EventsNode", "event": "other_event"},
                    },
                ],
            },
            allow_unknown_events=True,
        )
        assert updated.metrics is not None
        uuid_0 = updated.metrics[0]["uuid"]
        uuid_1 = updated.metrics[1]["uuid"]
        assert uuid_0 == shared_uuid
        assert uuid_1 != shared_uuid
        UUID(uuid_1)

    def test_soft_delete_succeeds_when_stored_metrics_had_duplicate_uuids(self):
        """An experiment with corrupt (duplicated) uuids in storage should still be soft-deletable.

        Pre-migration data could have two metrics sharing one uuid in the DB. The
        post-migration code path should not block a soft-delete PATCH on that row.
        """
        self._create_flag(key="corrupt-soft-delete")
        service = self._service()
        experiment = service.create_experiment(
            name="Corrupt",
            feature_flag_key="corrupt-soft-delete",
            allow_unknown_events=True,
        )
        # Bypass the service to plant corrupt data, mirroring what legacy rows look like.
        shared_uuid = "22bfb66a-51f5-48d0-a87e-bde2b4c958a6"
        Experiment.objects.filter(id=experiment.id).update(
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": shared_uuid,
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": shared_uuid,
                    "source": {"kind": "EventsNode", "event": "other_event"},
                },
            ],
            primary_metrics_ordered_uuids=[shared_uuid, shared_uuid],
        )
        experiment.refresh_from_db()

        updated = service.update_experiment(experiment, {"deleted": True}, allow_unknown_events=True)
        assert updated.deleted is True

    def test_clone_regenerates_metric_uuids(self):
        """Cloning an experiment must produce metrics with fresh uuids — never shared with the source."""
        self._create_flag(key="clone-fresh-uuids")
        service = self._service()
        source = service.create_experiment(
            name="Source",
            feature_flag_key="clone-fresh-uuids",
            allow_unknown_events=True,
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
                    "source": {"kind": "EventsNode", "event": "other_event"},
                },
            ],
        )
        assert source.metrics is not None
        assert source.metrics_secondary is not None
        source_primary_uuid = source.metrics[0]["uuid"]
        source_secondary_uuid = source.metrics_secondary[0]["uuid"]

        dup = service.duplicate_experiment(source)

        assert dup.metrics is not None
        assert dup.metrics_secondary is not None
        dup_primary_uuid = dup.metrics[0]["uuid"]
        dup_secondary_uuid = dup.metrics_secondary[0]["uuid"]
        assert dup_primary_uuid != source_primary_uuid
        assert dup_secondary_uuid != source_secondary_uuid
        UUID(dup_primary_uuid)
        UUID(dup_secondary_uuid)
        # Ordering arrays should reference the new uuids, not the source ones.
        assert dup.primary_metrics_ordered_uuids == [dup_primary_uuid]
        assert dup.secondary_metrics_ordered_uuids == [dup_secondary_uuid]

    def test_dedup_regenerates_inline_uuids_that_collide_with_saved_metric_uuid(self):
        """When an inline metric reuses a saved-metric's uuid, dedup must regenerate
        the inline copy so each ordering entry resolves to exactly one thing.

        The saved-metric link is independent of the inline metrics array, but its
        uuid lives alongside inline-metric uuids in primary_metrics_ordered_uuids.
        An inline metric reusing the saved-metric uuid would make ordering ambiguous.
        """
        self._create_flag(key="dedup-with-saved")
        saved_metric_uuid = "33bfb66a-51f5-48d0-a87e-bde2b4c958a6"
        sm = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="SM with dup uuid",
            query={
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "uuid": saved_metric_uuid,
                "source": {"kind": "EventsNode", "event": "$pageview"},
            },
        )
        service = self._service()
        experiment = service.create_experiment(
            name="With Saved + Dup",
            feature_flag_key="dedup-with-saved",
            allow_unknown_events=True,
            saved_metrics_ids=[{"id": sm.id, "metadata": {"type": "primary"}}],
        )
        # Sanity: the saved-metric uuid is in the ordering.
        assert experiment.primary_metrics_ordered_uuids == [saved_metric_uuid]

        # Now the user sends an update with two inline metrics, both reusing the
        # saved-metric's uuid (the case where an LLM/frontend has inlined the
        # shared metric twice).
        updated = service.update_experiment(
            experiment,
            {
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "uuid": saved_metric_uuid,
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    },
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "uuid": saved_metric_uuid,
                        "source": {"kind": "EventsNode", "event": "other_event"},
                    },
                ],
            },
            allow_unknown_events=True,
        )
        # Both inline metrics get fresh uuids — neither shares the saved-metric uuid.
        assert updated.metrics is not None
        uuid_0 = updated.metrics[0]["uuid"]
        uuid_1 = updated.metrics[1]["uuid"]
        assert uuid_0 != saved_metric_uuid
        assert uuid_1 != saved_metric_uuid
        assert uuid_0 != uuid_1
        UUID(uuid_0)
        UUID(uuid_1)
        # The saved-metric uuid is still in ordering, plus both new inline uuids.
        assert updated.primary_metrics_ordered_uuids is not None
        assert saved_metric_uuid in updated.primary_metrics_ordered_uuids
        assert uuid_0 in updated.primary_metrics_ordered_uuids
        assert uuid_1 in updated.primary_metrics_ordered_uuids
        # The saved-metric link itself is untouched.
        assert list(updated.experimenttosavedmetric_set.values_list("saved_metric_id", flat=True)) == [sm.id]

    def test_create_regenerates_inline_uuid_that_collides_with_saved_metric_uuid(self):
        """Same protection on create: inline metric reusing a saved-metric uuid gets regenerated."""
        self._create_flag(key="create-dedup-with-saved")
        saved_metric_uuid = "55bfb66a-51f5-48d0-a87e-bde2b4c958a6"
        sm = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="SM",
            query={
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "uuid": saved_metric_uuid,
                "source": {"kind": "EventsNode", "event": "$pageview"},
            },
        )
        service = self._service()
        experiment = service.create_experiment(
            name="Create Dedup with Saved",
            feature_flag_key="create-dedup-with-saved",
            allow_unknown_events=True,
            saved_metrics_ids=[{"id": sm.id, "metadata": {"type": "primary"}}],
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "uuid": saved_metric_uuid,
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            ],
        )
        assert experiment.metrics is not None
        inline_uuid = experiment.metrics[0]["uuid"]
        assert inline_uuid != saved_metric_uuid
        UUID(inline_uuid)
        assert experiment.primary_metrics_ordered_uuids is not None
        assert saved_metric_uuid in experiment.primary_metrics_ordered_uuids
        assert inline_uuid in experiment.primary_metrics_ordered_uuids

    def test_clone_regenerates_uuids_even_when_source_uuid_matches_saved_metric(self):
        """Cloning regenerates inline metric uuids so they no longer collide with the
        saved metric's uuid carried by the cloned saved-metric link."""
        self._create_flag(key="clone-saved-collision")
        saved_metric_uuid = "44bfb66a-51f5-48d0-a87e-bde2b4c958a6"
        sm = ExperimentSavedMetric.objects.create(
            team=self.team,
            name="SM",
            query={
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "uuid": saved_metric_uuid,
                "source": {"kind": "EventsNode", "event": "$pageview"},
            },
        )
        service = self._service()
        source = service.create_experiment(
            name="With Saved + Inline Same UUID",
            feature_flag_key="clone-saved-collision",
            allow_unknown_events=True,
            saved_metrics_ids=[{"id": sm.id, "metadata": {"type": "primary"}}],
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "other_event"},
                },
            ],
        )
        assert source.metrics is not None
        source_inline_uuid = source.metrics[0]["uuid"]

        dup = service.duplicate_experiment(source)

        # Clone's inline metric has a fresh uuid.
        assert dup.metrics is not None
        dup_inline_uuid = dup.metrics[0]["uuid"]
        assert dup_inline_uuid != source_inline_uuid
        UUID(dup_inline_uuid)
        # Saved metric uuid (carried via the link in the clone) must still be in ordering.
        assert dup.primary_metrics_ordered_uuids is not None
        assert saved_metric_uuid in dup.primary_metrics_ordered_uuids
        assert dup_inline_uuid in dup.primary_metrics_ordered_uuids
        # Cloned saved-metric link points to the same saved metric (same team).
        assert list(dup.experimenttosavedmetric_set.values_list("saved_metric_id", flat=True)) == [sm.id]

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
            ("created_by",),
            ("-created_by",),
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

    def test_update_experiment_launch_via_start_date_with_deleted_flag_raises(self):
        """Launching a draft by PATCHing start_date must reject a deleted flag, like the launch action."""
        experiment = self._create_launchable_experiment(
            name="PATCH Launch Deleted Flag",
            feature_flag_key="patch-launch-deleted-flag",
        )
        experiment.feature_flag.deleted = True
        experiment.feature_flag.save()

        service = self._service()
        with self.assertRaises(ValidationError) as ctx:
            service.update_experiment(experiment, {"start_date": timezone.now()})
        assert "deleted" in str(ctx.exception.detail).lower()

        # The flag must not have been activated, and the experiment must stay a draft
        experiment.refresh_from_db()
        experiment.feature_flag.refresh_from_db()
        assert experiment.start_date is None
        assert experiment.feature_flag.active is False

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

    def test_funnel_metric_with_empty_series_raises(self):
        # The experiment exposure event is prepended as step_0 at query time, so an
        # empty series would produce a degenerate single-step funnel with no conversion event.
        service = self._service()
        with self.assertRaises(ValidationError) as ctx:
            service.create_experiment(
                name="Empty Funnel",
                feature_flag_key="empty-funnel-flag",
                allow_unknown_events=True,
                metrics=[
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [],
                    },
                ],
            )
        assert "at least one step" in str(ctx.exception)

    @parameterized.expand(
        [
            ("primary", "metrics"),
            ("secondary", "metrics_secondary"),
        ]
    )
    def test_update_experiment_rejects_empty_funnel_series(self, _name, field):
        experiment = self._create_draft_experiment()
        service = self._service()
        with self.assertRaises(ValidationError):
            service.update_experiment(
                experiment,
                {
                    field: [
                        {
                            "kind": "ExperimentMetric",
                            "metric_type": "funnel",
                            "series": [],
                        }
                    ],
                },
                allow_unknown_events=True,
            )

    @parameterized.expand(
        [
            (
                "single_step",
                [{"kind": "EventsNode", "event": "$pageview"}],
            ),
            (
                "two_steps",
                [
                    {"kind": "EventsNode", "event": "$pageview"},
                    {"kind": "EventsNode", "event": "$pageleave"},
                ],
            ),
        ]
    )
    def test_funnel_metric_with_valid_series_succeeds(self, name, series):
        # Single-step series is valid: the exposure event is prepended as step_0 at query
        # time, yielding a standard conversion-rate funnel (exposure → event).
        flag_key = f"valid-funnel-flag-{name.replace('_', '-')}"
        self._create_flag(key=flag_key)
        service = self._service()
        experiment = service.create_experiment(
            name=f"Valid Funnel {name}",
            feature_flag_key=flag_key,
            allow_unknown_events=True,
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "funnel",
                    "series": series,
                },
            ],
        )
        assert experiment.metrics is not None and len(experiment.metrics) == 1
        assert experiment.metrics[0]["metric_type"] == "funnel"

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

    # Shared cases for blank/whitespace event regression tests across create and update.
    # Regression: pydantic permits event="" but it's not a queryable event name.
    # Treat blank/whitespace events like None / "All events" instead of producing
    # the misleading "Event(s) '' not found" error customers were hitting.
    _BLANK_EVENT_CASES = [
        (
            "empty_mean",
            {
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "EventsNode", "event": ""},
            },
        ),
        (
            "whitespace_ratio",
            {
                "kind": "ExperimentMetric",
                "metric_type": "ratio",
                "numerator": {"kind": "EventsNode", "event": "   "},
                "denominator": {"kind": "EventsNode", "event": ""},
            },
        ),
        (
            "empty_funnel_step",
            {
                "kind": "ExperimentMetric",
                "metric_type": "funnel",
                "series": [{"kind": "EventsNode", "event": ""}],
            },
        ),
    ]

    @parameterized.expand(_BLANK_EVENT_CASES)
    def test_blank_event_names_pass_validation_on_create(self, name: str, metric: dict) -> None:
        service = self._service()
        experiment = service.create_experiment(
            name=f"Blank Event Create {name}",
            feature_flag_key=f"blank-event-create-{name.replace('_', '-')}-flag",
            metrics=[metric],
        )
        assert experiment.metrics is not None and len(experiment.metrics) == 1

    @parameterized.expand(_BLANK_EVENT_CASES)
    def test_blank_event_names_pass_validation_on_update(self, name: str, metric: dict) -> None:
        service = self._service()
        experiment = service.create_experiment(
            name=f"Blank Event Update {name}",
            feature_flag_key=f"blank-event-update-{name.replace('_', '-')}-flag",
        )
        # Should not raise — both paths share the same validator but go through
        # separate functions (create_experiment vs update_experiment).
        service.update_experiment(experiment, {"metrics": [metric]})

    @parameterized.expand(
        [
            ("int", 42, "int"),
            ("json_object", {"kind": "EventsNode", "event": "nested"}, "dict"),
            ("list", ["a", "b"], "list"),
        ]
    )
    def test_unexpected_event_shape_is_skipped_and_logged(
        self, _: str, malformed_event: object, expected_type_name: str
    ) -> None:
        # Pydantic should reject anything other than str/None for the `event` field
        # in the incoming payload. If a malformed payload (e.g. int, dict, list)
        # bypasses that check, we want to skip the value (don't crash, don't add a
        # non-string to the lookup set) and log so we can find the offending caller.
        # This is purely about the *incoming* payload shape — no DB lookup happens
        # in `_extract_entity_nodes`.
        from products.experiments.backend.experiment_service import logger as service_logger

        service = self._service()
        with patch.object(service_logger, "warning") as mock_warning:
            event_names = service._extract_entity_nodes(
                [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": malformed_event},
                    },
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    },
                ]
            )[0]

        # Malformed value was skipped, "$pageview" kept
        assert event_names == {"$pageview"}
        mock_warning.assert_called_once()
        kwargs = mock_warning.call_args.kwargs
        assert kwargs.get("event_type") == expected_type_name

    def test_event_validation_uses_project_scope(self):
        # Regression: the frontend event picker queries EventDefinition by project_id
        # (see posthog/api/event_definition.py), so users in multi-team projects see
        # events ingested by sibling teams. Validation must match that scope or it
        # rejects legitimate selections (e.g. "$pageview not found" reports).
        sibling_team = Team.objects.create(
            organization=self.organization,
            project=self.project,
            name="Sibling team in same project",
        )
        EventDefinition.objects.create(team=sibling_team, project=self.project, name="purchase_v2")
        # Note: NOT creating purchase_v2 on self.team — only the sibling team has it,
        # but they share a project so the picker would show it.

        service = self._service()
        experiment = service.create_experiment(
            name="Cross-team Event",
            feature_flag_key="cross-team-event-flag",
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "purchase_v2"},
                },
            ],
        )
        assert experiment.metrics is not None and len(experiment.metrics) == 1

    def test_sibling_team_can_use_legacy_primary_team_event(self):
        # Regression: the legacy fallback in validate_metric_event_names uses
        #     team_id = project_id  (NOT team_id = self.team.id)
        # because legacy EventDefinitions (project_id IS NULL) belong to the
        # *primary* team — and by convention, primary_team.id == project.id.
        # The picker mirrors this exact predicate (posthog/api/event_definition.py),
        # so a sibling-team user must be able to validate against legacy events
        # tied to the primary team. Swapping `team_id = project_id` for
        # `team_id = self.team.id` would silently exclude those rows for sibling
        # teams, even though the picker shows them.
        primary_team = self.team  # APIBaseTest sets primary_team.id == project.id
        assert primary_team.id == primary_team.project_id, "test fixture invariant: self.team is primary"

        sibling_team = Team.objects.create(
            organization=self.organization,
            project=self.project,
            name="Sibling team in same project",
        )
        # A legacy event tied to the primary team — no project_id set.
        EventDefinition.objects.create(team=primary_team, project=None, name="legacy_event")

        # Run validation as the SIBLING team (not the primary). Without the
        # legacy fallback's team_id=project_id semantics, this would raise.
        sibling_service = ExperimentService(team=sibling_team, user=self.user)
        experiment = sibling_service.create_experiment(
            name="Sibling Legacy Event",
            feature_flag_key="sibling-legacy-event-flag",
            metrics=[
                {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "legacy_event"},
                },
            ],
        )
        assert experiment.metrics is not None and len(experiment.metrics) == 1

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

    VARIANT_KEYS = ["control", "test"]

    @parameterized.expand(
        [
            ("valid_baseline_control", {"baseline_variant_key": "control"}, VARIANT_KEYS, False),
            ("valid_baseline_test", {"baseline_variant_key": "test"}, VARIANT_KEYS, False),
            ("unknown_baseline", {"baseline_variant_key": "nonexistent"}, VARIANT_KEYS, True),
            ("baseline_absent", {"method": "bayesian"}, VARIANT_KEYS, False),
            ("none_stats_config", None, VARIANT_KEYS, False),
            ("empty_stats_config", {}, VARIANT_KEYS, False),
            ("unknown_baseline_no_variant_keys", {"baseline_variant_key": "nonexistent"}, None, False),
            ("unknown_baseline_empty_variant_keys", {"baseline_variant_key": "nonexistent"}, [], False),
        ]
    )
    def test_validate_stats_config_baseline_variant_key(
        self,
        _name: str,
        stats_config: dict | None,
        variant_keys: list[str] | None,
        expect_error: bool,
    ) -> None:
        if expect_error:
            with self.assertRaises(ValidationError):
                ExperimentService.validate_stats_config(stats_config, variant_keys)
        else:
            ExperimentService.validate_stats_config(stats_config, variant_keys)

    def test_create_experiment_validates_baseline_against_resolved_default_variants(self) -> None:
        service = self._service()

        # No parameters.feature_flag_variants supplied: the new flag falls back to
        # DEFAULT_VARIANTS (control/test), so a baseline that isn't one must be rejected.
        with self.assertRaises(ValidationError):
            service.create_experiment(
                name="Bad baseline new flag",
                feature_flag_key="baseline-default-variants",
                stats_config={"baseline_variant_key": "nonexistent"},
            )
        assert not FeatureFlag.objects.filter(key="baseline-default-variants", team_id=self.team.id).exists()

    def test_create_experiment_validates_baseline_against_existing_flag_variants(self) -> None:
        self._create_flag(
            key="baseline-existing-flag",
            variants=[
                {"key": "control", "name": "Control", "rollout_percentage": 50},
                {"key": "variant-a", "name": "Variant A", "rollout_percentage": 50},
            ],
        )
        service = self._service()

        experiment = service.create_experiment(
            name="Existing flag baseline",
            feature_flag_key="baseline-existing-flag",
            stats_config={"baseline_variant_key": "variant-a"},
        )
        assert experiment.stats_config is not None
        assert experiment.stats_config["baseline_variant_key"] == "variant-a"

        with self.assertRaises(ValidationError):
            service.create_experiment(
                name="Existing flag bad baseline",
                feature_flag_key="baseline-existing-flag",
                stats_config={"baseline_variant_key": "test"},
            )

    def test_update_experiment_revalidates_baseline_when_variants_change(self) -> None:
        self._create_flag(
            key="baseline-update-flag",
            variants=[
                {"key": "control", "name": "Control", "rollout_percentage": 50},
                {"key": "test", "name": "Test", "rollout_percentage": 50},
            ],
        )
        service = self._service()
        experiment = service.create_experiment(
            name="Update baseline experiment",
            feature_flag_key="baseline-update-flag",
            stats_config={"baseline_variant_key": "test"},
        )

        # A variants-only edit that removes the current baseline ("test") must be rejected,
        # even though stats_config is absent from the update payload.
        with self.assertRaises(ValidationError):
            service.update_experiment(
                experiment,
                {},
                feature_flag_config={
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "control", "rollout_percentage": 50},
                                {"key": "variant-b", "rollout_percentage": 50},
                            ]
                        }
                    }
                },
            )


class TestValidateExcludedVariantKeys:
    _VARIANT_KEYS = {"control", "test-1", "test-2"}

    @pytest.mark.parametrize(
        "excluded_variants,baseline_key",
        [
            ([], "control"),
            (["test-2"], "control"),
            (["test-2", "test-2"], "control"),
        ],
    )
    def test_valid_excluded_variants(self, excluded_variants: list[str], baseline_key: str):
        ExperimentService._validate_excluded_variant_keys(excluded_variants, self._VARIANT_KEYS, baseline_key)

    @pytest.mark.parametrize(
        "excluded_variants,baseline_key,match",
        [
            (["does-not-exist"], "control", "unknown variants"),
            (["control"], "control", "baseline variant cannot be excluded"),
            (["holdout-42"], "control", "cannot exclude holdout"),
            (["test-1", "test-2"], "control", "at least one test variant"),
            (["test-1"], "test-1", "baseline variant cannot be excluded"),
        ],
    )
    def test_invalid_excluded_variants_raises(self, excluded_variants: list[str], baseline_key: str, match: str):
        with pytest.raises(ValidationError, match=match):
            ExperimentService._validate_excluded_variant_keys(excluded_variants, self._VARIANT_KEYS, baseline_key)


class TestValidateExcludedVariants:
    @pytest.mark.parametrize(
        "value",
        [
            None,
            [],
            ["test-2"],
            ["test-1", "test-2"],
        ],
    )
    def test_valid(self, value):
        ExperimentService.validate_excluded_variants(value)

    @pytest.mark.parametrize(
        "value",
        [
            "test-2",
            [123],
        ],
    )
    def test_invalid_raises(self, value):
        with pytest.raises(ValidationError, match="must be a list of strings"):
            ExperimentService.validate_excluded_variants(value)


@patch("posthoganalytics.feature_enabled", new=MagicMock(return_value=True))
class TestExperimentServiceWarehouseMetricAccess(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        self.membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        self.membership.level = OrganizationMembership.Level.MEMBER
        self.membership.save()

        credential = DataWarehouseCredential.objects.create(access_key="x", access_secret="x", team=self.team)
        self.table = DataWarehouseTable.objects.create(
            name="restricted_revenue",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            credential=credential,
            url_pattern="s3://bucket/restricted/*",
            columns={"id": "String"},
        )
        # Deny this member every warehouse object (warehouse_table inherits the warehouse_objects resource).
        AccessControl.objects.create(team=self.team, resource="warehouse_objects", access_level="none")

    def _dw_metric(self) -> dict:
        return {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "source": {
                "kind": "ExperimentDataWarehouseNode",
                "table_name": self.table.name,
                "events_join_key": "distinct_id",
                "data_warehouse_join_key": "id",
                "timestamp_field": "ds",
                "math": "total",
            },
        }

    def test_create_experiment_with_restricted_warehouse_metric_is_denied(self):
        service = ExperimentService(team=self.team, user=self.user)
        with pytest.raises(PermissionDenied):
            service.create_experiment(
                name="DW experiment",
                feature_flag_key="dw-create",
                metrics=[self._dw_metric()],
                allow_unknown_events=True,
            )

    def test_update_experiment_with_restricted_warehouse_metric_is_denied(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="dw-update",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        experiment = Experiment.objects.create(team=self.team, created_by=self.user, name="E", feature_flag=flag)
        service = ExperimentService(team=self.team, user=self.user)
        with pytest.raises(PermissionDenied):
            service.update_experiment(experiment, {"metrics": [self._dw_metric()]})

    def test_org_admin_can_author_restricted_warehouse_metric(self):
        self.membership.level = OrganizationMembership.Level.ADMIN
        self.membership.save()
        service = ExperimentService(team=self.team, user=self.user)
        experiment = service.create_experiment(
            name="DW experiment allowed",
            feature_flag_key="dw-allowed",
            metrics=[self._dw_metric()],
            allow_unknown_events=True,
        )
        assert experiment.metrics is not None
        assert len(experiment.metrics) == 1

    def test_attaching_saved_metric_on_restricted_table_is_denied(self):
        # A saved metric on the denied table (authored by someone with access) can't be smuggled in
        # by attaching it via saved_metrics_ids.
        saved_metric = ExperimentSavedMetric.objects.create(
            team=self.team,
            created_by=self.user,
            name="DW saved metric",
            query=self._dw_metric(),
        )
        service = ExperimentService(team=self.team, user=self.user)
        with pytest.raises(PermissionDenied):
            service.create_experiment(
                name="DW via saved metric",
                feature_flag_key="dw-saved",
                saved_metrics_ids=[{"id": saved_metric.id, "metadata": {"type": "primary"}}],
            )


class TestDeprecatedFieldsInRequest(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "deprecated_parameters_and_secondary_metrics",
                {
                    "parameters": {"feature_flag_variants": [{"key": "control"}], "rollout_percentage": 100},
                    "secondary_metrics": [{"kind": "x"}],
                },
                {
                    "experiment_create_deprecated_fields": ["parameters", "secondary_metrics"],
                    "experiment_create_deprecated_parameters_keys": ["feature_flag_variants", "rollout_percentage"],
                },
            ),
            (
                "new_feature_flag_object_is_not_deprecated",
                {"feature_flag": {"filters": {"multivariate": {}}}, "metrics": [{"kind": "x"}]},
                {"experiment_create_deprecated_fields": []},
            ),
            (
                "legacy_filters",
                {"filters": {"events": []}},
                {"experiment_create_deprecated_fields": ["filters"]},
            ),
            (
                "empty_parameters_not_counted",
                {"parameters": {}},
                {"experiment_create_deprecated_fields": []},
            ),
            (
                "parameters_with_only_non_deprecated_keys",
                {"parameters": {"variant_notes": {"control": "n"}}},
                {"experiment_create_deprecated_fields": ["parameters"]},
            ),
            (
                "non_dict_body",
                [1, 2, 3],
                {},
            ),
        ]
    )
    def test_detects_deprecated_fields(self, _name: str, body: Any, expected: dict[str, Any]) -> None:
        request = MagicMock()
        request.data = body
        assert _deprecated_fields_in_request(request) == expected

    def test_returns_empty_when_reading_body_raises(self) -> None:
        request = MagicMock()
        type(request).data = PropertyMock(side_effect=RuntimeError("stream consumed"))
        assert _deprecated_fields_in_request(request) == {}


class TestDeprecatedParametersKeysInRequest(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "deprecated_subset_sorted",
                {"parameters": {"rollout_percentage": 50, "feature_flag_variants": [], "variant_notes": {}}},
                ["feature_flag_variants", "rollout_percentage"],
            ),
            ("only_non_deprecated_keys", {"parameters": {"variant_notes": {"control": "n"}}}, []),
            ("parameters_not_a_dict", {"parameters": [1, 2]}, []),
            ("non_dict_body", [1, 2, 3], []),
        ]
    )
    def test_detects_deprecated_parameters_keys(self, _name: str, body: Any, expected: list[str]) -> None:
        request = MagicMock()
        request.data = body
        assert _deprecated_parameters_keys_in_request(request) == expected

    def test_returns_empty_when_reading_body_raises(self) -> None:
        request = MagicMock()
        type(request).data = PropertyMock(side_effect=RuntimeError("stream consumed"))
        assert _deprecated_parameters_keys_in_request(request) == []
