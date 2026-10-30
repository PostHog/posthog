from collections.abc import Mapping
from datetime import date, datetime, timedelta
from enum import StrEnum
from functools import reduce
from operator import or_
from typing import Any, Literal

from django.conf import settings
from django.db.models import Q, QuerySet
from django.utils import timezone

import pydantic

from posthog.schema import (
    ActionsNode,
    CohortPropertyFilter,
    EventPropertyFilter,
    ExperimentEventExposureConfig,
    MultipleVariantHandling,
    PersonPropertyFilter,
    PropertyOperator,
)

from posthog.hogql.constants import EXCEPTION_STRING_ARRAY_PROPERTIES
from posthog.hogql.property import operator_is_negative

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team.team import Team

from products.cohorts.backend.models.cohort import Cohort
from products.event_definitions.backend.models import EventDefinition, PropertyDefinition, effective_project_id_expr
from products.experiments.backend.facade.contracts import (
    ExperimentHealthFlagChangeKind,
    ExperimentHealthMetricCompileErrorKind,
)
from products.experiments.backend.facade.enums import ExposuresPath
from products.experiments.backend.health.delays import ENDED_FLAG_QUIET_PERIOD, LAST_CALLED_AT_LAG_DURATION
from products.experiments.backend.hogql_queries.experiment_exposure_query_builder import ExposureSegmentDimension
from products.experiments.backend.hogql_queries.experiment_query_builder import get_exposure_config_params_for_builder
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    DEFAULT_EXPOSURE_EVENT,
    EXPERIMENT_EXPOSURE_EVENT,
    get_exposure_event_and_property,
    normalize_to_exposure_criteria,
)
from products.experiments.backend.logic.result_stats import MetricResultStats
from products.experiments.backend.metric_resolution import MetricRole, saved_metric_link_role, saved_metric_links
from products.experiments.backend.metric_utils import get_default_metric_title
from products.experiments.backend.metric_validation import defined_event_names, extract_entity_nodes
from products.experiments.backend.models.experiment import Experiment, ExperimentToSavedMetric
from products.experiments.backend.running_time_target import RunningTimeTarget
from products.feature_flags.backend.facade.edits import (
    BucketingChange,
    ConditionsChange,
    FlagVariant,
    ReleaseCondition,
    SplitChange,
    parse_percentage,
    parse_variants,
)
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.facade.filters import condition_aggregation, pinned_variant, reachable_conditions
from products.feature_flags.backend.facade.flags import get_organization_flag_evaluations_mode, has_active_flags

# A change of the flag after launch that can move exposed people. A new kind needs its class in the flags facade
# (`facade/edits.py`), its member in this union, an `ExperimentHealthFlagChangeKind`, its read and its set-back
# question in `exposure_gate.py`, its row in `inputs_payload.py`, and its check.
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
    # pinned: the finding's `reason`.
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
    # The cohorts whose members the condition matches. A `not_in` cohort filter matches the users outside the cohort.
    member_cohort_ids: frozenset[int] = frozenset()


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
    # The end of the window, which is the time of the scan.
    until: datetime
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
class PrimaryMetric:
    """The experiment's first primary metric, which its running-time estimate sizes, with its stored result."""

    name: str
    is_funnel: bool
    # The target of the running time estimate, which the header of the experiment page shows.
    target: RunningTimeTarget
    # The current stored result, the one the results page shows after its last calculation. None when no completed
    # result is stored under the metric's current calculation key. Only read for a funnel.
    result: MetricResultStats | None


@frozen
class ExposureSegment:
    """The persons or groups whose first exposure carries one value of a dimension, such as the SDK library."""

    dimension: ExposureSegmentDimension
    # The property's value on the first exposure. BREAKDOWN_NULL_STRING_LABEL when the event has none, and
    # BREAKDOWN_OTHER_STRING_LABEL for the values outside the largest segments of the dimension. The version in the
    # library version dimension.
    value: str
    exposed_by_variant: Mapping[str, int]
    # The library of a library version segment, also BREAKDOWN_NULL_STRING_LABEL when the event has none. None in the
    # other dimensions and in the BREAKDOWN_OTHER_STRING_LABEL segment.
    library: str | None = None


