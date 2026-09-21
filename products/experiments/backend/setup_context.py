"""Facts an agent needs before it configures a new experiment in a project.

Each provider reads one kind of fact and returns a frozen dataclass, so a backend caller can use
the providers without HTTP. `build_setup_context` runs them all and wraps each result in a
section with a status, so one slow or failing read never fails the whole call.

The providers return raw counts and shares only. They carry no thresholds and no
recommendations, because every consumer applies its own policy to the same facts.
"""

import json
import hashlib
import logging
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any, Final, Generic, TypeVar

from django.db import models
from django.db.models import BooleanField, Case, Count, F, Max, Prefetch, Q, QuerySet, Value, When
from django.db.models.fields.json import KT, KeyTransform
from django.utils import timezone

from posthog.schema import ActionsNode

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.exceptions import (
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.production_event_activation import MOBILE_SIDE_LIBS, SERVER_SIDE_LIBS
from posthog.models.team.team import Team
from posthog.utils import get_safe_cache, safe_cache_set

from products.experiments.backend.hogql_queries.exposure_query_logic import (
    DEFAULT_EXPOSURE_EVENT,
    EXPERIMENT_EXPOSURE_EVENT,
    apply_exposure_criteria_defaults,
    get_multiple_variant_handling_from_experiment,
    get_test_accounts_filter,
    is_default_exposure_config,
    multivariate_flag_response_expr,
    normalize_to_exposure_criteria,
    resolve_default_exposure_event,
    resolve_flag_call_source_event,
)
from products.experiments.backend.metric_utils import (
    collect_metric_events_and_action_ids,
    filter_metric_group_ids_by_event,
)
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
)
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.variant_distribution import is_evenly_distributed

logger = logging.getLogger(__name__)

T = TypeVar("T")

EXPERIMENT_SETUP_CONTEXT_FLAG: Final = "experiment-setup-context"


class SetupContextSectionStatus(models.TextChoices):
    OK = "ok"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"
    ERROR = "error"


class SdkLibCategory(models.TextChoices):
    WEB = "web"
    MOBILE = "mobile"
    SERVER = "server"
    OTHER = "other"


class PreviousExperimentState(models.TextChoices):
    """Every value `Experiment.status_label` can return, which is what this section reports."""

    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    EXPOSURE_FROZEN = "exposure_frozen"
    STOPPED = "stopped"


WEB_LIB: Final = "web"
# The borrowed sets are short because their own heuristic can afford a false negative. Here a lib
# that falls through to `other` weakens the server-and-web overlap signal, so the additions widen
# them. Classification feeds that signal only, because every per-SDK share comes from the rows.
SERVER_LIBS: Final[frozenset[str]] = frozenset(
    {
        *SERVER_SIDE_LIBS,
        "posthog-server",
        "posthog-rails",
        "posthog-aspnetcore",
        "posthog-edge",
        "posthog-convex",
    }
)
MOBILE_LIBS: Final[frozenset[str]] = frozenset({*MOBILE_SIDE_LIBS, "posthog-unity"})

# The frontend uses this value when the team has no default minimum detectable effect.
PRODUCT_DEFAULT_MINIMUM_DETECTABLE_EFFECT: Final = 30

SDK_PROFILE_WINDOW_DAYS: Final = 7
TARGET_WINDOW_DAYS: Final = 14
SDK_PROFILE_MAX_LIBS: Final = 10
TARGET_SURFACE_MAX_LIBS: Final = 5
DEFAULT_LIST_LIMIT: Final = 10
MAX_LIST_LIMIT: Final = 25

# Matching a saved metric against an event resolves its actions, so it can't run in the database.
# This caps how many of the team's saved metrics that scan reads, newest first.
SHARED_METRIC_EVENT_MATCH_SCAN_LIMIT: Final = 500

QUERY_TIMEOUT_SECONDS: Final = 20
SDK_PROFILE_CACHE_TTL: Final = 6 * 60 * 60
TARGET_CACHE_TTL: Final = 60 * 60

MEAN_COUNT_NOTE: Final = "events counted in the whole window, not only after the first target event"

_CLICKHOUSE_TOO_EXPENSIVE = (
    ClickHouseQueryTimeOut,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
)


def classify_lib(lib: str | None) -> SdkLibCategory:
    if lib == WEB_LIB:
        return SdkLibCategory.WEB
    if lib in SERVER_LIBS:
        return SdkLibCategory.SERVER
    if lib in MOBILE_LIBS:
        return SdkLibCategory.MOBILE
    return SdkLibCategory.OTHER


@frozen
class SetupContextInputs:
    target_event: str | None = None
    target_url_contains: str | None = None
    metric_event: str | None = None
    previous_experiments_limit: int = DEFAULT_LIST_LIMIT
    shared_metrics_limit: int = DEFAULT_LIST_LIMIT

    def __post_init__(self) -> None:
        if self.target_url_contains and self.target_event != "$pageview":
            raise ValueError("target_url_contains needs target_event to be $pageview")
        # The same event on both sides makes every person who reached the surface a converter, so
        # the baseline would always be 1.0 and tell the caller nothing.
        if self.metric_event and self.metric_event == self.target_event:
            raise ValueError("metric_event must differ from target_event")
        for limit in (self.previous_experiments_limit, self.shared_metrics_limit):
            if not 1 <= limit <= MAX_LIST_LIMIT:
                raise ValueError(f"list limits must be between 1 and {MAX_LIST_LIMIT}")


