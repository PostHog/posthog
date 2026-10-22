from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from django.conf import settings
from django.utils import timezone

import pydantic

from posthog.schema import EventPropertyFilter, ExperimentEventExposureConfig, MultipleVariantHandling, PropertyOperator

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team.team import Team

from products.experiments.backend.facade.contracts import ExperimentHealthFlagChangeKind
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    DEFAULT_EXPOSURE_EVENT,
    EXPERIMENT_EXPOSURE_EVENT,
    get_exposure_event_and_property,
    normalize_to_exposure_criteria,
)
from products.experiments.backend.metric_resolution import MetricRole, saved_metric_link_role, saved_metric_links
from products.experiments.backend.metric_utils import get_default_metric_title
from products.experiments.backend.metric_validation import defined_event_names, extract_entity_nodes
from products.experiments.backend.models.experiment import Experiment, ExperimentToSavedMetric
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.facade.filters import condition_aggregation, pinned_variant, reachable_conditions
from products.feature_flags.backend.facade.flags import get_organization_flag_evaluations_mode, has_active_flags


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
    # Whether the experiment counts groups rather than persons, by the rule the exposure query uses.
    counts_groups: bool
    # The persons or groups exposed between launch and the last counted change of a kind, up to
    # MIN_EXPOSED_UNITS_TO_WARN. Asked only for a kind with a counted change, so a kind that was not asked is absent.
    # None when unknown.
    exposed_units_before_last: Mapping[ExperimentHealthFlagChangeKind, int | None]

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
# A few early exposures, usually the creator's own test, can't move a result, so a change before this many is info.
MIN_EXPOSED_UNITS_TO_WARN = 5


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
class VariantProperty:
    """A property whose value names the variant. A person and a group, or two group types, can have a property with
    the same key, and those are different properties."""

    key: str
    group_type_index: int | None


@frozen
class ReachableCondition:
    # Numbered from 1, as the page labels the release conditions ("Set 2").
    number: int
    pinned_variant: str | None
    # The person or group property that the condition matches on alone, when its one value is the pinned variant's
    # key. The variant then comes from whatever sets that property, usually the customer's own assignment.
    variant_property: VariantProperty | None


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
    # The people who got a variant in a call that carries no flag version and is not a local evaluation in a server
    # SDK, from the start of the flag-state check's grace period after `since`. Such a call comes from a bootstrap or
    # from the customer's own code, so it can serve a variant that the flag's release conditions don't.
    people_assigned_outside: int


@frozen
class PauseHistory:
    """The experiment's latest pause or resume since launch, from its activity log. The experiment's Pause and Resume
    write these entries, from the page, the API or MCP. A flag disabled or enabled anywhere else, such as on the flag
    page, writes none."""

    launched_at: datetime
    team_timezone: str
    # The time of the latest entry when it is a pause. None when it is a resume, or the experiment has no entry.
    paused_at: datetime | None


@frozen
class ExposureTotals:
    total_exposures: Mapping[str, int]
    multiple_variant_handling: MultipleVariantHandling
    # None when the exposure query had too little data for the sample ratio test.
    sample_ratio_mismatch_p_value: float | None
    hours_since_launch: float | None
    # Whether the totals count groups rather than persons, by the rule the exposure query uses.
    counts_groups: bool


@frozen
class MetricEvents:
    """A metric of the experiment and the events that it reads by name."""

    name: str
    role: MetricRole
    events: tuple[str, ...]


@frozen
class FlagKeyFilter:
    """An event property filter of the exposure criteria on `$feature_flag`, the key of the called flag."""

    operator: PropertyOperator
    values: tuple[str | float | bool, ...]


@frozen
class ExposureEvents:
    """The events that the exposure criteria count."""

    # The event that the criteria name in place of the flag call events. None when the criteria count the flag call
    # events or an action.
    custom_event: str | None
    # The flag key that the exposure query requires in `$feature_flag`, because the flag call events are not specific
    # to one flag. None when the criteria count a custom event or an action, and when the experiment has no flag.
    required_flag_key: str | None
    flag_key_filters: tuple[FlagKeyFilter, ...]


