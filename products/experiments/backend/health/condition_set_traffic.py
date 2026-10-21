"""
Loads the `$feature_flag_called` events of a running experiment's flag in the last days, by the release condition
set that served each person. The forced-variant check grades its finding by the share of people that the pinned
sets served. These are the people the flag served a variant, not the exposures that the experiment's exposure
criteria count when they name another event, filters or an action, so the finding speaks of the users who got a
variant.

The flag-state check reads the people who got a variant from a call that the flag service did not evaluate. When
the flag has a 0% rollout, neither the flag service nor local evaluation serves a variant, so these people got it
from the customer's own assignment.

The flag service names the set in the reason "Matched condition set N", numbered from 1 in the stored order of the
conditions (`get_reason_description` in rust/feature-flags/src/api/types.rs). Only calls of the flag's current
version count, so the numbers match the conditions that the check reads. No call before the flag's last save can
carry that version, so the scan starts there at the earliest.

The scan runs without the reader, and every reader shares its cached answer. So it skips the filter for internal
and test users: that filter often reads person properties or cohorts, which is too slow for a request, and it can
read tables that a reader may not query.
"""

import json
import hashlib
from dataclasses import asdict
from datetime import datetime, timedelta
from time import monotonic, sleep
from uuid import UUID

from django.core.cache import cache
from django.utils import timezone

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.exceptions_capture import capture_exception
from posthog.utils import safe_cache_add

from products.experiments.backend.facade.contracts import ExperimentHealthReaderAccess
from products.experiments.backend.health.checks.conditions_changed import removed_overrides_to_grade
from products.experiments.backend.health.checks.flag_state import (
    OUTSIDE_ASSIGNMENT_GRACE,
    needs_outside_assignment_check,
    outside_assignment_unsettled,
)
from products.experiments.backend.health.checks.forced_variant import overrides_to_grade
from products.experiments.backend.health.context import ConditionSetTraffic, HealthContext
from products.experiments.backend.health.exposure_gate import UNKNOWN, cache_failed_scan
from products.experiments.backend.health.pinned_share import (
    TRAFFIC_WINDOW,
    PinnedConditions,
    PinnedShareUnknownReason,
    grade_pinned_share,
)
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    DEFAULT_EXPOSURE_EVENT,
    exposure_event_name_filter,
    get_entity_key,
    multivariate_flag_response_expr,
)
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.facade.flags import get_organization_flag_evaluations_mode

QUERY_TIMEOUT_SECONDS = 10
_ANSWER_CACHE_SECONDS = int(timedelta(days=1).total_seconds())
# Too few people to grade usually means that the window started recently, at launch or at a save of the flag.
# It fills up, so the answer is asked again sooner.
_TOO_FEW_PEOPLE_CACHE_SECONDS = int(timedelta(hours=1).total_seconds())
_MATCHED_REASON = "^Matched condition set ([0-9]+)$"
# The scan runs without the reader, so it can't apply a reader's property access rules. A reader denied one of
# these gets no share instead of counts derived from it.
_SCANNED_PROPERTIES = frozenset(
    {"$feature_flag", "$feature_flag_response", "$feature_flag_reason", "$feature_flag_version", "locally_evaluated"}
)
# The reason that posthog-node sends for a local evaluation. posthog-python sends `locally_evaluated` instead.
_LOCALLY_EVALUATED_REASON = "Evaluated locally"
# Part of the cache key. Raise it when the fields of `ConditionSetTraffic` change, because an answer cached with
# other fields can't be read back into it.
_ANSWER_SHAPE = 2
_MAX_CONDITION_SETS = 1000
_SCAN_LOCK_SECONDS = QUERY_TIMEOUT_SECONDS + 5
_WAIT_FOR_SCAN_SECONDS = QUERY_TIMEOUT_SECONDS + 1
_WAIT_STEP_SECONDS = 0.25


def load_condition_set_traffic(
    experiment: Experiment, ctx: HealthContext, *, reader_access: ExperimentHealthReaderAccess
) -> ConditionSetTraffic | None:
    """
    The traffic of the experiment's flag when the forced-variant check grades by it, or None. None also when
    unknown. Never raises: the health endpoint serves the other findings when this fails.
    """
    if (
        not reader_access.can_query_events
        or denied_scanned_properties(reader_access)
        or not needs_condition_set_traffic(ctx)
    ):
        return None
    try:
        return _load_condition_set_traffic(experiment, ctx)
    except Exception as error:
        capture_exception(error)
        return None


