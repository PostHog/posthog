from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum

from posthog.schema import MultipleVariantHandling

from posthog.dataclasses import frozen

from products.experiments.backend.metric_resolution import saved_metric_link_role, saved_metric_links
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.facade.filters import pinned_variant, reachable_conditions


@frozen
class FlagVariant:
    key: str | None
    rollout_percentage: float | None


Split = tuple[FlagVariant, ...]


@frozen
class SplitChange:
    changed_at: datetime
    before: Split
    after: Split


@frozen
class SplitHistory:
    """The changes of the flag's split after launch that can have moved exposed people to another variant."""

    launched_at: datetime
    team_timezone: str
    # Every split change since launch. The counted changes are its tail.
    changes: tuple[SplitChange, ...]
    # From the first change with an exposure before it, or with an unknown answer, to the last change.
    # Empty when nobody was exposed before any change: those changes moved nobody.
    counted_changes: tuple[SplitChange, ...]
    # None when unknown: the exposure query failed, or the request ran out of queries or time.
    exposed_before_first: bool | None
    # Asked only when the last change sets the split back to what it was before the first. None when not
    # asked, or unknown.
    exposed_between: bool | None


class SplitHistoryNotCheckedReason(StrEnum):
    # pinned: the finding's `evidence.reason`.
    NO_HISTORY_ACCESS = "no_history_access"
    NO_QUERY_ACCESS = "no_query_access"
    EXPOSURE_FILTERS = "exposure_filters"
    EXPOSURE_ACTION = "exposure_action"
    EXPOSURE_CRITERIA = "exposure_criteria"


@frozen
class SplitHistoryNotChecked:
    """A split history that was not compared with the exposures, and the reason."""

    reason: SplitHistoryNotCheckedReason
    launched_at: datetime
    team_timezone: str
    # Every split change since launch. Empty for NO_HISTORY_ACCESS, which does not read them.
    changes: tuple[SplitChange, ...]


@frozen
class FlagReleaseGroup:
    rollout_percentage: float | None
    property_count: int | None


@frozen
class ReachableCondition:
    # Numbered from 1, as the page labels the release conditions ("Set 2").
    number: int
    pinned_variant: str | None


@frozen
class FlagState:
    active: bool
    deleted: bool
    release_groups: tuple[FlagReleaseGroup, ...]
    variants: tuple[FlagVariant, ...]
    # The release conditions that can serve a request, in evaluation order.
    reachable_conditions: tuple[ReachableCondition, ...]


@frozen
class ConditionSetTraffic:
    """The flag's `$feature_flag_called` events of the last days, by the release condition that served each person."""

    # The latest of launch, the flag's last save and the start of the window.
    since: datetime
    team_timezone: str
    # People by the condition set that served their latest call of the flag's current version.
    people_by_set: Mapping[int, int]
    # The calls that returned a variant, and those of them that the flag service evaluated, which alone name a set.
    calls: int
    remotely_evaluated_calls: int


@frozen
class ExposureTotals:
    total_exposures: Mapping[str, int]
    multiple_variant_handling: MultipleVariantHandling
    # None when the exposure query had too little data for the sample ratio test.
    sample_ratio_mismatch_p_value: float | None
    hours_since_launch: float | None


@frozen
class HealthContext:
    """Every input of the health checks, loaded once, so that each check is a pure function of it."""

    is_launched: bool
    is_running: bool
    has_ended: bool
    is_paused: bool
    archived: bool
    flag: FlagState | None
    # The baseline set in the experiment's settings. None when unset: the analysis then picks a variant of the flag.
    baseline_variant_key: str | None
    primary_metric_count: int
    secondary_metric_count: int
    exposures: ExposureTotals | None
    # None when not loaded. Only the health endpoint loads it, because it can query the exposures.
    split_history: SplitHistory | SplitHistoryNotChecked | None
    # None when not loaded or unknown. Only the health endpoint loads it, because it queries the events.
    condition_set_traffic: ConditionSetTraffic | None
    # The variants that the analysis leaves out of the results.
    excluded_variant_keys: frozenset[str]


