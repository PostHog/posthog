import dataclasses
from datetime import timedelta
from typing import Any

from django.utils import timezone

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models.group_type_mapping import get_group_types_for_project
from posthog.models.team.team import Team

from .impact_lens import issue_state_join, per_team_results
from .known_patterns import noise_issue_ids

logger = structlog.get_logger(__name__)

WINDOW_DAYS = 14
ACCOUNT_GROUP_TYPE_INDEX = 0
DEFAULT_GROUP_LABEL = "accounts"
# Keeps the per-team row count bounded; both account lenses keep far fewer issues than this.
MAX_CANDIDATES = 500

ISSUE_QUERY = """
    SELECT
        team_id,
        issue_id,
        uniqExactMerge(people_state) AS people,
        uniqExactMerge(sessions_state) AS sessions,
        countIf(account != '') AS accounts,
        argMaxIf(account, account_sessions, account != '') AS top_account,
        maxIf(account_sessions, account != '') AS top_account_sessions
    FROM (
        SELECT
            team_id,
            issue_id,
            account,
            uniqExactState(person_id) AS people_state,
            uniqExactState(if(session_id != '', session_id, NULL)) AS sessions_state,
            uniqExactIf(session_id, session_id != '') AS account_sessions
        FROM (
            SELECT
                events.team_id AS team_id,
                issue_state.issue_id AS issue_id,
                events.person_id AS person_id,
                events.`$session_id` AS session_id,
                events.`$group_0` AS account
            FROM events
            {issue_state_join}
            WHERE events.team_id IN %(team_ids)s
                AND events.event = '$exception'
                AND events.timestamp >= now() - toIntervalDay(%(window_days)s)
                AND issue_state.issue_status = 'active'
        )
        GROUP BY team_id, issue_id, account
    )
    GROUP BY team_id, issue_id
    HAVING accounts > 0
    ORDER BY team_id, sessions DESC
    LIMIT %(max_candidates)s BY team_id
"""

# Active accounts are those seen on pageviews or exceptions, so the accounts an issue reached are always among them.
TEAM_QUERY = """
    SELECT team_id, uniqIf(account, account != '') AS active_accounts
    FROM (
        SELECT events.team_id AS team_id, events.event AS event, events.`$group_0` AS account
        FROM events
        WHERE events.team_id IN %(team_ids)s
            AND events.event IN ('$pageview', '$exception')
            AND events.timestamp >= now() - toIntervalDay(%(window_days)s)
    )
    GROUP BY team_id
"""

ACCOUNT_NAMES_QUERY = """
    SELECT team_id, group_key, argMax(JSONExtractString(group_properties, 'name'), _timestamp) AS name
    FROM groups
    WHERE team_id IN %(team_ids)s
        AND group_type_index = %(group_type_index)s
        AND group_key IN %(group_keys)s
    GROUP BY team_id, group_key
"""


@frozen
class TeamAccounts:
    active_accounts: int

    @property
    def evaluable(self) -> bool:
        # Without any account on pageviews or exceptions, neither account lens can say anything.
        return self.active_accounts > 0


@frozen
class IssueAccounts:
    team_id: int
    issue_id: str
    people: int
    sessions: int
    accounts: int
    top_account: str
    top_account_sessions: int

    @property
    def top_account_share(self) -> float:
        return self.top_account_sessions / self.sessions if self.sessions else 0.0


@frozen
class TeamReach:
    issues: list[IssueAccounts]
    accounts: TeamAccounts


NO_REACH = TeamReach(issues=[], accounts=TeamAccounts(active_accounts=0))


@frozen
class AccountReach:
    issues: list[IssueAccounts]
    teams: dict[int, TeamAccounts]

    def team(self, team_id: int) -> TeamAccounts:
        return self.teams.get(team_id, NO_REACH.accounts)