def needs_condition_set_traffic(ctx: HealthContext) -> bool:
    """Whether a check reads the flag's calls: the forced-variant or release-condition check to grade by the pinned
    share, or the flag-state check for a flag with a 0% rollout."""
    return grades_by_pinned_share(ctx) or needs_outside_assignment_check(ctx)


def grades_by_pinned_share(ctx: HealthContext) -> bool:
    """Whether a check grades its finding by the users that pinned conditions served: the forced-variant check for
    the overrides in place, and the release-condition check for an override removed after launch."""
    return ctx.is_launched and any(pins.weighted for pins in _pins_to_grade(ctx))


def has_too_few_people(ctx: HealthContext, traffic: ConditionSetTraffic) -> bool:
    """Whether a check leaves the share of `traffic` unknown only because too few people count."""
    return any(
        pins.weighted and grade_pinned_share(pins, traffic).unknown_reason == PinnedShareUnknownReason.TOO_FEW_PEOPLE
        for pins in _pins_to_grade(ctx)
    )


def _pins_to_grade(ctx: HealthContext) -> list[PinnedConditions]:
    return [pins for pins in (overrides_to_grade(ctx), removed_overrides_to_grade(ctx)) if pins is not None]


def denied_scanned_properties(reader_access: ExperimentHealthReaderAccess) -> frozenset[str]:
    """The properties that the scan reads and that the reader is denied. The scan does not run when there are any."""
    return reader_access.denied_event_properties & _SCANNED_PROPERTIES


def query_condition_set_traffic(
    experiment: Experiment, *, window_start: datetime, window_end: datetime
) -> ConditionSetTraffic:
    """The calls of the experiment's flag in `[window_start, window_end)`."""
    team = experiment.team
    flag = experiment.feature_flag
    query = parse_select(
        """
        SELECT condition_set, count(), sum(calls), sum(remotely_evaluated_calls), countIf(assigned_outside)
        FROM (
            SELECT
                {entity} AS entity,
                argMaxIf(
                    toInt(extract(properties.$feature_flag_reason, {matched_reason})),
                    timestamp,
                    toFloat(properties.$feature_flag_version) = {flag_version}
                        AND match(properties.$feature_flag_reason, {matched_reason})
                ) AS condition_set,
                count() AS calls,
                countIf(isNotNull(toFloat(properties.$feature_flag_version))) AS remotely_evaluated_calls,
                countIf(
                    isNull(toFloat(properties.$feature_flag_version))
                        AND ifNull(toString(properties.locally_evaluated), '') != 'true'
                        AND ifNull(properties.$feature_flag_reason, '') != {locally_evaluated_reason}
                        AND timestamp >= {assigned_outside_since}
                ) > 0 AS assigned_outside
            FROM events
            WHERE {flag_calls}
                AND timestamp >= {window_start} AND timestamp < {window_end}
                AND properties.$feature_flag = {flag_key}
                AND {returned_variant}
            GROUP BY entity
        )
        GROUP BY condition_set
        LIMIT {max_rows}
        """,
        placeholders={
            "flag_calls": exposure_event_name_filter(
                DEFAULT_EXPOSURE_EVENT, read_copies=_reads_exposure_copies(team.organization_id)
            ),
            "entity": ast.Field(chain=[get_entity_key(flag.aggregation_group_type_index)]),
            "matched_reason": ast.Constant(value=_MATCHED_REASON),
            "flag_version": ast.Constant(value=flag.version),
            "locally_evaluated_reason": ast.Constant(value=_LOCALLY_EVALUATED_REASON),
            "assigned_outside_since": ast.Constant(value=window_start + OUTSIDE_ASSIGNMENT_GRACE),
            "window_start": ast.Constant(value=window_start),
            "window_end": ast.Constant(value=window_end),
            "flag_key": ast.Constant(value=flag.key),
            # A call that returned no variant, such as "Out of rollout bound", put nobody in the experiment, so it
            # must not count toward the share of calls that name a set.
            "returned_variant": multivariate_flag_response_expr(),
            # One row per condition set, plus one for people without a matched set. HogQL adds LIMIT 100 otherwise.
            "max_rows": ast.Constant(value=_MAX_CONDITION_SETS + 1),
        },
    )
    with tags_context(
        product=Product.EXPERIMENTS, feature=Feature.HEALTH_CHECK, team_id=team.pk, org_id=team.organization_id
    ):
        # No user, as in the exposure gate, because every reader gets the cached answer.
        response = execute_hogql_query(
            query,
            team=team,
            # The join that applies person merges costs seconds on large teams and moves the counts by a tiny
            # fraction, because a merge moves few people.
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS
            ),
            # A profile that breaks on timeout returns partial counts, which would read as a smaller share.
            settings=HogQLGlobalSettings(max_execution_time=QUERY_TIMEOUT_SECONDS, timeout_overflow_mode="throw"),
        )
    people_by_set: dict[int, int] = {}
    calls = remotely_evaluated_calls = people_assigned_outside = 0
    for condition_set, people, set_calls, set_remotely_evaluated_calls, set_assigned_outside in response.results or []:
        if condition_set:
            people_by_set[int(condition_set)] = int(people)
        calls += int(set_calls)
        remotely_evaluated_calls += int(set_remotely_evaluated_calls)
        people_assigned_outside += int(set_assigned_outside)
    return ConditionSetTraffic(
        since=window_start,
        team_timezone=team.timezone,
        people_by_set=people_by_set,
        calls=calls,
        remotely_evaluated_calls=remotely_evaluated_calls,
        people_assigned_outside=people_assigned_outside,
    )