@frozen
class SetupContextSection(Generic[T]):
    status: SetupContextSectionStatus
    data: T | None = None


@frozen
class TeamDefaults:
    stats_method: str | None
    confidence_level: float | None
    minimum_detectable_effect: int | None
    product_default_minimum_detectable_effect: int
    only_count_matured_users: bool
    cuped_enabled: bool
    sequential_testing_enabled: bool
    flags_persistence_default: bool
    test_account_filter_count: int
    test_account_filters_default_checked: bool
    default_exposure_event: str


@frozen
class SdkLibProfile:
    lib: str | None
    category: SdkLibCategory
    calls: int
    distinct_ids: int
    device_id_share: float
    # None when no call from this SDK carried the property at all, so a 0 is never mistaken for a
    # fact. Derived from what the rows carry rather than from the SDK's name, because the name
    # lists are incomplete and each SDK decides for itself what it sends.
    locally_evaluated_share: float | None
    anonymous_share: float | None


@frozen
class SdkProfile:
    window_days: int
    source_event: str
    computed_at: datetime
    libs: list[SdkLibProfile]
    libs_truncated: bool
    flags_seen: int
    flags_evaluated_on_server_and_web: int
    evaluated_on_server_and_web: bool


@frozen
class LibReach:
    lib: str | None
    category: SdkLibCategory
    unique_persons: int


@frozen
class TargetSurface:
    window_days: int
    source_event: str
    target_url_contains: str | None
    computed_at: datetime
    test_accounts_filtered: bool
    unique_persons: int
    exposures_per_day_estimate: float
    libs: list[LibReach]
    anonymous_share: float | None
    device_id_share: float | None


@frozen
class FunnelBaselineStats:
    number_of_samples: int
    # The calculator's input contract requires `sum` on every baseline, so the funnel carries it too.
    sum: float
    step_counts: list[float]


@frozen
class MeanCountBaselineStats:
    number_of_samples: int
    sum: float
    sum_squares: float


@frozen
class CandidateMetric:
    window_days: int
    source_event: str
    target_event: str | None
    computed_at: datetime
    test_accounts_filtered: bool
    persons_reached: int | None = None
    persons_converted: int | None = None
    conversion_rate: float | None = None
    funnel_baseline_stats: FunnelBaselineStats | None = None
    mean_count_baseline_stats: MeanCountBaselineStats | None = None
    note: str | None = None
    event_volume: int | None = None
    unique_persons: int | None = None


@frozen
class ExperimentOutcome:
    # None when the stored result carries no sample counts at all, which must not read as a zero:
    # "the experiment analyzed nobody" is the signal this section exists to surface.
    analyzed_exposures: int | None
    any_variant_significant: bool
    result_completed_at: datetime | None


@frozen
class PreviousExperiment:
    id: int
    name: str
    state: PreviousExperimentState
    created_at: datetime
    start_date: datetime | None
    end_date: datetime | None
    conclusion: str | None
    variant_count: int
    # None on a boolean flag, which has no variants to split.
    split_even: bool | None
    rollout_percentage: float | None
    multiple_variant_handling: str
    multiple_variant_handling_set: bool
    ensure_experience_continuity: bool
    bucketing_identifier: str
    evaluation_runtime: str
    group_aggregation: bool
    custom_exposure_event: str | None
    custom_exposure_action_id: int | None
    filter_test_accounts: bool
    primary_metric_count: int
    secondary_metric_count: int
    shared_metric_count: int
    primary_metric_types: list[str]
    minimum_detectable_effect: float | None
    stats_method: str
    has_holdout: bool
    outcome: ExperimentOutcome | None


@frozen
class PreviousExperimentsSummary:
    total: int
    launched: int
    launched_without_results: int
    launched_with_unknown_analyzed_exposures: int
    launched_with_zero_analyzed_exposures: int
    launched_with_under_100_analyzed_exposures: int
    using_device_id_bucketing: int
    using_persistence: int
    using_custom_exposure: int
    using_uneven_split: int


@frozen
class PreviousExperiments:
    experiments: list[PreviousExperiment]
    summary: PreviousExperimentsSummary


@frozen
class SharedMetricUsage:
    id: int
    name: str
    metric_type: str | None
    events: list[str]
    action_ids: list[int]
    used_as_primary: int
    used_as_secondary: int
    last_used_at: datetime | None
    matches_metric_event: bool | None


@frozen
class SharedMetrics:
    metric_event: str | None
    metric_event_match_truncated: bool
    metrics: list[SharedMetricUsage]


@frozen
class ExperimentSetupContext:
    team_defaults: SetupContextSection[TeamDefaults]
    sdk_profile: SetupContextSection[SdkProfile]
    target_surface: SetupContextSection[TargetSurface]
    candidate_metric: SetupContextSection[CandidateMetric]
    previous_experiments: SetupContextSection[PreviousExperiments]
    shared_metrics: SetupContextSection[SharedMetrics]


