"""Experiment service — single source of truth for experiment business logic."""

from collections.abc import Mapping
from copy import deepcopy
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Case, Count, F, Prefetch, Q, QuerySet, Value, When
from django.db.models.functions import Now
from django.utils import timezone

import pydantic
import structlog
from rest_framework.exceptions import ValidationError

from posthog.schema import ActionsNode, ExperimentEventExposureConfig, ExperimentFunnelMetric, ExperimentMetric

from posthog.api.cohort import CohortSerializer
from posthog.api.feature_flag import FeatureFlagSerializer
from posthog.event_usage import EventSource, report_user_action
from posthog.hogql_queries.experiments.experiment_metric_fingerprint import compute_metric_fingerprint
from posthog.hogql_queries.experiments.funnel_validation import FunnelDWValidator
from posthog.models.action.action import Action
from posthog.models.cohort import Cohort
from posthog.models.evaluation_context import FeatureFlagEvaluationContext
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.filters.filter import Filter
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team
from posthog.utils import str_to_bool

from products.experiments.backend.models.experiment import (
    LEGACY_METRIC_KINDS,
    Experiment,
    ExperimentHoldout,
    ExperimentMetricResult,
    ExperimentSavedMetric,
    ExperimentTimeseriesRecalculation,
    experiment_has_legacy_metrics,
    holdout_filters_for_flag,
)
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig

from ee.clickhouse.views.experiment_saved_metrics import ExperimentToSavedMetricSerializer

logger = structlog.get_logger(__name__)

DEFAULT_ROLLOUT_PERCENTAGE = 100

ExperimentCreationMode = Literal["new", "duplicate", "copy_to_project"]

DEFAULT_VARIANTS = [
    {"key": "control", "name": "Control Group", "rollout_percentage": 50},
    {"key": "test", "name": "Test Variant", "rollout_percentage": 50},
]


class ExperimentQueryStatus(str, Enum):
    """
    Filter values for the experiment list endpoint.

    PAUSED is derived (not stored): an experiment is paused when its stored status is RUNNING and
    its linked feature flag is inactive. RUNNING and PAUSED are mutually exclusive at the API
    layer — RUNNING returns only experiments whose flag is active.
    """

    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ALL = "all"


