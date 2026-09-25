"""Per-flag session-id coverage for an experiment's replay surfaces.

A recordings filter matches through events that carry a `$session_id`, so a surface that filters
on an experiment's exposure event first has to know whether that event carries one. The taxonomy
`seen_together` fact answers a coarser question: has this *event name* ever, anywhere in the
project, been ingested with a `$session_id`. In a project that evaluates some flags on the client
and some on the server, `$feature_flag_called` passes that test on the strength of the client-side
flags alone, while the server-side flag's own calls carry no session id at all. Every surface that
trusts the coarse answer then keeps an exposure filter that can only match zero sessions.

This module asks the narrower question the surfaces actually need: over a recent window, does
*this experiment's flag* produce exposure events carrying a session id, and does the
`$feature/<flag_key>` stand-in the surfaces fall back to carry one either. Both answers come from
live events, because `posthog_eventproperty` has no flag dimension to scope on.

The flag-property scan has no event name to prune on, so it only runs when the exposure scan has
already reported no coverage, and only for the default exposure events, the only ones a surface
stands in for — the minority case, and the only one where the answer changes what a surface does.
Both scans stop at the first matching row and are capped, so an unbounded window can't turn a
tab's mount into a long query. An unknown answer (a refused or failed scan, an action-based
exposure criteria, an experiment that never launched, a window holding no exposure event at all)
is reported as `None`, and every caller treats that as "assume it matches", the fail-open posture
the rest of the linkability seam takes.
"""

import json
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional

from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.utils import get_safe_cache, safe_cache_set

from products.access_control.backend.facade.property_access import sort_restricted_properties
from products.access_control.backend.property_access_control import (
    get_restricted_properties_with_group_type_index_for_team,
)
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    DEFAULT_EXPOSURE_EVENT,
    EXPERIMENT_EXPOSURE_EVENT,
    build_exposure_event_conditions,
    get_exposure_event_and_property,
    get_test_accounts_filter,
    resolve_default_exposure_event,
)
from products.experiments.backend.models.experiment import Experiment

logger = logging.getLogger(__name__)

# How far back a scan reads. Long enough that a quiet weekend doesn't read as "no coverage", short
# enough that the answer follows an SDK change rather than being outvoted by history — the failure
# the all-time taxonomy fact has.
COVERAGE_WINDOW_DAYS = 7

# A scan that can't answer inside this is refused rather than held, because the caller is a tab
# mount and an unknown answer is the same fail-open as a slow one.
COVERAGE_MAX_EXECUTION_SECONDS = 15

COVERAGE_CACHE_TTL = 10 * 60


@frozen
class FlagSessionCoverage:
    """Whether this experiment's flag produces anything a recordings filter can match.

    `None` means the scan couldn't answer, never "no": callers fail open on it.
    """

    # Exposure events for this flag, carrying a session id, inside the window. False only when the
    # window held exposure events and none of them carried one.
    exposure_event: Optional[bool]
    # Events stamped with `$feature/<flag_key>`, carrying a session id, inside the window. Only
    # scanned when `exposure_event` is False, since that is the only case where a surface reads it.
    flag_property: Optional[bool]
    # A ceiling, not the window a scan read: `_coverage_window` clips it to the experiment's run.
    max_window_days: int = COVERAGE_WINDOW_DAYS


@frozen
class CoverageWindow:
    """The span of time a scan reads over."""

    start: datetime
    end: datetime


def _coverage_window(experiment: Experiment) -> Optional[CoverageWindow]:
    """The window a scan reads, clipped to the experiment's own run.

    Reading outside the run would answer about a flag the experiment wasn't using yet, and reading
    an unlaunched or long-finished experiment answers nothing a surface can act on.
    """
    if experiment.start_date is None:
        return None
    window_end = min(timezone.now(), experiment.end_date) if experiment.end_date else timezone.now()
    window_start = max(experiment.start_date, window_end - timedelta(days=COVERAGE_WINDOW_DAYS))
    if window_start >= window_end:
        return None
    return CoverageWindow(start=window_start, end=window_end)