def parse_flag_state(
    *,
    active: bool,
    deleted: bool,
    groups: object,
    variants: object,
    aggregation_group_type_index: int | None = None,
    early_exit: bool = False,
) -> FlagState:
    conditions = groups if isinstance(groups, list) else []
    flag_variants = parse_variants(variants)
    variant_keys = {variant.key for variant in flag_variants if variant.key}
    reachable = reachable_conditions(conditions, flag_aggregation=aggregation_group_type_index, early_exit=early_exit)
    return FlagState(
        active=active,
        deleted=deleted,
        release_groups=tuple(_release_group(group) for group in conditions),
        variants=flag_variants,
        reachable_conditions=tuple(
            ReachableCondition(number=index + 1, pinned_variant=pinned_variant(conditions[index], variant_keys))
            for index in reachable
        ),
    )


def _release_group(group: object) -> FlagReleaseGroup:
    if not isinstance(group, dict):
        return FlagReleaseGroup(rollout_percentage=None, property_count=None)
    properties = group.get("properties")
    return FlagReleaseGroup(
        rollout_percentage=_percentage(group.get("rollout_percentage")),
        property_count=len(properties) if isinstance(properties, list) else None,
    )


def _variant(variant: object) -> FlagVariant:
    if not isinstance(variant, dict):
        return FlagVariant(key=None, rollout_percentage=None)
    key = variant.get("key")
    return FlagVariant(
        key=key if isinstance(key, str) else None,
        rollout_percentage=_percentage(variant.get("rollout_percentage")),
    )


def parse_variants(variants: object) -> Split:
    return tuple(_variant(variant) for variant in variants) if isinstance(variants, list) else ()


def _percentage(value: object) -> float | None:
    # The page compares with `=== 0` and `=== 100`, so only a JSON number can match. A string or a
    # boolean must not, and Python's `False == 0` would let a boolean through.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _load_flag_state(experiment: Experiment) -> FlagState | None:
    # django-stubs types the id as int, but an unsaved instance can carry None.
    feature_flag_id: int | None = experiment.feature_flag_id
    if feature_flag_id is None:
        return None
    flag = experiment.feature_flag
    return parse_flag_state(
        active=bool(flag.active),
        deleted=bool(flag.deleted),
        groups=flag.conditions,
        variants=flag.variants,
        aggregation_group_type_index=flag.aggregation_group_type_index,
        early_exit=flag.early_exit,
    )


def _configured_baseline_variant_key(stats_config: object) -> str | None:
    # An empty key counts as unset, as in `get_baseline_variant_key`.
    key = stats_config.get("baseline_variant_key") if isinstance(stats_config, dict) else None
    return key if isinstance(key, str) and key else None


def load_health_context(
    experiment: Experiment,
    exposures: ExposureTotals | None = None,
    *,
    split_history: SplitHistory | SplitHistoryNotChecked | None = None,
) -> HealthContext:
    shared_metric_roles = [saved_metric_link_role(link) for link in saved_metric_links(experiment)]
    return HealthContext(
        is_launched=experiment.is_launched,
        is_running=experiment.is_running,
        has_ended=experiment.is_stopped,
        is_paused=experiment.is_paused,
        archived=experiment.archived,
        flag=_load_flag_state(experiment),
        baseline_variant_key=_configured_baseline_variant_key(experiment.stats_config),
        primary_metric_count=len(experiment.metrics or []) + shared_metric_roles.count("primary"),
        secondary_metric_count=len(experiment.metrics_secondary or []) + shared_metric_roles.count("secondary"),
        exposures=exposures,
        split_history=split_history,
        condition_set_traffic=None,
        excluded_variant_keys=frozenset(experiment.excluded_variants or []),
    )