def build_setup_context(
    *,
    team: Team,
    inputs: SetupContextInputs,
    experiments: QuerySet[Experiment],
    saved_metrics: QuerySet[ExperimentSavedMetric],
) -> ExperimentSetupContext:
    """Assemble every section of the setup context.

    `experiments` and `saved_metrics` must already be filtered to what the caller may see: the
    Postgres sections list individual objects, so the access check belongs to the caller.
    """
    # The sections run in sequence. Running the ClickHouse ones in a thread pool would triple the
    # Postgres connections a single request holds, because building the HogQL database reads (and
    # on a first call for a team writes) team extension rows outside ClickHouse.
    skipped: SetupContextSection[Any] = SetupContextSection(status=SetupContextSectionStatus.SKIPPED)
    return ExperimentSetupContext(
        team_defaults=_run_section("team_defaults", team, lambda: get_team_defaults(team)),
        sdk_profile=_run_section("sdk_profile", team, lambda: get_sdk_profile(team)),
        target_surface=(
            _run_section("target_surface", team, lambda: get_target_surface(team, inputs))
            if inputs.target_event
            else skipped
        ),
        candidate_metric=(
            _run_section("candidate_metric", team, lambda: get_candidate_metric(team, inputs))
            if inputs.metric_event
            else skipped
        ),
        previous_experiments=_run_section(
            "previous_experiments",
            team,
            lambda: get_previous_experiments(experiments, limit=inputs.previous_experiments_limit),
        ),
        shared_metrics=_run_section(
            "shared_metrics",
            team,
            lambda: get_shared_metrics(
                team,
                saved_metrics,
                experiments=experiments,
                limit=inputs.shared_metrics_limit,
                metric_event=inputs.metric_event,
            ),
        ),
    )


def _run_section(name: str, team: Team, provider: Callable[[], T]) -> SetupContextSection[T]:
    try:
        return SetupContextSection(status=SetupContextSectionStatus.OK, data=provider())
    except _CLICKHOUSE_TOO_EXPENSIVE:
        logger.warning("experiment_setup_context_section_timed_out", extra={"section": name, "team_id": team.pk})
        return SetupContextSection(status=SetupContextSectionStatus.TIMED_OUT)
    except Exception:
        logger.exception("experiment_setup_context_section_failed", extra={"section": name, "team_id": team.pk})
        return SetupContextSection(status=SetupContextSectionStatus.ERROR)


def get_team_defaults(team: Team) -> TeamDefaults:
    config = get_or_create_team_extension(team, TeamExperimentsConfig)
    confidence_level = config.default_experiment_confidence_level
    test_account_filters = team.test_account_filters if isinstance(team.test_account_filters, list) else []
    return TeamDefaults(
        stats_method=config.default_experiment_stats_method,
        confidence_level=float(confidence_level) if confidence_level is not None else None,
        minimum_detectable_effect=config.default_minimum_detectable_effect,
        product_default_minimum_detectable_effect=PRODUCT_DEFAULT_MINIMUM_DETECTABLE_EFFECT,
        only_count_matured_users=config.default_only_count_matured_users,
        cuped_enabled=config.default_cuped_enabled,
        sequential_testing_enabled=config.default_sequential_testing_enabled,
        flags_persistence_default=bool(team.flags_persistence_default),
        test_account_filter_count=len(test_account_filters),
        test_account_filters_default_checked=bool(team.test_account_filters_default_checked),
        default_exposure_event=resolve_default_exposure_event(team, timezone.now()),
    )


# ClickHouse providers


def _cache_key(team: Team, section: str, inputs: dict[str, Any]) -> str:
    # Bump the version whenever a cached dataclass changes shape: entries are pickled, so a deploy
    # would otherwise restore instances that miss the new fields.
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    return f"experiment_setup_context_v1_{team.pk}_{section}_{digest}"


def _cached(key: str, ttl: int, compute: Callable[[], T]) -> T:
    cached = get_safe_cache(key)
    if cached is not None:
        return cached
    value = compute()
    safe_cache_set(key, value, timeout=ttl)
    return value


def _run_query(team: Team, query_type: str, query: str, placeholders: dict[str, ast.Expr]) -> list[Any]:
    with tags_context(product=Product.EXPERIMENTS, feature=Feature.QUERY, team_id=team.pk, org_id=team.organization_id):
        response = execute_hogql_query(
            parse_select(query, placeholders=placeholders),
            team=team,
            query_type=query_type,
            settings=HogQLGlobalSettings(max_execution_time=QUERY_TIMEOUT_SECONDS),
        )
    return response.results or []


def _share(part: int, whole: int) -> float | None:
    return part / whole if whole else None


@frozen
class TimeWindow:
    start: datetime
    end: datetime

    @classmethod
    def ending_now(cls, days: int) -> "TimeWindow":
        end = timezone.now()
        return cls(start=end - timedelta(days=days), end=end)

    def conditions(self) -> list[ast.Expr]:
        return [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=self.start),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Lt, left=ast.Field(chain=["timestamp"]), right=ast.Constant(value=self.end)
            ),
        ]


