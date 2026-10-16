from datetime import UTC, datetime, timedelta
from typing import Any

from django.utils import timezone

from posthog.schema import ProductKey

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

from .impact_lens import MAX_ISSUES, WINDOW_HOURS, ImpactLens, issue_state_join, issue_summaries, with_issue_details
from .known_patterns import noise_issue_ids

TOGETHER_WITHIN_MS = 5000
MIN_SHARED_SESSIONS = 15
# Sessions where both fire close together must be at least this share of the sessions with either issue.
MIN_SHARED_SHARE = 0.5
# One issue must come first in this share of the shared sessions where one came first, for the pair to have a direction.
MIN_LEAD_SHARE = 0.9
# Most shared sessions must have one issue strictly first. Two issues from one throw land in the same millisecond, and
# such ties say nothing about which leads.
MIN_ORDERED_SHARE = 0.5
# Each issue must have this share of its sessions shared for the pair to read as one problem filed twice.
MIN_SAME_SHARE = 0.95
# Bounds the pairs a session can produce. A session with more distinct issues than this is rare and mostly noise.
MAX_ISSUES_PER_SESSION = 30

# One pass over each session's first occurrence of every issue. Issue rows count the sessions with an issue; pair rows
# count, for two issues in the same session, the sessions with both, with both close together, and with each one
# strictly first. Building the pairs inside each session avoids a self-join that would read the events twice.
QUERY = """
    SELECT
        team_id,
        tupleElement(item, 1) AS kind,
        tupleElement(item, 2) AS issue_a,
        tupleElement(item, 3) AS issue_b,
        count() AS sessions,
        countIf(abs(tupleElement(item, 5) - tupleElement(item, 4)) <= %(within_ms)s) AS shared_sessions,
        countIf(
            abs(tupleElement(item, 5) - tupleElement(item, 4)) <= %(within_ms)s AND tupleElement(item, 4) < tupleElement(item, 5)
        ) AS a_first_sessions,
        countIf(
            abs(tupleElement(item, 5) - tupleElement(item, 4)) <= %(within_ms)s AND tupleElement(item, 5) < tupleElement(item, 4)
        ) AS b_first_sessions
    FROM (
        SELECT
            team_id,
            arrayJoin(arrayConcat(
                arrayMap(first -> ('issue', first.1, first.1, first.2, first.2), firsts),
                arrayFlatten(arrayMap(
                    i -> arrayMap(
                        j -> ('pair', firsts[i].1, firsts[j].1, firsts[i].2, firsts[j].2),
                        range(i + 1, length(firsts) + 1)
                    ),
                    range(1, length(firsts) + 1)
                ))
            )) AS item
        FROM (
            SELECT
                team_id,
                session_id,
                -- Sorted by issue id, so every pair has the smaller id first.
                arraySort(first -> first.1, groupArray(%(max_issues_per_session)s)((issue_id, first_ms))) AS firsts
            FROM (
                SELECT
                    events.team_id AS team_id,
                    events.`$session_id` AS session_id,
                    toString(issue_state.issue_id) AS issue_id,
                    min(toUnixTimestamp64Milli(events.timestamp)) AS first_ms
                FROM events
                {issue_state_join}
                WHERE events.team_id IN %(team_ids)s
                    AND events.event = '$exception'
                    AND events.timestamp >= toDateTime64(%(since)s, 6, 'UTC')
                    AND events.timestamp < toDateTime64(%(until)s, 6, 'UTC')
                    AND events.`$session_id` != ''
                    AND issue_state.issue_status = 'active'
                GROUP BY team_id, session_id, issue_id
            )
            GROUP BY team_id, session_id
        )
    )
    GROUP BY team_id, kind, issue_a, issue_b
    HAVING (kind = 'issue' AND sessions >= %(min_shared_sessions)s)
        OR (kind = 'pair' AND shared_sessions >= %(min_shared_sessions)s)
"""


@frozen
class PairRow:
    team_id: int
    issue_a: str
    issue_b: str
    # With both issues at any time, with both within a few seconds, and with each one strictly first among those.
    both_sessions: int
    shared_sessions: int
    a_first_sessions: int
    b_first_sessions: int