@frozen
class HealthContext:
    """Every input of the health checks, loaded once, so that each check is a pure function of it."""

    is_launched: bool
    is_running: bool
    has_ended: bool
    is_paused: bool
    archived: bool
    flag: FlagState | None
    # Whether PostHog has recorded a call of the flag. None when the experiment has no flag, or when PostHog can't
    # record the calls of this organization's flags.
    flag_called: bool | None
    # Whether the team has an active flag, which posthog-js needs to request flags on page load. None when not read:
    # it is read only for a draft whose flag has no recorded call.
    team_has_active_flag: bool | None
    # The baseline set in the experiment's settings. None when unset: the analysis then picks a variant of the flag.
    baseline_variant_key: str | None
    primary_metric_count: int
    secondary_metric_count: int
    hours_since_launch: float | None
    metric_events: tuple[MetricEvents, ...]
    # None when the stored exposure criteria don't parse.
    exposure_events: ExposureEvents | None
    # Whether the project has received each event that `metric_events` and `exposure_events` name. A name that
    # ingestion never writes an event definition for is absent, because its absence proves nothing.
    events_received: Mapping[str, bool]
    exposures: ExposureTotals | None
    # None when not loaded. Only the health endpoint loads it, because it can query the exposures.
    flag_history: FlagHistory | FlagHistoryNotChecked | None
    # None when not loaded or unknown. Only the health endpoint loads it, because it queries the events.
    condition_set_traffic: ConditionSetTraffic | None
    # None when not loaded or unknown. Only the health endpoint loads it, and only for a paused experiment.
    pause_history: PauseHistory | None
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
            _reachable_condition(index + 1, conditions[index], variant_keys, aggregation_group_type_index)
            for index in reachable
        ),
    )


def _reachable_condition(
    number: int, condition: Mapping[str, Any], variant_keys: set[str], flag_aggregation: int | None
) -> ReachableCondition:
    pinned = pinned_variant(condition, variant_keys)
    return ReachableCondition(
        number=number,
        pinned_variant=pinned,
        variant_property=None if pinned is None else _variant_property(condition, pinned, flag_aggregation),
    )


