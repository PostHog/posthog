"""
Loads the `$feature_flag_called` events of a running experiment's flag in the last days, by the release condition
set that served each person. The forced-variant check grades its finding by the share of people that the pinned
conditions served.

The flag service writes the set on the event as the reason "Matched condition set N", numbered from 1 in the
stored order of the conditions (`get_reason_description` in rust/feature-flags/src/api/types.rs). Only events of
the flag's current version count, so the numbers match the conditions that the check reads. A save of the flag
raises the version, so the scan starts at the last save: no earlier event can carry the current version.

An organization on FLAG_EVALUATIONS_ONLY writes no `$feature_flag_called` to events for the teams in the ingestion
allowlist. Ingestion copies each multivariate call as `$experiment_exposure` with every property, the reason and the
version included, so the scan reads the copy for such an organization too.

The scan does not apply the filter for internal and test users. That filter often reads person properties or
cohorts, which makes the scan too slow for a request, and it can read tables that each reader may or may not
query, so no cached answer for it is safe to share. Internal users change the share only where they are a large
part of the flag's traffic.

The answer is cached per flag version and shared by every reader, so the scan runs about once a day, not on every
load of the experiment page. A failed scan is cached as unknown too.
"""

import json
import hashlib
from datetime import datetime, timedelta
from uuid import UUID

from django.core.cache import cache
from django.utils import timezone

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.errors import CH_TRANSIENT_ERRORS
from posthog.exceptions_capture import capture_exception

from products.experiments.backend.facade.contracts import ExperimentHealthReaderAccess
from products.experiments.backend.health.checks.forced_variant import (
    MIN_MATCHED_PEOPLE,
    TRAFFIC_WINDOW,
    needs_condition_set_traffic,
)
from products.experiments.backend.health.context import ConditionSetTraffic, HealthContext
from products.experiments.backend.health.exposure_gate import TOO_EXPENSIVE_ERRORS
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    DEFAULT_EXPOSURE_EVENT,
    EXPERIMENT_EXPOSURE_EVENT,
    get_entity_key,
)
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.facade.flags import get_organization_flag_evaluations_mode

QUERY_TIMEOUT_SECONDS = 10
_ANSWER_CACHE_SECONDS = int(timedelta(days=1).total_seconds())
# Too few people to grade usually means that the window started recently, at launch or at a save of the flag.
# It fills up, so the answer is asked again sooner.
_TOO_FEW_PEOPLE_CACHE_SECONDS = int(timedelta(hours=1).total_seconds())
# A scan too large for a request stays too large, so it waits a day. Another error can be brief, so it waits an hour.
_TOO_EXPENSIVE_CACHE_SECONDS = int(timedelta(days=1).total_seconds())
_FAILED_CACHE_SECONDS = int(timedelta(hours=1).total_seconds())
_UNKNOWN = "unknown"
_MATCHED_REASON = "^Matched condition set ([0-9]+)$"
# The scan runs without the reader, so it can't apply a reader's property access rules. A reader denied one of
# these gets no share instead of counts derived from it.
_SCANNED_PROPERTIES = frozenset({"$feature_flag", "$feature_flag_reason", "$feature_flag_version"})
_MAX_CONDITION_SETS = 1000


def load_condition_set_traffic(
    experiment: Experiment, ctx: HealthContext, *, reader_access: ExperimentHealthReaderAccess
) -> ConditionSetTraffic | None:
    """
    The traffic of the experiment's flag when the forced-variant check grades by it, or None. None also when
    unknown. Never raises: the health endpoint serves the other findings when this fails.
    """
    if (
        not reader_access.can_query_events
        or reader_access.denied_event_properties & _SCANNED_PROPERTIES
        or not needs_condition_set_traffic(ctx)
    ):
        return None
    try:
        return _load_condition_set_traffic(experiment)
    except Exception as error:
        capture_exception(error)
        return None