@frozen
class ExposureTotals:
    total_exposures: Mapping[str, int]
    multiple_variant_handling: MultipleVariantHandling
    # None when the exposure query had too little data for the sample ratio test.
    sample_ratio_mismatch_p_value: float | None
    # The expected count of each variant that the sample ratio test compares, in the shares of the current split, and
    # the persons or groups first exposed on each day of the team's time zone, by variant. Only the exposure query
    # fills them, for the retest of `srm`, so both are empty elsewhere and without the test.
    sample_ratio_expected: Mapping[str, float]
    daily_exposures: Mapping[str, Mapping[date, int]]
    hours_since_launch: float | None
    # Whether the totals count groups rather than persons, by the rule the exposure query uses.
    counts_groups: bool
    # The next two need a scan of the exposure events. Only the exposure query loads them, and only when the check
    # that reads them reports a finding. None when not loaded or when the query failed.
    segments: tuple[ExposureSegment, ...] | None = None
    exposed_without_test_account_filter: int | None = None


@frozen
class MetricEvents:
    """A metric of the experiment and the events that it reads by name."""

    name: str
    role: MetricRole
    events: tuple[str, ...]


@frozen
class MetricCompileFailure:
    """A metric whose query doesn't compile, so every calculation of the metric fails."""

    metric_id: str
    name: str
    role: MetricRole
    kind: ExperimentHealthMetricCompileErrorKind
    # The compiler's message. None when it can hold the evaluation rules that the markers keep out of the browser.
    message: str | None
    # The effective definition, in which the wording looks for the names that the message gives.
    definition: Mapping[str, Any]


@frozen
class MetricCompiles:
    """The compile of the query of each metric that the experiment calculates, without running it."""

    metric_count: int
    failures: tuple[MetricCompileFailure, ...]
    # The metrics whose compile raised an error that names no problem of the metric, such as a defect of PostHog.
    unknown_count: int
    # The metrics that read a warehouse table or view that the reader may not query.
    no_access_count: int
    # Whether the exposure query alone doesn't compile. A failure then says nothing about the metric, so `failures`
    # is empty.
    exposure_query_fails: bool


@frozen
class MetricCalculationFailure:
    """A metric whose latest calculation failed, with the error that the calculation stored for it."""

    metric_id: str
    name: str
    role: MetricRole
    # The class that `classify_experiment_query_error` gave the error, or the class of a rejected calculation. None
    # for a failure that stores no class, such as one stored before calculations stored it.
    error_type: str | None
    step: str | None
    # The message as the results page shows it, without the names that HogQL suggests and the list of a scope's
    # fields. It can be the raw text of a ClickHouse or Python exception.
    message: str
    # Whether a HogQL message can quote the evaluation rules that the markers keep out of the browser, because the
    # definition holds a marker.
    can_quote_evaluation_rules: bool
    # Whether the results page shows a "Try again" button for the failure, which it does only for an error stored as
    # retriable.
    retriable: bool
    # The effective definition now, in which the wording looks for the names that the message gives.
    definition: Mapping[str, Any]
    # Where the query read the exposures. None for a failure stored before calculations stored it, and for a query that
    # failed before it was built.
    exposures_path: ExposuresPath | None


@frozen
class LatestCalculation:
    """The latest finished calculation of the experiment's metrics, whose results and errors the results page
    shows."""

    metric_count: int
    # None when no calculation has finished, so the page shows no stored error.
    finished_at: datetime | None
    # The metrics of the experiment now whose latest calculation failed, in calculation order.
    failures: tuple[MetricCalculationFailure, ...]
    # The metrics of the experiment now whose result of this calculation the page shows.
    completed_count: int
    # Where the queries of those results read the exposures, when there is a failure to compare them with.
    completed_exposures_paths: frozenset[ExposuresPath]


@frozen
class FlagKeyFilter:
    """An event property filter of the exposure criteria on `$feature_flag`, the key of the called flag."""

    operator: PropertyOperator
    values: tuple[str | float | bool, ...]


ExposurePropertyType = Literal["event", "person"]
ExposureFilterPropertyType = ExposurePropertyType | Literal["group"]


class ExposureFilterSource(StrEnum):
    EXPOSURE_CRITERIA = "exposure_criteria"
    EXPOSURE_ACTION = "exposure_action"
    TEST_ACCOUNTS = "test_accounts"


@frozen
class ExposureFilterWithoutColumn:
    """A property that the exposure query filters on and reads from the JSON of all the properties of each event, person
    or group."""

    type: ExposureFilterPropertyType
    key: str
    source: ExposureFilterSource


