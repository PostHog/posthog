"""Experiment service — single source of truth for experiment business logic."""

from datetime import datetime
from typing import Any

from rest_framework.exceptions import ValidationError

from posthog.api.feature_flag import FeatureFlagSerializer
from posthog.hogql_queries.experiments.experiment_metric_fingerprint import compute_metric_fingerprint
from posthog.models.experiment import Experiment, ExperimentHoldout, ExperimentSavedMetric
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.team.team import Team

from ee.clickhouse.views.experiment_saved_metrics import ExperimentToSavedMetricSerializer

DEFAULT_ROLLOUT_PERCENTAGE = 100

DEFAULT_VARIANTS = [
    {"key": "control", "name": "Control Group", "rollout_percentage": 50},
    {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
]


class ExperimentService:
    """Single source of truth for experiment business logic."""

    def __init__(self, team: Team, user: Any):
        self.team = team
        self.user = user

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
    ) -> Experiment:
        """Create experiment with full validation and defaults."""
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

        self._validate_metric_ordering(experiment)

        return experiment

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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

        holdout_groups = holdout.filters if holdout else None
        params = parameters or {}
        experiment_rollout_percentage = params.get("rollout_percentage", DEFAULT_ROLLOUT_PERCENTAGE)

        feature_flag_filters = {
            "groups": [{"properties": [], "rollout_percentage": experiment_rollout_percentage}],
            "multivariate": {"variants": variants or list(DEFAULT_VARIANTS)},
            "aggregation_group_type_index": aggregation_group_type_index,
            "holdout_groups": holdout_groups,
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

    def _validate_metric_ordering(self, experiment: Experiment) -> None:
        """Validate that ordering arrays contain all metric UUIDs."""
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