def query_condition_set_traffic(
    experiment: Experiment, *, window_start: datetime, window_end: datetime
) -> ConditionSetTraffic:
    """The calls of the experiment's flag in `[window_start, window_end)`."""
    team = experiment.team
    flag = experiment.feature_flag
    query = parse_select(
        """
        SELECT condition_set, count(), sum(calls), sum(remotely_evaluated_calls)
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
                countIf(isNotNull(toFloat(properties.$feature_flag_version))) AS remotely_evaluated_calls
            FROM events
            WHERE event IN {flag_call_events}
                AND timestamp >= {window_start} AND timestamp < {window_end}
                AND properties.$feature_flag = {flag_key}
            GROUP BY entity
        )
        GROUP BY condition_set
        LIMIT {max_rows}
        """,
        placeholders={
            "flag_call_events": ast.Constant(value=_flag_call_events(team.organization_id)),
            "entity": ast.Field(chain=[get_entity_key(flag.aggregation_group_type_index)]),
            "matched_reason": ast.Constant(value=_MATCHED_REASON),
            "flag_version": ast.Constant(value=flag.version),
            "window_start": ast.Constant(value=window_start),
            "window_end": ast.Constant(value=window_end),
            "flag_key": ast.Constant(value=flag.key),
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
    rows = response.results or []
    return ConditionSetTraffic(
        since=window_start,
        team_timezone=team.timezone,
        people_by_set={int(condition_set): int(people) for condition_set, people, _, _ in rows if condition_set},
        calls=sum(int(calls) for _, _, calls, _ in rows),
        remotely_evaluated_calls=sum(int(remotely_evaluated) for _, _, _, remotely_evaluated in rows),
    )


def _flag_call_events(organization_id: UUID) -> list[str]:
    if get_organization_flag_evaluations_mode(organization_id) != FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY:
        return [DEFAULT_EXPOSURE_EVENT]
    # Ingestion holds the allowlist, so a team of the organization can still write the call, the copy or both. A
    # call and its copy are two rows of one person, and each person counts once under their latest set.
    return [DEFAULT_EXPOSURE_EVENT, EXPERIMENT_EXPOSURE_EVENT]


def _load_condition_set_traffic(experiment: Experiment) -> ConditionSetTraffic | None:
    launched_at = experiment.start_date
    flag = experiment.feature_flag
    if launched_at is None or flag.version is None:
        return None
    cache_key = _cache_key(experiment, launched_at)
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return ConditionSetTraffic(**cached)
    if cached == _UNKNOWN:
        return None

    now = timezone.now()
    window_start = max(launched_at, flag.updated_at or launched_at, now - TRAFFIC_WINDOW)
    try:
        traffic = query_condition_set_traffic(experiment, window_start=window_start, window_end=now)
    except Exception as error:
        # The page calls the endpoint on every load, so a scan that fails must not run again on every load.
        # Cluster memory pressure subclasses the per-query memory error, but it says nothing about this scan.
        transient = isinstance(error, CH_TRANSIENT_ERRORS)
        too_expensive = not transient and isinstance(error, TOO_EXPENSIVE_ERRORS)
        if not transient and not too_expensive:
            capture_exception(error)
        cache.set(cache_key, _UNKNOWN, _TOO_EXPENSIVE_CACHE_SECONDS if too_expensive else _FAILED_CACHE_SECONDS)
        return None
    cache.set(
        cache_key,
        {
            "since": traffic.since,
            "team_timezone": traffic.team_timezone,
            "people_by_set": dict(traffic.people_by_set),
            "calls": traffic.calls,
            "remotely_evaluated_calls": traffic.remotely_evaluated_calls,
        },
        _TOO_FEW_PEOPLE_CACHE_SECONDS
        if sum(traffic.people_by_set.values()) < MIN_MATCHED_PEOPLE
        else _ANSWER_CACHE_SECONDS,
    )
    return traffic


def _cache_key(experiment: Experiment, launched_at: datetime) -> str:
    flag = experiment.feature_flag
    # Every input of the query except the end of the window, which moves with the clock.
    inputs = json.dumps(
        [
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