def _event_is(event: str) -> ast.Expr:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq, left=ast.Field(chain=["event"]), right=ast.Constant(value=event)
    )


def _new_experiment_exposure_criteria() -> dict[str, Any]:
    """The exposure criteria a new experiment gets when the caller sets none."""
    return apply_exposure_criteria_defaults(None)


def _test_account_conditions(team: Team) -> list[ast.Expr]:
    # Filtered exactly as the experiment built from this baseline will filter, so the estimate is
    # measured over the population that experiment analyzes.
    return get_test_accounts_filter(team, _new_experiment_exposure_criteria())


def _and(exprs: Sequence[ast.Expr]) -> ast.Expr:
    return ast.And(exprs=list(exprs)) if len(exprs) > 1 else exprs[0]


def _flag_call_conditions(events: Sequence[str], window: TimeWindow) -> list[ast.Expr]:
    """Rows that count as a multivariate flag call, whichever of the two events carries them."""
    return [
        ast.CompareOperation(
            op=ast.CompareOperationOp.In, left=ast.Field(chain=["event"]), right=ast.Constant(value=list(events))
        ),
        *window.conditions(),
        multivariate_flag_response_expr(),
    ]


def get_sdk_profile(team: Team) -> SdkProfile:
    return _cached(
        _cache_key(team, "sdk_profile", {}),
        SDK_PROFILE_CACHE_TTL,
        lambda: _compute_sdk_profile(team),
    )


def _compute_sdk_profile(team: Team) -> SdkProfile:
    window = TimeWindow.ending_now(SDK_PROFILE_WINDOW_DAYS)
    both_events = [EXPERIMENT_EXPOSURE_EVENT, DEFAULT_EXPOSURE_EVENT]

    # Grouping by event as well as by flag answers which of the two events this team's flag calls
    # arrive on, so the per-lib pass below reads one event instead of both and no separate probe
    # query is needed.
    flag_rows = _run_query(
        team,
        "ExperimentSetupContextSdkFlagOverlap",
        """
        SELECT event, uniq(flag), countIf(on_server AND on_web)
        FROM (
            SELECT
                event,
                properties.$feature_flag AS flag,
                countIf(properties.$lib IN {server_libs}) > 0 AS on_server,
                countIf(properties.$lib = {web_lib}) > 0 AS on_web
            FROM events
            WHERE {where}
            GROUP BY event, flag
        )
        GROUP BY event
        """,
        {
            "where": _and(_flag_call_conditions(both_events, window)),
            "server_libs": ast.Constant(value=sorted(SERVER_LIBS)),
            "web_lib": ast.Constant(value=WEB_LIB),
        },
    )
    source_event = resolve_flag_call_source_event({row[0] for row in flag_rows})
    flags_seen, server_and_web = next(((row[1], row[2]) for row in flag_rows if row[0] == source_event), (0, 0))

    # Every property below resolves to a materialized column or to a property-group map column, so
    # the scan never touches the `properties` blob. Adding one that resolves to neither puts the
    # whole blob back and costs two orders of magnitude more read, which is why this reports
    # neither $used_bootstrap_value nor $feature_flag_error.
    # posthog/clickhouse/property_groups.py decides what a property resolves to.
    lib_rows = _run_query(
        team,
        "ExperimentSetupContextSdkProfile",
        """
        SELECT
            properties.$lib AS lib,
            count() AS calls,
            uniq(distinct_id) AS distinct_ids,
            countIf(coalesce(toString(properties.locally_evaluated), '') != '') AS locally_evaluated_reported,
            countIf(toString(properties.locally_evaluated) = 'true') AS locally_evaluated_calls,
            countIf(coalesce(toString(properties.$device_id), '') != '') AS device_id_calls,
            uniqIf(distinct_id, toString(properties.$is_identified) = 'false') AS anonymous_distinct_ids,
            uniqIf(distinct_id, toString(properties.$is_identified) IN ('true', 'false')) AS identity_known_ids
        FROM events
        WHERE {where}
        GROUP BY lib
        ORDER BY calls DESC, lib ASC
        LIMIT {limit}
        """,
        {
            "where": _and([_event_is(source_event), *window.conditions(), multivariate_flag_response_expr()]),
            "limit": ast.Constant(value=SDK_PROFILE_MAX_LIBS + 1),
        },
    )

    libs = [
        SdkLibProfile(
            lib=lib,
            category=classify_lib(lib),
            calls=int(calls),
            distinct_ids=int(distinct_ids),
            device_id_share=device_id_calls / calls,
            locally_evaluated_share=_share(locally_evaluated_calls, locally_evaluated_reported),
            anonymous_share=_share(anonymous_distinct_ids, identity_known_ids),
        )
        for (
            lib,
            calls,
            distinct_ids,
            locally_evaluated_reported,
            locally_evaluated_calls,
            device_id_calls,
            anonymous_distinct_ids,
            identity_known_ids,
        ) in lib_rows[:SDK_PROFILE_MAX_LIBS]
    ]

    return SdkProfile(
        window_days=SDK_PROFILE_WINDOW_DAYS,
        source_event=source_event,
        computed_at=window.end,
        libs=libs,
        libs_truncated=len(lib_rows) > SDK_PROFILE_MAX_LIBS,
        flags_seen=int(flags_seen),
        flags_evaluated_on_server_and_web=int(server_and_web),
        evaluated_on_server_and_web=int(server_and_web) > 0,
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _target_conditions(inputs: SetupContextInputs) -> list[ast.Expr]:
    assert inputs.target_event is not None
    conditions = [_event_is(inputs.target_event)]
    if inputs.target_url_contains:
        conditions.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.ILike,
                left=ast.Field(chain=["properties", "$current_url"]),
                right=ast.Constant(value=f"%{_escape_like(inputs.target_url_contains)}%"),
            )
        )
    return conditions