def _variant_property(
    condition: Mapping[str, Any], pinned: str, flag_aggregation: int | None
) -> VariantProperty | None:
    properties = condition.get("properties")
    if not isinstance(properties, list) or len(properties) != 1 or not isinstance(properties[0], dict):
        return None
    key = properties[0].get("key")
    value = properties[0].get("value")
    values = value if isinstance(value, list) else [value]
    if (
        properties[0].get("type") not in ("person", "group")
        or properties[0].get("operator") not in ("exact", None)
        or len(values) != 1
        or not isinstance(key, str)
    ):
        return None
    # The flag service compares `exact` values as lowercase strings.
    if str(values[0]).lower() != pinned.lower():
        return None
    if properties[0].get("type") == "person":
        return VariantProperty(key=key, group_type_index=None)
    # A group filter without its own group type reads the group the condition aggregates on.
    group_type_index = properties[0].get("group_type_index")
    return VariantProperty(
        key=key,
        group_type_index=group_type_index
        if isinstance(group_type_index, int)
        else condition_aggregation(condition, flag_aggregation),
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


def _flag_called(experiment: Experiment) -> bool | None:
    # django-stubs types the id as int, but an unsaved instance can carry None.
    feature_flag_id: int | None = experiment.feature_flag_id
    if feature_flag_id is None:
        return None
    if experiment.feature_flag.last_called_at is not None:
        return True
    # The task that sets `last_called_at` reads `$feature_flag_called` from the events table, unless it is set to
    # read flag_evaluations. On FLAG_EVALUATIONS_ONLY, ingestion writes no `$feature_flag_called` to the events table
    # for the teams in its allowlist, which this side can't read. Their flags keep no `last_called_at` however often
    # they are called.
    if settings.FEATURE_FLAG_LAST_CALLED_AT_SYNC_SOURCE != "flag_evaluations" and (
        get_organization_flag_evaluations_mode(experiment.team.organization_id)
        == FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY
    ):
        return None
    return False


def _metric_events(experiment: Experiment, links: list[ExperimentToSavedMetric]) -> tuple[MetricEvents, ...]:
    named: list[tuple[str | None, MetricRole, object]] = [
        *((None, "primary", metric) for metric in experiment.metrics or []),
        *((None, "secondary", metric) for metric in experiment.metrics_secondary or []),
        *((link.saved_metric.name, saved_metric_link_role(link), link.saved_metric.query) for link in links),
    ]
    metrics: list[MetricEvents] = []
    for shared_name, role, metric in named:
        if not isinstance(metric, dict):
            continue
        events, _ = extract_entity_nodes([metric])
        if events:
            name = shared_name or metric.get("name") or get_default_metric_title(metric)
            metrics.append(MetricEvents(name=name, role=role, events=tuple(sorted(events))))
    return tuple(metrics)


def _exposure_events(experiment: Experiment) -> ExposureEvents | None:
    try:
        criteria = normalize_to_exposure_criteria(experiment.exposure_criteria)
    except pydantic.ValidationError:
        return None
    flag_key = experiment.feature_flag.key if experiment.feature_flag_id else None
    event, _ = get_exposure_event_and_property(flag_key or "", criteria, default_exposure_event=DEFAULT_EXPOSURE_EVENT)
    reads_flag_calls = event in (DEFAULT_EXPOSURE_EVENT, EXPERIMENT_EXPOSURE_EVENT)
    config = criteria.exposure_config if criteria else None
    properties = config.properties if isinstance(config, ExperimentEventExposureConfig) else []
    return ExposureEvents(
        custom_event=event if event is not None and not reads_flag_calls else None,
        required_flag_key=flag_key if reads_flag_calls else None,
        flag_key_filters=tuple(
            # The exposure query reads a filter without an operator as `exact`, as `property_to_expr` does.
            FlagKeyFilter(operator=prop.operator or PropertyOperator.EXACT, values=_filter_values(prop.value))
            for prop in properties
            if isinstance(prop, EventPropertyFilter) and prop.key == "$feature_flag"
        ),
    )


def _filter_values(value: list[str | float | bool] | str | float | bool | None) -> tuple[str | float | bool, ...]:
    if isinstance(value, list):
        return tuple(value)
    return () if value is None else (value,)


# Ingestion writes no event definition for these names, so a missing definition doesn't show that the project never
# received the event. See `EVENTS_WITHOUT_PROPERTIES` and `will_fit_in_postgres_column` in
# rust/property-defs-rs/src/types.rs.
_EVENTS_WITHOUT_DEFINITION = frozenset({"$$plugin_metrics"})
_MAX_EVENT_DEFINITION_NAME_BYTES = 200


def _has_event_definition(name: str) -> bool:
    return name not in _EVENTS_WITHOUT_DEFINITION and len(name.encode()) <= _MAX_EVENT_DEFINITION_NAME_BYTES


def _events_received(
    experiment: Experiment, metric_events: tuple[MetricEvents, ...], exposure_events: ExposureEvents | None
) -> dict[str, bool]:
    names = {event for metric in metric_events for event in metric.events}
    if exposure_events is not None and exposure_events.custom_event is not None:
        names.add(exposure_events.custom_event)
    checked = {name for name in names if _has_event_definition(name)}
    project_id = experiment.team.project_id
    received = defined_event_names(project_id, checked, seen_only=True)
    checked -= _deleted_definition_names(project_id, checked - received, since=_deletions_since(experiment))
    return {name: name in received for name in checked}


# Ingestion writes a deleted definition again when it next sees the event, which takes up to about an hour for an
# event that keeps arriving. A margin of a day also covers events that arrive a few times a day.
_DEFINITION_RECREATION_MARGIN = timedelta(days=1)


def _deletions_since(experiment: Experiment) -> datetime:
    # An earlier deletion matters only if the event stopped arriving: an event that arrived during the run, or
    # within the margin, has a new definition. So a deletion before then leaves the finding correct.
    recent = timezone.now() - _DEFINITION_RECREATION_MARGIN
    return min(experiment.start_date, recent) if experiment.start_date is not None else recent


def _deleted_definition_names(project_id: int, names: set[str], *, since: datetime) -> set[str]:
    # Until ingestion writes a deleted definition again, the project can hold the event without a definition.
    if not names:
        return set()
    return set(
        ActivityLog.objects.filter(
            team_id__in=Team.objects.filter(project_id=project_id).values("id"),
            scope="EventDefinition",
            activity="deleted",
            created_at__gte=since,
            # These match the condition of `idx_alog_team_act_scope_usr`, so the lookup reads only the deletions. A
            # deletion made while impersonating a user is not read.
            was_impersonated=False,
            is_system=False,
            detail__name__in=names,
        ).values_list("detail__name", flat=True)
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
    links = saved_metric_links(experiment)
    shared_metric_roles = [saved_metric_link_role(link) for link in links]
    flag_called = _flag_called(experiment)
    metric_events = _metric_events(experiment, links)
    exposure_events = _exposure_events(experiment)
    return HealthContext(
        is_launched=experiment.is_launched,
        is_running=experiment.is_running,
        has_ended=experiment.is_stopped,
        is_paused=experiment.is_paused,
        archived=experiment.archived,
        flag=_load_flag_state(experiment),
        flag_called=flag_called,
        team_has_active_flag=(
            has_active_flags(experiment.team) if flag_called is False and not experiment.is_launched else None
        ),
        baseline_variant_key=_configured_baseline_variant_key(experiment.stats_config),
        primary_metric_count=len(experiment.metrics or []) + shared_metric_roles.count("primary"),
        secondary_metric_count=len(experiment.metrics_secondary or []) + shared_metric_roles.count("secondary"),
        hours_since_launch=experiment.hours_since_launch,
        metric_events=metric_events,
        exposure_events=exposure_events,
        events_received=_events_received(experiment, metric_events, exposure_events),
        exposures=exposures,
        flag_history=flag_history,
        condition_set_traffic=None,
        pause_history=None,
        excluded_variant_keys=frozenset(experiment.excluded_variants or []),
    )
