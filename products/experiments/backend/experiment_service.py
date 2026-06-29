"""Experiment service — single source of truth for experiment business logic."""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Case, CharField, Count, F, Prefetch, Q, QuerySet, Value, When
from django.db.models.functions import Coalesce, Now, NullIf
from django.utils import timezone

import pydantic
import structlog
from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.schema import (
    ActionsNode,
    ExperimentEventExposureConfig,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetric,
)

from posthog.api.cohort import CohortSerializer
from posthog.event_usage import EventSource, report_user_action
from posthog.models.activity_logging.utils import get_changed_fields_local
from posthog.models.filters.filter import Filter
from posthog.models.signals import mute_selected_signals
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.rbac.user_access_control import UserAccessControl
from posthog.utils import str_to_bool

from products.actions.backend.models.action import Action
from products.approvals.backend.policies import PolicyEngine
from products.cohorts.backend.models.cohort import Cohort
from products.experiments.backend.hogql_queries.base_query_utils import is_threshold_supported_math
from products.experiments.backend.hogql_queries.experiment_metric_fingerprint import compute_metric_fingerprint
from products.experiments.backend.hogql_queries.funnel_validation import FunnelDWValidator
from products.experiments.backend.metric_utils import filter_metric_group_ids_by_event
from products.experiments.backend.models.experiment import (
    LEGACY_METRIC_KINDS,
    Experiment,
    ExperimentHoldout,
    ExperimentMetricResult,
    ExperimentSavedMetric,
    ExperimentTimeseriesRecalculation,
    ExperimentToSavedMetric,
    experiment_has_legacy_metrics,
    holdout_filters_for_flag,
)
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.result_serialization import strip_step_sessions
from products.experiments.backend.warehouse_access_control import enforce_warehouse_metric_access
from products.feature_flags.backend.api.feature_flag import (
    FeatureFlagSerializer,
    parse_created_by_ids,
    raise_if_flag_has_dependents,
)
from products.feature_flags.backend.models.evaluation_context import FeatureFlagEvaluationContext
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    SourceType,
    TargetType,
    create_notification,
)

