"""The configuration of one metric calculation, and the key that files and finds its results.

A `MetricCalculationConfig` combines the effective definition of one metric with what its calculation reads
from the experiment, its feature flag, the team and the team's experiment settings, with defaults resolved to
concrete values. `build_calculation_configs` builds the configs of the metrics that an experiment calculates.
Building a config does not schedule or run a calculation.

A config does not pin the events and warehouse rows, the definitions a metric references (actions,
cohorts, warehouse tables, property types), the team's HogQL modifiers, or the clock that the maturity
filters read. The same config can therefore give a different result later. Equality and the key also leave out
which event the `experiment-exposure-event` flag picks as the default exposure event, so a result stays
reusable for its window when that flag changes for the team.

The settings factories reset a value that the calculation ignores to its default: the CUPED lookback without
CUPED, and the sequential tuning parameter without sequential testing. So such a value does not split equal
configs.

The calculation key (version 2) hashes the metric and an explicit field list of each setting that equality
compares, with numbers normalized. So equal configs have equal keys, and so do settings that differ only by float
noise. Key version 1 (`legacy_key`) hashes only part of a config: the metric, the start date, the stats method,
the exposure criteria as stored, maturity and the excluded variants. Results stored under version 1 can therefore
come from other baseline, CUPED, statistics, entity or test account settings than the current ones, so readers
show them as legacy history and never reuse them.
"""

import json
import hashlib
import dataclasses
from collections.abc import Collection, Mapping
from copy import deepcopy
from dataclasses import field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import pydantic

from posthog.schema import ActionsNode, ExperimentEventExposureConfig

from posthog.dataclasses import frozen

from products.experiments.backend.hogql_queries import get_baseline_variant_key
from products.experiments.backend.hogql_queries.cuped_config import CupedQueryConfig, resolve_experiment_cuped_config
from products.experiments.backend.hogql_queries.experiment_query_builder import (
    ExposureQueryParams,
    get_exposure_config_params_for_builder,
)
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    DEFAULT_EXPOSURE_EVENT,
    get_multiple_variant_handling_from_experiment,
    is_default_exposure_config,
    normalize_to_exposure_criteria,
    resolve_filter_test_accounts,
)
from products.experiments.backend.hogql_queries.utils import (
    BayesianSettings,
    FrequentistSettings,
    StatsMethod,
    resolve_bayesian_settings,
    resolve_frequentist_settings,
    resolve_stats_method,
)
from products.experiments.backend.metric_resolution import (
    MetricRole,
    apply_saved_metric_overrides,
    get_effective_experiment_metrics,
    get_metrics_for_calculation,
    saved_metric_link_role,
    saved_metric_links,
)
from products.experiments.backend.models.experiment import Experiment, metric_display_rank
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.stats.frequentist.method import DEFAULT_SEQUENTIAL_TUNING_PARAMETER

if TYPE_CHECKING:
    from posthog.models.team.team import Team

    from products.feature_flags.backend.models.feature_flag import FeatureFlag

SPEC_VERSION = 1

# The version of the calculation key, hashed into the key itself. A change that makes the engine compute a
# different result for an existing config bumps it, so that results computed before the change stop counting
# for reuse.
CALCULATION_KEY_VERSION = 2

# Significant digits that a float keeps in the calculation key. Stored settings carry float noise, for
# example `1 - 0.95` is stored as 0.050000000000000044, and the noise must not split equal settings into
# two keys.
_KEY_FLOAT_DIGITS = 12

# Stands for the default exposure event in the key. The `experiment-exposure-event` flag picks that event, and each
# process evaluates the flag locally (`resolve_default_exposure_event`). A key that hashed the picked event would
# change at each rollout step of the flag, and two processes that evaluate the flag differently would file and look
# up the results of one experiment under two keys. A stored result therefore stays reusable for its window when the
# flag changes. To make results computed with the old default event stop counting for reuse when the new event
# ships to every team, treat the switch as an engine change and bump CALCULATION_KEY_VERSION.
_DEFAULT_EXPOSURE_EVENT_IN_KEY = "$default_exposure_event"

