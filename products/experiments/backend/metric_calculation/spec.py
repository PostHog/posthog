"""The inputs of one metric calculation, and the key that files and finds its results.

A `CalculationSpec` holds what one metric calculation reads from the experiment, its feature flag, the
team and the team's experiment settings, with defaults resolved to concrete values. `plan` builds the
specs of the scheduled metrics of an experiment.

A spec does not pin the events and warehouse rows, the definitions a metric references (actions,
cohorts, warehouse tables, property types), the team's HogQL modifiers, or the clock that the maturity
filters read. The same spec can therefore give a different result later.

Key version 1 hashes only part of a spec: the metric, the start date, the stats method, the exposure
criteria as stored, maturity and the excluded variants. The other fields do not change it.
"""

import json
import hashlib
from copy import deepcopy
from dataclasses import field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import pydantic

from posthog.dataclasses import frozen
from posthog.models.team.extensions import get_or_create_team_extension

from products.experiments.backend.hogql_queries import get_baseline_variant_key
from products.experiments.backend.hogql_queries.cuped_config import CupedQueryConfig, resolve_experiment_cuped_config
from products.experiments.backend.hogql_queries.experiment_query_builder import (
    ExposureQueryParams,
    get_exposure_config_params_for_builder,
)
from products.experiments.backend.hogql_queries.utils import (
    BayesianSettings,
    FrequentistSettings,
    StatsMethod,
    resolve_bayesian_settings,
    resolve_frequentist_settings,
    resolve_stats_method,
)
from products.experiments.backend.metric_resolution import MetricRole, resolve_scheduled_metrics
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig

if TYPE_CHECKING:
    from posthog.models.team.team import Team

    from products.feature_flags.backend.models.feature_flag import FeatureFlag

SPEC_VERSION = 1

# Fields of a stored metric definition that do not describe what the metric computes: its identity, its
# display name, the stored key itself, and an experiment-level setting that some stored definitions carry.
_NON_ANALYTICAL_METRIC_FIELDS = frozenset({"uuid", "name", "kind", "fingerprint", "only_count_matured_users"})


def _strip_empty_breakdowns(metric: dict[str, Any]) -> None:
    """Remove a breakdownFilter that carries no breakdowns.

    An empty breakdown list is the same metric config as no breakdowns, but the two dict shapes hash to
    different values. Saved-metric resolution (`resolve_saved_metric_definition`) injects
    `breakdownFilter.breakdowns = []` when the experiment link has none, so without this normalization the
    merged dict would hash away from an identical config stored without a breakdownFilter, and rows written
    under one shape would be invisible to readers hashing the other.
    """
    breakdown_filter = metric.get("breakdownFilter")
    if breakdown_filter is None:
        metric.pop("breakdownFilter", None)
        return
    if isinstance(breakdown_filter, dict) and not breakdown_filter.get("breakdowns"):
        remaining = {key: value for key, value in breakdown_filter.items() if key != "breakdowns"}
        if remaining:
            metric["breakdownFilter"] = remaining
        else:
            metric.pop("breakdownFilter")


def _analytical_definition(definition: dict[str, Any]) -> dict[str, Any]:
    metric = deepcopy(definition)
    for field_name in _NON_ANALYTICAL_METRIC_FIELDS:
        metric.pop(field_name, None)
    _strip_empty_breakdowns(metric)
    return metric


def _variant_keys(feature_flag: "FeatureFlag", excluded_variants: tuple[str, ...]) -> tuple[str, ...]:
    keys = (variant.get("key") for variant in feature_flag.variants if isinstance(variant, dict))
    return tuple(key for key in keys if isinstance(key, str) and key not in excluded_variants)


def _resolve_exposure(
    exposure_criteria: dict[str, Any] | None, team: "Team", start_date: datetime | None
) -> ExposureQueryParams | None:
    try:
        return get_exposure_config_params_for_builder(exposure_criteria, team, start_date)
    except pydantic.ValidationError:
        return None