def _target_cache_inputs(team: Team, inputs: SetupContextInputs) -> dict[str, Any]:
    # The test-account filters belong in the key: editing them changes every count below, and an
    # hour of a stale answer would hide the edit.
    return {
        "target_event": inputs.target_event,
        "target_url_contains": inputs.target_url_contains,
        "metric_event": inputs.metric_event,
        "filter_test_accounts": bool(_new_experiment_exposure_criteria().get("filterTestAccounts")),
        "test_account_filters": team.test_account_filters if isinstance(team.test_account_filters, list) else [],
    }


def get_target_surface(team: Team, inputs: SetupContextInputs) -> TargetSurface:
    if not inputs.target_event:
        raise ValueError("target_event is required for the target surface")
    return _cached(
        _cache_key(team, "target_surface", _target_cache_inputs(team, inputs)),
        TARGET_CACHE_TTL,
        lambda: _compute_target_surface(team, inputs),
    )


def _compute_target_surface(team: Team, inputs: SetupContextInputs) -> TargetSurface:
    assert inputs.target_event is not None
    window = TimeWindow.ending_now(TARGET_WINDOW_DAYS)
    test_account_conditions = _test_account_conditions(team)
    conditions = [*_target_conditions(inputs), *window.conditions(), *test_account_conditions]

    # One pass: the totals merge the per-lib uniq states, so a person who uses two SDKs is counted
    # once overall while still appearing under each of them.
    rows = _run_query(
        team,
        "ExperimentSetupContextTargetSurface",
        """
        SELECT
            uniqMerge(persons),
            sum(web_events),
            sum(web_device_id_events),
            uniqMerge(web_anonymous_ids),
            uniqMerge(web_identity_known_ids),
            -- Negating the person count makes the ascending tuple sort read "most persons first,
            -- then lib name", and the slice bounds what a project with many $lib values returns.
            arraySlice(arraySort(groupArray((-_toInt64(lib_persons), lib))), 1, {limit})
        FROM (
            SELECT
                properties.$lib AS lib,
                uniqState(person_id) AS persons,
                uniq(person_id) AS lib_persons,
                countIf(properties.$lib = {web_lib}) AS web_events,
                countIf(
                    properties.$lib = {web_lib} AND coalesce(toString(properties.$device_id), '') != ''
                ) AS web_device_id_events,
                uniqStateIf(
                    distinct_id, properties.$lib = {web_lib} AND toString(properties.$is_identified) = 'false'
                ) AS web_anonymous_ids,
                uniqStateIf(
                    distinct_id,
                    properties.$lib = {web_lib} AND toString(properties.$is_identified) IN ('true', 'false')
                ) AS web_identity_known_ids
            FROM events
            WHERE {where}
            GROUP BY lib
        )
        """,
        {
            "where": _and(conditions),
            "web_lib": ast.Constant(value=WEB_LIB),
            "limit": ast.Constant(value=TARGET_SURFACE_MAX_LIBS),
        },
    )
    unique_persons, web_events, web_device_id_events, web_anonymous_ids, web_identity_known_ids, top_libs = (
        rows[0] if rows else (0, 0, 0, 0, 0, [])
    )

    return TargetSurface(
        window_days=TARGET_WINDOW_DAYS,
        source_event=inputs.target_event,
        target_url_contains=inputs.target_url_contains,
        computed_at=window.end,
        test_accounts_filtered=bool(test_account_conditions),
        unique_persons=int(unique_persons),
        exposures_per_day_estimate=int(unique_persons) / TARGET_WINDOW_DAYS,
        libs=[
            LibReach(lib=lib, category=classify_lib(lib), unique_persons=-int(negated_persons))
            for negated_persons, lib in top_libs or []
        ],
        anonymous_share=_share(web_anonymous_ids, web_identity_known_ids),
        device_id_share=_share(web_device_id_events, web_events),
    )


def get_candidate_metric(team: Team, inputs: SetupContextInputs) -> CandidateMetric:
    if not inputs.metric_event:
        raise ValueError("metric_event is required for the candidate metric")
    return _cached(
        _cache_key(team, "candidate_metric", _target_cache_inputs(team, inputs)),
        TARGET_CACHE_TTL,
        lambda: _compute_candidate_metric(team, inputs),
    )