# Metric types whose query does not read the team's time zone, so a time zone change keeps their key. A retention
# metric truncates its window to days or hours in that time zone, and a metric type outside this set, or a legacy
# metric without one, keeps the time zone in its key. A HogQL expression inside a metric can also read the time
# zone, and the key does not detect that case.
_TIMEZONE_FREE_METRIC_TYPES = frozenset({"mean", "funnel", "ratio"})

# Fields of a stored metric definition that do not describe what the metric computes: its identity, its
# display name, the stored key itself, and an experiment-level setting that some stored definitions carry.
_NON_ANALYTICAL_METRIC_FIELDS = frozenset({"uuid", "name", "kind", "fingerprint", "only_count_matured_users"})


def _strip_empty_breakdowns(metric: dict[str, Any]) -> None:
    """Remove a breakdownFilter that carries no breakdowns.

    An empty breakdown list is the same metric config as no breakdowns, but the two dict shapes hash to
    different values. Saved-metric resolution (`apply_saved_metric_overrides`) injects
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


def _canonical(value: Any) -> Any:
    """`value` as JSON data that is equal for equal settings: floats rounded to _KEY_FLOAT_DIGITS significant
    digits, a float with an integral value as an int, enums as their values, and datetimes as UTC ISO strings, so
    the same instant gives the same key in every timezone.

    It refuses models and dataclasses. A dump of a whole model hashes every field the model has, so a schema change
    that adds a defaulted field would change every key. The key reads such inputs through explicit field lists.
    """
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        rounded = float(f"{value:.{_KEY_FLOAT_DIGITS}g}")
        return int(rounded) if rounded.is_integer() else rounded
    if isinstance(value, Enum):
        return _canonical(value.value)
    if isinstance(value, datetime):
        return value.astimezone(ZoneInfo("UTC")).isoformat()
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_canonical(item) for item in value]
    raise TypeError(f"Cannot hash a {type(value).__name__} into a calculation key")


def _variant_keys(feature_flag: "FeatureFlag", excluded_variants: tuple[str, ...]) -> tuple[str, ...]:
    keys = (variant.get("key") for variant in feature_flag.variants if isinstance(variant, dict))
    return tuple(key for key in keys if isinstance(key, str) and key not in excluded_variants)


def team_experiments_configs(team_ids: Collection[int]) -> dict[int, TeamExperimentsConfig]:
    """The experiment settings of each team, read in one query.

    A team without a stored row gets an unsaved row with the model defaults. `get_or_create_team_extension`
    stores the same values, so the settings do not change, and a read path such as the experiment API
    response never writes a row.
    """
    stored = {config.team_id: config for config in TeamExperimentsConfig.objects.filter(team_id__in=team_ids)}
    return {team_id: stored.get(team_id) or TeamExperimentsConfig(team_id=team_id) for team_id in team_ids}


def _resolve_exposure(
    exposure_criteria: dict[str, Any] | None, team: "Team", start_date: datetime | None
) -> ExposureQueryParams | None:
    try:
        return get_exposure_config_params_for_builder(exposure_criteria, team, start_date)
    except pydantic.ValidationError:
        return None


def _exposure_entity(
    config: ExperimentEventExposureConfig | ActionsNode | None, stored_config: Any, *, default_event_resolves: bool
) -> dict[str, Any]:
    """The event or action of an exposure or activation config, and its property filters as stored. The stored
    filters stay the same when a schema change adds a defaulted field to a filter model, so the key does too."""
    stored_properties = stored_config.get("properties") if isinstance(stored_config, dict) else None
    properties = deepcopy(list(stored_properties or []))
    if isinstance(config, ActionsNode):
        return {"action_id": config.id, "properties": properties}
    if config is None or (default_event_resolves and config.event == DEFAULT_EXPOSURE_EVENT):
        return {"event": _DEFAULT_EXPOSURE_EVENT_IN_KEY, "properties": properties}
    return {"event": config.event, "properties": properties}


def normalize_exposure(exposure_criteria: dict[str, Any] | None) -> dict[str, Any]:
    """The stored exposure criteria with the product defaults applied, as the calculation key reads them.

    It follows `get_exposure_config_params_for_builder`, except that the default exposure event stays unresolved
    (`_DEFAULT_EXPOSURE_EVENT_IN_KEY`). Activation applies only with the default exposure, and an activation config
    names its event literally, as in the query builder.
    """
    try:
        criteria = normalize_to_exposure_criteria(exposure_criteria)
    except pydantic.ValidationError:
        # The query runner rejects such criteria. Their stored form keeps them apart from every valid configuration.
        return {"unparsed": deepcopy(exposure_criteria)}
    stored = exposure_criteria if isinstance(exposure_criteria, dict) else {}
    exposure_config = criteria.exposure_config if criteria is not None else None
    normalized: dict[str, Any] = {
        "exposure": _exposure_entity(exposure_config, stored.get("exposure_config"), default_event_resolves=True),
        "multiple_variant_handling": get_multiple_variant_handling_from_experiment(criteria).value,
        "filter_test_accounts": resolve_filter_test_accounts(criteria),
    }
    if criteria is not None and criteria.activation_config is not None and is_default_exposure_config(exposure_config):
        normalized["activation"] = _exposure_entity(
            criteria.activation_config, stored.get("activation_config"), default_event_resolves=False
        )
    return normalized


def _statistics_key_input(stats: BayesianSettings | FrequentistSettings) -> dict[str, Any]:
    if isinstance(stats, FrequentistSettings):
        return {
            "method": "frequentist",
            "alpha": _canonical(stats.alpha),
            "difference_type": stats.difference_type.value,
            "sequential_testing_enabled": stats.sequential_testing_enabled,
            "sequential_tuning_parameter": _canonical(stats.sequential_tuning_parameter),
        }
    return {
        "method": "bayesian",
        "ci_level": _canonical(stats.ci_level),
        "difference_type": stats.difference_type.value,
    }


def _cuped_key_input(cuped: CupedQueryConfig) -> dict[str, Any]:
    return {"enabled": cuped.enabled, "lookback_days": cuped.lookback_days}


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
    # What the query runner resolves from the stored exposure criteria. The `experiment-exposure-event` flag picks its
    # default exposure event, so equality and the key read `normalized_exposure` instead. None when the stored
    # criteria do not parse. The query runner rejects such an experiment.
    exposure: ExposureQueryParams | None = field(compare=False)
    # The stored exposure criteria as `normalize_exposure` returns them.
    normalized_exposure: dict[str, Any]
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
    def from_configuration(
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
        Without `team_config`, this reads the team's experiment settings with one query.
        """
        config = team_config or team_experiments_configs([team.id])[team.id]
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
            # Only the sequential test reads the tuning parameter. Without sequential testing, the stored value
            # computes the same thing as the default, as a CUPED lookback does without CUPED.
            if not stats.sequential_testing_enabled:
                stats = dataclasses.replace(stats, sequential_tuning_parameter=DEFAULT_SEQUENTIAL_TUNING_PARAMETER)
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
            normalized_exposure=normalize_exposure(exposure_criteria),
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
    def from_experiment(
        cls, experiment: Experiment, *, team_config: TeamExperimentsConfig | None = None
    ) -> "ExperimentCalculationSettings":
        """Settings from the current fields of the experiment, which does not need to be saved. A caller that
        builds the configs of several experiments of one team passes the team's config to read it once."""
        return cls.from_configuration(
            team=experiment.team,
            feature_flag=experiment.feature_flag,
            start_date=experiment.start_date,
            stats_config=experiment.stats_config,
            exposure_criteria=experiment.exposure_criteria,
            only_count_matured_users=experiment.only_count_matured_users,
            excluded_variants=experiment.excluded_variants,
            team_config=team_config,
        )

    def build_metric_config(
        self, *, metric_id: str, role: MetricRole, definition: dict[str, Any]
    ) -> "MetricCalculationConfig":
        """The calculation config of one metric under these settings. `definition` is the effective
        definition, with the saved-metric link overrides applied."""
        return MetricCalculationConfig(
            spec_version=SPEC_VERSION,
            metric_id=metric_id,
            role=role,
            metric=_analytical_definition(definition),
            definition=deepcopy(definition),
            settings=self,
        )