@frozen
class ExposurePropertyFilter:
    """A filter of the exposure criteria on an event or a person property. The exposure query applies it to each event
    that it reads, so it leaves out events, not users."""

    type: ExposurePropertyType
    key: str
    operator: PropertyOperator
    # None when the filter has no value. A list of values compiles differently from a missing value.
    values: tuple[str | float | bool, ...] | None
    # The event that the filter applies to. None for an action, which can match several events.
    event: str | None

    @classmethod
    def of(cls, prop: EventPropertyFilter | PersonPropertyFilter, event: str | None) -> "ExposurePropertyFilter":
        return cls(
            type=prop.type,
            key=prop.key,
            # The exposure query reads a filter without an operator as `exact`, as `property_to_expr` does.
            operator=prop.operator or PropertyOperator.EXACT,
            values=None if prop.value is None else _filter_values(prop.value),
            event=event,
        )

    @property
    def fails_when_missing(self) -> bool:
        """Whether no event without the property passes the filter, as `property_to_expr` compiles it.
        `TestFailsWhenMissing` compares this with the compiled filter in ClickHouse for every operator and value shape."""
        if self.values is None:
            return self.operator == PropertyOperator.IS_SET
        if not self.values:
            # An empty list matches every event, except for `icontains`.
            return self.operator == PropertyOperator.ICONTAINS
        if self.operator == PropertyOperator.FLAG_EVALUATES_TO or (
            self.operator == PropertyOperator.BETWEEN and len(self.values) != 2
        ):
            # The filter doesn't compile, so the exposure query fails before it reads a property.
            return False
        if self.operator == PropertyOperator.SEMVER_NEQ:
            # The scalar comparison drops a missing value, which isn't a version. The negated test of an exception
            # array keeps a missing array.
            return not (self.type == "event" and self.key in EXCEPTION_STRING_ARRAY_PROPERTIES)
        return not operator_is_negative(self.operator)

    @property
    def definition_recorded(self) -> bool:
        """Whether ingestion writes a definition of the property when it arrives, so a missing one shows that the
        project never received it."""
        return _has_property_definition(self.type, self.key) and (
            self.type == "person" or (self.event is not None and _records_event_properties(self.event))
        )


@frozen
class ExposureCohort:
    """A cohort that the exposure criteria filter on."""

    id: int
    name: str
    is_static: bool


@frozen
class ExposureEvents:
    """The events that the exposure criteria count."""

    # The event that the criteria name in place of the flag call events. None when the criteria count the flag call
    # events or an action.
    custom_event: str | None
    # The flag key that the exposure query requires in `$feature_flag`, because the flag call events are not specific
    # to one flag. None when the criteria count a custom event or an action, and when the experiment has no flag.
    required_flag_key: str | None
    # The event property that holds the variant: `$feature_flag_response` on the flag call events, `$feature/<flag key>`
    # on a custom event or the events of an action.
    variant_property: str
    flag_key_filters: tuple[FlagKeyFilter, ...]
    # The event, or the action's name, that has to follow a user's flag call before the user counts. None without an
    # activation, which the exposure query reads only next to the flag call events.
    activation: str | None = None
    property_filters: tuple[ExposurePropertyFilter, ...] = ()
    # The filters inside an action's steps are not read.
    cohort_ids: tuple[int, ...] = ()
    # Of `cohort_ids`, the cohorts whose members the criteria keep. A `not_in` filter leaves the members out.
    member_cohort_ids: frozenset[int] = frozenset()

    @property
    def required_properties(self) -> tuple[ExposurePropertyFilter, ...]:
        """The filters that no event passes without their property. `flag_key_filters` reads the flag key filter."""
        return tuple(f for f in self.property_filters if f.key != "$feature_flag" and f.fails_when_missing)