def _reads_exposure_copies(organization_id: UUID) -> bool:
    # On FLAG_EVALUATIONS_ONLY, events hold no `$feature_flag_called` for the teams in ingestion's allowlist. The
    # `$experiment_exposure` copy carries every property, the reason and the version included. A team can still
    # write both, and then each person counts once under their latest set.
    return get_organization_flag_evaluations_mode(organization_id) == FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY


def _load_condition_set_traffic(experiment: Experiment, ctx: HealthContext) -> ConditionSetTraffic | None:
    launched_at = experiment.start_date
    if launched_at is None or experiment.feature_flag.version is None:
        return None
    cache_key = _cache_key(experiment, launched_at)
    hit, traffic = _cached(cache_key)
    if hit:
        return traffic
    # Readers share one scan. A request that finds another scan in flight waits for its answer. The lock is
    # never released: every scan caches an answer, which readers check first, so the lock only has to expire.
    if not safe_cache_add(f"{cache_key}:scanning", True, _SCAN_LOCK_SECONDS):
        return _wait_for_scan(cache_key)
    # A scan can finish between the read above and the lock.
    hit, traffic = _cached(cache_key)
    if hit:
        return traffic
    return _scan(experiment, ctx, cache_key, launched_at)


def _scan(
    experiment: Experiment, ctx: HealthContext, cache_key: str, launched_at: datetime
) -> ConditionSetTraffic | None:
    flag = experiment.feature_flag
    now = timezone.now()
    window_start = max(launched_at, flag.updated_at or launched_at, now - TRAFFIC_WINDOW)
    try:
        traffic = query_condition_set_traffic(experiment, window_start=window_start, window_end=now)
    except Exception as error:
        cache_failed_scan(cache_key, error)
        return None
    asked_again_sooner = has_too_few_people(ctx, traffic) or outside_assignment_unsettled(ctx, traffic, now=now)
    cache.set(
        cache_key, asdict(traffic), _TOO_FEW_PEOPLE_CACHE_SECONDS if asked_again_sooner else _ANSWER_CACHE_SECONDS
    )
    return traffic


def _cached(cache_key: str) -> tuple[bool, ConditionSetTraffic | None]:
    """Whether the cache holds an answer, and the answer. A failed scan is cached as UNKNOWN, and answers None."""
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return True, ConditionSetTraffic(**cached)
    return cached == UNKNOWN, None


def _wait_for_scan(cache_key: str) -> ConditionSetTraffic | None:
    """The answer of the scan in flight, or None when it does not arrive within the query timeout."""
    deadline = monotonic() + _WAIT_FOR_SCAN_SECONDS
    while monotonic() < deadline:
        sleep(_WAIT_STEP_SECONDS)
        hit, traffic = _cached(cache_key)
        if hit:
            return traffic
    return None


def _cache_key(experiment: Experiment, launched_at: datetime) -> str:
    flag = experiment.feature_flag
    # Every input of the query except the end of the window, which moves with the clock.
    inputs = json.dumps(
        [
            _ANSWER_SHAPE,
            launched_at.isoformat(),
            flag.key,
            flag.version,
            flag.updated_at.isoformat() if flag.updated_at else None,
            flag.aggregation_group_type_index,
        ],
        sort_keys=True,
    )
    digest = hashlib.sha256(inputs.encode()).hexdigest()
    return f"experiment_condition_set_traffic:{experiment.team_id}:{experiment.id}:{digest}"