@frozen
class MetricCalculationConfig:
    """The configuration one metric calculation reads, and the key its results are filed under.

    Equal configs compute the same thing. The metric id and the role identify the metric and take no part
    in equality, so an inline metric and a saved metric with the same effective definition have equal configs.
    """

    spec_version: int
    # A metric without a uuid gets an empty id. Nothing can calculate or look up such a metric, and only
    # its stored `fingerprint` reads the config.
    metric_id: str = field(compare=False)
    role: MetricRole = field(compare=False)
    # The effective definition without the fields in _NON_ANALYTICAL_METRIC_FIELDS and without an empty
    # breakdown list.
    metric: dict[str, Any]
    # The effective definition as the API returns it and as the query runner receives it.
    definition: dict[str, Any] = field(compare=False)
    settings: ExperimentCalculationSettings

    def calculation_key(self) -> str:
        """The key that files and finds the results of this config, a SHA-256 hex digest (key version 2).

        It hashes the metric and each settings field that equality compares, except the team, together
        with CALCULATION_KEY_VERSION. Nested settings enter through explicit field lists. The time zone enters
        only for a metric type that reads it (`_TIMEZONE_FREE_METRIC_TYPES`). Result rows in
        ExperimentMetricResult and the stored `fingerprint` of each inline metric hold this key. A change to the
        hashed payload makes every stored result unreachable for reuse, so it goes with a bump of
        CALCULATION_KEY_VERSION.
        """
        settings = self.settings
        payload: dict[str, Any] = {
            "key_version": CALCULATION_KEY_VERSION,
            "metric": _canonical(self.metric),
            "start_date": _canonical(settings.start_date),
            "feature_flag_key": settings.feature_flag_key,
            "aggregation_group_type_index": settings.aggregation_group_type_index,
            "variants": list(settings.variants),
            "baseline": settings.baseline,
            "excluded_variants": list(settings.excluded_variants),
            "exposure": _canonical(settings.normalized_exposure),
            "test_account_filters": _canonical(settings.test_account_filters),
            "stats": _statistics_key_input(settings.stats),
            "cuped": _cuped_key_input(settings.cuped),
            "only_count_matured_users": settings.only_count_matured_users,
        }
        if self.metric.get("metric_type") not in _TIMEZONE_FREE_METRIC_TYPES:
            payload["timezone"] = settings.timezone
        return _sha256(payload)

    def legacy_key(self) -> str:
        """Key version 1, which rows written before key version 2 carry. Readers use it only to show those
        rows as legacy history. Nothing reuses a result found by this key."""
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
        return _sha256(payload)