@frozen
class HealthContext:
    """Every input of the health checks, loaded once, so that each check is a pure function of it."""

    is_launched: bool
    is_running: bool
    has_ended: bool
    # None while the experiment has not ended.
    ended_at: datetime | None
    is_paused: bool
    archived: bool
    team_timezone: str
    flag: FlagState | None
    # Whether PostHog has recorded a call of the flag. None when the experiment has no flag, or when PostHog can't
    # record the calls of this organization's flags.
    flag_called: bool | None
    # Whether PostHog has recorded a call of the flag between launch and the end, or until now while the experiment
    # runs. A flag that served an earlier experiment can carry only calls from before launch, so `flag_called` doesn't
    # answer this. None before launch, when the experiment has no flag, when the flag's latest call came after the
    # end, or when PostHog can't record the calls of this organization's flags.
    flag_called_during_run: bool | None
    # Whether the flag's latest recorded call came after the end. False only when no call is recorded in the
    # ENDED_FLAG_QUIET_PERIOD after the end, also for a flag without a recorded call. None before the end, when the
    # experiment has no flag, before that period is over, or when PostHog can't record the calls of this
    # organization's flags.
    flag_called_after_end: bool | None
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
    # ingestion never writes an event definition for is absent, because its absence proves nothing. So is every name
    # without a definition when no event of the experiment shows that ingestion records the project.
    events_received: Mapping[str, bool]
    # Whether the project has received each property that `exposure_events.property_filters` name, by type and key. A
    # property that the definitions can't answer for is absent, under the same rules as `events_received`.
    exposure_properties_received: Mapping[tuple[ExposurePropertyType, str], bool]
    # The cohorts of `exposure_events.cohort_ids` that exist. The exposure query fails on a deleted or missing cohort.
    exposure_cohorts: tuple[ExposureCohort, ...]
    exposures: ExposureTotals | None
    # None when not loaded. The health endpoint loads it. The exposure answer loads it only when the sample ratio test
    # fails, because the load can query the exposures and `srm` is the only exposure check that reads it.
    flag_history: FlagHistory | FlagHistoryNotChecked | None
    # None when not loaded or unknown. Only the health endpoints load it, because it queries the events.
    condition_set_traffic: ConditionSetTraffic | None
    # None when not loaded or unknown. Only the health endpoints load it, and only for a paused experiment.
    pause_history: PauseHistory | None
    # None when not loaded, unknown, or the experiment calculates no primary metric. Only the health endpoints load it,
    # and only for a launched experiment.
    primary_metric: PrimaryMetric | None
    # The variants that the analysis leaves out of the results.
    excluded_variant_keys: frozenset[str]
    # None when not loaded or unknown. Only the health endpoints load it, as the reader.
    metric_compiles: MetricCompiles | None
    # None when not loaded or unknown. Only the health endpoints load it, and only for a launched experiment that
    # isn't archived.
    latest_calculation: LatestCalculation | None
    # None when not loaded or unknown. Only the health endpoints load it, and only when no metric of the latest
    # calculation completed and a failed query read the events.
    exposure_filters_without_column: tuple[ExposureFilterWithoutColumn, ...] | None


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


def _member_cohort_ids(condition: Mapping[str, Any]) -> frozenset[int]:
    # The flag service reads a cohort filter without an operator as `in`, and a filter with an operator other than `in`
    # or `not_in` as no match. See `cohort_operations.rs` in rust/feature-flags.
    properties = condition.get("properties")
    return frozenset(
        int(prop["value"])
        for prop in (properties if isinstance(properties, list) else [])
        if isinstance(prop, dict)
        and prop.get("type") == "cohort"
        and prop.get("operator") in (None, PropertyOperator.IN_)
        and (isinstance(prop.get("value"), int) or (isinstance(prop.get("value"), str) and prop["value"].isdecimal()))
    )


def _reachable_condition(
    number: int, condition: Mapping[str, Any], variant_keys: set[str], flag_aggregation: int | None
) -> ReachableCondition:
    pinned = pinned_variant(condition, variant_keys)
    return ReachableCondition(
        number=number,
        pinned_variant=pinned,
        variant_property=None if pinned is None else _variant_property(condition, pinned, flag_aggregation),
        member_cohort_ids=_member_cohort_ids(condition),
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
        rollout_percentage=parse_percentage(group.get("rollout_percentage")),
        property_count=len(properties) if isinstance(properties, list) else None,
    )


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
    return None if _flag_calls_unrecorded(experiment) else False


def _flag_called_during_run(experiment: Experiment, flag_called: bool | None) -> bool | None:
    start_date = experiment.start_date
    if start_date is None or flag_called is None:
        return None
    if flag_called is False:
        return False
    last_called_at = experiment.feature_flag.last_called_at
    if last_called_at is not None and last_called_at >= start_date:
        # `last_called_at` holds only the latest call, so a call after the end hides whether any came during the run.
        end_date = experiment.end_date
        return True if end_date is None or last_called_at <= end_date else None
    return None if _flag_calls_unrecorded(experiment) else False