def find_related_issues(
    pair_rows: list[PairRow], issue_sessions: dict[tuple[int, str], int]
) -> dict[int, list[dict[str, Any]]]:
    """Pick the pairs of issues that fire close together in the same sessions.

    ``issue_sessions`` maps ``(team_id, issue_id)`` to the sessions with that issue.
    """
    result: dict[int, list[dict[str, Any]]] = {}
    for row in pair_rows:
        sessions_a = issue_sessions.get((row.team_id, row.issue_a), 0)
        sessions_b = issue_sessions.get((row.team_id, row.issue_b), 0)
        either = sessions_a + sessions_b - row.both_sessions
        shared = row.shared_sessions
        if shared < MIN_SHARED_SESSIONS or either <= 0 or shared < MIN_SHARED_SHARE * either:
            continue
        ordered = row.a_first_sessions + row.b_first_sessions
        a_leads = row.a_first_sessions / ordered if ordered else 0.5
        directed = ordered >= MIN_ORDERED_SHARE * shared and (
            a_leads >= MIN_LEAD_SHARE or a_leads <= 1 - MIN_LEAD_SHARE
        )
        same = shared >= MIN_SAME_SHARE * sessions_a and shared >= MIN_SAME_SHARE * sessions_b
        a_is_lead = a_leads >= MIN_LEAD_SHARE if directed else sessions_a >= sessions_b
        lead, other = (row.issue_a, row.issue_b) if a_is_lead else (row.issue_b, row.issue_a)
        result.setdefault(row.team_id, []).append(
            {
                "id": lead,
                "sessions": sessions_a if a_is_lead else sessions_b,
                "related_id": other,
                "related_sessions": sessions_b if a_is_lead else sessions_a,
                "both_sessions": row.both_sessions,
                "shared_sessions": shared,
                "leads_share": round(a_leads if a_is_lead else 1 - a_leads, 4),
                "relation": "same" if same else "causes" if directed else "together",
            }
        )
    for team_id, pairs in result.items():
        result[team_id] = sorted(pairs, key=lambda pair: -pair["shared_sessions"])[:MAX_ISSUES]
    return result


class RelatedIssuesRecommendation(ImpactLens):
    type = "related_issues"
    refresh_interval = timedelta(hours=6)

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        tag_queries(
            product=ProductKey.ERROR_TRACKING,
            feature=Feature.ENRICHMENT,
            name="recommendations:related_issues",
        )
        now = timezone.now()
        rows = sync_execute(
            QUERY.format(issue_state_join=issue_state_join()),
            {
                "team_ids": team_ids,
                "since": _clickhouse_time(now - timedelta(hours=WINDOW_HOURS)),
                "until": _clickhouse_time(now),
                "within_ms": TOGETHER_WITHIN_MS,
                "min_shared_sessions": MIN_SHARED_SESSIONS,
                "max_issues_per_session": MAX_ISSUES_PER_SESSION,
            },
            workload=Workload.OFFLINE,
        )
        issue_sessions: dict[tuple[int, str], int] = {}
        pair_rows: list[PairRow] = []
        for team_id, kind, issue_a, issue_b, sessions, shared, a_first, b_first in rows:
            if kind == "issue":
                issue_sessions[(team_id, issue_a)] = sessions
            else:
                pair_rows.append(
                    PairRow(
                        team_id=team_id,
                        issue_a=issue_a,
                        issue_b=issue_b,
                        both_sessions=sessions,
                        shared_sessions=shared,
                        a_first_sessions=a_first,
                        b_first_sessions=b_first,
                    )
                )
        noise = noise_issue_ids(team_ids)
        pair_rows = [
            row
            for row in pair_rows
            if row.issue_a not in noise.get(row.team_id, set()) and row.issue_b not in noise.get(row.team_id, set())
        ]
        pairs = find_related_issues(pair_rows, issue_sessions)

        related = issue_summaries(
            team_ids, [pair["related_id"] for team_pairs in pairs.values() for pair in team_pairs]
        )
        with_related: dict[int, list[dict[str, Any]]] = {}
        for team_id, team_pairs in pairs.items():
            for pair in team_pairs:
                related_issue = related.get((team_id, pair.pop("related_id")))
                # Fingerprint state can reference issues deleted from Postgres, so drop the pair.
                if related_issue is None:
                    continue
                with_related.setdefault(team_id, []).append({**pair, "related": related_issue})

        issues = with_issue_details(team_ids, with_related)
        # Pairs need issues that reach enough sessions, so a project without any has nothing this lens can relate.
        evaluable = {team_id for team_id, _ in issue_sessions}
        return {
            team_id: {"window_hours": WINDOW_HOURS, "evaluable": team_id in evaluable, "issues": issues[team_id]}
            for team_id in team_ids
        }


def _clickhouse_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