def _sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_calculation_configs(
    experiment: Experiment, *, team_config: TeamExperimentsConfig | None = None
) -> list[MetricCalculationConfig]:
    """One calculation config per metric that `get_metrics_for_calculation` returns, in that order."""
    metrics = get_metrics_for_calculation(experiment)
    if not metrics:
        return []
    settings = ExperimentCalculationSettings.from_experiment(experiment, team_config=team_config)
    return [
        settings.build_metric_config(metric_id=metric.uuid, role=metric.role, definition=metric.definition)
        for metric in metrics
    ]


def build_primary_calculation_configs(
    experiment: Experiment, *, team_config: TeamExperimentsConfig | None = None
) -> list[MetricCalculationConfig]:
    """The configs of the primary metrics that the experiment calculates, inline and saved, in the order the
    results page lists them. The first one is the metric the product calls the experiment's primary metric."""
    rank = metric_display_rank(experiment.primary_metrics_ordered_uuids)
    primary = [
        calculation_config
        for calculation_config in build_calculation_configs(experiment, team_config=team_config)
        if calculation_config.role == "primary"
    ]
    # Stable, so metrics missing from the ordering keep the order of `get_metrics_for_calculation` behind the
    # ordered ones.
    return sorted(primary, key=lambda calculation_config: rank(calculation_config.metric_id))