@frozen
class ExperimentCalculationSettings:
    """What every metric calculation of an experiment reads outside the metric definition, with the
    team defaults and the product defaults resolved to concrete values."""

    team_id: int
    start_date: datetime | None
    feature_flag_key: str
    # None aggregates by person. An index aggregates by that group type.
    aggregation_group_type_index: int | None
    # The flag's variant keys without the excluded ones, in flag order.
    variants: tuple[str, ...]
    baseline: str
    excluded_variants: tuple[str, ...]
    # None when the stored exposure criteria do not parse. The query runner rejects such an experiment.
    exposure: ExposureQueryParams | None
    # The team's test account filters when the exposure filters test accounts, else empty.
    test_account_filters: tuple[dict[str, Any], ...]
    stats: BayesianSettings | FrequentistSettings
    # The CUPED setting of the experiment. The query builders apply it only to metrics that support CUPED.
    cuped: CupedQueryConfig
    only_count_matured_users: bool
    # Retention metrics bucket their windows into days or hours in this time zone.
    timezone: str
    # The exposure criteria as stored. Key version 1 hashes this form, so settings that resolve to the
    # same `exposure` can still have different keys when their stored JSON differs.
    stored_exposure_criteria: dict[str, Any] | None = field(compare=False)

    @property
    def stats_method(self) -> StatsMethod:
        return "frequentist" if isinstance(self.stats, FrequentistSettings) else "bayesian"

    @classmethod
    def resolve(
        cls,
        *,
        team: "Team",
        feature_flag: "FeatureFlag",
        start_date: datetime | None,
        stats_config: dict[str, Any] | None,
        exposure_criteria: dict[str, Any] | None,
        only_count_matured_users: bool | None,
        excluded_variants: list[str] | None,
        team_config: TeamExperimentsConfig | None = None,
    ) -> "ExperimentCalculationSettings":
        """Settings from explicit values, for a caller that holds a configuration that is not saved yet.

        Stored configuration never makes this raise, because the experiment read and write paths build
        settings to stamp the metric keys. A configuration the query runner rejects still resolves.
        """
        config = team_config or get_or_create_team_extension(team, TeamExperimentsConfig)
        stats_config = stats_config if isinstance(stats_config, dict) else None
        excluded = tuple(sorted(set(excluded_variants or [])))
        variants = _variant_keys(feature_flag, excluded)
        exposure = _resolve_exposure(exposure_criteria, team, start_date)
        test_account_filters = team.test_account_filters
        stats: BayesianSettings | FrequentistSettings
        if resolve_stats_method(stats_config) == "frequentist":
            stats = resolve_frequentist_settings(
                stats_config,
                team_default_sequential_testing_enabled=config.default_sequential_testing_enabled,
                team_default_sequential_tuning_parameter=config.default_sequential_tuning_parameter,
            )
        else:
            stats = resolve_bayesian_settings(stats_config)
        return cls(
            team_id=team.id,
            start_date=start_date,
            feature_flag_key=feature_flag.key_without_tombstone(),
            aggregation_group_type_index=feature_flag.aggregation_group_type_index,
            variants=variants,
            baseline=get_baseline_variant_key(stats_config, list(variants)),
            excluded_variants=excluded,
            exposure=exposure,
            test_account_filters=(
                tuple(deepcopy(test_account_filters))
                if exposure is not None and exposure.filter_test_accounts and isinstance(test_account_filters, list)
                else ()
            ),
            stats=stats,
            cuped=resolve_experiment_cuped_config(
                stats_config,
                team_default_enabled=config.default_cuped_enabled,
                team_default_lookback_days=config.default_cuped_lookback_days,
            ),
            only_count_matured_users=bool(only_count_matured_users),
            timezone=team.timezone,
            stored_exposure_criteria=deepcopy(exposure_criteria),
        )

    @classmethod
    def of_experiment(cls, experiment: Experiment) -> "ExperimentCalculationSettings":
        """Settings from the current fields of the experiment, which does not need to be saved."""
        return cls.resolve(
            team=experiment.team,
            feature_flag=experiment.feature_flag,
            start_date=experiment.start_date,
            stats_config=experiment.stats_config,
            exposure_criteria=experiment.exposure_criteria,
            only_count_matured_users=experiment.only_count_matured_users,
            excluded_variants=experiment.excluded_variants,
        )

    def spec_for(self, *, metric_id: str, role: MetricRole, definition: dict[str, Any]) -> "CalculationSpec":
        """The spec of one metric under these settings. `definition` is the effective definition, with
        the saved-metric link overrides applied."""
        return CalculationSpec(
            spec_version=SPEC_VERSION,
            metric_id=metric_id,
            role=role,
            metric=_analytical_definition(definition),
            definition=deepcopy(definition),
            settings=self,
        )


