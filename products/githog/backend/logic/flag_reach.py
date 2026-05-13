"""Empirical reach for a set of feature-flag keys.

Reach is measured from `$feature_flag_called` events — the real
evaluation log — rather than inferred from configured rollout
percentages. This is the only way to correctly handle:

- Property-based targeting (rollout % ≠ global %)
- Nested feature gates (compounding outer/inner flags)
- Multivariate splits
- Anonymous-vs-identified evaluation differences

Two computations:

1. Per-flag reach (users / sessions / call count, with variant
   breakdown) for each key independently.

2. Intersection reach: distinct persons who had EVERY supplied key
   evaluated truthy in the window. This is the right answer to
   "how many users will see this code path," assuming the supplied
   set covers the relevant flags on that path.
"""

from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

if TYPE_CHECKING:
    from posthog.models import Team

    from ..facade.contracts import FlagReach


# Treat the flag response as truthy unless it is exactly the string "false"
# or boolean false. Multivariate variants (e.g. "control", "treatment_a")
# are truthy. Empty / null responses are treated as not truthy — they
# represent failed or unevaluated calls.
_TRUTHY_PREDICATE = "toString(properties.$feature_flag_response) NOT IN ('false', '', 'null')"


def _string_array(keys: list[str]) -> ast.Array:
    return ast.Array(exprs=[ast.Constant(value=k) for k in keys])


def compute_per_flag_reach(team: "Team", keys: list[str], lookback_days: int) -> list["FlagReach"]:
    """Aggregate users/sessions/calls per flag, plus variant breakdown.

    Returns a FlagReach per *requested* key (in the order supplied),
    even if some keys have no data — those come back with zeroed
    counts and `has_data=False`, so the caller can surface "unknown"
    rather than misleading zeros.
    """
    from ..facade.contracts import FlagReach, VariantReach

    if not keys:
        return []

    # nosemgrep: hogql-fstring (truthy predicate is a constant)
    response = execute_hogql_query(
        query=f"""
            SELECT
                properties.$feature_flag AS flag_key,
                toString(properties.$feature_flag_response) AS variant,
                uniq(person_id) AS users,
                uniq($session_id) AS sessions,
                count() AS calls
            FROM events
            WHERE event = '$feature_flag_called'
              AND timestamp > now() - toIntervalDay({{lookback_days}})
              AND properties.$feature_flag IN {{flag_keys}}
              AND {_TRUTHY_PREDICATE}
            GROUP BY flag_key, variant
        """,
        team=team,
        placeholders={
            "lookback_days": ast.Constant(value=lookback_days),
            "flag_keys": _string_array(keys),
        },
    )

    # Aggregate rows: per-flag totals plus per-variant breakdown.
    # uniq() of a union of variant rows is not summable — for the
    # per-flag total we run a second, simpler query without the
    # variant grouping. Cheaper than client-side union estimation.
    by_flag: dict[str, dict[str, int]] = {}
    variants_by_flag: dict[str, list[VariantReach]] = {k: [] for k in keys}
    for row in response.results or []:
        flag_key, variant, users, sessions, calls = row
        by_flag.setdefault(flag_key, {"users": 0, "sessions": 0, "calls": 0})
        variants_by_flag.setdefault(flag_key, []).append(VariantReach(variant=variant, users_affected=int(users or 0)))

    totals = execute_hogql_query(
        query=f"""
            SELECT
                properties.$feature_flag AS flag_key,
                uniq(person_id) AS users,
                uniq($session_id) AS sessions,
                count() AS calls
            FROM events
            WHERE event = '$feature_flag_called'
              AND timestamp > now() - toIntervalDay({{lookback_days}})
              AND properties.$feature_flag IN {{flag_keys}}
              AND {_TRUTHY_PREDICATE}
            GROUP BY flag_key
        """,
        team=team,
        placeholders={
            "lookback_days": ast.Constant(value=lookback_days),
            "flag_keys": _string_array(keys),
        },
    )
    totals_by_flag: dict[str, tuple[int, int, int]] = {}
    for row in totals.results or []:
        flag_key, users, sessions, calls = row
        totals_by_flag[flag_key] = (int(users or 0), int(sessions or 0), int(calls or 0))

    out: list[FlagReach] = []
    for key in keys:
        users, sessions, calls = totals_by_flag.get(key, (0, 0, 0))
        variants = tuple(sorted(variants_by_flag.get(key, []), key=lambda v: -v.users_affected))
        out.append(
            FlagReach(
                key=key,
                users_affected=users,
                sessions_affected=sessions,
                call_count=calls,
                variants=variants,
                has_data=key in totals_by_flag,
            )
        )
    return out


def compute_intersection_reach(team: "Team", keys: list[str], lookback_days: int) -> tuple[int, int]:
    """Persons (and sessions) who had EVERY supplied flag evaluated truthy.

    Returns (users, sessions).

    Sessions are counted as: sessions in which the union of truthy flag
    evaluations across the session covers all requested keys. This is
    a session-level rather than person-level join, which is closer to
    "code path hit" semantics for in-product flag chains.
    """
    if not keys:
        return (0, 0)
    if len(keys) == 1:
        # Special-case: intersection of one flag IS that flag's reach.
        # Avoid the extra subquery roundtrip.
        single = compute_per_flag_reach(team, keys, lookback_days)
        if not single:
            return (0, 0)
        return (single[0].users_affected, single[0].sessions_affected)

    placeholders = {
        "lookback_days": ast.Constant(value=lookback_days),
        "flag_keys": _string_array(keys),
    }

    # Persons who had every flag in `keys` evaluated truthy at some
    # point in the window. Person-level grain (i.e. covered across
    # multiple sessions counts).
    # nosemgrep: hogql-fstring (truthy predicate is a constant)
    person_resp = execute_hogql_query(
        query=f"""
            SELECT count() FROM (
                SELECT
                    person_id,
                    groupUniqArrayIf(
                        properties.$feature_flag,
                        {_TRUTHY_PREDICATE}
                    ) AS truthy_flags
                FROM events
                WHERE event = '$feature_flag_called'
                  AND timestamp > now() - toIntervalDay({{lookback_days}})
                  AND properties.$feature_flag IN {{flag_keys}}
                GROUP BY person_id
                HAVING hasAll(truthy_flags, {{flag_keys}})
            )
        """,
        team=team,
        placeholders=placeholders,
    )
    users = int(person_resp.results[0][0]) if person_resp.results and person_resp.results[0] else 0

    # Sessions that covered every flag within the same session. Stricter
    # — closer to "user hit the actual code path in one go" semantics.
    # nosemgrep: hogql-fstring (truthy predicate is a constant)
    session_resp = execute_hogql_query(
        query=f"""
            SELECT count() FROM (
                SELECT
                    $session_id AS session_id,
                    groupUniqArrayIf(
                        properties.$feature_flag,
                        {_TRUTHY_PREDICATE}
                    ) AS truthy_flags
                FROM events
                WHERE event = '$feature_flag_called'
                  AND timestamp > now() - toIntervalDay({{lookback_days}})
                  AND properties.$feature_flag IN {{flag_keys}}
                  AND $session_id != ''
                GROUP BY session_id
                HAVING hasAll(truthy_flags, {{flag_keys}})
            )
        """,
        team=team,
        placeholders=placeholders,
    )
    sessions = int(session_resp.results[0][0]) if session_resp.results and session_resp.results[0] else 0

    return (users, sessions)