def _flag_called_after_end(experiment: Experiment) -> bool | None:
    end_date = experiment.end_date
    # django-stubs types the id as int, but an unsaved instance can carry None.
    feature_flag_id: int | None = experiment.feature_flag_id
    if not experiment.is_stopped or end_date is None or feature_flag_id is None:
        return None
    last_called_at = experiment.feature_flag.last_called_at
    if last_called_at is not None and last_called_at > end_date:
        return True
    if timezone.now() - end_date < ENDED_FLAG_QUIET_PERIOD + LAST_CALLED_AT_LAG_DURATION:
        return None
    return None if _flag_calls_unrecorded(experiment) else False


def _flag_calls_unrecorded(experiment: Experiment) -> bool:
    # The task that sets `last_called_at` reads `$feature_flag_called` from the events table, unless it is set to
    # read flag_evaluations. On FLAG_EVALUATIONS_ONLY, ingestion writes no `$feature_flag_called` to the events table
    # for the teams in its allowlist, which this side can't read. Their flags keep no `last_called_at` however often
    # they are called.
    return settings.FEATURE_FLAG_LAST_CALLED_AT_SYNC_SOURCE != "flag_evaluations" and (
        get_organization_flag_evaluations_mode(experiment.team.organization_id)
        == FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY
    )


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
    # A deleted flag carries a tombstone in its key, and the exposure query reads the key without it.
    flag_key = experiment.feature_flag.key_without_tombstone() if experiment.feature_flag_id else None
    event, variant_property = get_exposure_event_and_property(
        flag_key or "", criteria, default_exposure_event=DEFAULT_EXPOSURE_EVENT
    )
    reads_flag_calls = event in (DEFAULT_EXPOSURE_EVENT, EXPERIMENT_EXPOSURE_EVENT)
    # The configs that the exposure query builds from, so the filters read here are the ones it applies.
    params = get_exposure_config_params_for_builder(criteria, experiment.team, experiment.start_date)
    config, activation = params.exposure_config, params.activation_config
    properties = config.properties if isinstance(config, ExperimentEventExposureConfig) else []
    filters = [(prop, source) for source in (config, activation) if source for prop in source.properties or []]
    cohorts = [prop for prop, _ in filters if isinstance(prop, CohortPropertyFilter)]
    return ExposureEvents(
        custom_event=event if event is not None and not reads_flag_calls else None,
        required_flag_key=flag_key if reads_flag_calls else None,
        variant_property=variant_property,
        flag_key_filters=tuple(
            # The exposure query reads a filter without an operator as `exact`, as `property_to_expr` does.
            FlagKeyFilter(operator=prop.operator or PropertyOperator.EXACT, values=_filter_values(prop.value))
            for prop in properties
            if isinstance(prop, EventPropertyFilter) and prop.key == "$feature_flag"
        ),
        activation=_activation_name(activation) if activation else None,
        property_filters=tuple(
            ExposurePropertyFilter.of(prop, source.event if isinstance(source, ExperimentEventExposureConfig) else None)
            for prop, source in filters
            if isinstance(prop, EventPropertyFilter | PersonPropertyFilter)
        ),
        cohort_ids=tuple(dict.fromkeys(prop.value for prop in cohorts)),
        # `property_to_expr` negates only a `not_in` cohort filter.
        member_cohort_ids=frozenset(prop.value for prop in cohorts if prop.operator != PropertyOperator.NOT_IN),
    )


def _activation_name(activation: ExperimentEventExposureConfig | ActionsNode) -> str:
    if isinstance(activation, ExperimentEventExposureConfig):
        return activation.event
    return activation.name or f"action {activation.id}"


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


def _records_event_properties(event: str) -> bool:
    # Of `$groupidentify`, ingestion writes only the group properties in `$group_set`.
    return _has_event_definition(event) and event != "$groupidentify"