def get_metric_calculation_config(experiment: Experiment, metric_uuid: str) -> MetricCalculationConfig | None:
    """The config that `build_calculation_configs` builds for one metric, or None when the experiment
    calculates no metric with this uuid."""
    return next(
        (
            calculation_config
            for calculation_config in build_calculation_configs(experiment)
            if calculation_config.metric_id == metric_uuid
        ),
        None,
    )


def find_calculation_config_by_key(
    experiment: Experiment, metric_uuid: str, calculation_key: str
) -> MetricCalculationConfig | None:
    """The calculation config of the experiment's metric with this uuid whose calculation key is `calculation_key`,
    under the current configuration of the experiment.

    Unlike `get_metric_calculation_config`, this keys an inline and a saved metric that share a uuid each by its
    own definition, the same way `metric_calculation_keys` does. None when no metric with this uuid has this key,
    for example because the configuration changed after the caller computed the key.
    """
    candidates = [metric for metric in get_effective_experiment_metrics(experiment) if metric.uuid == metric_uuid]
    if not candidates:
        return None
    settings = ExperimentCalculationSettings.from_experiment(experiment)
    for metric in candidates:
        calculation_config = settings.build_metric_config(
            metric_id=metric.uuid, role=metric.role, definition=metric.definition
        )
        if calculation_config.calculation_key() == calculation_key:
            return calculation_config
    return None


def stamp_calculation_keys(
    metrics: list[dict[str, Any]], role: MetricRole, settings: ExperimentCalculationSettings
) -> list[dict[str, Any]]:
    """Copies of stored inline metric definitions, each with its calculation key in `fingerprint`. Readers
    derive the key from the config, so the stored value only describes the metric to API clients."""
    stamped = []
    for metric in metrics:
        metric_copy = deepcopy(metric)
        calculation_config = settings.build_metric_config(
            metric_id=metric.get("uuid") or "", role=role, definition=metric
        )
        metric_copy["fingerprint"] = calculation_config.calculation_key()
        stamped.append(metric_copy)
    return stamped


def inline_metric_calculation_keys(experiment: Experiment, settings: ExperimentCalculationSettings) -> dict[str, str]:
    """The key of each inline metric of the experiment, by metric uuid.

    When inline metrics share a uuid, the first one in primary-then-secondary order wins. The daily
    calculation computes that metric for the uuid, so the key matches what it computes.
    """
    keys: dict[str, str] = {}
    for metric in get_effective_experiment_metrics(experiment):
        if metric.source == "inline" and metric.uuid not in keys:
            calculation_config = settings.build_metric_config(
                metric_id=metric.uuid, role=metric.role, definition=metric.definition
            )
            keys[metric.uuid] = calculation_config.calculation_key()
    return keys


def saved_metric_calculation_keys(experiment: Experiment, settings: ExperimentCalculationSettings) -> dict[int, str]:
    """The key of each saved metric linked to the experiment, by link id.

    Unlike `build_calculation_configs`, this keeps metrics that cannot be scheduled, and it keys each saved
    metric by its own effective definition even when an inline metric has the same uuid. The daily
    saved-metric discovery and the `fingerprint` in the API response hash each link this way. A prefetched
    `experimenttosavedmetric_set` with its saved metrics makes this read no rows.
    """
    keys: dict[int, str] = {}
    for link in saved_metric_links(experiment):
        query = link.saved_metric.query
        if isinstance(query, dict):
            calculation_config = settings.build_metric_config(
                metric_id=query.get("uuid") or "",
                role=saved_metric_link_role(link),
                definition=apply_saved_metric_overrides(query, link.metadata),
            )
            keys[link.id] = calculation_config.calculation_key()
    return keys