def fetch_account_reach(team_ids: list[int]) -> AccountReach:
    """Who each issue reached. Within one sweep batch, each team is queried once for both account lenses."""
    by_team = per_team_results(("account_reach",), team_ids, _query_account_reach, lambda: NO_REACH)
    return AccountReach(
        issues=[issue for team_id in team_ids for issue in by_team[team_id].issues],
        teams={team_id: by_team[team_id].accounts for team_id in team_ids},
    )


def _query_account_reach(team_ids: list[int]) -> dict[int, TeamReach]:
    params = {"team_ids": team_ids, "window_days": WINDOW_DAYS, "max_candidates": MAX_CANDIDATES}
    issue_rows = sync_execute(
        ISSUE_QUERY.format(issue_state_join=issue_state_join()), params, workload=Workload.OFFLINE
    )
    team_rows = sync_execute(TEAM_QUERY, params, workload=Workload.OFFLINE)
    issues: dict[int, list[IssueAccounts]] = {team_id: [] for team_id in team_ids}
    for team_id, issue_id, people, sessions, accounts, top_account, top_account_sessions in issue_rows:
        issues[team_id].append(
            IssueAccounts(
                team_id=team_id,
                issue_id=str(issue_id),
                people=people,
                sessions=sessions,
                accounts=accounts,
                top_account=top_account,
                top_account_sessions=top_account_sessions,
            )
        )
    active: dict[int, int] = dict(team_rows)
    return {
        team_id: TeamReach(issues=issues[team_id], accounts=TeamAccounts(active_accounts=active.get(team_id, 0)))
        for team_id in team_ids
    }


def without_noise(team_ids: list[int], reach: AccountReach) -> AccountReach:
    """The reach of the issues that are not likely noise."""
    candidates: dict[int, set[str]] = {}
    for issue in reach.issues:
        candidates.setdefault(issue.team_id, set()).add(issue.issue_id)
    noise = noise_issue_ids(team_ids, candidates, timezone.now() - timedelta(days=WINDOW_DAYS))
    return dataclasses.replace(
        reach, issues=[issue for issue in reach.issues if issue.issue_id not in noise.get(issue.team_id, set())]
    )


def account_names(team_ids: list[int], keys: list[str]) -> dict[tuple[int, str], str]:
    if not keys:
        return {}
    rows = sync_execute(
        ACCOUNT_NAMES_QUERY,
        {"team_ids": team_ids, "group_type_index": ACCOUNT_GROUP_TYPE_INDEX, "group_keys": sorted(set(keys))},
        workload=Workload.OFFLINE,
    )
    return {(team_id, key): name for team_id, key, name in rows if name}


def group_labels(team_ids: list[int]) -> dict[int, str]:
    """The plural name of group type 0 per team, such as "organizations"."""
    labels: dict[int, str] = {}
    for team in Team.objects.filter(id__in=team_ids).only("id", "project_id"):
        labels[team.id] = DEFAULT_GROUP_LABEL
        try:
            mappings = get_group_types_for_project(team.project_id, caller_tag="error_tracking_account_reach")
        except Exception:
            logger.warning("error_tracking_account_reach_group_types_failed", team_id=team.id, exc_info=True)
            continue
        for mapping in mappings:
            if mapping.get("group_type_index") == ACCOUNT_GROUP_TYPE_INDEX:
                plural = mapping.get("name_plural") or (
                    f"{mapping['group_type']}s" if mapping.get("group_type") else None
                )
                labels[team.id] = plural or DEFAULT_GROUP_LABEL
    return labels


def account_lens_meta(
    team_ids: list[int], reach: AccountReach, issues: dict[int, list[dict[str, Any]]]
) -> dict[int, dict[str, Any]]:
    labels = group_labels(team_ids)
    return {
        team_id: {
            "window_days": WINDOW_DAYS,
            "evaluable": reach.team(team_id).evaluable,
            "group_label": labels.get(team_id, DEFAULT_GROUP_LABEL),
            "active_accounts": reach.team(team_id).active_accounts,
            "issues": issues[team_id],
        }
        for team_id in team_ids
    }