def _session_id_present() -> ast.Expr:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.NotEq,
        left=ast.Field(chain=["$session_id"]),
        right=ast.Constant(value=""),
    )


def _has_matching_row(team: Team, user: User, where: list[ast.Expr]) -> Optional[bool]:
    """Whether any event matches `where`.

    One row is enough, so the scan stops at the first match instead of counting. A failure is
    `None` rather than False: a refused scan must not read as evidence of absence. The viewer is
    threaded through so member- and role-level property restrictions compile into the SQL, the same
    as every other request-serving scan in this product.
    """
    query = ast.SelectQuery(
        select=[ast.Constant(value=1)],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=ast.And(exprs=where),
        limit=ast.Constant(value=1),
    )
    try:
        response = execute_hogql_query(
            query,
            team=team,
            user=user,
            settings=HogQLGlobalSettings(
                max_execution_time=COVERAGE_MAX_EXECUTION_SECONDS,
                # Under a "break" timeout profile the kill returns an empty partial result instead
                # of raising, which reads here as a confident absence and is then cached for ten
                # minutes. Absence is the one answer this seam must never guess, so the kill throws
                # and the caller reports the unknown.
                timeout_overflow_mode="throw",
            ),
        )
    except Exception:
        logger.warning("experiment replay session coverage scan failed", exc_info=True, extra={"team_id": team.pk})
        return None
    return bool(response.results)


def _session_id_coverage(team: Team, user: User, where: list[ast.Expr]) -> Optional[bool]:
    """Whether the events matching `where` carry a session id.

    False means matching events exist and none of them carried one. A window holding no matching
    event at all says nothing about whether these events carry a session id, so that is `None`, the
    same unknown a refused scan reports: a flag quiet for a week must not read as a flag whose
    events can't match a recording. The second probe runs only once the first found nothing.
    """
    linked = _has_matching_row(team, user, [*where, _session_id_present()])
    if linked is not False:
        return linked
    return False if _has_matching_row(team, user, where) is True else None


def _stamped_for_this_experiment(experiment: Experiment, flag_key: str) -> ast.Expr:
    """Events the stand-in filter could match: stamped with one of the experiment's variants.

    The surfaces that fall back to the stand-in narrow it to the experiment's own variant keys, so
    a scan that accepted any stamped value would report coverage they can't use: a partial rollout
    stamps `false` on everyone outside it, and those are ordinary client events carrying a session
    id. A flag with no variants keeps the wider "stamped at all" test, which is what those surfaces
    fall back to as well.
    """
    stamped_value = ast.Call(name="toString", args=[ast.Field(chain=["properties", f"$feature/{flag_key}"])])
    variant_keys = [variant["key"] for variant in experiment.feature_flag.variants if variant.get("key")]
    if not variant_keys:
        # `notEmpty(ifNull(...))` rather than a `!=` comparison: HogQL reads a null as "not equal",
        # so comparing an absent property to the empty string matches every event that never
        # carried it.
        return ast.Call(
            name="notEmpty",
            args=[ast.Call(name="ifNull", args=[stamped_value, ast.Constant(value="")])],
        )
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=stamped_value,
        right=ast.Constant(value=variant_keys),
    )


def _window_bounds(window_start: datetime, window_end: datetime) -> list[ast.Expr]:
    return [
        ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=ast.Field(chain=["timestamp"]),
            right=ast.Constant(value=window_start),
        ),
        ast.CompareOperation(
            op=ast.CompareOperationOp.LtEq,
            left=ast.Field(chain=["timestamp"]),
            right=ast.Constant(value=window_end),
        ),
    ]


def _restriction_signature(team: Team, user: User) -> str:
    """The viewer's property restrictions, as a cache-key fragment.

    Restrictions compile into the SQL, so unlike recording access they can't be re-filtered on
    read; a restriction change has to miss the cache instead. Mirrors `session_buckets`.
    """
    return json.dumps(
        [
            {
                "name": restriction.name,
                "property_type": restriction.property_type,
                "group_type_index": restriction.group_type_index,
            }
            for restriction in sort_restricted_properties(
                get_restricted_properties_with_group_type_index_for_team(user=user, team=team)
            )
        ]
    )