def _events_received(
    experiment: Experiment, metric_events: tuple[MetricEvents, ...], exposure_events: ExposureEvents | None
) -> dict[str, bool]:
    names = {event for metric in metric_events for event in metric.events}
    if exposure_events is not None and exposure_events.custom_event is not None:
        names.add(exposure_events.custom_event)
    checked = {name for name in names if _has_event_definition(name)}
    project_id = experiment.team.project_id
    received = defined_event_names(project_id, checked, seen_only=True)
    checked -= _deleted_definition_names(
        project_id, checked - received, scope="EventDefinition", since=_deletions_since(experiment)
    )
    return {name: name in received for name in checked}


# Ingestion writes no property definition for these names: HogQL reads them from columns, or ingestion skips them. See
# `SKIP_PROPERTIES` in rust/property-defs-rs/src/types.rs, and `property_to_expr` in posthog/hogql/property.py.
_PROPERTIES_WITHOUT_DEFINITION: dict[ExposurePropertyType, frozenset[str]] = {
    "event": frozenset(
        {"$set", "$set_once", "$unset", "$groups", *(f"$group_{index}" for index in range(5)), "$elements_chain"}
    ),
    # Ingestion sets `$creator_event_uuid` when it creates the person, outside `$set`.
    "person": frozenset({"distinct_id", "$creator_event_uuid"}),
}


def _has_property_definition(property_type: ExposurePropertyType, key: str) -> bool:
    # HogQL computes a `$virt` property at query time, and ingestion skips a person property of a push subscription.
    # Ingestion replaces a NUL in a name, so the definition holds another name.
    return not (
        key in _PROPERTIES_WITHOUT_DEFINITION[property_type]
        or key.startswith("$virt")
        or (property_type == "person" and key.startswith("$device_push_subscription_"))
        or "\x00" in key
        or len(key.encode()) > _MAX_EVENT_DEFINITION_NAME_BYTES
    )


def _exposure_properties_received(
    experiment: Experiment, exposure_events: ExposureEvents | None
) -> dict[tuple[ExposurePropertyType, str], bool]:
    filters = exposure_events.required_properties if exposure_events else ()
    checked = {(f.type, f.key) for f in filters if f.definition_recorded}
    if not checked:
        return {}
    project_id = experiment.team.project_id
    received: set[tuple[ExposurePropertyType, str]] = set()
    for definition_type, name in _property_definitions(project_id, name__in={key for _, key in checked}).values_list(
        "type", "name"
    ):
        if definition_type == PropertyDefinition.Type.EVENT:
            received.add(("event", name))
        elif definition_type == PropertyDefinition.Type.PERSON:
            received.add(("person", name))
    missing = checked - received
    # Ingestion writes a deleted definition again only once the property drops out of its cache, which no time bounds,
    # so a deletion at any time leaves the answer open.
    deleted = _deleted_definition_names(project_id, {key for _, key in missing}, scope="PropertyDefinition", since=None)
    return {
        (property_type, key): (property_type, key) in received
        for property_type, key in checked
        if (property_type, key) in received or key not in deleted
    }


def _property_definitions(project_id: int, **filters: Any) -> QuerySet[PropertyDefinition]:
    return PropertyDefinition.objects.alias(effective_project_id=effective_project_id_expr()).filter(
        effective_project_id=project_id, **filters
    )


def _exposure_cohorts(experiment: Experiment, exposure_events: ExposureEvents | None) -> tuple[ExposureCohort, ...]:
    cohort_ids = exposure_events.cohort_ids if exposure_events else ()
    if not cohort_ids:
        return ()
    cohorts = {
        cohort_id: (name, is_static)
        for cohort_id, name, is_static in Cohort.objects.filter(
            team__project_id=experiment.team.project_id, pk__in=cohort_ids, deleted=False
        ).values_list("id", "name", "is_static")
    }
    return tuple(
        ExposureCohort(
            id=cohort_id, name=cohorts[cohort_id][0] or f"Cohort {cohort_id}", is_static=cohorts[cohort_id][1]
        )
        for cohort_id in cohort_ids
        if cohort_id in cohorts
    )


# Ingestion writes a deleted definition again when it next sees the event, which takes up to about an hour for an
# event that keeps arriving. A margin of a day also covers events that arrive a few times a day.
_DEFINITION_RECREATION_MARGIN = timedelta(days=1)