def _compute_candidate_metric(team: Team, inputs: SetupContextInputs) -> CandidateMetric:
    assert inputs.metric_event is not None
    window = TimeWindow.ending_now(TARGET_WINDOW_DAYS)
    test_account_conditions = _test_account_conditions(team)
    scope = [*window.conditions(), *test_account_conditions]

    if not inputs.target_event:
        rows = _run_query(
            team,
            "ExperimentSetupContextCandidateMetricVolume",
            "SELECT count(), uniq(person_id) FROM events WHERE {where}",
            {"where": _and([_event_is(inputs.metric_event), *scope])},
        )
        event_volume, unique_persons = rows[0] if rows else (0, 0)
        return CandidateMetric(
            window_days=TARGET_WINDOW_DAYS,
            source_event=inputs.metric_event,
            target_event=None,
            computed_at=window.end,
            test_accounts_filtered=bool(test_account_conditions),
            event_volume=int(event_volume),
            unique_persons=int(unique_persons),
        )

    # A person converts when their last metric event is at or after their first target event,
    # which holds exactly when any metric event is. Reading the event pair only, before grouping,
    # keeps the per-person scan narrow.
    rows = _run_query(
        team,
        "ExperimentSetupContextCandidateMetric",
        """
        SELECT
            count(),
            countIf(converted),
            sum(metric_count),
            sum(metric_count * metric_count)
        FROM (
            SELECT
                person_id,
                countIf({is_metric}) AS metric_count,
                metric_count > 0 AND maxIf(timestamp, {is_metric}) >= minIf(timestamp, {is_target}) AS converted
            FROM events
            WHERE {where}
            GROUP BY person_id
            HAVING countIf({is_target}) > 0
        )
        """,
        {
            "where": _and(
                [
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.In,
                        left=ast.Field(chain=["event"]),
                        right=ast.Constant(value=[inputs.target_event, inputs.metric_event]),
                    ),
                    *scope,
                ]
            ),
            "is_target": _and(_target_conditions(inputs)),
            "is_metric": _event_is(inputs.metric_event),
        },
    )
    reached, converted, metric_sum, metric_sum_squares = rows[0] if rows else (0, 0, 0, 0)
    reached, converted = int(reached), int(converted)

    return CandidateMetric(
        window_days=TARGET_WINDOW_DAYS,
        source_event=inputs.metric_event,
        target_event=inputs.target_event,
        computed_at=window.end,
        test_accounts_filtered=bool(test_account_conditions),
        persons_reached=reached,
        persons_converted=converted,
        conversion_rate=_share(converted, reached),
        funnel_baseline_stats=FunnelBaselineStats(
            number_of_samples=reached, sum=float(converted), step_counts=[float(converted)]
        ),
        mean_count_baseline_stats=MeanCountBaselineStats(
            number_of_samples=reached, sum=float(metric_sum or 0), sum_squares=float(metric_sum_squares or 0)
        ),
        note=MEAN_COUNT_NOTE,
    )


# Postgres providers


def _experiment_state(experiment: Experiment) -> PreviousExperimentState:
    # status_label is the single source for the API serializer and the dashboard widgets, so this
    # section names a state the same way the rest of the product does. It falls back to the dates
    # when the stored status is null, which older rows still are.
    return PreviousExperimentState(experiment.status_label)


def _saved_metric_links(experiment: Experiment) -> list[ExperimentToSavedMetric]:
    return list(experiment.experimenttosavedmetric_set.all())


def _link_type(link: ExperimentToSavedMetric) -> str:
    return (link.metadata or {}).get("type", "primary")


def _first_primary_metric_uuid(experiment: Experiment) -> str | None:
    """The uuid the experiment's results page shows first among its primary metrics."""
    inline_uuids = [metric.get("uuid") for metric in experiment.metrics or [] if isinstance(metric, dict)]
    saved_uuids = [
        link.saved_metric.query.get("uuid")
        for link in _saved_metric_links(experiment)
        if _link_type(link) == "primary" and isinstance(link.saved_metric.query, dict)
    ]
    candidates = [uuid for uuid in [*inline_uuids, *saved_uuids] if uuid]
    for uuid in experiment.primary_metrics_ordered_uuids or []:
        if uuid in candidates:
            return uuid
    return candidates[0] if candidates else None


@frozen
class CustomExposure:
    event: str | None = None
    action_id: int | None = None


def _custom_exposure(experiment: Experiment, exposure_criteria: dict[str, Any]) -> CustomExposure:
    """What the experiment counts as an exposure, when it is not the default event.

    Resolved through the same helpers the exposure queries use, so this reports what the
    experiment actually analyzes rather than a second reading of the stored JSON.
    """
    try:
        criteria = normalize_to_exposure_criteria(exposure_criteria)
    except Exception:
        # Criteria the exposure queries would reject too. Report no custom exposure rather than
        # guessing at a shape the analysis itself cannot read.
        logger.warning(
            "experiment_setup_context_exposure_criteria_invalid",
            extra={"experiment_id": experiment.pk},
            exc_info=True,
        )
        return CustomExposure()
    config = criteria.exposure_config if criteria else None
    if is_default_exposure_config(config):
        return CustomExposure()
    if isinstance(config, ActionsNode):
        return CustomExposure(action_id=int(config.id))
    return CustomExposure(event=str(config.event) if config and config.event else None)