from ee.clickhouse.views.experiment_saved_metrics import ExperimentToSavedMetricSerializer
from ee.hogai.context.experiment.format import ExperimentTimeseriesFormatter

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
            keys = [variant["key"] for variant in variants]
            if "control" not in keys:
                # Surface the keys we did receive so LLM callers can self-correct without a
                # second roundtrip. Capitalized 'Control' is auto-normalized in
                # ExperimentParametersField.to_internal_value, so anything reaching this
                # branch genuinely lacks a baseline variant.
                raise ValidationError(
                    "Feature flag variants must contain a variant with key 'control' "
                    f"(lowercase, exactly). Got keys: {keys}. Rename the baseline variant's "
                    "'key' to 'control'."
                )

    @staticmethod
    def _validate_excluded_variant_keys(
        excluded_variants: list[str], variant_keys: Iterable[str], baseline_key: str
    ) -> None:
        """Semantic checks for excluded variants against an already-resolved variant set.

        Variant keys come from the linked feature flag (the source of truth), so the canonical
        `excluded_variants` path validates without re-sending `feature_flag_variants`.
        """
        if not excluded_variants:
            return

        variant_key_set = set(variant_keys)

        holdout_excluded = {k for k in excluded_variants if k.startswith("holdout-")}
        if holdout_excluded:
            raise ValidationError(f"cannot exclude holdout pseudo-variants: {sorted(holdout_excluded)}")

        if baseline_key in excluded_variants:
            raise ValidationError(f"baseline variant cannot be excluded ('{baseline_key}')")

        unknown = set(excluded_variants) - variant_key_set
        if unknown:
            raise ValidationError(f"unknown variants for this experiment: {sorted(unknown)}")

        if not variant_key_set - set(excluded_variants) - {baseline_key}:
            raise ValidationError("at least one test variant must remain in analysis")

    @staticmethod
    def validate_excluded_variants(value: list[str] | None) -> None:
        """Shape check for the canonical excluded_variants list (the serializer also enforces
        this via ListField, but direct service callers don't go through it).

        Semantic checks (holdout/baseline/unknown/at-least-one-remains) run in create/update
        against the resolved feature-flag variants — see ``_validate_excluded_variant_keys``.
        """
        if value is None:
            return
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValidationError("excluded_variants must be a list of strings")

    RUNNING_TIME_CALCULATION_KEYS = (
        "minimum_detectable_effect",
        "recommended_running_time",
        "recommended_sample_size",
        "exposure_estimate_config",
    )

    @staticmethod
    def validate_running_time_calculation(value: dict | None) -> None:
        """Validate the running-time calculator config accepted by the API layer."""
        if not value:
            return
        if not isinstance(value, dict):
            raise ValidationError("running_time_calculation must be an object")

        unknown = set(value.keys()) - set(ExperimentService.RUNNING_TIME_CALCULATION_KEYS)
        if unknown:
            raise ValidationError(f"running_time_calculation got unknown keys: {sorted(unknown)}")

        for key in ("minimum_detectable_effect", "recommended_running_time", "recommended_sample_size"):
            number = value.get(key)
            if number is not None and (isinstance(number, bool) or not isinstance(number, int | float)):
                raise ValidationError(f"{key} must be a number")

        exposure_estimate_config = value.get("exposure_estimate_config")
        if exposure_estimate_config is not None and not isinstance(exposure_estimate_config, dict):
            raise ValidationError("exposure_estimate_config must be an object")

    EXPOSURE_CONFIG_KINDS = ("ExperimentEventExposureConfig", "ActionsNode")

    EXPOSURE_CONFIG_HINT = (
        "Expected either an event-based config like "
        "{'kind': 'ExperimentEventExposureConfig', 'event': '<event_name>', 'properties': []} "
        "or an action-based config like {'kind': 'ActionsNode', 'id': <action_id>}."
    )

    # Cap user-supplied values reflected into validation error messages so a large
    # or sensitive payload cannot bloat responses, logs, or error tracking. repr()
    # already escapes control characters, so the only remaining concern is length.
    _ERROR_VALUE_MAX_LEN = 80

    @classmethod
    def _safe_repr(cls, value: object) -> str:
        rendered = repr(value)
        if len(rendered) > cls._ERROR_VALUE_MAX_LEN:
            return rendered[: cls._ERROR_VALUE_MAX_LEN] + "...(truncated)"
        return rendered

    @classmethod
    def validate_experiment_exposure_criteria(cls, exposure_criteria: object) -> None:
        """Validate experiment exposure criteria payloads.

        Accepts `object` because the input arrives from a DRF `JSONField`, which
        can deserialize to any JSON shape. The validator narrows defensively.
        """
        if exposure_criteria is None:
            return

        if not isinstance(exposure_criteria, dict):
            raise ValidationError(
                f"exposure_criteria must be an object, got {type(exposure_criteria).__name__}. "
                "Expected shape: {'filterTestAccounts': <bool>, 'exposure_config': <object>}."
            )

        if "filterTestAccounts" in exposure_criteria:
            filter_test_accounts = exposure_criteria["filterTestAccounts"]
            if not isinstance(filter_test_accounts, bool):
                raise ValidationError(
                    f"exposure_criteria.filterTestAccounts must be a boolean, got "
                    f"{type(filter_test_accounts).__name__}: {cls._safe_repr(filter_test_accounts)}."
                )

        if "exposure_config" in exposure_criteria:
            exposure_config = exposure_criteria["exposure_config"]

            if not isinstance(exposure_config, dict):
                raise ValidationError(
                    f"exposure_criteria.exposure_config must be an object, got "
                    f"{type(exposure_config).__name__}. {cls.EXPOSURE_CONFIG_HINT}"
                )

            # `kind` is optional; missing kind defaults to ExperimentEventExposureConfig
            # to mirror the pydantic Literal default on that model.
            kind = exposure_config.get("kind", "ExperimentEventExposureConfig")
            if kind not in cls.EXPOSURE_CONFIG_KINDS:
                raise ValidationError(
                    f"exposure_criteria.exposure_config.kind must be one of "
                    f"{list(cls.EXPOSURE_CONFIG_KINDS)}, got {cls._safe_repr(kind)}. "
                    f"{cls.EXPOSURE_CONFIG_HINT}"
                )

            model_cls = ActionsNode if kind == "ActionsNode" else ExperimentEventExposureConfig
            try:
                model_cls.model_validate(exposure_config)
            except pydantic.ValidationError as e:
                # Surface only the field locations and error types from pydantic — not the
                # echoed `input` and `url` fields, which would reflect arbitrary user data
                # back into the response.
                safe_errors = [
                    {"loc": err.get("loc"), "type": err.get("type"), "msg": err.get("msg")} for err in e.errors()
                ]
                raise ValidationError(
                    f"Invalid exposure_criteria.exposure_config (kind={cls._safe_repr(kind)}): "
                    f"{safe_errors}. {cls.EXPOSURE_CONFIG_HINT}"
                )

    # Maps the public `metric_type` literal to the pydantic class name that pydantic reports
    # in `loc[0]` when validation fails. Used to narrow union-variant errors to the variant
    # the caller picked. A drift test asserts this stays in sync with the ExperimentMetric union.
    _METRIC_TYPE_TO_CLASS = {
        "mean": "ExperimentMeanMetric",
        "funnel": "ExperimentFunnelMetric",
        "ratio": "ExperimentRatioMetric",
        "retention": "ExperimentRetentionMetric",
    }

    # Cap reported pydantic errors so a funnel with many steps (each producing union-variant
    # errors) cannot blow up the response size. The first N errors are the most actionable.
    _MAX_REPORTED_METRIC_ERRORS = 15

    _EVENTS_NODE_ID_HINT = (
        "EventsNode does not accept an 'id' field. "
        "To reference an event, use {'kind': 'EventsNode', 'event': '<event_name>'} (omit 'id'). "
        "To reference an action, switch to {'kind': 'ActionsNode', 'id': <integer_action_id>} (omit 'event')."
    )

    @staticmethod
    def _is_events_node_actions_node_confusion(err: dict) -> bool:
        """An `id` field was passed on an EventsNode (probably meant ActionsNode)."""
        loc = tuple(err.get("loc") or ())
        if len(loc) < 2 or err.get("type") != "extra_forbidden":
            return False
        return loc[-1] == "id" and "EventsNode" in loc

    @classmethod
    def _build_metric_validation_hint(cls, safe_errors: list[dict]) -> str:
        """Return a targeted hint for an observed pydantic error pattern, or '' if none applies.

        The structural shape of valid metrics is conveyed by `safe_errors` itself (loc, type,
        msg) — adding prose duplicates the pydantic models and rots silently. Only hints
        whose facts are independent of metric shape belong here."""
        for err in safe_errors:
            if cls._is_events_node_actions_node_confusion(err):
                return cls._EVENTS_NODE_ID_HINT
        return ""

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
                    elif isinstance(actual_metric, ExperimentMeanMetric) and actual_metric.threshold is not None:
                        # A threshold turns the per-user value into a binary "did the user reach N"
                        # outcome, which only makes sense for sum/count math types.
                        source_math = getattr(actual_metric.source, "math", None)
                        if not is_threshold_supported_math(source_math):
                            raise ValidationError(
                                f"Invalid metric at index {i}: a threshold is only supported for "
                                "sum or count (total) math types."
                            )
                        # A non-positive threshold is satisfied by every user (missing users
                        # accumulate to 0), producing a meaningless 100% proportion.
                        if actual_metric.threshold <= 0:
                            raise ValidationError(f"Invalid metric at index {i}: threshold must be a positive number.")
                        # Winsorization caps continuous outliers, which is meaningless once the
                        # value collapses to a binary threshold outcome.
                        if (
                            actual_metric.lower_bound_percentile is not None
                            or actual_metric.upper_bound_percentile is not None
                        ):
                            raise ValidationError(
                                f"Invalid metric at index {i}: a threshold cannot be combined with "
                                "outlier handling (winsorization)."
                            )

                except pydantic.ValidationError as e:
                    # Surface only the field locations and error types from pydantic — not the
                    # echoed `input`, `ctx`, and `url` fields, which would reflect arbitrary
                    # user data back into the response (potentially unbounded in size).
                    safe_errors = [
                        {"loc": err.get("loc"), "type": err.get("type"), "msg": err.get("msg")} for err in e.errors()
                    ]
                    # ExperimentMetric is a union of four variants; pydantic reports errors against
                    # every variant by default. If the caller picked a metric_type, narrow to that
                    # variant's errors so the message stays actionable instead of dumping 25+ errors.
                    metric_type = metric.get("metric_type")
                    variant_class = cls._METRIC_TYPE_TO_CLASS.get(metric_type) if isinstance(metric_type, str) else None
                    if variant_class is not None:
                        filtered = [err for err in safe_errors if err["loc"] and err["loc"][0] == variant_class]
                        if filtered:
                            safe_errors = filtered
                    hint = cls._build_metric_validation_hint(safe_errors)
                    if len(safe_errors) > cls._MAX_REPORTED_METRIC_ERRORS:
                        truncated = safe_errors[: cls._MAX_REPORTED_METRIC_ERRORS]
                        truncated.append({"truncated": f"...{len(safe_errors) - cls._MAX_REPORTED_METRIC_ERRORS} more"})
                        safe_errors = truncated
                    suffix = f" {hint}" if hint else ""
                    raise ValidationError(f"Invalid metric at index {i}: {safe_errors}.{suffix}")

    VALID_STATS_METHODS = {"bayesian", "frequentist"}

    EXPERIMENT_ORDER_ALLOWLIST = {
        "created_at",
        "-created_at",
        "created_by",
        "-created_by",
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
    def validate_stats_config(cls, stats_config: dict | None, variant_keys: list[str] | None = None) -> None:
        """Validate stats_config shape, method value, and baseline variant key.

        When ``variant_keys`` is provided, a ``baseline_variant_key`` set in
        ``stats_config`` must be one of them. When ``variant_keys`` is None/empty,
        baseline validation is skipped (the caller couldn't supply the keys).
        Absence of ``baseline_variant_key`` is always valid (defaults to control downstream).
        """
        if not stats_config:
            return
        method = stats_config.get("method")
        if method is not None and method not in cls.VALID_STATS_METHODS:
            raise ValidationError(
                f"Invalid stats method: '{method}'. Must be one of: {', '.join(sorted(cls.VALID_STATS_METHODS))}"
            )
        baseline_variant_key = stats_config.get("baseline_variant_key")
        if baseline_variant_key is not None and variant_keys and baseline_variant_key not in variant_keys:
            raise ValidationError(
                f"Invalid baseline_variant_key: '{baseline_variant_key}'. "
                f"Must be one of: {', '.join(sorted(variant_keys))}"
            )

    # Feature-flag config keys that belong on the linked FeatureFlag (the source of truth). They are
    # accepted as create/update input to build/sync the flag, projected back into the deprecated
    # `parameters` API field at read time (see ExperimentBaseSerializer), but never persisted into
    # the `parameters` column.
    FEATURE_FLAG_CONFIG_KEYS = ("feature_flag_variants", "rollout_percentage", "aggregation_group_type_index")

    @classmethod
    def _strip_feature_flag_config(cls, parameters: dict | None) -> dict | None:
        """Return ``parameters`` without the feature-flag config keys, so they are not stored in the
        deprecated column. Callers consume those keys earlier to build/sync the flag; reads
        re-derive them from it. Returns a new dict, leaving the caller's input untouched."""
        if not parameters:
            return parameters
        return {k: v for k, v in parameters.items() if k not in cls.FEATURE_FLAG_CONFIG_KEYS}

    @staticmethod
    def feature_flag_config_to_parameters(feature_flag_input: dict, parameters: dict | None) -> dict:
        """Translate a ``feature_flag`` config object (the flag's native write shape:
        ``filters.multivariate.variants``, ``filters.groups``, ``filters.aggregation_group_type_index``,
        ``filters.payloads``, ``ensure_experience_continuity``) into the legacy ``parameters`` input
        keys the service still consumes to build/sync the flag.

        The explicit ``feature_flag`` object wins over any matching keys already in ``parameters``.
        This is the create/update write counterpart to the read projection (see
        ``ExperimentBaseSerializer``): callers send config through the flag object instead of
        ``parameters``, and this normalizes it while ``parameters`` remains the internal input shape.
        Returns a new dict, leaving the caller's input untouched.
        """
        params = dict(parameters or {})
        filters = feature_flag_input.get("filters") or {}
        multivariate = filters.get("multivariate") or {}
        if isinstance(multivariate.get("variants"), list):
            params["feature_flag_variants"] = multivariate["variants"]
        groups = filters.get("groups")
        if isinstance(groups, list) and groups:
            rollout_percentage = groups[0].get("rollout_percentage")
            if rollout_percentage is not None:
                params["rollout_percentage"] = rollout_percentage
        if "aggregation_group_type_index" in filters:
            params["aggregation_group_type_index"] = filters["aggregation_group_type_index"]
        if "payloads" in filters:
            params["feature_flag_payloads"] = filters["payloads"]
        if "ensure_experience_continuity" in feature_flag_input:
            params["ensure_experience_continuity"] = feature_flag_input["ensure_experience_continuity"]
        return params

    @staticmethod
    def _variant_keys(variants: list | None) -> list[str]:
        """Extract variant keys from a feature_flag_variants list, skipping malformed entries."""
        return [variant["key"] for variant in (variants or []) if isinstance(variant, dict)]

    @classmethod
    def _resolved_variant_keys(cls, experiment: Experiment, update_data: dict) -> list[str]:
        """Variant keys the experiment will have after this update.

        Prefer the variants the PATCH sets; otherwise resolve from the linked flag,
        which is the source of truth for variants.
        """
        update_variants = (update_data.get("parameters") or {}).get("feature_flag_variants")
        if update_variants is None:
            update_variants = experiment.feature_flag.variants if experiment.feature_flag else []
        return cls._variant_keys(update_variants)

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
                "If you meant a different event, please correct it. "
                "Only if the user has explicitly confirmed they want to proceed with "
                "the unknown event (e.g. they will instrument it shortly), "
                "call again with allow_unknown_events=True. "
                "Do not flip the flag silently to bypass this check."
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
        running_time_calculation: dict | None = None,
        excluded_variants: list[str] | None = None,
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
        # Seed the dedup set with uuids the inline metrics must not collide with:
        # - any saved-metric uuids referenced via saved_metrics_ids (their query.uuid
        #   appears in the ordering arrays, so any inline copy must be regenerated).
        # Then share ``seen`` across primary + secondary so a uuid present on one
        # list can't collide with the other. Regenerated dups don't need an
        # ordering remap: the kept incumbent still uses the original uuid, so any
        # ordering reference to it remains valid. The regenerated uuid is appended
        # to ordering by the loop below as a brand-new entry.
        seen_metric_uuids: set[str] = self._collect_saved_metric_uuids(saved_metrics_ids)
        metrics = self._assign_uuids_to_metrics(metrics, seen=seen_metric_uuids)
        metrics_secondary = self._assign_uuids_to_metrics(metrics_secondary, seen=seen_metric_uuids)
        self.validate_variant_shapes(parameters)
        self.validate_variant_percentages(parameters)
        self.validate_running_time_calculation(running_time_calculation)
        self.validate_excluded_variants(excluded_variants)
        running_time_calculation = running_time_calculation or {}
        self.validate_experiment_metrics(metrics)
        self.validate_experiment_metrics(metrics_secondary)
        self.validate_metric_action_ids(metrics, self.team.id)
        self.validate_metric_action_ids(metrics_secondary, self.team.id)
        if not allow_unknown_events:
            self.validate_metric_event_names(metrics)
            self.validate_metric_event_names(metrics_secondary)
        enforce_warehouse_metric_access(
            [
                *(metrics or []),
                *(metrics_secondary or []),
                *self._collect_saved_metric_queries(saved_metrics_ids),
            ],
            team=self.team,
            user=self.user,
        )
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

        # Validate the baseline against the variants the flag actually ends up with.
        # used_variants reflects DEFAULT_VARIANTS / an existing linked flag, which the
        # raw parameters payload may omit. This runs inside the @transaction.atomic
        # create, so a raise rolls back the just-created flag.
        used_variant_keys = self._variant_keys(used_variants)
        self.validate_stats_config(stats_config, used_variant_keys)

        # Validate excluded_variants against the variants the flag actually ends up with,
        # mirroring the baseline check above. Resolving against the flag (not the request
        # payload) is what lets the excluded_variants path skip re-sending feature_flag_variants.
        if excluded_variants:
            baseline_key = (stats_config or {}).get("baseline_variant_key", "control")
            self._validate_excluded_variant_keys(excluded_variants, used_variant_keys, baseline_key)

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
                    excluded_variants=excluded_variants,
                )
        if metrics_secondary is not None:
            for metric in metrics_secondary:
                metric["fingerprint"] = compute_metric_fingerprint(
                    metric,
                    start_date,
                    stats_method,
                    exposure_criteria,
                    only_count_matured_users=only_count_matured_users,
                    excluded_variants=excluded_variants,
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
            # Feature-flag config was already consumed by _ensure_feature_flag above; strip it so it
            # lives only on the flag, not mirrored into the deprecated `parameters` column.
            "parameters": self._strip_feature_flag_config(parameters),
            "running_time_calculation": running_time_calculation,
            "excluded_variants": excluded_variants,
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
        # Defer the analytics capture until after commit so create_experiment's @transaction.atomic
        # doesn't hold posthog_experiment / posthog_filesystem locks open across an external SDK call.
        transaction.on_commit(
            lambda: self._report_experiment_created_safe(
                experiment,
                serializer_context=serializer_context,
                event_source=event_source,
                allow_unknown_events=allow_unknown_events,
                creation_mode=creation_mode,
            )
        )

        return experiment

    def _report_experiment_created_safe(
        self,
        experiment: Experiment,
        *,
        serializer_context: dict | None,
        event_source: EventSource | None,
        allow_unknown_events: bool,
        creation_mode: ExperimentCreationMode,
    ) -> None:
        # Post-commit: the experiment is already persisted, so analytics failures must not break the request.
        try:
            self._report_experiment_created(
                experiment,
                serializer_context=serializer_context,
                event_source=event_source,
                allow_unknown_events=allow_unknown_events,
                creation_mode=creation_mode,
            )
        except Exception:
            logger.exception("experiment_created_analytics_failed", experiment_id=experiment.id)

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

        # Per-variant payloads (variant_key -> JSON string). Callers pass this when they need to
        # attach metadata that the SDK can read alongside the variant assignment, e.g. prompt
        # experiments map each variant to {"prompt_name": ..., "prompt_version": ...}.
        feature_flag_payloads = params.get("feature_flag_payloads")
        if feature_flag_payloads:
            feature_flag_filters["payloads"] = feature_flag_payloads

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

    def _assert_flag_not_deleted_for_launch(self, feature_flag: FeatureFlag) -> None:
        """A deleted flag distributes no traffic, so an experiment can never go live on it."""
        if feature_flag.deleted:
            raise ValidationError("Experiment cannot be launched because its feature flag has been deleted.")

    @staticmethod
    def _assign_uuids_to_metrics(
        metrics: list[dict] | None,
        *,
        seen: set[str] | None = None,
    ) -> list[dict] | None:
        """Return a deep copy of ``metrics`` with a unique ``uuid`` on every entry.

        Fills missing uuids and regenerates any uuid that collides with one already
        in ``seen`` (used to share a single uniqueness space across primary +
        secondary metric lists, plus saved-metric query uuids).

        Ordering arrays don't need a remap from this function: the first occurrence
        of a duplicated uuid keeps its original value, so existing ordering entries
        stay valid; regenerated duplicates are handled as new additions by
        ``_sync_ordering_with_metric_changes`` (update path) or by the append loop
        in ``create_experiment``.

        Callers pass dicts by reference, so we deepcopy to avoid leaking the
        generated uuid back into their data.
        """
        if metrics is None:
            return None
        prepared = deepcopy(metrics)
        seen = seen if seen is not None else set()
        for metric in prepared:
            original = metric.get("uuid")
            if not original or original in seen:
                new_uuid = str(uuid4())
                metric["uuid"] = new_uuid
                seen.add(new_uuid)
            else:
                seen.add(original)
        return prepared

    @staticmethod
    def _remap_ordering(ordering: list[str] | None, remap: dict[str, str]) -> list[str] | None:
        """Rewrite an ordering array with the old→new uuid mapping from dedup."""
        if not ordering or not remap:
            return ordering
        return [remap.get(uuid, uuid) for uuid in ordering]

    def _collect_saved_metric_uuids(self, saved_metrics_ids: list | None) -> set[str]:
        """Return the set of saved-metric query uuids referenced by ``saved_metrics_ids``.

        These uuids live in the experiment's ordering arrays alongside inline-metric
        uuids. Any inline metric in the same write must not collide with one — if
        the payload reuses a saved-metric uuid for an inline metric, dedup
        regenerates the inline copy so each ordering entry resolves to one thing.
        """
        if not saved_metrics_ids:
            return set()
        ids = [sm["id"] for sm in saved_metrics_ids if isinstance(sm, dict) and "id" in sm]
        if not ids:
            return set()
        seen: set[str] = set()
        for sm in ExperimentSavedMetric.objects.filter(id__in=ids, team_id=self.team.id).only("query"):
            if sm.query and (uuid := sm.query.get("uuid")):
                seen.add(uuid)
        return seen

    def _collect_saved_metric_queries(self, saved_metrics_ids: list | None) -> list[dict]:
        """Query definitions of the attached saved metrics, so their tables get the same warehouse
        access check as inline metrics."""
        if not saved_metrics_ids:
            return []
        ids = [sm["id"] for sm in saved_metrics_ids if isinstance(sm, dict) and "id" in sm]
        if not ids:
            return []
        return [
            sm.query
            for sm in ExperimentSavedMetric.objects.filter(id__in=ids, team_id=self.team.id).only("query")
            if sm.query
        ]

    @staticmethod
    def _regenerate_all_metric_uuids(metrics: list[dict] | None) -> tuple[list[dict] | None, dict[str, str]]:
        """Return a deep copy of ``metrics`` with every uuid regenerated.

        Used by clone flows so a cloned experiment never shares metric uuids with
        its source. Returns the prepared list plus an old→new mapping the caller
        threads into the corresponding ordering array.
        """
        if metrics is None:
            return None, {}
        prepared = deepcopy(metrics)
        remap: dict[str, str] = {}
        for metric in prepared:
            new_uuid = str(uuid4())
            original = metric.get("uuid")
            if original:
                remap[original] = new_uuid
            metric["uuid"] = new_uuid
        return prepared, remap

    @staticmethod
    def _recompute_fingerprints(
        metrics: list[dict],
        start_date: datetime | None,
        stats_config: dict | None,
        exposure_criteria: dict | None,
        only_count_matured_users: bool = False,
        excluded_variants: list[str] | None = None,
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
                excluded_variants=excluded_variants,
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
        self._assert_flag_not_deleted_for_launch(feature_flag)
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
                        metrics,
                        experiment.start_date,
                        experiment.stats_config,
                        experiment.exposure_criteria,
                        excluded_variants=experiment.excluded_variants or [],
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
    def archive_experiment(
        self,
        experiment: Experiment,
        *,
        disable_feature_flag: bool = False,
        can_write_feature_flag: bool = True,
        request: Any | None = None,
    ) -> Experiment:
        """Archive an ended experiment: validate it has ended, set archived=True.

        When the linked flag is still enabled, it is only disabled and archived if
        ``disable_feature_flag`` is set — an enabled flag may still be serving traffic
        (e.g. rolling out the winning variant), so archiving it is an explicit choice.
        An already-disabled flag is archived regardless.

        ``can_write_feature_flag`` reflects whether the caller's token carries
        ``feature_flag:write`` — touching the linked flag is skipped when it doesn't.
        """
        if experiment.archived:
            raise ValidationError("Experiment is already archived.")
        if not experiment.is_stopped:
            raise ValidationError("Experiment must be ended before it can be archived.")

        experiment.archived = True
        experiment.save()

        self._archive_linked_feature_flag(
            experiment, disable_if_active=disable_feature_flag, can_write_feature_flag=can_write_feature_flag
        )

        self._report_experiment_archived(experiment, request=request)

        return experiment

    def _user_can_edit_flag(self, feature_flag: FeatureFlag) -> bool:
        """Whether self.user has editor access to this flag — the same check the feature flag API enforces."""
        user = self.user
        if not isinstance(user, User) or user.is_anonymous:
            return False
        return UserAccessControl(user=user, team=self.team).check_access_level_for_object(feature_flag, "editor")

    def _flag_disable_requires_approval(self) -> bool:
        """Whether an enabled approval policy gates disabling a flag for this team/org."""
        policy = PolicyEngine().get_policy(
            action_key="feature_flag.disable", team=self.team, organization=self.team.organization
        )
        return policy is not None

    def _archive_linked_feature_flag(
        self, experiment: Experiment, *, disable_if_active: bool = False, can_write_feature_flag: bool = True
    ) -> None:
        """Archive the experiment's flag along with it, so it stops cluttering the flag list.

        An already-disabled flag is archived. An enabled flag is left untouched unless
        ``disable_if_active`` is set, in which case it is disabled and archived together —
        an enabled flag may still be serving traffic (e.g. rolling out the winning variant).
        Never touches a flag still used by another live experiment.

        Mutating the linked flag is gated by the same authorization the flag API enforces:
        the caller's token must carry ``feature_flag:write`` (``can_write_feature_flag``)
        and the user must have editor access to the flag, and disabling an active flag is
        refused when an approval policy would gate it (a side-effect mutation can't be
        routed through the change-request flow). The implicit archive-only cleanup is
        skipped silently when the caller lacks access — the experiment still archives.
        """
        # Lock the row so a concurrent enable can't slip in between the check and the save,
        # which would produce an archived flag that is still active.
        feature_flag = (
            FeatureFlag.objects.select_for_update()
            .filter(pk=experiment.feature_flag_id, team_id=experiment.team_id)
            .first()
        )
        if feature_flag is None or feature_flag.deleted or feature_flag.archived:
            return
        if feature_flag.experiment_set.filter(deleted=False, archived=False).exclude(id=experiment.id).exists():
            return

        can_edit = self._user_can_edit_flag(feature_flag)

        if feature_flag.active:
            if not disable_if_active:
                return
            # Explicit, user-requested flag change: enforce the same gates the flag API does.
            if not can_write_feature_flag:
                raise PermissionDenied(
                    "You don't have feature flag write access, so this experiment's feature flag can't be disabled."
                )
            if not can_edit:
                raise PermissionDenied(
                    "You don't have editor access to this experiment's feature flag, so it can't be disabled. "
                    "Archive the experiment without disabling the flag, or ask someone with flag access."
                )
            if self._flag_disable_requires_approval():
                raise PermissionDenied(
                    "Disabling this feature flag requires approval. Disable it from the feature flag page "
                    "to go through the approval flow, then archive the experiment."
                )
            # Mirror the feature flag API's check: don't disable a flag other active flags depend on.
            raise_if_flag_has_dependents(feature_flag)
            feature_flag.active = False
        elif not can_edit or not can_write_feature_flag:
            # Implicit cleanup of an already-disabled flag — skip silently when the caller
            # lacks flag editor access or feature_flag:write scope; the experiment still archives.
            return

        feature_flag.archived = True
        feature_flag.save(update_fields=["archived", "active"])

        # Remember that this experiment archived the flag, so unarchiving the experiment
        # only undoes its own archive — never one the user performed manually.
        experiment.feature_flag_auto_archived = True
        experiment.save(update_fields=["feature_flag_auto_archived"])

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

    @transaction.atomic
    def unarchive_experiment(
        self, experiment: Experiment, *, can_write_feature_flag: bool = True, request: Any | None = None
    ) -> Experiment:
        """Unarchive an archived experiment: validate it is archived, set archived=False.

        ``can_write_feature_flag`` reflects whether the caller's token carries
        ``feature_flag:write`` — un-archiving the linked flag is skipped when it doesn't.
        """
        if not experiment.archived:
            raise ValidationError("Experiment is not archived.")

        experiment.archived = False
        experiment.save()

        self._unarchive_linked_feature_flag(experiment, can_write_feature_flag=can_write_feature_flag)

        self._report_experiment_unarchived(experiment, request=request)

        return experiment

    def _unarchive_linked_feature_flag(self, experiment: Experiment, *, can_write_feature_flag: bool = True) -> None:
        """Mirror of _archive_linked_feature_flag: bring the flag back with the experiment.

        Only undoes an archive this experiment performed — a flag the user archived
        manually stays archived. The flag stays disabled either way; re-enabling it is
        an explicit user decision. Un-archiving the flag is a feature_flag write, so it's
        skipped (leaving the flag archived and the bookkeeping intact, recoverable later)
        when the caller lacks feature_flag:write scope or editor access to the flag.
        """
        if not experiment.feature_flag_auto_archived:
            return

        feature_flag = (
            FeatureFlag.objects.select_for_update()
            .filter(pk=experiment.feature_flag_id, team_id=experiment.team_id)
            .first()
        )
        if feature_flag is None or feature_flag.deleted or not feature_flag.archived:
            # Flag is gone or already un-archived — clear the now-stale bookkeeping.
            experiment.feature_flag_auto_archived = False
            experiment.save(update_fields=["feature_flag_auto_archived"])
            return

        if not can_write_feature_flag or not self._user_can_edit_flag(feature_flag):
            return

        feature_flag.archived = False
        feature_flag.save(update_fields=["archived"])

        experiment.feature_flag_auto_archived = False
        experiment.save(update_fields=["feature_flag_auto_archived"])

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

        # Skip notifying the creator when they're the one ending the experiment —
        # surfacing a notification for an action they just performed is noise.
        if experiment.created_by_id and experiment.created_by_id != self.user.id:
            try:
                significant = completed_metadata.get("significant")
                body = ""
                if significant is True:
                    body = "Primary metric: significant"
                elif significant is False:
                    body = "Primary metric: inconclusive"

                create_notification(
                    NotificationData(
                        team_id=experiment.team_id,
                        notification_type=NotificationType.EXPERIMENT_CONCLUDED,
                        priority=Priority.NORMAL,
                        title=f"Experiment concluded: {experiment.name}"[:100],
                        body=body,
                        target_type=TargetType.USER,
                        target_id=str(experiment.created_by_id),
                        resource_type="experiment",
                        resource_id=str(experiment.id),
                        source_url=f"/project/{self.team.project_id}/experiments/{experiment.id}",
                        source_type=SourceType.EXPERIMENT,
                        source_id=str(experiment.id),
                    )
                )
            except Exception as e:
                logger.exception(
                    "experiment_concluded.realtime_failed",
                    experiment_id=experiment.id,
                    error=str(e),
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
        release_to_everyone: bool = False,
        conclusion: str | None = None,
        conclusion_comment: str | None = None,
        request: Any,
    ) -> Experiment:
        """Ship a variant and (optionally) end the experiment.

        Updates the feature flag so the selected variant gets 100% of the variant
        distribution. By default (``release_to_everyone=False``) existing release
        conditions on the flag are preserved untouched — the variant is served
        only to users who already match them, and any per-user variant overrides
        continue to apply. Pass ``release_to_everyone=True`` to also prepend a
        catch-all release condition that rolls the variant out to 100% of users
        (overrides any existing release conditions and per-user overrides).

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

        new_filters = self._transform_filters_for_winning_variant(
            flag.filters, variant_key, release_to_everyone=release_to_everyone
        )

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

        self._report_experiment_variant_shipped(
            experiment, variant_key=variant_key, release_to_everyone=release_to_everyone, request=request
        )
        if was_running:
            self._report_experiment_ended(experiment, request=request)

        return experiment

    @staticmethod
    def _transform_filters_for_winning_variant(
        current_filters: dict,
        variant_key: str,
        *,
        release_to_everyone: bool = False,
    ) -> dict:
        """Rewrite flag filters so the selected variant gets 100% of the variant distribution.

        When ``release_to_everyone`` is False (default), existing release conditions on
        the flag are preserved untouched: the variant is served only to users who
        already match them, and any per-user variant overrides keep applying.

        When ``release_to_everyone`` is True, a catch-all release condition is prepended
        that rolls the variant out to 100% of users — note that under top-down
        first-match evaluation this overrides any existing release conditions and
        per-user variant overrides below it.
        """
        groups = list(current_filters.get("groups", []))
        if release_to_everyone:
            groups = [
                {
                    "properties": [],
                    "rollout_percentage": 100,
                    "description": "Added automatically when the experiment was ended to keep only one variant.",
                },
                *groups,
            ]

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
            "groups": groups,
        }

    def _report_experiment_variant_shipped(
        self,
        experiment: Experiment,
        *,
        variant_key: str,
        release_to_everyone: bool = False,
        request: Any | None = None,
    ) -> None:
        if request is None:
            return

        metadata = experiment.get_analytics_metadata()
        metadata["variant_key"] = variant_key
        metadata["release_to_everyone"] = release_to_everyone
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
        event_source: EventSource | None = None,
    ) -> Experiment:
        """Update an experiment with full business-logic validation.

        ``update_data`` mirrors the DRF ``validated_data`` dict produced by
        ``ExperimentSerializer``.  The caller is responsible for DRF-level input
        validation (field types, metric schema, etc.) before calling this method.

        ``event_source`` attributes the "experiment updated" event for non-HTTP callers,
        mirroring ``create_experiment``.
        """
        update_feature_flag_params = update_data.pop("update_feature_flag_params", False)

        # Snapshot before the update to diff what actually changed. The activity-log diff
        # misses the saved-metric M2M, so capture its signature separately, before the sync
        # below mutates it. Skip the reads when neither channel will report.
        report_request = serializer_context.get("request") if serializer_context else None
        should_report_update = report_request is not None or event_source is not None
        before_update = experiment._get_before_update() if should_report_update else None
        before_saved_metrics = self._saved_metric_signature(experiment) if should_report_update else frozenset()

        if "saved_metrics_ids" in update_data:
            self.validate_saved_metrics_ids(update_data["saved_metrics_ids"], self.team.id)

        # Seed the uniqueness set with uuids that must remain stable in the
        # ordering arrays — any inline metric reusing one of these gets
        # regenerated to keep ordering entries unambiguous:
        # - the stored inline metric list NOT being updated (a primary-only
        #   update must not collide with the stored secondary, and vice versa).
        # - saved-metric query uuids (post-update set: the payload's
        #   saved_metrics_ids if supplied, otherwise the experiment's current
        #   links).
        seen_metric_uuids: set[str] = set()
        if "metrics" in update_data and "metrics_secondary" not in update_data:
            for metric in experiment.metrics_secondary or []:
                if uuid := metric.get("uuid"):
                    seen_metric_uuids.add(uuid)
        if "metrics_secondary" in update_data and "metrics" not in update_data:
            for metric in experiment.metrics or []:
                if uuid := metric.get("uuid"):
                    seen_metric_uuids.add(uuid)
        if "saved_metrics_ids" in update_data:
            seen_metric_uuids |= self._collect_saved_metric_uuids(update_data["saved_metrics_ids"])
        else:
            for link in experiment.experimenttosavedmetric_set.select_related("saved_metric").all():
                if link.saved_metric.query and (uuid := link.saved_metric.query.get("uuid")):
                    seen_metric_uuids.add(uuid)

        # Regenerated dups don't need an ordering remap: the original uuid is
        # kept on the incumbent so any ordering reference to it remains valid
        # (including references to saved-metric uuids that happen to be inlined).
        # _sync_ordering_with_metric_changes runs later and appends the new
        # regenerated uuids as additions; _sync_ordering_for_saved_metrics_on_update
        # handles saved-metric link uuids independently.
        if "metrics" in update_data:
            update_data["metrics"] = self._assign_uuids_to_metrics(update_data["metrics"], seen=seen_metric_uuids)
            self.validate_experiment_metrics(update_data["metrics"])
            self.validate_metric_action_ids(update_data["metrics"], self.team.id)
            if not allow_unknown_events:
                self.validate_metric_event_names(update_data["metrics"])
        if "metrics_secondary" in update_data:
            update_data["metrics_secondary"] = self._assign_uuids_to_metrics(
                update_data["metrics_secondary"], seen=seen_metric_uuids
            )
            self.validate_experiment_metrics(update_data["metrics_secondary"])
            self.validate_metric_action_ids(update_data["metrics_secondary"], self.team.id)
            if not allow_unknown_events:
                self.validate_metric_event_names(update_data["metrics_secondary"])

        enforce_warehouse_metric_access(
            [
                *(update_data.get("metrics") or []),
                *(update_data.get("metrics_secondary") or []),
                *self._collect_saved_metric_queries(update_data.get("saved_metrics_ids")),
            ],
            team=self.team,
            user=self.user,
        )

        context = serializer_context or self._build_serializer_context()
        feature_flag = experiment.feature_flag

        self._validate_update_payload(experiment, update_data, feature_flag)

        update_saved_metrics = "saved_metrics_ids" in update_data
        saved_metrics_data: list[dict] = update_data.pop("saved_metrics_ids", []) or []
        update_data.pop("get_feature_flag_key", None)

        # --- saved metrics sync (update-in-place) -----------
        old_saved_metric_uuids: dict[str, set[str]] = {"primary": set(), "secondary": set()}
        if update_saved_metrics:
            existing_links = {
                link.saved_metric_id: link
                for link in experiment.experimenttosavedmetric_set.select_related("saved_metric").all()
            }

            for link in existing_links.values():
                if link.saved_metric.query:
                    uuid = link.saved_metric.query.get("uuid")
                    if uuid:
                        metric_type = (link.metadata or {}).get("type", "primary")
                        if metric_type == "primary":
                            old_saved_metric_uuids["primary"].add(uuid)
                        else:
                            old_saved_metric_uuids["secondary"].add(uuid)

            new_saved_metric_ids = {sm["id"] for sm in saved_metrics_data}
            existing_saved_metric_ids = set(existing_links.keys())

            # Delete links no longer in the list (one by one to trigger activity logging)
            to_delete = existing_saved_metric_ids - new_saved_metric_ids
            for saved_metric_id in to_delete:
                existing_links[saved_metric_id].delete()

            # Update or create links
            for saved_metric_data in saved_metrics_data:
                saved_metric_id = saved_metric_data["id"]
                new_metadata = saved_metric_data.get("metadata") or {}

                if saved_metric_id in existing_links:
                    existing_link = existing_links[saved_metric_id]
                    if (existing_link.metadata or {}) != new_metadata:
                        existing_link.metadata = new_metadata
                        existing_link.save(update_fields=["metadata", "updated_at"])
                else:
                    saved_metric_serializer = ExperimentToSavedMetricSerializer(
                        data={
                            "experiment": experiment.id,
                            "saved_metric": saved_metric_id,
                            "metadata": new_metadata,
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
        # Revalidate the baseline whenever either side of the constraint changes:
        # the stats_config itself, or the variant set it references. A variants-only
        # PATCH (e.g. updateDistribution) that renames/removes the current baseline
        # must not leave a dangling baseline_variant_key behind.
        update_variants = (update_data.get("parameters") or {}).get("feature_flag_variants")
        if "stats_config" in update_data or update_variants is not None:
            variant_keys = self._resolved_variant_keys(experiment, update_data)
            effective_stats_config = update_data.get("stats_config", experiment.stats_config)
            self.validate_stats_config(effective_stats_config, variant_keys)

        # Validate excluded_variants against the resolved flag variants — no
        # feature_flag_variants resend required.
        if "excluded_variants" in update_data:
            new_excluded = update_data["excluded_variants"]
            if new_excluded:
                variant_keys = self._resolved_variant_keys(experiment, update_data)
                effective_stats_config = update_data.get("stats_config", experiment.stats_config)
                baseline_key = (effective_stats_config or {}).get("baseline_variant_key", "control")
                self._validate_excluded_variant_keys(new_excluded, variant_keys, baseline_key)

        # Defense-in-depth: only validate the inline metric lists this update
        # is actually touching. Dedup-on-input has already made these lists
        # unique; validating the stored arrays would block a soft-delete (or any
        # other PATCH) on rows that pre-date the dedup logic.
        if "metrics" in update_data or "metrics_secondary" in update_data:
            self.validate_no_duplicate_metric_uuids(update_data.get("metrics"), update_data.get("metrics_secondary"))

        # --- fingerprint recalculation -------------------------------------
        start_date = update_data.get("start_date", experiment.start_date)
        stats_config = update_data.get("stats_config", experiment.stats_config)
        exposure_criteria = update_data.get("exposure_criteria", experiment.exposure_criteria)
        only_count_matured_users = update_data.get("only_count_matured_users", experiment.only_count_matured_users)
        # Canonical excluded_variants for fingerprints: prefer an explicit column update,
        # otherwise the stored canonical value. So a client PATCHing only excluded_variants
        # still fingerprints with the new exclusions.
        if "excluded_variants" in update_data:
            excluded_variants = update_data["excluded_variants"]
        else:
            excluded_variants = experiment.excluded_variants or []

        for metric_field in ["metrics", "metrics_secondary"]:
            metrics = update_data.get(metric_field, getattr(experiment, metric_field, None))
            if metrics:
                update_data[metric_field] = self._recompute_fingerprints(
                    metrics,
                    start_date,
                    stats_config,
                    exposure_criteria,
                    only_count_matured_users=only_count_matured_users,
                    excluded_variants=excluded_variants,
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
        # Feature-flag config was already synced to the flag above; strip it so it is not mirrored
        # into the deprecated `parameters` column. Reads re-derive it from the flag.
        if update_data.get("parameters") is not None:
            update_data["parameters"] = self._strip_feature_flag_config(update_data["parameters"])
        for attr, value in update_data.items():
            setattr(experiment, attr, value)
        experiment.save()

        if should_report_update:
            changed_fields = self._compute_changed_fields(
                experiment, before_update=before_update, before_saved_metrics=before_saved_metrics
            )
            if changed_fields:
                self._report_experiment_updated(
                    experiment, changed_fields=changed_fields, request=report_request, event_source=event_source
                )

        return experiment

    def _compute_changed_fields(
        self,
        experiment: Experiment,
        *,
        before_update: "Experiment | None",
        before_saved_metrics: frozenset[tuple[int, str]],
    ) -> list[str]:
        """The experiment fields that actually changed, sorted and deduped.

        Scalar/JSON fields come from the activity-log diff; the saved-metric M2M is diffed
        separately because that relation is excluded from it.
        """
        changed_fields = get_changed_fields_local(before_update, experiment) if before_update is not None else []
        # Check if saved_metric assignment has changed
        if before_saved_metrics != self._saved_metric_signature(experiment):
            changed_fields = [*changed_fields, "saved_metrics"]
        return sorted(set(changed_fields))

    @staticmethod
    def _saved_metric_signature(experiment: Experiment) -> frozenset[tuple[int, str]]:
        """Identity of an experiment's shared-metric links: (saved_metric_id, type)."""
        return frozenset(
            (saved_metric_id, (metadata or {}).get("type", "primary"))
            for saved_metric_id, metadata in experiment.experimenttosavedmetric_set.values_list(
                "saved_metric_id", "metadata"
            )
        )

    def _report_experiment_updated(
        self,
        experiment: Experiment,
        *,
        changed_fields: list[str],
        request: Any | None = None,
        event_source: EventSource | None = None,
    ) -> None:
        if request is None and event_source is None:
            return

        metadata = experiment.get_analytics_metadata()
        metadata["changed_fields"] = changed_fields
        if event_source is not None:
            metadata["source"] = event_source

        report_user_action(
            self.user,
            "experiment updated",
            metadata,
            team=experiment.team,
            request=request,
        )

    def _validate_update_payload(self, experiment: Experiment, update_data: dict, feature_flag: FeatureFlag) -> None:
        """Validate update payload before any database mutations occur."""
        # Prevent restoring a deleted experiment if the linked feature flag is also deleted
        if experiment.deleted and update_data.get("deleted") is False and feature_flag.deleted:
            raise ValidationError(
                "Cannot restore experiment: the linked feature flag has been deleted. "
                "Restore the feature flag first, then restore the experiment."
            )

        # Launching a draft via PATCH (start_date) is an alternate launch path, so it must
        # run the same flag guards as the dedicated launch_experiment action: flag not
        # deleted, and a valid control/variant configuration.
        if experiment.is_draft and update_data.get("start_date") is not None:
            self._assert_flag_not_deleted_for_launch(feature_flag)
            self._validate_existing_flag(feature_flag)

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
            "running_time_calculation",
            "excluded_variants",
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

        self.validate_running_time_calculation(update_data.get("running_time_calculation"))
        self.validate_excluded_variants(update_data.get("excluded_variants"))

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

        # Variants come from the source experiment's feature flag (the source of truth),
        # not the stale copy denormalized into parameters.
        source_variants = source_experiment.feature_flag.variants
        if source_variants:
            parameters["feature_flag_variants"] = deepcopy(source_variants)

        # An existing flag in the target project wins — reuse its variants instead.
        # For cross-project clones we always check the target; for same-project
        # clones we only check when the key differs from the source flag.
        should_check_existing = is_cross_project or feature_flag_key != source_experiment.feature_flag.key
        if should_check_existing:
            existing_flag = FeatureFlag.objects.filter(key=feature_flag_key, team_id=target.id).first()
            if existing_flag and existing_flag.variants:
                parameters["feature_flag_variants"] = deepcopy(existing_flag.variants)

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

        # Regenerate metric uuids so the clone has its own identity space — sharing
        # uuids with the source is a foot-gun for any code that uses uuid as a
        # metric identifier across experiments (recalculations, fingerprints).
        cloned_metrics, primary_remap = self._regenerate_all_metric_uuids(source_experiment.metrics)
        cloned_metrics_secondary, secondary_remap = self._regenerate_all_metric_uuids(
            source_experiment.metrics_secondary
        )
        cloned_primary_ordering = self._remap_ordering(source_experiment.primary_metrics_ordered_uuids, primary_remap)
        cloned_secondary_ordering = self._remap_ordering(
            source_experiment.secondary_metrics_ordered_uuids, secondary_remap
        )

        service = ExperimentService(team=target, user=self.user) if is_cross_project else self
        creation_mode: ExperimentCreationMode = "copy_to_project" if is_cross_project else "duplicate"
        return service.create_experiment(
            name=clone_name,
            feature_flag_key=feature_flag_key,
            description=source_experiment.description or "",
            type=source_experiment.type or "product",
            parameters=parameters,
            running_time_calculation=deepcopy(source_experiment.running_time_calculation),
            filters=source_experiment.filters,
            metrics=cloned_metrics,
            metrics_secondary=cloned_metrics_secondary,
            stats_config=source_experiment.stats_config,
            scheduling_config=source_experiment.scheduling_config,
            exposure_criteria=source_experiment.exposure_criteria,
            saved_metrics_ids=saved_metrics_data,
            primary_metrics_ordered_uuids=cloned_primary_ordering,
            secondary_metrics_ordered_uuids=cloned_secondary_ordering,
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

    def _experiments_matching_event(self, queryset: QuerySet[Experiment], event: str) -> list[int]:
        """Return PKs of experiments whose metrics reference the given event.

        Reads only the metric columns — no model hydration or prefetches, so the
        caller's prefetch-heavy queryset isn't materialized twice — and resolves
        every referenced action in a single batched query to avoid an N+1.
        """
        inline_metrics = list(queryset.values_list("pk", "metrics", "metrics_secondary"))
        pks = [pk for pk, _, _ in inline_metrics]

        saved_queries_by_experiment: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for experiment_id, query in ExperimentToSavedMetric.objects.filter(experiment_id__in=pks).values_list(
            "experiment_id", "saved_metric__query"
        ):
            if query:
                saved_queries_by_experiment[experiment_id].append(query)

        metric_groups: list[tuple[int, list[dict[str, Any]]]] = [
            (
                pk,
                [*(metrics or []), *(metrics_secondary or []), *saved_queries_by_experiment.get(pk, [])],
            )
            for pk, metrics, metrics_secondary in inline_metrics
        ]
        return filter_metric_group_ids_by_event(metric_groups, event, self.team)

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
                user_ids = parse_created_by_ids(created_by_id)
                if user_ids:
                    queryset = queryset.filter(created_by_id__in=user_ids)

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

            prompt_name = query_params.get("prompt_name")
            if prompt_name:
                queryset = queryset.filter(parameters__prompt_metadata__name=prompt_name)

            event = query_params.get("event")
            if event:
                # Event references live deep in the metrics JSON, so filter in Python and
                # narrow the queryset by primary key to preserve ordering and pagination.
                queryset = queryset.filter(pk__in=self._experiments_matching_event(queryset, event))

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
            elif order_value in ["created_by", "-created_by"]:
                # Match the frontend column's `first_name || email` sorter — treat an
                # empty `first_name` as missing and fall back to `email`, so users with
                # a blank first name aren't bunched at one end of the list.
                prefix = "-" if order_value.startswith("-") else ""
                queryset = queryset.annotate(
                    created_by_display=Coalesce(
                        NullIf(F("created_by__first_name"), Value("")),
                        F("created_by__email"),
                        # first_name is a CharField and email an EmailField; Django refuses to
                        # infer a type across the two, so set it explicitly.
                        output_field=CharField(),
                    )
                ).order_by(f"{prefix}created_by_display")
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
            user_ids = parse_created_by_ids(created_by_id)
            if user_ids:
                queryset = queryset.filter(created_by_id__in=user_ids)

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
                    timeseries[date_key] = strip_step_sessions(metric_result.result)
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
        response = {
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
        response["formatted_results"] = ExperimentTimeseriesFormatter(response).format()
        return response

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
        """Sync ordering arrays with saved metric changes during update.

        When a saved metric is added or removed, the ordering arrays are kept in
        sync. The classification rule for the resulting write is:

        - If the user did not supply the ordering field, or supplied a value that
          equals what auto-sync would have produced, treat the write as bookkeeping
          and persist it via a muted ``experiment.save(update_fields=...)`` so only
          the add/remove appears in the activity log.
        - Otherwise the user layered an explicit reorder on top of the add/remove.
          Merge their order with the add/remove side effects and let the value flow
          through the normal ``experiment.save()`` so the reorder is logged.
        """
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

        # Fields whose new value is purely a side effect of add/remove — save these
        # via a muted save to avoid logging a spurious "reordered metrics" entry
        # alongside the add/remove entry.
        auto_synced_fields: list[str] = []

        def resolve_ordering(
            field: str,
            base_ordering: list[str],
            added: set[str],
            removed: set[str],
        ) -> None:
            auto_sync_result = [u for u in base_ordering if u not in removed]
            for uuid in added:
                if uuid not in auto_sync_result:
                    auto_sync_result.append(uuid)

            user_supplied = field in update_data
            supplied_value = list(update_data.get(field) or []) if user_supplied else None

            if user_supplied and supplied_value != auto_sync_result:
                # Real user reorder layered on top of the add/remove. Fold in the
                # add/remove side effects so we don't lose newly-added UUIDs or
                # retain newly-removed ones, but keep the user's chosen order.
                merged = [u for u in supplied_value or [] if u not in removed]
                for uuid in added:
                    if uuid not in merged:
                        merged.append(uuid)
                update_data[field] = merged
                # leave it to flow through the normal save() — logged as reorder
            else:
                update_data[field] = auto_sync_result
                auto_synced_fields.append(field)

        if added_primary or removed_primary:
            resolve_ordering(
                "primary_metrics_ordered_uuids",
                list(experiment.primary_metrics_ordered_uuids or []),
                added_primary,
                removed_primary,
            )

        if added_secondary or removed_secondary:
            resolve_ordering(
                "secondary_metrics_ordered_uuids",
                list(experiment.secondary_metrics_ordered_uuids or []),
                added_secondary,
                removed_secondary,
            )

        # Persist auto-synced ordering via a muted save so the add/remove of the
        # saved metric is the only activity log entry. The user-initiated reorder
        # path still flows through the normal save() at the end of update_experiment.
        if auto_synced_fields:
            for field in auto_synced_fields:
                setattr(experiment, field, update_data.pop(field))
            with mute_selected_signals():
                experiment.save(update_fields=[*auto_synced_fields, "updated_at"])

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