def _received(
    experiment: Experiment, metric_events: tuple[MetricEvents, ...], exposure_events: ExposureEvents | None
) -> tuple[dict[str, bool], dict[tuple[ExposurePropertyType, str], bool]]:
    events = _events_received(experiment, metric_events, exposure_events)
    properties = _exposure_properties_received(experiment, exposure_events)
    if False not in (*events.values(), *properties.values()) or _ingestion_records_project(
        experiment, metric_events, exposure_events
    ):
        return events, properties
    return {name: True for name, seen in events.items() if seen}, {
        key: True for key, seen in properties.items() if seen
    }


def _ingestion_records_project(
    experiment: Experiment, metric_events: tuple[MetricEvents, ...], exposure_events: ExposureEvents | None
) -> bool:
    """Whether ingestion writes the project's definitions now, which a missing definition needs to prove anything.
    Ingestion can be set to skip a team, and then writes no definition at all. It refreshes `last_seen_at` of an event
    that it sees about once an hour. So a flag call or an event of the experiment seen within the margin shows that it
    records the project."""
    names = {DEFAULT_EXPOSURE_EVENT, EXPERIMENT_EXPOSURE_EVENT, *(event for m in metric_events for event in m.events)}
    if exposure_events is not None and exposure_events.custom_event is not None:
        names.add(exposure_events.custom_event)
    return (
        EventDefinition.objects.alias(effective_project_id=effective_project_id_expr())
        .filter(
            effective_project_id=experiment.team.project_id,
            name__in=names,
            last_seen_at__gte=timezone.now() - _DEFINITION_RECREATION_MARGIN,
        )
        .exists()
    )


def _deletions_since(experiment: Experiment) -> datetime:
    # An earlier deletion matters only if the event stopped arriving: an event that arrived during the run, or
    # within the margin, has a new definition. So a deletion before then leaves the finding correct.
    recent = timezone.now() - _DEFINITION_RECREATION_MARGIN
    return min(experiment.start_date, recent) if experiment.start_date is not None else recent


def _deleted_definition_names(
    project_id: int,
    names: set[str],
    *,
    scope: Literal["EventDefinition", "PropertyDefinition"],
    since: datetime | None,
) -> set[str]:
    # Until ingestion writes a deleted definition again, the project can hold the event without a definition.
    if not names:
        return set()
    deletions = ActivityLog.objects.filter(
        team_id__in=Team.objects.filter(project_id=project_id).values("id"),
        scope=scope,
        activity="deleted",
    )
    if since is not None:
        deletions = deletions.filter(created_at__gte=since)
    return set(
        deletions.filter(
            # A containment test per name can use `idx_alog_detail_gin_path_ops`, which `detail__name__in` can't.
            reduce(or_, (Q(detail__contains={"name": name}) for name in names)),
            # These match the condition of `idx_alog_team_act_scope_usr`, so the lookup reads only the deletions. A
            # deletion made while impersonating a user is not read.
            was_impersonated=False,
            is_system=False,
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
    events_received, properties_received = _received(experiment, metric_events, exposure_events)
    return HealthContext(
        is_launched=experiment.is_launched,
        is_running=experiment.is_running,
        has_ended=experiment.is_stopped,
        ended_at=experiment.end_date if experiment.is_stopped else None,
        is_paused=experiment.is_paused,
        archived=experiment.archived,
        team_timezone=experiment.team.timezone,
        flag=_load_flag_state(experiment),
        flag_called=flag_called,
        flag_called_during_run=_flag_called_during_run(experiment, flag_called),
        flag_called_after_end=_flag_called_after_end(experiment),
        team_has_active_flag=(
            has_active_flags(experiment.team) if flag_called is False and not experiment.is_launched else None
        ),
        baseline_variant_key=_configured_baseline_variant_key(experiment.stats_config),
        primary_metric_count=len(experiment.metrics or []) + shared_metric_roles.count("primary"),
        secondary_metric_count=len(experiment.metrics_secondary or []) + shared_metric_roles.count("secondary"),
        hours_since_launch=experiment.hours_since_launch,
        metric_events=metric_events,
        exposure_events=exposure_events,
        events_received=events_received,
        exposure_properties_received=properties_received,
        exposure_cohorts=_exposure_cohorts(experiment, exposure_events),
        exposures=exposures,
        flag_history=flag_history,
        condition_set_traffic=None,
        pause_history=None,
        primary_metric=None,
        excluded_variant_keys=frozenset(experiment.excluded_variants or []),
        metric_compiles=None,
        latest_calculation=None,
        exposure_filters_without_column=None,
    )