class ExperimentService:
    """Single source of truth for experiment business logic."""

    def __init__(self, team: Team, user: Any):
        self.team = team
        self.user = user

    @staticmethod
    def validate_experiment_date_range(start_date: datetime | None, end_date: datetime | None) -> None:
        """Validate experiment start/end date ordering."""
        if start_date and end_date and start_date >= end_date:
            raise ValidationError("End date must be after start date")

    @staticmethod
    def validate_variant_shapes(parameters: dict | None) -> None:
        """Validate that variant entries are well-formed dicts with required keys.

        This catches malformed input early before it reaches FeatureFlagSerializer,
        preventing unhandled KeyError/AttributeError 500s.
        """
        if not parameters:
            return
        variants = parameters.get("feature_flag_variants", [])
        for i, variant in enumerate(variants):
            if not isinstance(variant, dict):
                raise ValidationError(f"Feature flag variant at index {i} must be an object")
            if "key" not in variant:
                raise ValidationError(f"Feature flag variant at index {i} must have a 'key' field")

    @staticmethod
    def validate_variant_percentages(parameters: dict | None) -> None:
        """Each variant must carry split_percent (recommended) or rollout_percentage (deprecated).

        The API serializer translates split_percent to rollout_percentage before this runs, but we
        check for either field so direct service callers (facade, max_tools) are also covered.
        Once we fully migrate to split_percent, we can remove this validation and make split_percent
        required in the type system instead.
        """
        if not parameters:
            return
        for variant in parameters.get("feature_flag_variants", []) or []:
            if not isinstance(variant, dict):
                continue  # validate_variant_shapes handles this
            if "split_percent" not in variant and "rollout_percentage" not in variant:
                raise ValidationError(
                    "Each variant must include split_percent (recommended) or rollout_percentage (deprecated)."
                )

    @staticmethod
    def validate_experiment_parameters(parameters: dict | None) -> None:
        """Validate experiment parameters accepted by the API layer.

        Includes shape validation plus count/control checks.
        Called from the serializer where the full parameter set is available.
        """
        if not parameters:
            return

        ExperimentService.validate_variant_shapes(parameters)
        ExperimentService.validate_variant_percentages(parameters)

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
            if kind in LEGACY_METRIC_KINDS:
                raise ValidationError(
                    f"Invalid metric at index {i}: legacy metric kind '{kind}' is no longer supported for new experiments. "
                    "Use 'ExperimentMetric' instead."
                )

            if kind != "ExperimentMetric":
                raise ValidationError(f"Invalid metric at index {i}: metric kind must be 'ExperimentMetric'")

            if kind == "ExperimentMetric":
                try:
                    validated_metric = ExperimentMetric.model_validate(metric)

                    # ExperimentMetric is a RootModel wrapping a union, so access .root to get the actual type
                    actual_metric = validated_metric.root
                    if isinstance(actual_metric, ExperimentFunnelMetric):
                        # The experiment exposure event is prepended as step_0 at query time,
                        # so series must contain at least one user-supplied step for the funnel
                        # to yield a meaningful conversion metric.
                        if not actual_metric.series:
                            raise ValidationError(
                                f"Invalid metric at index {i}: funnel metrics require at least one step. "
                                "The experiment exposure event is added as the initial step automatically."
                            )
                        # Additional validation for funnel metrics with DW steps
                        FunnelDWValidator.validate_funnel_metric(actual_metric)

                except pydantic.ValidationError as e:
                    raise ValidationError(f"Invalid metric at index {i}: {e.errors()}")

    VALID_STATS_METHODS = {"bayesian", "frequentist"}

    EXPERIMENT_ORDER_ALLOWLIST = {
        "created_at",
        "-created_at",
        "updated_at",
        "-updated_at",
        "name",
        "-name",
        "start_date",
        "-start_date",
        "end_date",
        "-end_date",
        "duration",
        "-duration",
        "status",
        "-status",
    }

    ELIGIBLE_FLAGS_ORDER_ALLOWLIST = {
        "created_at",
        "-created_at",
        "key",
        "-key",
        "name",
        "-name",
    }

    @classmethod
    def validate_stats_config(cls, stats_config: dict | None) -> None:
        """Validate stats_config shape and method value."""
        if not stats_config:
            return
        method = stats_config.get("method")
        if method is not None and method not in cls.VALID_STATS_METHODS:
            raise ValidationError(
                f"Invalid stats method: '{method}'. Must be one of: {', '.join(sorted(cls.VALID_STATS_METHODS))}"
            )

    @staticmethod
    def validate_no_duplicate_metric_uuids(*metric_lists: list | None) -> None:
        """Reject metrics with duplicate UUIDs across all provided metric lists."""
        seen: set[str] = set()
        for metrics in metric_lists:
            if not metrics:
                continue
            for metric in metrics:
                if not isinstance(metric, dict):
                    continue
                uuid = metric.get("uuid")
                if uuid is not None:
                    if uuid in seen:
                        raise ValidationError(f"Duplicate metric UUID: '{uuid}'. Each metric must have a unique UUID.")
                    seen.add(uuid)

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

    @staticmethod
    def _extract_entity_nodes(metrics: list[dict] | None) -> tuple[set[str], set[int]]:
        """Extract event names and action IDs from all EventsNode/ActionsNode refs in metrics."""
        event_names: set[str] = set()
        action_ids: set[int] = set()
        if not metrics:
            return event_names, action_ids

        for metric in metrics:
            nodes: list[dict] = []
            metric_type = metric.get("metric_type")
            if metric_type == "mean":
                if source := metric.get("source"):
                    nodes.append(source)
            elif metric_type == "funnel":
                nodes.extend(metric.get("series") or [])
            elif metric_type == "ratio":
                if num := metric.get("numerator"):
                    nodes.append(num)
                if den := metric.get("denominator"):
                    nodes.append(den)
            elif metric_type == "retention":
                if se := metric.get("start_event"):
                    nodes.append(se)
                if ce := metric.get("completion_event"):
                    nodes.append(ce)

            for node in nodes:
                kind = node.get("kind")
                if kind == "EventsNode":
                    event = node.get("event")
                    # Treat None and empty/whitespace-only strings as "no event"
                    # (semantically equivalent to "All events"). The pydantic
                    # schema permits "" but it can't reference a real event.
                    if isinstance(event, str) and event.strip():
                        event_names.add(event)
                    elif event is not None and not isinstance(event, str):
                        # Pydantic should have rejected non-str/None upstream;
                        # log so we can catch any path that bypassed validation
                        # rather than silently dropping the value.
                        logger.warning(
                            "experiment_metric_unexpected_event_type",
                            event_type=type(event).__name__,
                            event_value=repr(event)[:100],
                        )
                elif kind == "ActionsNode":
                    if (action_id := node.get("id")) is not None:
                        action_ids.add(int(action_id))

        return event_names, action_ids

    @classmethod
    def validate_metric_action_ids(cls, metrics: list[dict] | None, team_id: int) -> None:
        """Validate that all ActionsNode IDs reference existing, non-deleted actions for the team.

        Actions are explicitly created entities with stable IDs, so a reference to a
        nonexistent action is almost certainly a mistake, so we raise a hard validation error.
        """
        _, action_ids = cls._extract_entity_nodes(metrics)
        if not action_ids:
            return

        existing_ids = set(
            Action.objects.filter(
                id__in=action_ids,
                team_id=team_id,
                deleted=False,
            ).values_list("id", flat=True)
        )
        missing = action_ids - existing_ids
        if missing:
            missing_str = ", ".join(str(aid) for aid in sorted(missing))
            raise ValidationError(
                f"Action(s) with ID {missing_str} not found or deleted. "
                "Each ActionsNode must reference an existing action belonging to this project."
            )

    def validate_metric_event_names(self, metrics: list[dict] | None) -> None:
        """Validate that all EventsNode event names have been seen by this project.

        The frontend event picker already prevents selecting unknown events, so an
        unrecognized name coming through the API is almost certainly a typo.
        Callers that intentionally reference not-yet-ingested events (e.g. setting up
        an experiment before deploying the emitting code) can pass
        ``allow_unknown_events=True`` to bypass this check.

        Scope must match the picker: the EventDefinition list endpoint is
        project-scoped (see posthog/api/event_definition.py), so a user in a
        multi-team project can pick an event ingested by a sibling team. We
        mirror that scope here to avoid rejecting legitimate selections.
        """
        event_names, _ = self._extract_entity_nodes(metrics)
        if not event_names:
            return

        from products.event_definitions.backend.models.event_definition import EventDefinition

        project_id = self.team.project_id
        # Uses `team_id = project_id` (not team_id = self.team.id)
        # on purpose: legacy EventDefinitions (project_id IS NULL) belong to the
        # *primary* team, and primary_team.id == project.id by convention. This
        # mirrors the picker SQL in posthog/api/event_definition.py so sibling
        # teams can validate against legacy primary-team events the picker shows.
        existing = set(
            EventDefinition.objects.filter(
                Q(project_id=project_id) | Q(project_id__isnull=True, team_id=project_id),
                name__in=event_names,
            ).values_list("name", flat=True)
        )
        unknown = event_names - existing
        if unknown:
            # Capture the rejected payload shape so we can identify clients
            # that send malformed metrics (e.g. event="").
            logger.warning(
                "experiment_metric_event_validation_rejected",
                team_id=self.team.id,
                project_id=project_id,
                unknown_events=sorted(unknown),
                all_extracted_events=sorted(event_names),
                metrics_count=len(metrics) if metrics else 0,
            )
            unknown_str = ", ".join(f"'{name}'" for name in sorted(unknown))
            raise ValidationError(
                f"Event(s) {unknown_str} not found. "
                "No events with these names have been ingested by this project. "
                "If this is intentional, set allow_unknown_events=True."
            )

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
        only_count_matured_users: bool | None = None,
        archived: bool = False,
        deleted: bool = False,
        conclusion: str | None = None,
        conclusion_comment: str | None = None,
        serializer_context: dict | None = None,
        event_source: EventSource | None = None,
        allow_unknown_events: bool = False,
        creation_mode: ExperimentCreationMode = "new",
    ) -> Experiment:
        """Create experiment with full validation and defaults."""
        metrics = self._assign_uuids_to_metrics(metrics)
        metrics_secondary = self._assign_uuids_to_metrics(metrics_secondary)
        self.validate_variant_shapes(parameters)
        self.validate_variant_percentages(parameters)
        self.validate_experiment_metrics(metrics)
        self.validate_experiment_metrics(metrics_secondary)
        self.validate_metric_action_ids(metrics, self.team.id)
        self.validate_metric_action_ids(metrics_secondary, self.team.id)
        if not allow_unknown_events:
            self.validate_metric_event_names(metrics)
            self.validate_metric_event_names(metrics_secondary)
        self.validate_stats_config(stats_config)
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

        team_config = self._get_team_experiments_config()
        stats_config = self._apply_stats_config_defaults(stats_config, team_config)
        exposure_criteria = self._apply_exposure_criteria_defaults(exposure_criteria)

        if only_count_matured_users is None:
            only_count_matured_users = team_config.default_only_count_matured_users

        stats_method = "bayesian" if stats_config is None else stats_config.get("method", "bayesian")
        if metrics is not None:
            for metric in metrics:
                metric["fingerprint"] = compute_metric_fingerprint(
                    metric,
                    start_date,
                    stats_method,
                    exposure_criteria,
                    only_count_matured_users=only_count_matured_users,
                )
        if metrics_secondary is not None:
            for metric in metrics_secondary:
                metric["fingerprint"] = compute_metric_fingerprint(
                    metric,
                    start_date,
                    stats_method,
                    exposure_criteria,
                    only_count_matured_users=only_count_matured_users,
                )

        self.validate_no_duplicate_metric_uuids(metrics, metrics_secondary)

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
            "only_count_matured_users": only_count_matured_users,
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
            allow_unknown_events=allow_unknown_events,
            creation_mode=creation_mode,
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
        allow_unknown_events: bool = False,
        creation_mode: ExperimentCreationMode,
    ) -> None:
        request = serializer_context.get("request") if serializer_context else None
        if request is None and event_source is None:
            return

        analytics_metadata = experiment.get_analytics_metadata()
        analytics_metadata["creation_mode"] = creation_mode
        if event_source is not None:
            analytics_metadata["source"] = event_source
        if allow_unknown_events:
            analytics_metadata["allow_unknown_events"] = True

        report_user_action(
            self.user,
            "experiment created",
            analytics_metadata,
            team=experiment.team,
            request=request,
        )

    def _report_experiment_launched(
        self,
        experiment: Experiment,
        *,
        request: Any | None = None,
    ) -> None:
        if request is None:
            return

        analytics_metadata = experiment.get_analytics_metadata()
        analytics_metadata["launch_date"] = experiment.start_date.isoformat() if experiment.start_date else None

        report_user_action(
            self.user,
            "experiment launched",
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
        else:
            feature_flag_data["ensure_experience_continuity"] = self.team.flags_persistence_default or False
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

    @staticmethod
    def _assign_uuids_to_metrics(metrics: list[dict] | None) -> list[dict] | None:
        """Return a deep copy of ``metrics`` with a ``uuid`` filled in on every entry.

        Run this before metric validation so the validated dict already carries its
        final uuid. Callers pass dicts by reference, so we deepcopy to avoid leaking
        the generated uuid back into their data.
        """
        if metrics is None:
            return None
        prepared = deepcopy(metrics)
        for metric in prepared:
            if not metric.get("uuid"):
                metric["uuid"] = str(uuid4())
        return prepared

    @staticmethod
    def _recompute_fingerprints(
        metrics: list[dict],
        start_date: datetime | None,
        stats_config: dict | None,
        exposure_criteria: dict | None,
        only_count_matured_users: bool = False,
    ) -> list[dict]:
        """Recompute fingerprints for a list of metrics. Returns a new list with updated fingerprints."""
        stats_method = "bayesian" if stats_config is None else stats_config.get("method", "bayesian")
        updated = []
        for metric in metrics:
            metric_copy = deepcopy(metric)
            metric_copy["fingerprint"] = compute_metric_fingerprint(
                metric_copy,
                start_date,
                stats_method,
                exposure_criteria,
                only_count_matured_users=only_count_matured_users,
            )
            updated.append(metric_copy)
        return updated

    def _get_team_experiments_config(self) -> TeamExperimentsConfig:
        return get_or_create_team_extension(self.team, TeamExperimentsConfig)

    def _apply_stats_config_defaults(
        self, stats_config: dict | None, team_config: TeamExperimentsConfig | None = None
    ) -> dict:
        """Apply team-level defaults to stats_config."""
        result = dict(stats_config or {})
        config = team_config or self._get_team_experiments_config()

        if not result.get("method"):
            default_method = config.default_experiment_stats_method or "bayesian"
            result["method"] = default_method

        if config.default_experiment_confidence_level is not None:
            confidence_level = float(config.default_experiment_confidence_level)
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
    # Launch
    # ------------------------------------------------------------------

    @transaction.atomic
    def launch_experiment(self, experiment: Experiment, *, request: Any | None = None) -> Experiment:
        """Launch a draft experiment: validate readiness, set start_date, activate feature flag."""
        if not experiment.is_draft:
            raise ValidationError("Experiment has already been launched.")

        # Validate feature flag configuration
        feature_flag = experiment.feature_flag
        if feature_flag.deleted:
            raise ValidationError("Experiment cannot be launched because its feature flag has been deleted.")
        self._validate_existing_flag(feature_flag)

        # Set start_date
        experiment.start_date = timezone.now()

        # Recompute metric fingerprints with the new start_date
        for metric_field in ["metrics", "metrics_secondary"]:
            metrics = getattr(experiment, metric_field, None)
            if metrics:
                setattr(
                    experiment,
                    metric_field,
                    self._recompute_fingerprints(
                        metrics, experiment.start_date, experiment.stats_config, experiment.exposure_criteria
                    ),
                )

        # Activate feature flag
        feature_flag.active = True
        feature_flag.save()

        experiment.save()

        self._report_experiment_launched(experiment, request=request)

        return experiment

    # ------------------------------------------------------------------
    # Archive
    # ------------------------------------------------------------------

    @transaction.atomic
    def archive_experiment(self, experiment: Experiment, *, request: Any | None = None) -> Experiment:
        """Archive an ended experiment: validate it has ended, set archived=True."""
        if experiment.archived:
            raise ValidationError("Experiment is already archived.")
        if not experiment.is_stopped:
            raise ValidationError("Experiment must be ended before it can be archived.")

        experiment.archived = True
        experiment.save()

        self._report_experiment_archived(experiment, request=request)

        return experiment

    def _report_experiment_archived(
        self,
        experiment: Experiment,
        *,
        request: Any | None = None,
    ) -> None:
        if request is None:
            return

        report_user_action(
            self.user,
            "experiment archived",
            experiment.get_analytics_metadata(),
            team=experiment.team,
            request=request,
        )

    # ------------------------------------------------------------------
    # Unarchive
    # ------------------------------------------------------------------

    def unarchive_experiment(self, experiment: Experiment, *, request: Any | None = None) -> Experiment:
        """Unarchive an archived experiment: validate it is archived, set archived=False."""
        if not experiment.archived:
            raise ValidationError("Experiment is not archived.")

        experiment.archived = False
        experiment.save()

        self._report_experiment_unarchived(experiment, request=request)

        return experiment

    def _report_experiment_unarchived(
        self,
        experiment: Experiment,
        *,
        request: Any | None = None,
    ) -> None:
        if request is None:
            return

        report_user_action(
            self.user,
            "experiment unarchived",
            experiment.get_analytics_metadata(),
            team=experiment.team,
            request=request,
        )

    # ------------------------------------------------------------------
    # Pause / Resume
    # ------------------------------------------------------------------

    @transaction.atomic
    def pause_experiment(self, experiment: Experiment, *, request: Any | None = None) -> Experiment:
        """Pause a running experiment: deactivate its feature flag so it is no longer served by /decide."""
        if experiment.is_draft:
            raise ValidationError("Experiment has not been launched yet.")
        if experiment.is_stopped:
            raise ValidationError("Experiment has already ended.")

        feature_flag = experiment.feature_flag
        if feature_flag is None:
            raise ValidationError("Experiment does not have a feature flag linked.")
        if not feature_flag.active:
            raise ValidationError("Experiment is already paused.")

        feature_flag.active = False
        feature_flag.save(update_fields=["active"])

        # Re-fetch so the serializer sees the updated flag
        experiment.feature_flag = feature_flag

        self._report_experiment_paused(experiment, request=request)

        return experiment

    @transaction.atomic
    def resume_experiment(self, experiment: Experiment, *, request: Any | None = None) -> Experiment:
        """Resume a paused experiment: reactivate its feature flag so /decide serves variants again."""
        if experiment.is_draft:
            raise ValidationError("Experiment has not been launched yet.")
        if experiment.is_stopped:
            raise ValidationError("Experiment has already ended.")

        feature_flag = experiment.feature_flag
        if feature_flag is None:
            raise ValidationError("Experiment does not have a feature flag linked.")
        if feature_flag.active:
            raise ValidationError("Experiment is not paused.")

        feature_flag.active = True
        feature_flag.save(update_fields=["active"])

        # Re-fetch so the serializer sees the updated flag
        experiment.feature_flag = feature_flag

        self._report_experiment_resumed(experiment, request=request)

        return experiment

    def _report_experiment_paused(
        self,
        experiment: Experiment,
        *,
        request: Any | None = None,
    ) -> None:
        if request is None:
            return

        report_user_action(
            self.user,
            "experiment paused",
            experiment.get_analytics_metadata(),
            team=experiment.team,
            request=request,
        )

    def _report_experiment_resumed(
        self,
        experiment: Experiment,
        *,
        request: Any | None = None,
    ) -> None:
        if request is None:
            return

        report_user_action(
            self.user,
            "experiment resumed",
            experiment.get_analytics_metadata(),
            team=experiment.team,
            request=request,
        )

    # ------------------------------------------------------------------
    # End
    # ------------------------------------------------------------------

    @transaction.atomic
    def end_experiment(
        self,
        experiment: Experiment,
        *,
        conclusion: str | None = None,
        conclusion_comment: str | None = None,
        request: Any | None = None,
    ) -> Experiment:
        """End a running experiment: set end_date and mark as stopped.

        Freezes the results window — experiment results will only include data
        up to end_date. Does NOT modify the feature flag; users continue to see
        their assigned variants.
        """
        if experiment.is_draft:
            raise ValidationError("Experiment has not been launched yet.")
        if experiment.is_stopped:
            raise ValidationError("Experiment has already ended.")

        experiment.end_date = timezone.now()
        experiment.conclusion = conclusion
        experiment.conclusion_comment = conclusion_comment
        experiment.save()

        self._report_experiment_ended(experiment, request=request)

        return experiment

    def _report_experiment_ended(
        self,
        experiment: Experiment,
        *,
        request: Any | None = None,
    ) -> None:
        if request is None:
            return

        completed_metadata = experiment.get_analytics_metadata()
        completed_metadata["end_date"] = experiment.end_date.isoformat() if experiment.end_date else None
        completed_metadata["parameters"] = experiment.parameters
        completed_metadata["saved_metrics_count"] = experiment.saved_metrics.count()
        completed_metadata["stats_method"] = (experiment.stats_config or {}).get("method", "bayesian")
        if experiment.start_date and experiment.end_date:
            completed_metadata["duration"] = int((experiment.end_date - experiment.start_date).total_seconds())

        # Look up whether the primary metric reached significance from the
        # latest cached result in Postgres (ExperimentMetricResult). This is
        # safe to call here because it's a simple indexed lookup — it reads
        # previously cached results, never triggers a ClickHouse query or
        # result computation. Returns None immediately if no results exist yet.
        try:
            first_metric = experiment.metrics[0] if experiment.metrics else None
            if first_metric and first_metric.get("uuid"):
                metric_result = (
                    ExperimentMetricResult.objects.filter(
                        experiment=experiment,
                        metric_uuid=first_metric["uuid"],
                        status=ExperimentMetricResult.Status.COMPLETED,
                    )
                    .order_by("-completed_at")
                    .first()
                )
                if metric_result and metric_result.result:
                    completed_metadata["significant"] = metric_result.result.get("significant", False)
        except Exception:
            logger.exception(
                "Failed to look up metric significance",
                experiment_id=experiment.id,
            )

        # Outcome event with enriched data (duration, end_date) for analyzing experiment quality and duration patterns.
        report_user_action(
            self.user,
            "experiment completed",
            completed_metadata,
            team=experiment.team,
            request=request,
        )

        # Lifecycle event with standard experiment metadata, consistent with paused/resumed/reset tracking.
        report_user_action(
            self.user,
            "experiment stopped",
            experiment.get_analytics_metadata(),
            team=experiment.team,
            request=request,
        )

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    @transaction.atomic
    def reset_experiment(self, experiment: Experiment, *, request: Any | None = None) -> Experiment:
        """Reset an experiment back to draft state so it can be re-run.

        The feature flag stays unchanged — users continue to see their assigned
        variants. Only the experiment dates, conclusion, and archived flag are
        cleared, moving the experiment back to draft state.
        """
        if experiment.is_draft:
            raise ValidationError("Experiment is already in draft state.")

        experiment.start_date = None
        experiment.end_date = None
        experiment.archived = False
        experiment.conclusion = None
        experiment.conclusion_comment = None

        experiment.save()

        self._report_experiment_reset(experiment, request=request)

        return experiment

    def _report_experiment_reset(
        self,
        experiment: Experiment,
        *,
        request: Any | None = None,
    ) -> None:
        if request is None:
            return

        report_user_action(
            self.user,
            "experiment reset",
            experiment.get_analytics_metadata(),
            team=experiment.team,
            request=request,
        )

    # ------------------------------------------------------------------
    # Ship variant
    # ------------------------------------------------------------------

    # Note that this action is not @transaction.atomic. This is because we go through
    # the FeatureFlagSerializer approval workflow, which conflicts with atomic. Since
    # this action were two separate calls from the frontend, having both calls coming
    # from the backend is already more robust (while not ideal).
    def ship_variant(
        self,
        experiment: Experiment,
        variant_key: str,
        *,
        conclusion: str | None = None,
        conclusion_comment: str | None = None,
        request: Any,
    ) -> Experiment:
        """Ship a variant to 100% of users, optionally ending the experiment.

        Rewrites the feature flag so the selected variant is served to everyone.
        Existing release conditions (flag groups) are preserved so the change can
        be rolled back by deleting the auto-added release condition in the flag UI.

        Can be called on both running and stopped experiments — supports the
        workflow where a user ends an experiment first, then ships the winner
        later. If the experiment is still running it will be ended atomically.

        The flag update goes through FeatureFlagSerializer so that the approval
        workflow (@approval_gate) is honoured. If change-request approval is
        required the serializer raises ApprovalRequired, the experiment is NOT
        ended, and a 409 is returned to the caller.

        ``request`` is required because the FeatureFlagSerializer needs a real
        request with authentication and session context for approval policy
        evaluation.
        """
        if experiment.is_draft:
            raise ValidationError("Experiment has not been launched yet.")

        flag = experiment.feature_flag
        if not flag:
            raise ValidationError("Experiment does not have a linked feature flag.")

        # Validate variant_key exists on the flag
        variants = flag.filters.get("multivariate", {}).get("variants", [])
        if not any(v["key"] == variant_key for v in variants):
            raise ValidationError(f"Variant '{variant_key}' not found on feature flag.")

        new_filters = self._transform_filters_for_winning_variant(flag.filters, variant_key)

        # Update the flag through the serializer to preserve the approval
        # workflow. If change-request approval is required, this raises
        # ApprovalRequired which surfaces as a 409 to the caller. The
        # experiment is NOT ended until the change request is approved and
        # the user retries.
        flag_serializer = FeatureFlagSerializer(
            flag,
            data={"filters": new_filters},
            partial=True,
            context={
                "request": request,
                "team_id": self.team.id,
                "project_id": self.team.project_id,
            },
        )
        flag_serializer.is_valid(raise_exception=True)
        flag_serializer.save()

        # Refresh the flag instance so the experiment's nested flag reflects
        # the updated filters when serialized in the response.
        flag.refresh_from_db()

        # End the experiment only if it's still running
        was_running = experiment.is_running
        if was_running:
            experiment.end_date = timezone.now()
        if conclusion is not None:
            experiment.conclusion = conclusion
        if conclusion_comment is not None:
            experiment.conclusion_comment = conclusion_comment
        experiment.save()

        self._report_experiment_variant_shipped(experiment, variant_key=variant_key, request=request)
        if was_running:
            self._report_experiment_ended(experiment, request=request)

        return experiment

    @staticmethod
    def _transform_filters_for_winning_variant(
        current_filters: dict,
        variant_key: str,
    ) -> dict:
        """Port of frontend transformFiltersForWinningVariant().

        Rewrites flag filters so that the selected variant gets 100% rollout
        and all others get 0%. Prepends a catch-all release condition and
        preserves existing release conditions (flag groups) for rollback.
        """
        return {
            "aggregation_group_type_index": current_filters.get("aggregation_group_type_index"),
            "payloads": current_filters.get("payloads", {}),
            "multivariate": {
                "variants": [
                    {
                        "key": v["key"],
                        "rollout_percentage": 100 if v["key"] == variant_key else 0,
                        **({"name": v["name"]} if v.get("name") else {}),
                    }
                    for v in current_filters.get("multivariate", {}).get("variants", [])
                ],
            },
            "groups": [
                {
                    "properties": [],
                    "rollout_percentage": 100,
                    "description": "Added automatically when the experiment was ended to keep only one variant.",
                },
                *(current_filters.get("groups", [])),
            ],
        }

    def _report_experiment_variant_shipped(
        self,
        experiment: Experiment,
        *,
        variant_key: str,
        request: Any | None = None,
    ) -> None:
        if request is None:
            return

        metadata = experiment.get_analytics_metadata()
        metadata["variant_key"] = variant_key
        metadata["parameters"] = experiment.parameters

        report_user_action(
            self.user,
            "experiment variant shipped",
            metadata,
            team=experiment.team,
            request=request,
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
        allow_unknown_events: bool = False,
    ) -> Experiment:
        """Update an experiment with full business-logic validation.

        ``update_data`` mirrors the DRF ``validated_data`` dict produced by
        ``ExperimentSerializer``.  The caller is responsible for DRF-level input
        validation (field types, metric schema, etc.) before calling this method.
        """
        update_feature_flag_params = update_data.pop("update_feature_flag_params", False)

        if "saved_metrics_ids" in update_data:
            self.validate_saved_metrics_ids(update_data["saved_metrics_ids"], self.team.id)
        if "metrics" in update_data:
            update_data["metrics"] = self._assign_uuids_to_metrics(update_data["metrics"])
            self.validate_experiment_metrics(update_data["metrics"])
            self.validate_metric_action_ids(update_data["metrics"], self.team.id)
            if not allow_unknown_events:
                self.validate_metric_event_names(update_data["metrics"])
        if "metrics_secondary" in update_data:
            update_data["metrics_secondary"] = self._assign_uuids_to_metrics(update_data["metrics_secondary"])
            self.validate_experiment_metrics(update_data["metrics_secondary"])
            self.validate_metric_action_ids(update_data["metrics_secondary"], self.team.id)
            if not allow_unknown_events:
                self.validate_metric_event_names(update_data["metrics_secondary"])

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

        # --- feature flag sync ------------------------------------------------
        # Draft experiments always sync parameters to the linked feature flag.
        # Running experiments only sync when update_feature_flag_params=True,
        # to prevent accidental side effects (e.g. overwrites when the frontend
        # spreads stale parameters alongside unrelated updates, or an agent
        # calls MCP with too many params).
        if experiment.is_draft or update_feature_flag_params:
            holdout = experiment.holdout
            if "holdout" in update_data:
                holdout = update_data["holdout"]

            if update_data.get("parameters"):
                variants = update_data["parameters"].get("feature_flag_variants", [])
                aggregation_group_type_index = update_data["parameters"].get("aggregation_group_type_index")

                existing_groups = feature_flag.filters.get("groups", [])
                experiment_rollout_percentage = update_data["parameters"].get("rollout_percentage")
                if experiment_rollout_percentage is not None and existing_groups:
                    new_groups = [
                        {**existing_groups[0], "rollout_percentage": experiment_rollout_percentage},
                        *existing_groups[1:],
                    ]
                else:
                    new_groups = list(existing_groups)

                new_filters = {
                    **feature_flag.filters,
                    "groups": new_groups,
                    "multivariate": {"variants": variants or list(DEFAULT_VARIANTS)},
                    "aggregation_group_type_index": aggregation_group_type_index,
                    **holdout_filters_for_flag(holdout.id if holdout else None, holdout.filters if holdout else None),
                }

                existing_flag_serializer = FeatureFlagSerializer(
                    feature_flag,
                    data={"filters": new_filters},
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

        # --- validate updated fields ------------------------------------------
        if "stats_config" in update_data:
            self.validate_stats_config(update_data["stats_config"])

        updated_primary = update_data.get("metrics", experiment.metrics)
        updated_secondary = update_data.get("metrics_secondary", experiment.metrics_secondary)
        self.validate_no_duplicate_metric_uuids(updated_primary, updated_secondary)

        # --- fingerprint recalculation -------------------------------------
        start_date = update_data.get("start_date", experiment.start_date)
        stats_config = update_data.get("stats_config", experiment.stats_config)
        exposure_criteria = update_data.get("exposure_criteria", experiment.exposure_criteria)
        only_count_matured_users = update_data.get("only_count_matured_users", experiment.only_count_matured_users)

        for metric_field in ["metrics", "metrics_secondary"]:
            metrics = update_data.get(metric_field, getattr(experiment, metric_field, None))
            if metrics:
                update_data[metric_field] = self._recompute_fingerprints(
                    metrics,
                    start_date,
                    stats_config,
                    exposure_criteria,
                    only_count_matured_users=only_count_matured_users,
                )

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
        # Prevent restoring a deleted experiment if the linked feature flag is also deleted
        if experiment.deleted and update_data.get("deleted") is False and feature_flag.deleted:
            raise ValidationError(
                "Cannot restore experiment: the linked feature flag has been deleted. "
                "Restore the feature flag first, then restore the experiment."
            )

        # Check for legacy metrics first
        if experiment_has_legacy_metrics(experiment):
            allowed_fields = {"name", "description", "end_date", "deleted"}
            update_fields = set(update_data.keys())

            # Remove internal fields that are handled separately
            update_fields.discard("get_feature_flag_key")

            disallowed_fields = update_fields - allowed_fields
            if disallowed_fields:
                raise ValidationError(
                    f"This experiment uses legacy metric formats and can only have its name, description, or end_date updated. "
                    f"Cannot update: {', '.join(sorted(disallowed_fields))}"
                )

            # Validate end_date if present
            if "end_date" in update_data:
                self.validate_experiment_date_range(experiment.start_date, update_data["end_date"])

            # If only allowed fields are being updated, skip the rest of the validation
            return

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
            "only_count_matured_users",
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

    def clone_experiment(
        self,
        source_experiment: Experiment,
        *,
        target_team: Team | None = None,
        feature_flag_key: str | None = None,
        name: str | None = None,
        serializer_context: dict | None = None,
    ) -> Experiment:
        """Clone an experiment as a new draft, optionally into a different project.

        Warning: if feature_flag_key is None or matches the source experiment's
        flag key, the duplicate will reuse the same FeatureFlag instance. This
        means lifecycle operations on either experiment (pause, ship, etc.) will
        affect both. Callers should provide a unique feature_flag_key.
        """
        target = target_team or self.team
        is_cross_project = target.id != self.team.id
        if feature_flag_key is None:
            feature_flag_key = source_experiment.feature_flag.key

        parameters = deepcopy(source_experiment.parameters) or {}

        # Reuse variants from an existing flag in the target project.
        # For cross-project clones we always check the target; for same-project
        # clones we only check when the key differs from the source flag.
        should_check_existing = is_cross_project or feature_flag_key != source_experiment.feature_flag.key
        if should_check_existing:
            existing_flag = FeatureFlag.objects.filter(key=feature_flag_key, team_id=target.id).first()
            if existing_flag and existing_flag.filters.get("multivariate", {}).get("variants"):
                parameters["feature_flag_variants"] = deepcopy(existing_flag.filters["multivariate"]["variants"])

        self.validate_experiment_parameters(parameters)
        self.validate_experiment_exposure_criteria(source_experiment.exposure_criteria)
        self.validate_experiment_metrics(source_experiment.metrics)
        self.validate_experiment_metrics(source_experiment.metrics_secondary)

        if name:
            clone_name = name
        else:
            base_name = f"{source_experiment.name} (Copy)"
            clone_name = base_name
            counter = 1
            while Experiment.objects.filter(team_id=target.id, name=clone_name, deleted=False).exists():
                clone_name = f"{base_name} {counter}"
                counter += 1

        # Saved metrics are team-scoped — only copy for same-project clones.
        saved_metrics_data: list[dict] | None = None
        if not is_cross_project:
            saved_metrics_data = [
                {"id": link.saved_metric.id, "metadata": link.metadata}
                for link in source_experiment.experimenttosavedmetric_set.all()
            ] or None

        service = ExperimentService(team=target, user=self.user) if is_cross_project else self
        creation_mode: ExperimentCreationMode = "copy_to_project" if is_cross_project else "duplicate"
        return service.create_experiment(
            name=clone_name,
            feature_flag_key=feature_flag_key,
            description=source_experiment.description or "",
            type=source_experiment.type or "product",
            parameters=parameters,
            filters=source_experiment.filters,
            metrics=deepcopy(source_experiment.metrics),
            metrics_secondary=deepcopy(source_experiment.metrics_secondary),
            stats_config=source_experiment.stats_config,
            scheduling_config=source_experiment.scheduling_config,
            exposure_criteria=source_experiment.exposure_criteria,
            saved_metrics_ids=saved_metrics_data,
            primary_metrics_ordered_uuids=source_experiment.primary_metrics_ordered_uuids,
            secondary_metrics_ordered_uuids=source_experiment.secondary_metrics_ordered_uuids,
            only_count_matured_users=source_experiment.only_count_matured_users,
            serializer_context=serializer_context,
            # For duplicate we set allow_unknown_events since the goal here is to actually duplicate:
            allow_unknown_events=True,
            creation_mode=creation_mode,
        )

    def duplicate_experiment(
        self,
        source_experiment: Experiment,
        *,
        feature_flag_key: str | None = None,
        name: str | None = None,
        serializer_context: dict | None = None,
    ) -> Experiment:
        """Duplicate an experiment as a new draft."""
        return self.clone_experiment(
            source_experiment,
            feature_flag_key=feature_flag_key,
            name=name,
            serializer_context=serializer_context,
        )

    def copy_experiment_to_project(
        self,
        source_experiment: Experiment,
        target_team: Team,
        *,
        feature_flag_key: str | None = None,
        name: str | None = None,
        serializer_context: dict | None = None,
    ) -> Experiment:
        """Duplicate an experiment as a new draft in a different project."""
        return self.clone_experiment(
            source_experiment,
            target_team=target_team,
            feature_flag_key=feature_flag_key,
            name=name,
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
    # Experiment list/querying
    # ------------------------------------------------------------------

    def filter_experiments_queryset(
        self,
        queryset: QuerySet[Experiment],
        *,
        action: str | None,
        query_params: Mapping[str, Any] | None = None,
        request_data: Mapping[str, Any] | None = None,
    ) -> QuerySet[Experiment]:
        """Apply experiment list/detail filtering and ordering rules."""
        query_params = query_params or {}
        request_data = request_data or {}

        include_deleted = False
        if action in ("partial_update", "update"):
            deleted_value = request_data.get("deleted")
            if deleted_value is not None:
                include_deleted = not str_to_bool(deleted_value)

        if not include_deleted:
            queryset = queryset.exclude(deleted=True)

        if action == "list":
            status = query_params.get("status")
            if status:
                normalized_status = str(status).lower()
                if normalized_status == "complete":
                    normalized_status = ExperimentQueryStatus.STOPPED.value

                try:
                    status_enum = ExperimentQueryStatus(normalized_status)
                except ValueError:
                    status_enum = None

                if status_enum and status_enum != ExperimentQueryStatus.ALL:
                    if status_enum == ExperimentQueryStatus.DRAFT:
                        queryset = queryset.filter(
                            Q(status=Experiment.Status.DRAFT) | Q(status__isnull=True, start_date__isnull=True)
                        )
                    elif status_enum == ExperimentQueryStatus.RUNNING:
                        queryset = queryset.filter(
                            Q(feature_flag__active=True)
                            & (
                                Q(status=Experiment.Status.RUNNING)
                                | Q(status__isnull=True, start_date__isnull=False, end_date__isnull=True)
                            )
                        )
                    elif status_enum == ExperimentQueryStatus.PAUSED:
                        queryset = queryset.filter(
                            Q(feature_flag__active=False)
                            & (
                                Q(status=Experiment.Status.RUNNING)
                                | Q(status__isnull=True, start_date__isnull=False, end_date__isnull=True)
                            )
                        )
                    elif status_enum == ExperimentQueryStatus.STOPPED:
                        queryset = queryset.filter(
                            Q(status=Experiment.Status.STOPPED) | Q(status__isnull=True, end_date__isnull=False)
                        )

            created_by_id = query_params.get("created_by_id")
            if created_by_id:
                queryset = queryset.filter(created_by_id=created_by_id)

            archived = query_params.get("archived")
            if archived is not None:
                archived_bool = str(archived).lower() == "true"
                queryset = queryset.filter(archived=archived_bool)
            else:
                queryset = queryset.filter(archived=False)

            feature_flag_id = query_params.get("feature_flag_id")
            if feature_flag_id:
                try:
                    queryset = queryset.filter(feature_flag_id=int(feature_flag_id))
                except ValueError:
                    raise ValidationError("feature_flag_id must be an integer")

        search = query_params.get("search")
        if search:
            queryset = queryset.filter(Q(name__icontains=search))

        order = query_params.get("order")
        if order:
            order_value = str(order)
            if order_value not in self.EXPERIMENT_ORDER_ALLOWLIST:
                raise ValidationError(f"Invalid order field: '{order_value}'")
            if order_value in ["duration", "-duration"]:
                queryset = queryset.annotate(
                    computed_duration=Case(
                        When(start_date__isnull=True, then=Value(None)),
                        When(end_date__isnull=False, then=F("end_date") - F("start_date")),
                        default=Now() - F("start_date"),
                    )
                )
                queryset = queryset.order_by(f"{'-' if order_value.startswith('-') else ''}computed_duration")
            elif order_value in ["status", "-status"]:
                queryset = queryset.annotate(
                    status_sort_key=Case(
                        When(start_date__isnull=True, then=Value(0)),
                        When(end_date__isnull=True, then=Value(1)),
                        default=Value(2),
                    )
                )
                if order_value.startswith("-"):
                    queryset = queryset.order_by(F("status_sort_key").desc())
                else:
                    queryset = queryset.order_by(F("status_sort_key").asc())
            else:
                queryset = queryset.order_by(order_value)
        else:
            queryset = queryset.order_by("-created_at")

        return queryset

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
        has_evaluation_contexts: str | bool | None = None,
    ) -> dict[str, Any]:
        """Get feature flags eligible for use in experiments."""
        queryset = self._get_eligible_feature_flags_queryset(
            excluded_flag_ids=excluded_flag_ids,
            search=search,
            active=active,
            created_by_id=created_by_id,
            order=order,
            evaluation_runtime=evaluation_runtime,
            has_evaluation_contexts=has_evaluation_contexts,
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
        has_evaluation_contexts: str | bool | None,
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

        if has_evaluation_contexts is not None:
            filter_value = (
                has_evaluation_contexts
                if isinstance(has_evaluation_contexts, bool)
                else str(has_evaluation_contexts).lower() in ("true", "1", "yes")
            )
            queryset = queryset.annotate(eval_context_count=Count("flag_evaluation_contexts"))
            if filter_value:
                queryset = queryset.filter(eval_context_count__gt=0)
            else:
                queryset = queryset.filter(eval_context_count=0)

        if order and order not in self.ELIGIBLE_FLAGS_ORDER_ALLOWLIST:
            raise ValidationError(f"Invalid order field: '{order}'")

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
        if not experiment.is_launched:
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