def resolve_flag_session_coverage(team: Team, experiment_id: int, user: User) -> FlagSessionCoverage:
    """Read this experiment's flag-scoped session-id coverage, cached per experiment and viewer.

    Takes the experiment id, not the object: this is the product's facade boundary, and a caller
    outside the product must not hold an experiments Django model.
    """
    unknown = FlagSessionCoverage(exposure_event=None, flag_property=None)
    experiment = Experiment.objects.filter(id=experiment_id, team=team).select_related("feature_flag").first()
    if experiment is None or getattr(experiment, "feature_flag", None) is None:
        return unknown
    window = _coverage_window(experiment)
    if window is None:
        return unknown
    # Historical events carry the key the flag had while the experiment ran, so a flag renamed by
    # soft-delete cleanup has to resolve back to it, the same way the population query does.
    flag_key = experiment.feature_flag.key_without_tombstone()
    default_exposure_event = resolve_default_exposure_event(team, experiment.start_date)
    exposure_event, _ = get_exposure_event_and_property(
        flag_key, experiment.exposure_criteria, default_exposure_event=default_exposure_event
    )
    if exposure_event is None:
        # Action criteria match several events, so there is no single flag-scoped scan to run.
        return unknown

    # Keyed by the viewer's property restrictions too: they compile into the scan's SQL, so a
    # cache shared across restriction sets would hand one viewer another's unrestricted verdict.
    restriction_signature = hashlib.sha256(_restriction_signature(team, user).encode()).hexdigest()[:16]
    cache_key = (
        f"experiment_replay_coverage_{team.pk}_{experiment.pk}_{flag_key}"
        f"_{default_exposure_event}_{restriction_signature}"
    )
    cached = get_safe_cache(cache_key)
    if cached is not None:
        return cached

    tag_queries(product=Product.EXPERIMENTS, feature=Feature.QUERY, team_id=team.pk)
    window_start, window_end = window.start, window.end
    # The surfaces this verdict steers drop test accounts when the criteria say so, so a scan that
    # kept them would answer over a wider population than the list and read one internal browser
    # session as coverage the real population doesn't have.
    test_account_conditions = get_test_accounts_filter(team, experiment.exposure_criteria)
    exposure_covered = _session_id_coverage(
        team,
        user,
        [
            *_window_bounds(window_start, window_end),
            *test_account_conditions,
            *build_exposure_event_conditions(
                experiment.exposure_criteria,
                team,
                flag_key,
                default_exposure_event=default_exposure_event,
            ),
        ],
    )
    flag_property_covered: Optional[bool] = None
    # Only the default exposure events have a stand-in, the same restriction
    # `SessionExposure.used_fallback` and `getExposureFallbackFilter` apply: custom criteria assert
    # that something specific happened, which the stamped flag property doesn't imply. Scanning it
    # there would answer a question no surface can act on, and read as a usable fallback.
    if exposure_covered is False and exposure_event in (DEFAULT_EXPOSURE_EVENT, EXPERIMENT_EXPOSURE_EVENT):
        # A plain probe, not the verdict above: `$feature/<flag_key>` is stamped by the client
        # SDK, which always attaches a session id, so no stamped event in the window means there is
        # nothing for a filter to match rather than a question the window couldn't answer.
        flag_property_covered = _has_matching_row(
            team,
            user,
            [
                *_window_bounds(window_start, window_end),
                *test_account_conditions,
                _session_id_present(),
                _stamped_for_this_experiment(experiment, flag_key),
            ],
        )
    coverage = FlagSessionCoverage(exposure_event=exposure_covered, flag_property=flag_property_covered)
    safe_cache_set(cache_key, coverage, timeout=COVERAGE_CACHE_TTL)
    return coverage
