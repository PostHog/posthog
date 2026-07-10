"""Resolve which experiments (and variants) a session recording saw.

Variants come from the flag, via two complementary event signals:

- `$feature_flag_called` exposure events (carry `$feature_flag`, `$feature_flag_response`,
  `$session_id`, and a timestamp — the flag-evaluation moment).
- `$feature/<key>` properties stamped on every captured event by posthog-js. These cover the
  SDK dedupe gap: a returning user's later sessions may carry no exposure event at all.

Flag evaluation is not the same thing as the experiment's exposure criteria (custom exposure
events, holdouts, and the run window all differ), so callers must present this as what the
session *saw*, not what the experiment analysis counts.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from django.db.models import Q

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.team.team import Team
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

from products.experiments.backend.models.experiment import Experiment

# Slack around the recording bounds — flag evaluation can be captured slightly outside the
# replay window (clock skew, events flushed before/after snapshots).
EVENT_WINDOW_SLACK = timedelta(hours=1)
MAX_CANDIDATE_EXPERIMENTS = 50


@dataclass(frozen=True)
class ExperimentSessionContextItem:
    experiment_id: int
    experiment_name: str
    flag_key: str
    variant: str
    variants_seen: list[str]
    multiple_variants: bool
    first_flag_evaluation_timestamp: Optional[datetime]
    experiment_start_date: Optional[datetime]
    experiment_end_date: Optional[datetime]


def get_session_experiment_context(team: Team, session_id: str) -> Optional[list[ExperimentSessionContextItem]]:
    """Returns the experiments the session saw, or None when the recording doesn't exist for this team."""
    metadata = SessionReplayEvents().get_metadata(session_id, team)
    if metadata is None:
        return None

    recording_start = metadata["start_time"]
    recording_end = metadata["end_time"]

    # Launched experiments whose run window overlaps the recording. Archived experiments are
    # kept on purpose: the session really saw their variant while they ran.
    candidates = list(
        Experiment.objects.filter(team_id=team.pk)
        .exclude(deleted=True)
        .filter(start_date__isnull=False, start_date__lte=recording_end)
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=recording_start))
        .select_related("feature_flag")[:MAX_CANDIDATE_EXPERIMENTS]
    )
    if not candidates:
        return []

    flag_keys = {experiment.feature_flag.key for experiment in candidates}
    window_start = recording_start - EVENT_WINDOW_SLACK
    window_end = recording_end + EVENT_WINDOW_SLACK

    exposures = _query_exposure_events(team, session_id, flag_keys, window_start, window_end)
    stamped = _query_stamped_flag_properties(team, session_id, flag_keys, window_start, window_end)

    items: list[ExperimentSessionContextItem] = []
    for experiment in candidates:
        flag_key = experiment.feature_flag.key
        # Only the flag's defined variant keys count, mirroring the `variant IN variants` filter in
        # build_common_exposure_conditions: a non-enrolled user's flag evaluation captures
        # `$feature_flag_response: false`, which must not surface as a variant named "false".
        defined_variants = _defined_variant_keys(experiment)
        exposure_rows = [row for row in exposures.get(flag_key, []) if row[0] in defined_variants]
        stamped_values = [value for value in stamped.get(flag_key, []) if value in defined_variants]
        variants_seen = sorted({variant for variant, _ in exposure_rows} | set(stamped_values))
        if not variants_seen:
            continue

        if exposure_rows:
            earliest_variant, first_seen = min(exposure_rows, key=lambda row: row[1])
            variant = earliest_variant
            first_flag_evaluation_timestamp: Optional[datetime] = first_seen
        else:
            variant = variants_seen[0]
            first_flag_evaluation_timestamp = None

        items.append(
            ExperimentSessionContextItem(
                experiment_id=experiment.pk,
                experiment_name=experiment.name,
                flag_key=flag_key,
                variant=variant,
                variants_seen=variants_seen,
                multiple_variants=len(variants_seen) > 1,
                first_flag_evaluation_timestamp=first_flag_evaluation_timestamp,
                experiment_start_date=experiment.start_date,
                experiment_end_date=experiment.end_date,
            )
        )

    return sorted(items, key=lambda item: item.experiment_name.lower())


def _defined_variant_keys(experiment: Experiment) -> set[str]:
    multivariate = (experiment.feature_flag.filters or {}).get("multivariate") or {}
    return {variant["key"] for variant in multivariate.get("variants", []) if variant.get("key")}


def _query_exposure_events(
    team: Team,
    session_id: str,
    flag_keys: set[str],
    window_start: datetime,
    window_end: datetime,
) -> dict[str, list[tuple[str, datetime]]]:
    """`$feature_flag_called` events in the session, as flag_key -> [(variant, first_seen)]."""
    query = parse_select(
        """
        SELECT properties.$feature_flag AS flag_key,
               toString(properties.$feature_flag_response) AS variant,
               min(timestamp) AS first_seen
        FROM events
        WHERE event = '$feature_flag_called'
          AND $session_id = {session_id}
          AND timestamp >= {window_start}
          AND timestamp <= {window_end}
        GROUP BY flag_key, variant
        """,
        placeholders={
            "session_id": ast.Constant(value=session_id),
            "window_start": ast.Constant(value=window_start),
            "window_end": ast.Constant(value=window_end),
        },
    )
    response = execute_hogql_query(query, team=team)

    exposures: dict[str, list[tuple[str, datetime]]] = {}
    for flag_key, variant, first_seen in response.results or []:
        if flag_key not in flag_keys or not variant:
            continue
        exposures.setdefault(str(flag_key), []).append((str(variant), first_seen))
    return exposures


def _query_stamped_flag_properties(
    team: Team,
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
    response = execute_hogql_query(query, team=team)

    row = response.results[0] if response.results else [[] for _ in sorted_keys]
    return {key: [value for value in row[index] if value] for index, key in enumerate(sorted_keys)}