def _filters_test_accounts(exposure_criteria: dict[str, Any]) -> bool:
    """Whether the experiment's own results leave test accounts out.

    Criteria that do not say resolve to on, which is what every metric and exposure query does
    (`get_exposure_config_params_for_builder`). Creation stores the field, but a large share of
    existing experiments leave it out, and reading their stored value raw would report `false` for
    results that do leave test accounts out.
    """
    configured = exposure_criteria.get("filterTestAccounts")
    return True if configured is None else bool(configured)


def _group_rollout(group: dict[str, Any]) -> float:
    rollout = group.get("rollout_percentage")
    return 100.0 if rollout is None else float(rollout)


def _multiple_variant_handling(exposure_criteria: dict[str, Any]) -> str:
    try:
        return get_multiple_variant_handling_from_experiment(exposure_criteria).value
    except Exception:
        # Stored criteria that no longer validate still analyze with the default handling.
        return get_multiple_variant_handling_from_experiment(None).value


def _outcomes(first_primary_uuids: dict[int, str]) -> dict[int, ExperimentOutcome]:
    """Latest completed stored result of each experiment's first primary metric, in one query."""
    if not first_primary_uuids:
        return {}
    rows = (
        ExperimentMetricResult.objects.filter(
            experiment_id__in=first_primary_uuids.keys(),
            metric_uuid__in=set(first_primary_uuids.values()),
            status=ExperimentMetricResult.Status.COMPLETED,
        )
        .order_by("experiment_id", "metric_uuid", F("completed_at").desc(nulls_last=True))
        .distinct("experiment_id", "metric_uuid")
        # Only the sample counts are read, so the stored query text in the result stays in Postgres.
        .values(
            "experiment_id",
            "metric_uuid",
            "completed_at",
            baseline_samples=KT("result__baseline__number_of_samples"),
            variant_results=KeyTransform("variant_results", "result"),
        )
    )
    outcomes: dict[int, ExperimentOutcome] = {}
    for row in rows:
        if first_primary_uuids.get(row["experiment_id"]) != row["metric_uuid"]:
            continue
        variants = [variant for variant in row["variant_results"] or [] if isinstance(variant, dict)]
        # Samples exclude users seen in several variants under the default handling, so this is
        # the analyzed population rather than every exposure. A result that stores no sample count
        # anywhere is unknown, not zero.
        stored_samples = [
            samples
            for samples in [row["baseline_samples"], *(variant.get("number_of_samples") for variant in variants)]
            if samples is not None
        ]
        outcomes[row["experiment_id"]] = ExperimentOutcome(
            analyzed_exposures=sum(int(float(samples)) for samples in stored_samples) if stored_samples else None,
            any_variant_significant=any(v.get("significant") is True for v in variants),
            result_completed_at=row["completed_at"],
        )
    return outcomes


def get_previous_experiments(experiments: QuerySet[Experiment], *, limit: int) -> PreviousExperiments:
    rows = list(
        experiments.exclude(deleted=True)
        .select_related("feature_flag")
        .prefetch_related(
            Prefetch(
                "experimenttosavedmetric_set",
                queryset=ExperimentToSavedMetric.objects.select_related("saved_metric").order_by("id"),
            )
        )
        .order_by("-created_at", "-id")[:limit]
    )

    first_primary_uuids = {
        experiment.id: uuid for experiment in rows if (uuid := _first_primary_metric_uuid(experiment)) is not None
    }
    outcomes = _outcomes(first_primary_uuids)

    previous: list[PreviousExperiment] = []
    for experiment in rows:
        flag = experiment.feature_flag
        flag_filters = flag.filters or {}
        variant_rollouts = [variant.get("rollout_percentage") or 0 for variant in flag.variants]
        groups = flag_filters.get("groups") or []
        exposure_criteria = experiment.exposure_criteria if isinstance(experiment.exposure_criteria, dict) else {}
        custom_exposure = _custom_exposure(experiment, exposure_criteria)
        links = _saved_metric_links(experiment)
        primary_saved = [link for link in links if _link_type(link) == "primary"]
        primary_metrics = [
            *(metric for metric in experiment.metrics or [] if isinstance(metric, dict)),
            *(link.saved_metric.query for link in primary_saved if isinstance(link.saved_metric.query, dict)),
        ]
        running_time_calculation = experiment.running_time_calculation or {}

        previous.append(
            PreviousExperiment(
                id=experiment.id,
                name=experiment.name,
                state=_experiment_state(experiment),
                created_at=experiment.created_at,
                start_date=experiment.start_date,
                end_date=experiment.end_date,
                conclusion=experiment.conclusion,
                variant_count=len(variant_rollouts),
                split_even=is_evenly_distributed(variant_rollouts) if variant_rollouts else None,
                # A release group without a rollout percentage serves everyone who matches it.
                rollout_percentage=(_group_rollout(groups[0]) if groups else None),
                multiple_variant_handling=_multiple_variant_handling(exposure_criteria),
                multiple_variant_handling_set=bool(exposure_criteria.get("multiple_variant_handling")),
                ensure_experience_continuity=bool(flag.ensure_experience_continuity),
                bucketing_identifier=flag.bucketing_identifier or "distinct_id",
                evaluation_runtime=flag.evaluation_runtime or "all",
                group_aggregation=flag_filters.get("aggregation_group_type_index") is not None,
                custom_exposure_event=custom_exposure.event,
                custom_exposure_action_id=custom_exposure.action_id,
                filter_test_accounts=_filters_test_accounts(exposure_criteria),
                primary_metric_count=len(primary_metrics),
                secondary_metric_count=len(experiment.metrics_secondary or []) + len(links) - len(primary_saved),
                shared_metric_count=len(links),
                primary_metric_types=[
                    str(metric.get("metric_type") or metric.get("kind") or "unknown") for metric in primary_metrics
                ],
                minimum_detectable_effect=running_time_calculation.get("minimum_detectable_effect"),
                stats_method=(experiment.stats_config or {}).get("method") or "bayesian",
                has_holdout=experiment.holdout_id is not None,
                outcome=outcomes.get(experiment.id),
            )
        )

    launched = [experiment for experiment in previous if experiment.start_date is not None]
    launched_outcomes = [experiment.outcome for experiment in launched if experiment.outcome is not None]
    analyzed = [outcome.analyzed_exposures for outcome in launched_outcomes if outcome.analyzed_exposures is not None]
    return PreviousExperiments(
        experiments=previous,
        summary=PreviousExperimentsSummary(
            total=len(previous),
            launched=len(launched),
            launched_without_results=len(launched) - len(launched_outcomes),
            launched_with_unknown_analyzed_exposures=len(launched_outcomes) - len(analyzed),
            launched_with_zero_analyzed_exposures=sum(1 for samples in analyzed if samples == 0),
            launched_with_under_100_analyzed_exposures=sum(1 for samples in analyzed if samples < 100),
            using_device_id_bucketing=sum(1 for e in previous if e.bucketing_identifier == "device_id"),
            using_persistence=sum(1 for e in previous if e.ensure_experience_continuity),
            using_custom_exposure=sum(
                1 for e in previous if e.custom_exposure_event or e.custom_exposure_action_id is not None
            ),
            using_uneven_split=sum(1 for e in previous if e.split_even is False),
        ),
    )