@frozen
class CalculationSpec:
    """The configuration one metric calculation reads, and the key its results are filed under.

    Equal specs compute the same thing. The metric id and the role identify the metric and take no part
    in equality, so an inline metric and a saved metric with the same effective definition have equal specs.
    """

    spec_version: int
    # A metric without a uuid gets an empty id. Nothing can calculate or look up such a metric, and only
    # its stored `fingerprint` reads the spec.
    metric_id: str = field(compare=False)
    role: MetricRole = field(compare=False)
    # The effective definition without the fields in _NON_ANALYTICAL_METRIC_FIELDS and without an empty
    # breakdown list.
    metric: dict[str, Any]
    # The effective definition as the API returns it and as the query runner receives it.
    definition: dict[str, Any] = field(compare=False)
    settings: ExperimentCalculationSettings

    def calculation_key(self) -> str:
        """Key version 1, a SHA-256 hex digest.

        Result rows in ExperimentMetricResult and the stored `fingerprint` of each metric hold this key.
        A change to the hashed payload makes every stored result unreachable, so a new analytical input
        needs a new key version, not an edit here.
        """
        settings = self.settings
        start_date = settings.start_date
        payload: dict[str, Any] = {
            "metric": self.metric,
            # The same instant gives the same key in every timezone.
            "start_date": start_date.astimezone(ZoneInfo("UTC")).isoformat() if start_date is not None else None,
            "stats_method": settings.stats_method,
        }
        if settings.stored_exposure_criteria:
            payload["exposure_criteria"] = settings.stored_exposure_criteria
        if settings.only_count_matured_users:
            payload["only_count_matured_users"] = True
        if settings.excluded_variants:
            payload["excluded_variants"] = list(settings.excluded_variants)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def plan(experiment: Experiment) -> list[CalculationSpec]:
    """One spec per scheduled metric of the experiment, in the order of `resolve_scheduled_metrics`."""
    metrics = resolve_scheduled_metrics(experiment)
    if not metrics:
        return []
    settings = ExperimentCalculationSettings.of_experiment(experiment)
    return [
        settings.spec_for(metric_id=metric.uuid, role=metric.role, definition=metric.definition) for metric in metrics
    ]


def plan_metric(experiment: Experiment, metric_uuid: str) -> CalculationSpec | None:
    """The spec `plan` builds for one scheduled metric, or None when the experiment has no scheduled
    metric with this uuid."""
    return next((spec for spec in plan(experiment) if spec.metric_id == metric_uuid), None)


def stamp_calculation_keys(
    metrics: list[dict[str, Any]], role: MetricRole, settings: ExperimentCalculationSettings
) -> list[dict[str, Any]]:
    """Copies of stored inline metric definitions, each with its calculation key in `fingerprint`. The
    chart reads the daily results of an inline metric by that stored key."""
    stamped = []
    for metric in metrics:
        metric_copy = deepcopy(metric)
        spec = settings.spec_for(metric_id=metric.get("uuid") or "", role=role, definition=metric)
        metric_copy["fingerprint"] = spec.calculation_key()
        stamped.append(metric_copy)
    return stamped
