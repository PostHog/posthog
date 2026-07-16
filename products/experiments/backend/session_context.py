"""Resolve which experiments (and variants) a session recording saw.

Variants come from the flag, via complementary event signals:

- `$feature_flag_called` flag evaluations: variant evidence for every experiment — the replay
  shows exactly what the session was served, whatever the exposure criteria say — and the
  exposure moment for experiments with the default criteria shape (variant in
  `$feature_flag_response`).
- Exposure events resolved per experiment from custom exposure criteria through the shared
  `exposure_query_logic` helpers: the configured event/action defines the exposure moment
  (variant in the stamped `$feature/<key>` property).
- `$feature/<key>` properties stamped on every captured event by posthog-js. These cover the
  SDK dedupe gap: a returning user's later sessions may carry no exposure event at all.

The exposure timestamp follows each experiment's exposure criteria, but only within this
session: the experiment analysis counts exposure per person across the whole run window
(and applies test-account filtering and multiple-variant handling, which are deliberately
not applied here — this surface shows the raw session truth). Callers must present this as
what the session *saw*, not what the experiment analysis counts.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from django.db.models import Q, QuerySet

import pydantic

from posthog.schema import ExperimentEventExposureConfig, ExperimentExposureCriteria

from posthog.hogql import ast
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

from products.cohorts.backend.models.cohort import Cohort
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    build_exposure_event_conditions,
    get_exposure_event_and_property,
    normalize_to_exposure_criteria,
)
from products.experiments.backend.models.experiment import Experiment

# Slack around the recording bounds — flag evaluation can be captured slightly outside the
# replay window (clock skew, events flushed before/after snapshots).
EVENT_WINDOW_SLACK = timedelta(hours=1)
MAX_CANDIDATE_EXPERIMENTS = 50
# The exposure query filters to real experiment flag keys and defined variant names, so its
# group-by output is bounded by team configuration, not by event payloads. The explicit limit
# is a backstop far above any real configuration — without it HogQL applies an implicit
# LIMIT 100, which would silently and nondeterministically truncate legitimate rows.
MAX_EXPOSURE_ROWS = 10_000


@dataclass(frozen=True)
class _ResolvedExposure:
    """An experiment's exposure criteria resolved to what its exposure query needs: which
    property carries the variant, the event/action + property conditions, and whether the
    experiment can share the batched default `$feature_flag_called` query."""

    variant_property: str
    conditions: list[ast.Expr]
    batchable: bool


@dataclass(frozen=True)
class ExperimentSessionContextItem:
    experiment_id: int
    experiment_name: str
    flag_key: str
    variant: str
    variants_seen: list[str]
    multiple_variants: bool
    first_exposure_timestamp: Optional[datetime]
    experiment_start_date: Optional[datetime]
    experiment_end_date: Optional[datetime]


def get_session_experiment_context(
    team: Team, session_id: str, experiments: QuerySet[Experiment], user: User
) -> Optional[list[ExperimentSessionContextItem]]:
    """Returns the experiments the session saw, or None when the recording doesn't exist for this team.

    `experiments` is the caller's base queryset — the view passes it through object-level
    access control so private experiments never surface in another user's session context.
    `user` is the viewer: exposure criteria can filter on arbitrary event/person properties,
    and the queries must enforce that user's property-level access control (as the experiment
    query runners do) — userless execution would apply only the default property rules.
    """
    metadata = SessionReplayEvents().get_metadata(session_id, team)
    if metadata is None:
        return None

    recording_start = metadata["start_time"]
    recording_end = metadata["end_time"]

    # Launched experiments whose run window overlaps the recording. Archived experiments are
    # kept on purpose: the session really saw their variant while they ran.
    overlapping = (
        experiments.filter(team_id=team.pk)
        .exclude(deleted=True)
        .filter(start_date__isnull=False, start_date__lte=recording_end)
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=recording_start))
        .select_related("feature_flag")
    )
    # The stamped-property query needs one column per flag, so its candidate set must be capped;
    # newest-first keeps the slice deterministic and biased toward the most relevant experiments.
    candidates = list(overlapping.order_by("-start_date")[:MAX_CANDIDATE_EXPERIMENTS])
    if not candidates:
        return []

    window_start = recording_start - EVENT_WINDOW_SLACK
    window_end = recording_end + EVENT_WINDOW_SLACK

    # Every overlapping experiment's flag key (uncapped — the rescue below must be able to see
    # beyond the candidate cap), its exposure criteria, and its defined variant names. Filtering
    # the exposure queries to these bounds their cardinality by real configuration: sessions call
    # plenty of non-experiment flags, and event payloads can carry arbitrary keys/variants.
    flag_meta = list(
        overlapping.order_by("-start_date").values_list(
            "id", "feature_flag__key", "feature_flag__filters", "exposure_criteria"
        )
    )
    if not any(_variant_keys_from_filters(filters) for _, _, filters, _ in flag_meta):
        # No overlapping experiment defines variants, so nothing could surface a variant seen.
        return []

    # Each experiment's exposure criteria resolve (through the shared helpers) to what counts
    # as its exposure event and which property carries the variant. Experiments with the plain
    # default shape take their exposure moment straight from the shared flag-evaluations query;
    # the rest get one union branch each. Everything is keyed by experiment id, since two
    # experiments can share a flag with different criteria.
    flag_key_by_id: dict[int, str] = {}
    batchable_ids: set[int] = set()
    all_variant_keys: set[str] = set()
    branch_meta: list[tuple[int, _ResolvedExposure, set[str]]] = []
    for experiment_id, flag_key, filters, exposure_criteria in flag_meta:
        variant_keys = _variant_keys_from_filters(filters)
        if not variant_keys:
            continue
        flag_key_by_id[experiment_id] = flag_key
        all_variant_keys |= variant_keys
        resolution = _resolve_exposure(team, flag_key, exposure_criteria)
        if resolution.batchable:
            batchable_ids.add(experiment_id)
        else:
            branch_meta.append((experiment_id, resolution, variant_keys))

    # Flag evaluations are variant evidence for every experiment — the replay shows exactly
    # what the session was served, whatever the exposure criteria say — and double as the
    # exposure moment for experiments with the default criteria shape.
    flag_evaluations = _query_flag_evaluations(
        team, user, session_id, window_start, window_end, set(flag_key_by_id.values()), all_variant_keys
    )
    exposures: dict[int, list[tuple[str, datetime]]] = {
        experiment_id: flag_evaluations[flag_key]
        for experiment_id, flag_key in flag_key_by_id.items()
        if experiment_id in batchable_ids and flag_key in flag_evaluations
    }
    # Same width backstop as the candidate cap — each branch experiment adds a union branch, so
    # (unlike the constant-width default query) non-batchable experiments beyond the cap are
    # deliberately not queried and forgo the rescue below.
    exposures.update(
        _query_exposure_event_branches(
            team, user, session_id, window_start, window_end, branch_meta[:MAX_CANDIDATE_EXPERIMENTS]
        )
    )

    # The exposure queries cover every overlapping experiment's flag (not just the capped
    # candidates), so a flag with verifiable in-session evidence rescues its experiment even
    # when it fell outside the cap above. Rescued keys join the stamped-property query too —
    # it stays bounded, since rescues are limited to real overlapping experiments the session
    # demonstrably called.
    evidenced_keys = set(flag_evaluations) | {flag_key_by_id[experiment_id] for experiment_id in exposures}
    candidate_keys = {experiment.feature_flag.key for experiment in candidates}
    rescued_keys = evidenced_keys - candidate_keys
    if rescued_keys:
        candidates += list(overlapping.filter(feature_flag__key__in=sorted(rescued_keys)))
        candidate_keys = {experiment.feature_flag.key for experiment in candidates}

    stamped = _query_stamped_flag_properties(team, user, session_id, candidate_keys, window_start, window_end)

    items: list[ExperimentSessionContextItem] = []
    for experiment in candidates:
        flag_key = experiment.feature_flag.key
        # Only the flag's defined variant keys count, mirroring the `variant IN variants` filter in
        # build_common_exposure_conditions: a non-enrolled user's flag evaluation captures
        # `$feature_flag_response: false`, which must not surface as a variant named "false".
        defined_variants = _defined_variant_keys(experiment)
        exposure_rows = [row for row in exposures.get(experiment.pk, []) if row[0] in defined_variants]
        flag_rows = [row for row in flag_evaluations.get(flag_key, []) if row[0] in defined_variants]
        stamped_values = [value for value in stamped.get(flag_key, []) if value in defined_variants]
        variants_seen = sorted(
            {variant for variant, _ in exposure_rows} | {variant for variant, _ in flag_rows} | set(stamped_values)
        )
        if not variants_seen:
            continue

        first_exposure_timestamp: Optional[datetime] = None
        if exposure_rows:
            variant, first_exposure_timestamp = min(exposure_rows, key=lambda row: row[1])
        elif flag_rows:
            # The session was demonstrably served this variant, but no event matched the
            # experiment's exposure criteria — so there is no exposure moment to point at.
            variant = min(flag_rows, key=lambda row: row[1])[0]
        else:
            variant = variants_seen[0]

        items.append(
            ExperimentSessionContextItem(
                experiment_id=experiment.pk,
                experiment_name=experiment.name,
                flag_key=flag_key,
                variant=variant,
                variants_seen=variants_seen,
                multiple_variants=len(variants_seen) > 1,
                first_exposure_timestamp=first_exposure_timestamp,
                experiment_start_date=experiment.start_date,
                experiment_end_date=experiment.end_date,
            )
        )

    return sorted(items, key=lambda item: item.experiment_name.lower())


def _resolve_exposure(team: Team, flag_key: str, exposure_criteria: Optional[dict]) -> _ResolvedExposure:
    """Resolve an experiment's exposure criteria through the shared `exposure_query_logic`
    helpers — the single seam that keeps this surface in sync with the experiment analysis.
    Malformed stored criteria fall back to the default exposure event rather than failing the
    whole surface for one broken experiment."""
    criteria: Optional[ExperimentExposureCriteria]
    try:
        criteria = normalize_to_exposure_criteria(exposure_criteria)
    except pydantic.ValidationError:
        criteria = None
    exposure_config = criteria.exposure_config if criteria else None
    event, variant_property = get_exposure_event_and_property(flag_key, criteria)
    # Only experiments whose criteria resolve to the plain `$feature_flag_called` shape (no
    # extra property filters) can share the batched query. The literal is deliberate — it names
    # the batched query's shape, not the default: if DEFAULT_EXPOSURE_EVENT ever changes in
    # `exposure_query_logic`, criteria-less experiments resolve to the new event here and
    # automatically take the per-experiment branch path, which follows the criteria.
    has_property_filters = isinstance(exposure_config, ExperimentEventExposureConfig) and bool(
        exposure_config.properties
    )
    batchable = event == "$feature_flag_called" and not has_property_filters
    conditions: list[ast.Expr] = []
    if not batchable:
        try:
            conditions = build_exposure_event_conditions(criteria, team, flag_key)
        except (Cohort.DoesNotExist, BaseHogQLError):
            # Criteria this project can't resolve — a cohort filter whose cohort doesn't exist
            # here (e.g. a duplicated experiment carrying the source project's cohort id), or a
            # property filter HogQL can't compile — must not fail the whole surface. Match
            # nothing instead, like `_build_action_filter` does for missing actions: the
            # experiment still surfaces through stamped properties, and no exposure moment is
            # fabricated from criteria the analysis can't honor either.
            conditions = [ast.Constant(value=False)]
    return _ResolvedExposure(variant_property=variant_property, conditions=conditions, batchable=batchable)


def _variant_keys_from_filters(filters: Optional[dict]) -> set[str]:
    multivariate = (filters or {}).get("multivariate") or {}
    return {variant["key"] for variant in multivariate.get("variants", []) if variant.get("key")}


def _defined_variant_keys(experiment: Experiment) -> set[str]:
    return _variant_keys_from_filters(experiment.feature_flag.filters)


def _query_flag_evaluations(
    team: Team,
    user: User,
    session_id: str,
    window_start: datetime,
    window_end: datetime,
    flag_keys: set[str],
    variants: set[str],
) -> dict[str, list[tuple[str, datetime]]]:
    """The session's `$feature_flag_called` events for the given experiment flag keys and
    defined variant names, as flag_key -> [(variant, first_seen)]. Serves two roles: variant
    evidence for every experiment (the replay shows what the session was served, whatever the
    exposure criteria say), and the exposure moment for experiments whose criteria resolve to
    the plain default shape (`$feature_flag_called` with no extra property filters).

    Shape-bound to `$feature_flag_called` on purpose — the `$feature_flag` batching key and
    the `$feature_flag_response` variant property come with that event, so all three are
    hardcoded together. If DEFAULT_EXPOSURE_EVENT changes in `exposure_query_logic`, this
    query needs no rewrite: flag evaluations stay `$feature_flag_called` events, and
    `_resolve_exposure` stops classifying criteria-less experiments as batchable, so their
    exposure moments move to the branch path."""
    query = parse_select(
        """
        SELECT properties.$feature_flag AS flag_key,
               toString(properties.$feature_flag_response) AS variant,
               min(timestamp) AS first_seen
        FROM events
        WHERE event = '$feature_flag_called'
          AND $session_id = {session_id}
          AND properties.$feature_flag IN {flag_keys}
          AND toString(properties.$feature_flag_response) IN {variants}
          AND timestamp >= {window_start}
          AND timestamp <= {window_end}
        GROUP BY flag_key, variant
        LIMIT {max_rows}
        """,
        placeholders={
            "session_id": ast.Constant(value=session_id),
            "flag_keys": ast.Constant(value=sorted(flag_keys)),
            "variants": ast.Constant(value=sorted(variants)),
            "window_start": ast.Constant(value=window_start),
            "window_end": ast.Constant(value=window_end),
            "max_rows": ast.Constant(value=MAX_EXPOSURE_ROWS),
        },
    )
    response = execute_hogql_query(query, team=team, user=user)

    exposures: dict[str, list[tuple[str, datetime]]] = {}
    for flag_key, variant, first_seen in response.results or []:
        if not flag_key or not variant:
            continue
        exposures.setdefault(str(flag_key), []).append((str(variant), first_seen))
    return exposures


def _query_exposure_event_branches(
    team: Team,
    user: User,
    session_id: str,
    window_start: datetime,
    window_end: datetime,
    branch_meta: list[tuple[int, _ResolvedExposure, set[str]]],
) -> dict[int, list[tuple[str, datetime]]]:
    """The session's exposure events for experiments whose criteria don't fit the batched
    default query (a custom event, an action, or the default event narrowed by property
    filters), as experiment_id -> [(variant, first_seen)].

    One union branch per experiment: the event/action and property filters come from the
    experiment's exposure criteria via `build_exposure_event_conditions`, and the variant from
    the property `get_exposure_event_and_property` dictates — the stamped `$feature/<key>`
    property for custom events and actions (they carry no `$feature_flag_response`),
    `$feature_flag_response` for the default event.
    """
    branches: list[ast.SelectQuery] = []
    for experiment_id, resolution, variants in branch_meta:
        branch = parse_select(
            """
            SELECT {experiment_id} AS experiment_id,
                   toString({variant_field}) AS variant,
                   min(timestamp) AS first_seen
            FROM events
            WHERE {exposure_conditions}
              AND $session_id = {session_id}
              AND toString({variant_field}) IN {variants}
              AND timestamp >= {window_start}
              AND timestamp <= {window_end}
            GROUP BY variant
            """,
            placeholders={
                "experiment_id": ast.Constant(value=experiment_id),
                "variant_field": ast.Field(chain=["properties", resolution.variant_property]),
                "exposure_conditions": ast.And(exprs=resolution.conditions)
                if resolution.conditions
                else ast.Constant(value=True),
                "session_id": ast.Constant(value=session_id),
                "variants": ast.Constant(value=sorted(variants)),
                "window_start": ast.Constant(value=window_start),
                "window_end": ast.Constant(value=window_end),
            },
        )
        assert isinstance(branch, ast.SelectQuery)
        branches.append(branch)

    if not branches:
        return {}

    query = ast.SelectSetQuery.create_from_queries(branches, "UNION ALL")
    # Backstop against HogQL's implicit LIMIT 100 truncating legitimate rows; the branches are
    # already bounded by each flag's defined variants.
    query.limit = ast.Constant(value=MAX_EXPOSURE_ROWS)
    response = execute_hogql_query(query, team=team, user=user)

    exposures: dict[int, list[tuple[str, datetime]]] = {}
    for experiment_id, variant, first_seen in response.results or []:
        if not variant:
            continue
        exposures.setdefault(int(experiment_id), []).append((str(variant), first_seen))
    return exposures


def _query_stamped_flag_properties(
    team: Team,
    user: User,
    session_id: str,
    flag_keys: set[str],
    window_start: datetime,
    window_end: datetime,
) -> dict[str, list[str]]:
    """Distinct stamped `$feature/<key>` property values in the session, as flag_key -> values."""
    sorted_keys = sorted(flag_keys)
    # Built as ast nodes, not string interpolation — flag keys can contain arbitrary characters.
    select: list[ast.Expr] = [
        ast.Alias(
            alias=f"v{index}",
            expr=ast.Call(
                name="groupUniqArray",
                args=[ast.Call(name="toString", args=[ast.Field(chain=["properties", f"$feature/{key}"])])],
            ),
        )
        for index, key in enumerate(sorted_keys)
    ]
    query = ast.SelectQuery(
        select=select,
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["$session_id"]),
                    right=ast.Constant(value=session_id),
                ),
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
        ),
    )
    response = execute_hogql_query(query, team=team, user=user)

    row = response.results[0] if response.results else [[] for _ in sorted_keys]
    return {key: [value for value in row[index] if value] for index, key in enumerate(sorted_keys)}
