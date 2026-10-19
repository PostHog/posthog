from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum

from posthog.schema import MultipleVariantHandling

from posthog.dataclasses import frozen

from products.experiments.backend.facade.contracts import ExperimentHealthFlagChangeKind
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


class BucketingSetting(StrEnum):
    # The flag settings besides the split that are inputs of the variant draw, in the order the findings name them.
    KEY = "key"
    AGGREGATION = "aggregation"
    BUCKETING_IDENTIFIER = "bucketing_identifier"
    EXPERIENCE_CONTINUITY = "experience_continuity"


@frozen
class BucketingChange:
    changed_at: datetime
    setting: BucketingSetting
    # The key as a string, the aggregation as a group type index or None for persons, the identifier as
    # "distinct_id" or "device_id", the continuity as a bool.
    before: str | int | bool | None
    after: str | int | bool | None


@frozen
class ReleaseCondition:
    # The group type and property filters of the condition, as a signature that is equal for two conditions
    # that match the same people under the flag-level aggregation of their save. The rollout is not part of it.
    criteria: str
    # The group type index that the condition matches, None for persons, and the keys of its property filters.
    # The flag page's history pairs two conditions that share them as one condition edited.
    aggregation: int | None
    property_keys: frozenset[str]
    rollout: float
    variant: str | None


@frozen
class ConditionsChange:
    changed_at: datetime
    before: tuple[ReleaseCondition, ...]
    after: tuple[ReleaseCondition, ...]


# A change of the flag after launch that can move exposed people. A new kind needs its class here, an
# `ExperimentHealthFlagChangeKind`, its read and its set-back question in `exposure_gate.py`, its row in
# `inputs_payload.py`, and its check.
FlagChange = SplitChange | BucketingChange | ConditionsChange


def changes_of_kind[C: FlagChange](changes: tuple[FlagChange, ...], kind: type[C]) -> tuple[C, ...]:
    return tuple(change for change in changes if isinstance(change, kind))


@frozen
class ChangeWindow:
    start: datetime
    end: datetime


@frozen
class FlagHistory:
    """The changes of the flag after launch that can have moved exposed people, and whether anyone was exposed
    before them. A change before the first exposure moved nobody, so it does not count."""

    launched_at: datetime
    team_timezone: str
    # Every change of every kind, in time order.
    changes: tuple[FlagChange, ...]
    # The time of the first change, of any kind, with an exposure before it or an unknown answer. Every change
    # from then on counts. None when nobody was exposed before any change.
    counted_since: datetime | None
    # None when unknown: the exposure query failed, or the request ran out of queries or time.
    exposed_before_first: bool | None
    # Whether anyone was exposed between the first and the last counted change of a kind. Asked only when the last
    # sets back what the first changed, so a kind that was not asked is absent. None when unknown.
    exposed_between: Mapping[ExperimentHealthFlagChangeKind, bool | None]
    # The flag's release conditions now. A save that no kind counts can renumber them after the last change, and
    # the findings and the traffic number the conditions as they are now.
    release_conditions: tuple[ReleaseCondition, ...]
    # Whether anyone was exposed while an override was set and removed again, or removed and set back. A user
    # exposed only outside that window got the same variant throughout. None when unknown.
    exposed_during_overrides: Mapping[ChangeWindow, bool | None]

    def of_kind[C: FlagChange](self, kind: type[C]) -> tuple[C, ...]:
        return changes_of_kind(self.changes, kind)

    def counted[C: FlagChange](self, kind: type[C]) -> tuple[C, ...]:
        since = self.counted_since
        return () if since is None else tuple(change for change in self.of_kind(kind) if change.changed_at >= since)


class FlagHistoryNotCheckedReason(StrEnum):
    # pinned: the finding's `evidence.reason`.
    NO_HISTORY_ACCESS = "no_history_access"
    NO_QUERY_ACCESS = "no_query_access"
    EXPOSURE_FILTERS = "exposure_filters"
    EXPOSURE_ACTION = "exposure_action"
    EXPOSURE_CRITERIA = "exposure_criteria"
    # The history is not read past these bounds, because the work grows with the saves and the conditions, and the
    # experiment page asks on every load.
    TOO_MANY_SAVES = "too_many_saves"
    TOO_MANY_CONDITIONS = "too_many_conditions"


MAX_FLAG_SAVES = 100
MAX_RELEASE_CONDITIONS = 100


@frozen
class FlagHistoryNotChecked:
    """A flag history that was not compared with the exposures, and the reason. Every change counts."""

    reason: FlagHistoryNotCheckedReason
    launched_at: datetime
    team_timezone: str
    # Every change since launch, in time order. Empty for NO_HISTORY_ACCESS, which does not read them.
    changes: tuple[FlagChange, ...]

    def of_kind[C: FlagChange](self, kind: type[C]) -> tuple[C, ...]:
        return changes_of_kind(self.changes, kind)


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
    flag_history: FlagHistory | FlagHistoryNotChecked | None
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
    flag_history: FlagHistory | FlagHistoryNotChecked | None = None,
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
        flag_history=flag_history,
        condition_set_traffic=None,
        excluded_variant_keys=frozenset(experiment.excluded_variants or []),
    )