def get_shared_metrics(
    team: Team,
    saved_metrics: QuerySet[ExperimentSavedMetric],
    *,
    experiments: QuerySet[Experiment],
    limit: int,
    metric_event: str | None,
) -> SharedMetrics:
    """Rank the team's shared metrics by how often the caller's own experiments reuse them.

    `saved_metrics` and `experiments` must already be filtered to what the caller may see: reuse
    counts name experiments the same way the list does, so both sides respect access.
    """
    # A link counts as reuse only when it points at an experiment the caller can see and that is
    # not deleted. `deleted` is nullable, so `exclude(deleted=True)` keeps the nulls.
    live_link = Q(experimenttosavedmetric__experiment__in=experiments.exclude(deleted=True).values("pk"))
    secondary_link = Q(experimenttosavedmetric__metadata__type="secondary")

    queryset = saved_metrics
    matching_ids: set[int] = set()
    match_truncated = False
    if metric_event:
        # Matching resolves each metric's actions to their step events, so it can't run in the
        # database. Scan the newest metrics only, and say so when there were more.
        scanned = list(
            queryset.order_by("-created_at", "-id").values_list("pk", "query")[
                : SHARED_METRIC_EVENT_MATCH_SCAN_LIMIT + 1
            ]
        )
        match_truncated = len(scanned) > SHARED_METRIC_EVENT_MATCH_SCAN_LIMIT
        groups = [(pk, [query] if query else []) for pk, query in scanned[:SHARED_METRIC_EVENT_MATCH_SCAN_LIMIT]]
        matching_ids = set(filter_metric_group_ids_by_event(groups, metric_event, team))

    ranked = (
        queryset.annotate(
            reuse_count=Count("experimenttosavedmetric", filter=live_link),
            secondary_count=Count("experimenttosavedmetric", filter=live_link & secondary_link),
            last_used_at=Max("experimenttosavedmetric__created_at", filter=live_link),
            matches=Case(
                When(pk__in=matching_ids, then=Value(True)), default=Value(False), output_field=BooleanField()
            ),
        )
        .order_by(
            "-matches",
            "-reuse_count",
            F("last_used_at").desc(nulls_last=True),
            "-created_at",
            "-id",
        )
        .only("id", "name", "query")[:limit]
    )

    metrics: list[SharedMetricUsage] = []
    for saved_metric in ranked:
        query = saved_metric.query if isinstance(saved_metric.query, dict) else {}
        events, action_ids = collect_metric_events_and_action_ids([query])
        metrics.append(
            SharedMetricUsage(
                id=saved_metric.id,
                name=saved_metric.name,
                metric_type=query.get("metric_type"),
                events=sorted(events),
                action_ids=sorted(action_ids),
                used_as_primary=saved_metric.reuse_count - saved_metric.secondary_count,
                used_as_secondary=saved_metric.secondary_count,
                last_used_at=saved_metric.last_used_at,
                matches_metric_event=(saved_metric.id in matching_ids) if metric_event else None,
            )
        )
    return SharedMetrics(metric_event=metric_event, metric_event_match_truncated=match_truncated, metrics=metrics)
