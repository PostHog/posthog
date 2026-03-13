"""Experiment service — single source of truth for experiment business logic."""

from copy import deepcopy
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Count, Prefetch, Q, QuerySet

import pydantic
from rest_framework.exceptions import ValidationError

from posthog.schema import ActionsNode, ExperimentEventExposureConfig, ExperimentMetric

from posthog.api.cohort import CohortSerializer
from posthog.api.feature_flag import FeatureFlagSerializer
from posthog.event_usage import EventSource, report_user_action
from posthog.hogql_queries.experiments.experiment_metric_fingerprint import compute_metric_fingerprint
from posthog.models.cohort import Cohort
from posthog.models.evaluation_context import FeatureFlagEvaluationContext
from posthog.models.experiment import (
    Experiment,
    ExperimentHoldout,
    ExperimentMetricResult,
    ExperimentSavedMetric,
    ExperimentTimeseriesRecalculation,
    holdout_filters_for_flag,
)
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.filters.filter import Filter
from posthog.models.team.team import Team

from ee.clickhouse.views.experiment_saved_metrics import ExperimentToSavedMetricSerializer

DEFAULT_ROLLOUT_PERCENTAGE = 100

DEFAULT_VARIANTS = [
    {"key": "control", "name": "Control Group", "rollout_percentage": 50},
    {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
]


class ExperimentService:
    """Single source of truth for experiment business logic."""

    VALID_METRIC_KINDS = {"ExperimentMetric", "ExperimentTrendsQuery", "ExperimentFunnelsQuery"}

    def __init__(self, team: Team, user: Any):
        self.team = team
        self.user = user

    @staticmethod
    def validate_experiment_date_range(start_date: datetime | None, end_date: datetime | None) -> None:
        """Validate experiment start/end date ordering."""
        if start_date and end_date and start_date >= end_date:
            raise ValidationError("End date must be after start date")

    @staticmethod
    def validate_experiment_parameters(parameters: dict | None) -> None:
        """Validate experiment parameters accepted by the API layer."""
        if not parameters:
            return

        variants = parameters.get("feature_flag_variants", [])

        if len(variants) >= 21:
            raise ValidationError("Feature flag variants must be less than 21")
        if len(variants) > 0:
            if len(variants) < 2:
                raise ValidationError(
                    "Feature flag must have at least 2 variants (control and at least one test variant)"
                )
            if "control" not in [variant["key"] for variant in variants]:
                raise ValidationError("Feature flag variants must contain a control variant")

    @staticmethod
    def validate_experiment_exposure_criteria(exposure_criteria: dict | None) -> None:
        """Validate experiment exposure criteria payloads."""
        if not exposure_criteria:
            return

        if "filterTestAccounts" in exposure_criteria and not isinstance(exposure_criteria["filterTestAccounts"], bool):
            raise ValidationError("filterTestAccounts must be a boolean")

        if "exposure_config" in exposure_criteria:
            exposure_config = exposure_criteria["exposure_config"]
            try:
                if exposure_config.get("kind") == "ActionsNode":
                    ActionsNode.model_validate(exposure_config)
                else:
                    ExperimentEventExposureConfig.model_validate(exposure_config)
            except Exception:
                raise ValidationError("Invalid exposure criteria")

    @classmethod
    def validate_experiment_metrics(cls, metrics: list | None) -> None:
        """Validate metric payloads accepted by the API layer."""
        if metrics is None:
            return

        if not isinstance(metrics, list):
            raise ValidationError("Metrics must be a list")

        for i, metric in enumerate(metrics):
            if not isinstance(metric, dict):
                raise ValidationError(f"Invalid metric at index {i}: must be a dict")

            kind = metric.get("kind")
            if kind not in cls.VALID_METRIC_KINDS:
                raise ValidationError(f"Invalid metric at index {i}: unknown kind '{kind}'")

            if kind == "ExperimentMetric":
                try:
                    ExperimentMetric.model_validate(metric)
                except pydantic.ValidationError as e:
                    raise ValidationError(f"Invalid metric at index {i}: {e.errors()}")

    @staticmethod
    def validate_saved_metrics_ids(saved_metrics_ids: list | None, team_id: int) -> None:
        """Validate saved metric references accepted by the API layer."""
        if saved_metrics_ids is None:
            return

        if not isinstance(saved_metrics_ids, list):
            raise ValidationError("Saved metrics must be a list")

        for saved_metric in saved_metrics_ids:
            if not isinstance(saved_metric, dict):
                raise ValidationError("Saved metric must be an object")
            if "id" not in saved_metric:
                raise ValidationError("Saved metric must have an id")
            if "metadata" in saved_metric and not isinstance(saved_metric["metadata"], dict):
                raise ValidationError("Metadata must be an object")
            if "metadata" in saved_metric and "type" not in saved_metric["metadata"]:
                raise ValidationError("Metadata must have a type key")

        saved_metrics = ExperimentSavedMetric.objects.filter(
            id__in=[saved_metric["id"] for saved_metric in saved_metrics_ids],
            team_id=team_id,
        )
        if saved_metrics.count() != len(saved_metrics_ids):
            raise ValidationError("Saved metric does not exist or does not belong to this project")

    @transaction.atomic
    def create_experiment(
        self,
        name: str,
        feature_flag_key: str,
        *,
        description: str = "",
        type: str = "product",
        parameters: dict | None = None,
        metrics: list[dict] | None = None,
        metrics_secondary: list[dict] | None = None,
        secondary_metrics: list[dict] | None = None,
        stats_config: dict | None = None,
        exposure_criteria: dict | None = None,
        holdout: ExperimentHoldout | None = None,
        saved_metrics_ids: list[dict] | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        primary_metrics_ordered_uuids: list[str] | None = None,
        secondary_metrics_ordered_uuids: list[str] | None = None,
        create_in_folder: str | None = None,
        filters: dict | None = None,
        scheduling_config: dict | None = None,
        exposure_preaggregation_enabled: bool = False,
        archived: bool = False,
        deleted: bool = False,
        conclusion: str | None = None,
        conclusion_comment: str | None = None,
        serializer_context: dict | None = None,
        event_source: EventSource | None = None,
    ) -> Experiment:
        """Create experiment with full validation and defaults."""
        self.validate_saved_metrics_ids(saved_metrics_ids, self.team.id)
        is_draft = start_date is None

        feature_flag, used_variants = self._ensure_feature_flag(
            feature_flag_key=feature_flag_key,
            experiment_name=name,
            parameters=parameters,
            holdout=holdout,
            is_draft=is_draft,
            create_in_folder=create_in_folder,
            serializer_context=serializer_context,
        )

        stats_config = self._apply_stats_config_defaults(stats_config)
        exposure_criteria = self._apply_exposure_criteria_defaults(exposure_criteria)

        stats_method = "bayesian" if stats_config is None else stats_config.get("method", "bayesian")
        if metrics is not None:
            for metric in metrics:
                metric["fingerprint"] = compute_metric_fingerprint(metric, start_date, stats_method, exposure_criteria)
        if metrics_secondary is not None:
            for metric in metrics_secondary:
                metric["fingerprint"] = compute_metric_fingerprint(metric, start_date, stats_method, exposure_criteria)

        if metrics is not None:
            primary_ordering = list(primary_metrics_ordered_uuids or [])
            for metric in metrics:
                if uuid := metric.get("uuid"):
                    if uuid not in primary_ordering:
                        primary_ordering.append(uuid)
            primary_metrics_ordered_uuids = primary_ordering

        if metrics_secondary is not None:
            secondary_ordering = list(secondary_metrics_ordered_uuids or [])
            for metric in metrics_secondary:
                if uuid := metric.get("uuid"):
                    if uuid not in secondary_ordering:
                        secondary_ordering.append(uuid)
            secondary_metrics_ordered_uuids = secondary_ordering

        create_kwargs: dict[str, Any] = {
            "team": self.team,
            "created_by": self.user,
            "feature_flag": feature_flag,
            "name": name,
            "description": description,
            "type": type,
            "parameters": parameters,
            "metrics": metrics if metrics is not None else [],
            "metrics_secondary": metrics_secondary if metrics_secondary is not None else [],
            "secondary_metrics": secondary_metrics if secondary_metrics is not None else [],
            "stats_config": stats_config,
            "exposure_criteria": exposure_criteria,
            "holdout": holdout,
            "start_date": start_date,
            "end_date": end_date,
            "filters": filters if filters is not None else {},
            "primary_metrics_ordered_uuids": primary_metrics_ordered_uuids,
            "secondary_metrics_ordered_uuids": secondary_metrics_ordered_uuids,
            "scheduling_config": scheduling_config,
            "exposure_preaggregation_enabled": exposure_preaggregation_enabled,
            "archived": archived,
            "deleted": deleted,
            "conclusion": conclusion,
            "conclusion_comment": conclusion_comment,
        }
        if create_in_folder is not None:
            create_kwargs["_create_in_folder"] = create_in_folder

        experiment = Experiment.objects.create(**create_kwargs)

        if type == "web":
            self._apply_web_variants(experiment, used_variants)

        if saved_metrics_ids:
            self._sync_saved_metrics(experiment, saved_metrics_ids, serializer_context)

        self._validate_metric_ordering_on_create(experiment)
        self._report_experiment_created(
            experiment,
            serializer_context=serializer_context,
            event_source=event_source,
        )

        return experiment

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _report_experiment_created(
        self,
        experiment: Experiment,
        *,
        serializer_context: dict | None,
        event_source: EventSource | None,
    ) -> None:
        request = serializer_context.get("request") if serializer_context else None
        if request is None and event_source is None:
            return

        analytics_metadata = experiment.get_analytics_metadata()
        if event_source is not None:
            analytics_metadata["source"] = event_source

        report_user_action(
            self.user,
            "experiment created",
            analytics_metadata,
            team=experiment.team,
            request=request,
        )

    def _ensure_feature_flag(
        self,
        feature_flag_key: str,
        experiment_name: str,
        parameters: dict | None,
        holdout: ExperimentHoldout | None,
        is_draft: bool,
        create_in_folder: str | None,
        serializer_context: dict | None,
    ) -> tuple[FeatureFlag, list[dict]]:
        """Resolve existing flag or create a new one. Returns (flag, variants_used)."""
        existing_flag = FeatureFlag.objects.filter(key=feature_flag_key, team_id=self.team.id).first()

        if existing_flag:
            self._validate_existing_flag(existing_flag)
            variants = existing_flag.filters.get("multivariate", {}).get("variants", list(DEFAULT_VARIANTS))
            return existing_flag, variants

        variants = []
        aggregation_group_type_index = None
        if parameters:
            variants = parameters.get("feature_flag_variants", [])
            aggregation_group_type_index = parameters.get("aggregation_group_type_index")

        params = parameters or {}
        experiment_rollout_percentage = params.get("rollout_percentage", DEFAULT_ROLLOUT_PERCENTAGE)

        feature_flag_filters = {
            "groups": [{"properties": [], "rollout_percentage": experiment_rollout_percentage}],
            "multivariate": {"variants": variants or list(DEFAULT_VARIANTS)},
            "aggregation_group_type_index": aggregation_group_type_index,
            **holdout_filters_for_flag(holdout.id if holdout else None, holdout.filters if holdout else None),
        }

        feature_flag_data: dict[str, Any] = {
            "key": feature_flag_key,
            "name": f"Feature Flag for Experiment {experiment_name}",
            "filters": feature_flag_filters,
            "active": not is_draft,
            "creation_context": "experiments",
        }
        if params.get("ensure_experience_continuity") is not None:
            feature_flag_data["ensure_experience_continuity"] = params["ensure_experience_continuity"]
        if create_in_folder is not None:
            feature_flag_data["_create_in_folder"] = create_in_folder

        context = serializer_context or self._build_serializer_context()
        feature_flag_serializer = FeatureFlagSerializer(
            data=feature_flag_data,
            context=context,
        )
        feature_flag_serializer.is_valid(raise_exception=True)
        feature_flag = feature_flag_serializer.save()

        return feature_flag, variants or list(DEFAULT_VARIANTS)

    def _validate_existing_flag(self, feature_flag: FeatureFlag) -> None:
        """Validate that an existing feature flag is suitable for experiment use."""
        variants = feature_flag.filters.get("multivariate", {}).get("variants", [])

        if len(variants) < 2:
            raise ValidationError("Feature flag must have at least 2 variants (control and at least one test variant)")

        if "control" not in [variant["key"] for variant in variants]:
            raise ValidationError("Feature flag must have a variant with key 'control'")

    def _apply_stats_config_defaults(self, stats_config: dict | None) -> dict:
        """Apply team-level defaults to stats_config."""
        result = dict(stats_config or {})

        if not result.get("method"):
            default_method = self.team.default_experiment_stats_method or "bayesian"
            result["method"] = default_method

        if self.team.default_experiment_confidence_level is not None:
            confidence_level = float(self.team.default_experiment_confidence_level)
            bayesian_config = result.get("bayesian") or {}
            frequentist_config = result.get("frequentist") or {}
            if bayesian_config.get("ci_level") is None:
                result["bayesian"] = {**bayesian_config, "ci_level": confidence_level}
            if frequentist_config.get("alpha") is None:
                result["frequentist"] = {**frequentist_config, "alpha": 1 - confidence_level}

        return result

    def _apply_exposure_criteria_defaults(self, exposure_criteria: dict | None) -> dict:
        """Apply default exposure criteria if not provided."""
        result = dict(exposure_criteria or {})
        if result.get("filterTestAccounts") is None:
            result["filterTestAccounts"] = True
        return result

    def _apply_web_variants(self, experiment: Experiment, variants: list[dict]) -> None:
        """Copy variant rollout data to web experiment."""
        web_variants = {}
        for variant in variants:
            web_variants[variant.get("key")] = {
                "rollout_percentage": variant.get("rollout_percentage"),
            }
        experiment.variants = web_variants
        experiment.save()

    def _sync_saved_metrics(
        self,
        experiment: Experiment,
        saved_metrics_ids: list[dict],
        serializer_context: dict | None,
    ) -> None:
        """Create saved metric junction records and sync ordering."""
        context = serializer_context or self._build_serializer_context()

        for saved_metric_data in saved_metrics_ids:
            saved_metric_serializer = ExperimentToSavedMetricSerializer(
                data={
                    "experiment": experiment.id,
                    "saved_metric": saved_metric_data["id"],
                    "metadata": saved_metric_data.get("metadata"),
                },
                context=context,
            )
            saved_metric_serializer.is_valid(raise_exception=True)
            saved_metric_serializer.save()

        primary_ordering = list(experiment.primary_metrics_ordered_uuids or [])
        secondary_ordering = list(experiment.secondary_metrics_ordered_uuids or [])
        ordering_changed = False

        saved_metric_id_list = [sm["id"] for sm in saved_metrics_ids]
        saved_metrics_map = {
            sm.id: sm for sm in ExperimentSavedMetric.objects.filter(id__in=saved_metric_id_list, team_id=self.team.id)
        }

        for sm_data in saved_metrics_ids:
            saved_metric = saved_metrics_map.get(sm_data["id"])
            if saved_metric and saved_metric.query:
                if uuid := saved_metric.query.get("uuid"):
                    metric_type = (sm_data.get("metadata") or {}).get("type", "primary")
                    if metric_type == "primary":
                        if uuid not in primary_ordering:
                            primary_ordering.append(uuid)
                            ordering_changed = True
                    else:
                        if uuid not in secondary_ordering:
                            secondary_ordering.append(uuid)
                            ordering_changed = True

        if ordering_changed:
            experiment.primary_metrics_ordered_uuids = primary_ordering
            experiment.secondary_metrics_ordered_uuids = secondary_ordering
            experiment.save(update_fields=["primary_metrics_ordered_uuids", "secondary_metrics_ordered_uuids"])

    def _validate_metric_ordering_on_create(self, experiment: Experiment) -> None:
        """Validate that ordering arrays contain all metric UUIDs (create path)."""
        primary_ordering = experiment.primary_metrics_ordered_uuids
        secondary_ordering = experiment.secondary_metrics_ordered_uuids

        primary_metrics = experiment.metrics or []
        secondary_metrics = experiment.metrics_secondary or []

        saved_metrics = list(experiment.experimenttosavedmetric_set.select_related("saved_metric").all())

        expected_primary_uuids: set[str] = set()
        expected_secondary_uuids: set[str] = set()

        for metric in primary_metrics:
            if uuid := metric.get("uuid"):
                expected_primary_uuids.add(uuid)

        for metric in secondary_metrics:
            if uuid := metric.get("uuid"):
                expected_secondary_uuids.add(uuid)

        for link in saved_metrics:
            saved_metric = link.saved_metric
            uuid = saved_metric.query.get("uuid") if saved_metric.query else None
            if uuid:
                metric_type = link.metadata.get("type", "primary") if link.metadata else "primary"
                if metric_type == "primary":
                    expected_primary_uuids.add(uuid)
                else:
                    expected_secondary_uuids.add(uuid)

        if expected_primary_uuids:
            if primary_ordering is None:
                raise ValidationError(
                    "primary_metrics_ordered_uuids is null but primary metrics exist. "
                    "This is likely a frontend bug - please refresh and try again."
                )
            missing = expected_primary_uuids - set(primary_ordering)
            if missing:
                raise ValidationError(
                    f"primary_metrics_ordered_uuids is missing UUIDs: {sorted(missing)}. "
                    "This is likely a frontend bug - please refresh and try again."
                )

        if expected_secondary_uuids:
            if secondary_ordering is None:
                raise ValidationError(
                    "secondary_metrics_ordered_uuids is null but secondary metrics exist. "
                    "This is likely a frontend bug - please refresh and try again."
                )
            missing = expected_secondary_uuids - set(secondary_ordering)
            if missing:
                raise ValidationError(
                    f"secondary_metrics_ordered_uuids is missing UUIDs: {sorted(missing)}. "
                    "This is likely a frontend bug - please refresh and try again."
                )

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    @transaction.atomic
    def update_experiment(
        self,
        experiment: Experiment,
        update_data: dict,
        *,
        serializer_context: dict | None = None,
    ) -> Experiment:
        """Update an experiment with full business-logic validation.

        ``update_data`` mirrors the DRF ``validated_data`` dict produced by
        ``ExperimentSerializer``.  The caller is responsible for DRF-level input
        validation (field types, metric schema, etc.) before calling this method.
        """
        if "saved_metrics_ids" in update_data:
            self.validate_saved_metrics_ids(update_data["saved_metrics_ids"], self.team.id)

        context = serializer_context or self._build_serializer_context()
        feature_flag = experiment.feature_flag

        self._validate_update_payload(experiment, update_data, feature_flag)

        update_saved_metrics = "saved_metrics_ids" in update_data
        saved_metrics_data: list[dict] = update_data.pop("saved_metrics_ids", []) or []
        update_data.pop("get_feature_flag_key", None)

        # --- saved metrics replacement (delete-all / re-create) -----------
        old_saved_metric_uuids: dict[str, set[str]] = {"primary": set(), "secondary": set()}
        if update_saved_metrics:
            for link in experiment.experimenttosavedmetric_set.select_related("saved_metric").all():
                if link.saved_metric.query:
                    uuid = link.saved_metric.query.get("uuid")
                    if uuid:
                        metric_type = (link.metadata or {}).get("type", "primary")
                        if metric_type == "primary":
                            old_saved_metric_uuids["primary"].add(uuid)
                        else:
                            old_saved_metric_uuids["secondary"].add(uuid)

            experiment.experimenttosavedmetric_set.all().delete()
            for saved_metric_data in saved_metrics_data:
                saved_metric_serializer = ExperimentToSavedMetricSerializer(
                    data={
                        "experiment": experiment.id,
                        "saved_metric": saved_metric_data["id"],
                        "metadata": saved_metric_data.get("metadata"),
                    },
                    context=context,
                )
                saved_metric_serializer.is_valid(raise_exception=True)
                saved_metric_serializer.save()

        # --- feature flag variant sync for draft experiments ---------------
        if experiment.is_draft:
            holdout = experiment.holdout
            if "holdout" in update_data:
                holdout = update_data["holdout"]

            if update_data.get("parameters"):
                variants = update_data["parameters"].get("feature_flag_variants", [])
                aggregation_group_type_index = update_data["parameters"].get("aggregation_group_type_index")

                feature_flag_filters = feature_flag.filters
                existing_groups = feature_flag.filters.get("groups", [])
                experiment_rollout_percentage = update_data["parameters"].get("rollout_percentage")
                if experiment_rollout_percentage is not None and existing_groups:
                    existing_groups[0]["rollout_percentage"] = experiment_rollout_percentage

                feature_flag_filters["groups"] = existing_groups
                feature_flag_filters["multivariate"] = {"variants": variants or list(DEFAULT_VARIANTS)}
                feature_flag_filters["aggregation_group_type_index"] = aggregation_group_type_index
                feature_flag_filters.update(
                    holdout_filters_for_flag(holdout.id if holdout else None, holdout.filters if holdout else None)
                )

                existing_flag_serializer = FeatureFlagSerializer(
                    feature_flag,
                    data={"filters": feature_flag_filters},
                    partial=True,
                    context=context,
                )
                existing_flag_serializer.is_valid(raise_exception=True)
                existing_flag_serializer.save()
            elif "holdout" in update_data:
                existing_flag_serializer = FeatureFlagSerializer(
                    feature_flag,
                    data={
                        "filters": {
                            **feature_flag.filters,
                            **holdout_filters_for_flag(
                                holdout.id if holdout else None, holdout.filters if holdout else None
                            ),
                        }
                    },
                    partial=True,
                    context=context,
                )
                existing_flag_serializer.is_valid(raise_exception=True)
                existing_flag_serializer.save()

        # --- fingerprint recalculation -------------------------------------
        start_date = update_data.get("start_date", experiment.start_date)
        stats_config = update_data.get("stats_config", experiment.stats_config)
        exposure_criteria = update_data.get("exposure_criteria", experiment.exposure_criteria)

        for metric_field in ["metrics", "metrics_secondary"]:
            metrics = update_data.get(metric_field, getattr(experiment, metric_field, None))
            if metrics:
                updated_metrics = []
                for metric in metrics:
                    metric_copy = deepcopy(metric)
                    stats_method = "bayesian" if stats_config is None else stats_config.get("method", "bayesian")
                    metric_copy["fingerprint"] = compute_metric_fingerprint(
                        metric_copy,
                        start_date,
                        stats_method,
                        exposure_criteria,
                    )
                    updated_metrics.append(metric_copy)
                update_data[metric_field] = updated_metrics

        # --- metric ordering sync + validation -----------------------------
        self._sync_ordering_with_metric_changes(experiment, update_data)
        self._sync_ordering_for_saved_metrics_on_update(
            experiment,
            update_data,
            old_saved_metric_uuids,
            saved_metrics_data if update_saved_metrics else None,
        )
        self._validate_metric_ordering_on_update(experiment, update_data)

        # --- feature flag activation on launch -----------------------------
        has_start_date = update_data.get("start_date") is not None
        if experiment.is_draft and has_start_date:
            feature_flag.active = True
            feature_flag.save()

        # --- apply changes and save ----------------------------------------
        for attr, value in update_data.items():
            setattr(experiment, attr, value)
        experiment.save()

        return experiment

    def _validate_update_payload(self, experiment: Experiment, update_data: dict, feature_flag: FeatureFlag) -> None:
        """Validate update payload before any database mutations occur."""
        if experiment.deleted and update_data.get("deleted") is False and feature_flag.deleted:
            raise ValidationError(
                "Cannot restore experiment: the linked feature flag has been deleted. "
                "Restore the feature flag first, then restore the experiment."
            )

        expected_keys = {
            "name",
            "description",
            "start_date",
            "end_date",
            "filters",
            "parameters",
            "archived",
            "deleted",
            "secondary_metrics",
            "holdout",
            "exposure_criteria",
            "metrics",
            "metrics_secondary",
            "stats_config",
            "scheduling_config",
            "conclusion",
            "conclusion_comment",
            "primary_metrics_ordered_uuids",
            "secondary_metrics_ordered_uuids",
            "saved_metrics_ids",
        }
        extra_keys = set(update_data.keys()) - expected_keys

        if feature_flag.key == update_data.get("get_feature_flag_key"):
            extra_keys.discard("get_feature_flag_key")

        if extra_keys:
            raise ValidationError(f"Can't update keys: {', '.join(sorted(extra_keys))} on Experiment")

        if not experiment.is_draft:
            if "feature_flag_variants" in update_data.get("parameters", {}):
                if len(update_data["parameters"]["feature_flag_variants"]) != len(feature_flag.variants):
                    raise ValidationError("Can't update feature_flag_variants on Experiment")
                for variant in update_data["parameters"]["feature_flag_variants"]:
                    if (
                        len([ff_variant for ff_variant in feature_flag.variants if ff_variant["key"] == variant["key"]])
                        != 1
                    ):
                        raise ValidationError("Can't update feature_flag_variants on Experiment")
            if "holdout" in update_data and update_data["holdout"] != experiment.holdout:
                raise ValidationError("Can't update holdout on running Experiment")

        properties = update_data.get("filters", {}).get("properties")
        if properties:
            raise ValidationError("Experiments do not support global filter properties")

    # ------------------------------------------------------------------
    # Duplication
    # ------------------------------------------------------------------

    def duplicate_experiment(
        self,
        source_experiment: Experiment,
        *,
        feature_flag_key: str | None = None,
        serializer_context: dict | None = None,
    ) -> Experiment:
        """Duplicate an experiment as a new draft."""
        if feature_flag_key is None:
            feature_flag_key = source_experiment.feature_flag.key

        parameters = deepcopy(source_experiment.parameters) or {}
        if feature_flag_key != source_experiment.feature_flag.key:
            existing_flag = FeatureFlag.objects.filter(key=feature_flag_key, team_id=self.team.id).first()
            if existing_flag and existing_flag.filters.get("multivariate", {}).get("variants"):
                parameters["feature_flag_variants"] = existing_flag.filters["multivariate"]["variants"]

        self.validate_experiment_parameters(parameters)
        self.validate_experiment_exposure_criteria(source_experiment.exposure_criteria)
        self.validate_experiment_metrics(source_experiment.metrics)
        self.validate_experiment_metrics(source_experiment.metrics_secondary)

        base_name = f"{source_experiment.name} (Copy)"
        duplicate_name = base_name
        counter = 1
        while Experiment.objects.filter(team_id=self.team.id, name=duplicate_name, deleted=False).exists():
            duplicate_name = f"{base_name} {counter}"
            counter += 1

        saved_metrics_data = []
        for link in source_experiment.experimenttosavedmetric_set.all():
            saved_metrics_data.append(
                {
                    "id": link.saved_metric.id,
                    "metadata": link.metadata,
                }
            )

        duplicate_description = source_experiment.description or ""
        duplicate_type = source_experiment.type or "product"

        return self.create_experiment(
            name=duplicate_name,
            feature_flag_key=feature_flag_key,
            description=duplicate_description,
            type=duplicate_type,
            parameters=parameters,
            filters=source_experiment.filters,
            metrics=source_experiment.metrics,
            metrics_secondary=source_experiment.metrics_secondary,
            stats_config=source_experiment.stats_config,
            scheduling_config=source_experiment.scheduling_config,
            exposure_criteria=source_experiment.exposure_criteria,
            saved_metrics_ids=saved_metrics_data or None,
            primary_metrics_ordered_uuids=source_experiment.primary_metrics_ordered_uuids,
            secondary_metrics_ordered_uuids=source_experiment.secondary_metrics_ordered_uuids,
            exposure_preaggregation_enabled=source_experiment.exposure_preaggregation_enabled,
            serializer_context=serializer_context,
        )

    # ------------------------------------------------------------------
    # Exposure cohort
    # ------------------------------------------------------------------

    def create_exposure_cohort(
        self,
        experiment: Experiment,
        *,
        serializer_context: dict | None = None,
    ) -> Cohort:
        """Create an exposure cohort for the experiment."""
        flag = getattr(experiment, "feature_flag", None)
        if not flag:
            raise ValidationError("Experiment does not have a feature flag")

        if not experiment.start_date:
            raise ValidationError("Experiment does not have a start date")

        if experiment.exposure_cohort:
            raise ValidationError("Experiment already has an exposure cohort")

        exposure_filter_data = (experiment.parameters or {}).get("custom_exposure_filter")
        exposure_filter = None
        if exposure_filter_data:
            exposure_filter = Filter(data={**exposure_filter_data, "is_simplified": True}, team=experiment.team)

        target_entity: int | str = "$feature_flag_called"
        target_entity_type = "events"
        target_filters = [
            {
                "key": "$feature_flag",
                "value": [flag.key],
                "operator": "exact",
                "type": "event",
            }
        ]

        if exposure_filter:
            entity = exposure_filter.entities[0]
            if entity.id:
                target_entity_type = entity.type if entity.type in ["events", "actions"] else "events"
                target_entity = entity.id
                if entity.type == "actions":
                    try:
                        target_entity = int(target_entity)
                    except ValueError:
                        raise ValidationError("Invalid action ID")

                target_filters = [
                    prop.to_dict()
                    for prop in entity.property_groups.flat
                    if prop.type in ("event", "feature", "element", "hogql")
                ]

        context = serializer_context or self._build_serializer_context()
        # CohortSerializer expects "team" directly in context
        cohort_context = {**context, "team": self.team}

        cohort_serializer = CohortSerializer(
            data={
                "is_static": False,
                "name": f'Users exposed to experiment "{experiment.name}"',
                "is_calculating": True,
                "filters": {
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "OR",
                                "values": [
                                    {
                                        "type": "behavioral",
                                        "value": "performed_event",
                                        "key": target_entity,
                                        "negation": False,
                                        "event_type": target_entity_type,
                                        "event_filters": target_filters,
                                        "explicit_datetime": experiment.start_date.isoformat(),
                                    }
                                ],
                            }
                        ],
                    }
                },
            },
            context=cohort_context,
        )

        cohort_serializer.is_valid(raise_exception=True)
        cohort = cohort_serializer.save()
        experiment.exposure_cohort = cohort
        experiment.save(update_fields=["exposure_cohort"])
        return cohort

    # ------------------------------------------------------------------
    # Eligible feature flags
    # ------------------------------------------------------------------

    def get_eligible_feature_flags(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        excluded_flag_ids: list[int] | set[int] | None = None,
        search: str | None = None,
        active: str | bool | None = None,
        created_by_id: str | int | None = None,
        order: str | None = None,
        evaluation_runtime: str | None = None,
        has_evaluation_tags: str | bool | None = None,
    ) -> dict[str, Any]:
        """Get feature flags eligible for use in experiments."""
        queryset = self._get_eligible_feature_flags_queryset(
            excluded_flag_ids=excluded_flag_ids,
            search=search,
            active=active,
            created_by_id=created_by_id,
            order=order,
            evaluation_runtime=evaluation_runtime,
            has_evaluation_tags=has_evaluation_tags,
        )

        return {
            "results": queryset[offset : offset + limit],
            "count": queryset.count(),
        }

    def _get_eligible_feature_flags_queryset(
        self,
        *,
        excluded_flag_ids: list[int] | set[int] | None,
        search: str | None,
        active: str | bool | None,
        created_by_id: str | int | None,
        order: str | None,
        evaluation_runtime: str | None,
        has_evaluation_tags: str | bool | None,
    ) -> QuerySet[FeatureFlag]:
        queryset = FeatureFlag.objects.filter(team__project_id=self.team.project_id)

        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (static SQL, no user input)
        queryset = queryset.extra(
            where=[
                """
                jsonb_array_length(filters->'multivariate'->'variants') >= 2
                AND filters->'multivariate'->'variants'->0->>'key' = 'control'
                """
            ]
        )

        if excluded_flag_ids:
            queryset = queryset.exclude(id__in=excluded_flag_ids)

        if search:
            queryset = queryset.filter(Q(key__icontains=search) | Q(name__icontains=search))

        if active is not None:
            active_bool = active if isinstance(active, bool) else str(active).lower() == "true"
            queryset = queryset.filter(active=active_bool)

        if created_by_id:
            queryset = queryset.filter(created_by_id=created_by_id)

        if evaluation_runtime:
            queryset = queryset.filter(evaluation_runtime=evaluation_runtime)

        if has_evaluation_tags is not None:
            filter_value = (
                has_evaluation_tags
                if isinstance(has_evaluation_tags, bool)
                else str(has_evaluation_tags).lower() in ("true", "1", "yes")
            )
            queryset = queryset.annotate(eval_tag_count=Count("flag_evaluation_contexts"))
            if filter_value:
                queryset = queryset.filter(eval_tag_count__gt=0)
            else:
                queryset = queryset.filter(eval_tag_count=0)

        queryset = queryset.order_by(order or "-created_at")

        return queryset.prefetch_related(
            Prefetch(
                "experiment_set", queryset=Experiment.objects.filter(deleted=False), to_attr="_active_experiments"
            ),
            "features",
            "analytics_dashboards",
            "surveys_linked_flag",
            Prefetch(
                "flag_evaluation_contexts",
                queryset=FeatureFlagEvaluationContext.objects.select_related("evaluation_context"),
            ),
            Prefetch(
                "team__cohort_set",
                queryset=Cohort.objects.filter(deleted=False).only("id", "name"),
                to_attr="available_cohorts",
            ),
        ).select_related("created_by", "last_modified_by")

    # ------------------------------------------------------------------
    # Timeseries
    # ------------------------------------------------------------------

    def get_timeseries_results(
        self,
        experiment: Experiment,
        *,
        metric_uuid: str,
        fingerprint: str,
    ) -> dict:
        """Retrieve timeseries results for an experiment-metric combination."""
        project_tz = ZoneInfo(experiment.team.timezone) if experiment.team.timezone else ZoneInfo("UTC")

        if not experiment.start_date:
            raise ValidationError("Experiment has not been started yet")
        start_date = experiment.start_date.date()
        end_date = experiment.end_date.date() if experiment.end_date else date.today()

        experiment_dates: list[date] = []
        current_date = start_date
        while current_date <= end_date:
            experiment_dates.append(current_date)
            current_date += timedelta(days=1)

        timeseries: dict[str, Any | None] = {}
        errors: dict[str, str] = {}
        for experiment_date in experiment_dates:
            timeseries[experiment_date.isoformat()] = None

        metric_results = ExperimentMetricResult.objects.filter(
            experiment_id=experiment.id, metric_uuid=metric_uuid, fingerprint=fingerprint
        ).order_by("query_to")

        completed_count = 0
        failed_count = 0
        pending_count = 0
        no_record_count = 0
        latest_completed_at = None

        results_by_date: dict[date, ExperimentMetricResult] = {}
        for result in metric_results:
            query_to_adjusted = result.query_to - timedelta(microseconds=1)
            query_to_in_project_tz = query_to_adjusted.astimezone(project_tz)
            day_in_project_tz = query_to_in_project_tz.date()
            results_by_date[day_in_project_tz] = result

        for experiment_date in experiment_dates:
            date_key = experiment_date.isoformat()

            if experiment_date in results_by_date:
                metric_result = results_by_date[experiment_date]

                if metric_result.status == "completed":
                    timeseries[date_key] = metric_result.result
                    completed_count += 1
                elif metric_result.status == "failed":
                    if metric_result.error_message:
                        errors[date_key] = metric_result.error_message
                    failed_count += 1
                elif metric_result.status == "pending":
                    pending_count += 1

                if metric_result.completed_at:
                    if latest_completed_at is None or metric_result.completed_at > latest_completed_at:
                        latest_completed_at = metric_result.completed_at
            else:
                no_record_count += 1

        total_experiment_days = len(experiment_dates)
        calculated_days = completed_count + failed_count + pending_count

        if calculated_days == 0:
            overall_status = "pending"
        elif completed_count == 0 and failed_count > 0:
            overall_status = "failed"
        elif completed_count == total_experiment_days:
            overall_status = "completed"
        else:
            overall_status = "partial"

        active_recalculation = ExperimentTimeseriesRecalculation.objects.filter(
            experiment=experiment,
            fingerprint=fingerprint,
            status__in=[
                ExperimentTimeseriesRecalculation.Status.PENDING,
                ExperimentTimeseriesRecalculation.Status.IN_PROGRESS,
            ],
        ).first()

        first_result = metric_results.first()
        last_result = metric_results.last()
        return {
            "experiment_id": experiment.id,
            "metric_uuid": metric_uuid,
            "status": overall_status,
            "timeseries": timeseries,
            "errors": errors if errors else None,
            "computed_at": latest_completed_at.isoformat() if latest_completed_at else None,
            "created_at": first_result.created_at.isoformat() if first_result else experiment.created_at.isoformat(),
            "updated_at": last_result.updated_at.isoformat() if last_result else experiment.updated_at.isoformat(),
            "recalculation_status": active_recalculation.status if active_recalculation else None,
            "recalculation_created_at": active_recalculation.created_at.isoformat() if active_recalculation else None,
        }

    def request_timeseries_recalculation(
        self,
        experiment: Experiment,
        *,
        metric: dict,
        fingerprint: str,
    ) -> dict:
        """Create an idempotent recalculation request for experiment timeseries data."""
        if not experiment.start_date:
            raise ValidationError("Cannot recalculate timeseries for experiment that hasn't started")

        existing_recalculation = ExperimentTimeseriesRecalculation.objects.filter(
            experiment=experiment,
            fingerprint=fingerprint,
            status__in=[
                ExperimentTimeseriesRecalculation.Status.PENDING,
                ExperimentTimeseriesRecalculation.Status.IN_PROGRESS,
            ],
        ).first()

        if existing_recalculation:
            return {
                "id": existing_recalculation.id,
                "experiment_id": experiment.id,
                "metric_uuid": existing_recalculation.metric.get("uuid"),
                "fingerprint": fingerprint,
                "status": existing_recalculation.status,
                "created_at": existing_recalculation.created_at.isoformat(),
                "is_existing": True,
            }

        metric_uuid = metric.get("uuid")
        if metric_uuid:
            ExperimentMetricResult.objects.filter(
                experiment_id=experiment.id,
                metric_uuid=metric_uuid,
                fingerprint=fingerprint,
            ).delete()

        recalculation_request = ExperimentTimeseriesRecalculation.objects.create(
            team=experiment.team,
            experiment=experiment,
            metric=metric,
            fingerprint=fingerprint,
            status=ExperimentTimeseriesRecalculation.Status.PENDING,
        )

        return {
            "id": recalculation_request.id,
            "experiment_id": experiment.id,
            "metric_uuid": metric.get("uuid"),
            "fingerprint": fingerprint,
            "status": recalculation_request.status,
            "created_at": recalculation_request.created_at.isoformat(),
            "is_existing": False,
        }

    # ------------------------------------------------------------------
    # Velocity stats
    # ------------------------------------------------------------------

    def get_velocity_stats(self) -> dict:
        """Get experimentation velocity statistics."""
        team_tz = ZoneInfo(self.team.timezone) if self.team.timezone else ZoneInfo("UTC")
        today = datetime.now(team_tz).date()

        last_30d_start = today - timedelta(days=30)
        previous_30d_start = today - timedelta(days=60)
        previous_30d_end = last_30d_start

        base_queryset = Experiment.objects.filter(team=self.team, deleted=False, archived=False)

        launched_last_30d = base_queryset.filter(
            start_date__gte=last_30d_start, start_date__lt=today + timedelta(days=1)
        ).count()

        launched_previous_30d = base_queryset.filter(
            start_date__gte=previous_30d_start, start_date__lt=previous_30d_end
        ).count()

        if launched_previous_30d == 0:
            percent_change = 100.0 if launched_last_30d > 0 else 0.0
        else:
            percent_change = ((launched_last_30d - launched_previous_30d) / launched_previous_30d) * 100

        active_experiments = base_queryset.filter(start_date__isnull=False, end_date__isnull=True).count()

        completed_last_30d = base_queryset.filter(
            end_date__gte=last_30d_start, end_date__lt=today + timedelta(days=1)
        ).count()

        return {
            "launched_last_30d": launched_last_30d,
            "launched_previous_30d": launched_previous_30d,
            "percent_change": round(percent_change, 1),
            "active_experiments": active_experiments,
            "completed_last_30d": completed_last_30d,
        }

    # ------------------------------------------------------------------
    # Private helpers — update ordering
    # ------------------------------------------------------------------

    def _sync_ordering_with_metric_changes(self, experiment: Experiment, update_data: dict) -> None:
        """Sync ordering arrays with inline metric changes during update."""
        if "metrics" in update_data:
            old_uuids = {m.get("uuid") for m in experiment.metrics or [] if m.get("uuid")}
            new_uuids = {m.get("uuid") for m in update_data.get("metrics") or [] if m.get("uuid")}

            added = new_uuids - old_uuids
            removed = old_uuids - new_uuids

            if added or removed:
                if "primary_metrics_ordered_uuids" in update_data:
                    current_ordering = list(update_data["primary_metrics_ordered_uuids"] or [])
                else:
                    current_ordering = list(experiment.primary_metrics_ordered_uuids or [])

                current_ordering = [u for u in current_ordering if u not in removed]
                for uuid in added:
                    if uuid not in current_ordering:
                        current_ordering.append(uuid)

                update_data["primary_metrics_ordered_uuids"] = current_ordering

        if "metrics_secondary" in update_data:
            old_uuids = {m.get("uuid") for m in experiment.metrics_secondary or [] if m.get("uuid")}
            new_uuids = {m.get("uuid") for m in update_data.get("metrics_secondary") or [] if m.get("uuid")}

            added = new_uuids - old_uuids
            removed = old_uuids - new_uuids

            if added or removed:
                if "secondary_metrics_ordered_uuids" in update_data:
                    current_ordering = list(update_data["secondary_metrics_ordered_uuids"] or [])
                else:
                    current_ordering = list(experiment.secondary_metrics_ordered_uuids or [])

                current_ordering = [u for u in current_ordering if u not in removed]
                for uuid in added:
                    if uuid not in current_ordering:
                        current_ordering.append(uuid)

                update_data["secondary_metrics_ordered_uuids"] = current_ordering

    def _sync_ordering_for_saved_metrics_on_update(
        self,
        experiment: Experiment,
        update_data: dict,
        old_saved_metric_uuids: dict[str, set[str]],
        saved_metrics_data: list[dict] | None,
    ) -> None:
        """Sync ordering arrays with saved metric changes during update."""
        if saved_metrics_data is None:
            return

        new_primary_uuids: set[str] = set()
        new_secondary_uuids: set[str] = set()

        saved_metric_ids_list = [sm["id"] for sm in saved_metrics_data]
        if saved_metric_ids_list:
            saved_metrics = {
                sm.id: sm
                for sm in ExperimentSavedMetric.objects.filter(id__in=saved_metric_ids_list, team_id=self.team.id)
            }

            for sm_data in saved_metrics_data:
                saved_metric = saved_metrics.get(sm_data["id"])
                if saved_metric and saved_metric.query:
                    uuid = saved_metric.query.get("uuid")
                    if uuid:
                        metric_type = (sm_data.get("metadata") or {}).get("type", "primary")
                        if metric_type == "primary":
                            new_primary_uuids.add(uuid)
                        else:
                            new_secondary_uuids.add(uuid)

        added_primary = new_primary_uuids - old_saved_metric_uuids["primary"]
        removed_primary = old_saved_metric_uuids["primary"] - new_primary_uuids
        added_secondary = new_secondary_uuids - old_saved_metric_uuids["secondary"]
        removed_secondary = old_saved_metric_uuids["secondary"] - new_secondary_uuids

        if added_primary or removed_primary:
            if "primary_metrics_ordered_uuids" in update_data:
                current_ordering = list(update_data["primary_metrics_ordered_uuids"] or [])
            else:
                current_ordering = list(experiment.primary_metrics_ordered_uuids or [])

            current_ordering = [u for u in current_ordering if u not in removed_primary]
            for uuid in added_primary:
                if uuid not in current_ordering:
                    current_ordering.append(uuid)
            update_data["primary_metrics_ordered_uuids"] = current_ordering

        if added_secondary or removed_secondary:
            if "secondary_metrics_ordered_uuids" in update_data:
                current_ordering = list(update_data["secondary_metrics_ordered_uuids"] or [])
            else:
                current_ordering = list(experiment.secondary_metrics_ordered_uuids or [])

            current_ordering = [u for u in current_ordering if u not in removed_secondary]
            for uuid in added_secondary:
                if uuid not in current_ordering:
                    current_ordering.append(uuid)
            update_data["secondary_metrics_ordered_uuids"] = current_ordering

    def _validate_metric_ordering_on_update(self, experiment: Experiment, update_data: dict) -> None:
        """Validate ordering arrays contain all metric UUIDs (update path)."""
        primary_ordering = update_data.get("primary_metrics_ordered_uuids", experiment.primary_metrics_ordered_uuids)
        secondary_ordering = update_data.get(
            "secondary_metrics_ordered_uuids", experiment.secondary_metrics_ordered_uuids
        )

        primary_metrics = update_data.get("metrics", experiment.metrics) or []
        secondary_metrics = update_data.get("metrics_secondary", experiment.metrics_secondary) or []

        saved_metrics = list(experiment.experimenttosavedmetric_set.select_related("saved_metric").all())

        expected_primary_uuids: set[str] = set()
        expected_secondary_uuids: set[str] = set()

        for metric in primary_metrics:
            if uuid := metric.get("uuid"):
                expected_primary_uuids.add(uuid)

        for metric in secondary_metrics:
            if uuid := metric.get("uuid"):
                expected_secondary_uuids.add(uuid)

        for link in saved_metrics:
            saved_metric = link.saved_metric
            uuid = saved_metric.query.get("uuid") if saved_metric.query else None
            if uuid:
                metric_type = link.metadata.get("type", "primary") if link.metadata else "primary"
                if metric_type == "primary":
                    expected_primary_uuids.add(uuid)
                else:
                    expected_secondary_uuids.add(uuid)

        if expected_primary_uuids:
            if primary_ordering is None:
                raise ValidationError(
                    "primary_metrics_ordered_uuids is null but primary metrics exist. "
                    "This is likely a frontend bug - please refresh and try again."
                )
            missing = expected_primary_uuids - set(primary_ordering)
            if missing:
                raise ValidationError(
                    f"primary_metrics_ordered_uuids is missing UUIDs: {sorted(missing)}. "
                    "This is likely a frontend bug - please refresh and try again."
                )

        if expected_secondary_uuids:
            if secondary_ordering is None:
                raise ValidationError(
                    "secondary_metrics_ordered_uuids is null but secondary metrics exist. "
                    "This is likely a frontend bug - please refresh and try again."
                )
            missing = expected_secondary_uuids - set(secondary_ordering)
            if missing:
                raise ValidationError(
                    f"secondary_metrics_ordered_uuids is missing UUIDs: {sorted(missing)}. "
                    "This is likely a frontend bug - please refresh and try again."
                )

    def _build_serializer_context(self) -> dict:
        """Build minimal DRF serializer context for internal service use."""
        return {
            "request": _ServiceRequest(self.user),
            "team_id": self.team.id,
            "project_id": self.team.project_id,
            "get_team": lambda: self.team,
        }


class _ServiceRequest:
    """Minimal request-like object for DRF serializers used from the service layer.

    Provides the subset of the DRF Request interface that FeatureFlagSerializer
    and other serializers actually use, without DRF's authentication machinery.
    """

    def __init__(self, user: Any):
        self.user = user
        self.method = "POST"
        self.data: dict = {}
        self.META: dict = {}
        self.headers: dict = {}
        self.session: dict = {}
