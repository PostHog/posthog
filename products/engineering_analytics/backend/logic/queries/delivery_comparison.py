"""Curated query: an author's ready-to-merge medians next to their team's and the repository's.

The merged pull requests come from the delivery summary's own read, so all three populations share one
definition with the summary figures. The team population is the team's members' pull requests, which is
what a github_team delivery scope reads too.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import (
    UNOWNED_TEAM,
    DeliveryComparison,
    DeliveryScopeKind,
    ReadyToMergeMedians,
    TeamReadyToMergeMedians,
)
from products.engineering_analytics.backend.logic.comparison_teams import TeamChoice, choose_comparison_teams
from products.engineering_analytics.backend.logic.delivery_scope import DeliveryScope
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    UNPAGED_SCAN_LIMIT,
    run_started_floor_constant,
)
from products.engineering_analytics.backend.logic.queries.census_counts import query_census_counts
from products.engineering_analytics.backend.logic.queries.delivery_summary import (
    CI_LOOKBACK,
    MergedPRFacts,
    pull_request_ready_to_merge,
    query_ready_to_merge_facts,
    ready_to_merge_medians,
)

# The census runs daily, so a few days always find its latest run.
_CENSUS_LOOKBACK = timedelta(days=3)
# Below this many other authors who contribute a value, the median is one or two pull requests wearing a
# team's label (SPEC §2). A noise floor, not a privacy floor: the population holds one value per merged pull
# request, and each of those times already shows on its own pull request page.
MIN_OTHER_TEAM_AUTHORS = 2

# Every team the author is in, with all of its members.
_AUTHOR_TEAMS_SELECT = f"""
    SELECT team_slug, groupUniqArray(member_handle) AS members
    FROM __MEMBERS_SOURCE__ AS m
    WHERE team_slug IN (
        SELECT team_slug FROM __MEMBERS_SOURCE__ AS mine WHERE mine.member_handle = {{author}}
    )
    GROUP BY team_slug
    LIMIT {UNPAGED_SCAN_LIMIT}
"""

# Per team: the author's pull requests that asked it to review in the window.
_WINDOW_REQUESTS_SELECT = f"""
    SELECT team_slug, uniq(pr_number) AS prs
    FROM __REQUESTS_SOURCE__ AS rr
    WHERE team_slug IN {{teams}} AND requested_at >= {{date_from}} __REQUESTED_TO__
        AND pr_number IN (SELECT number FROM __PR_SOURCE__ AS pr WHERE pr.author_handle = {{author}})
    GROUP BY team_slug
    LIMIT {UNPAGED_SCAN_LIMIT}
"""

# The teams the pull request in focus asked to review, when the author wrote it. A long-lived pull request
# asked them before the window, so this read has no scan floor.
_FOCUS_REQUESTS_SELECT = f"""
    SELECT DISTINCT team_slug
    FROM __REQUESTS_SOURCE__ AS rr
    WHERE team_slug IN {{teams}} AND pr_number = {{focus_pr}}
        AND pr_number IN (
            SELECT number FROM __PR_SOURCE__ AS pr WHERE pr.number = {{focus_pr}} AND pr.author_handle = {{author}}
        )
    LIMIT {UNPAGED_SCAN_LIMIT}
"""


def _query_author_teams(curated: CuratedGitHubSource, *, author: str) -> dict[str, set[str]]:
    members_source = curated.members_source()
    if members_source is None:
        return {}
    response = curated.run(
        _AUTHOR_TEAMS_SELECT.replace("__MEMBERS_SOURCE__", members_source),
        query_type="engineering_analytics.delivery_comparison_teams",
        placeholders={"author": ast.Constant(value=author)},
    )
    return {team: set(members) for team, members in response.results or [] if team}


def _query_code_teams(curated: CuratedGitHubSource) -> set[str]:
    now = datetime.now(tz=UTC)
    census_from = now - _CENSUS_LOOKBACK
    code_teams = set(query_census_counts(curated=curated, date_from=census_from, scan_from=census_from, date_to=now))
    code_teams.discard(UNOWNED_TEAM)
    return code_teams


def _choose_teams(
    curated: CuratedGitHubSource,
    *,
    author: str,
    author_teams: set[str],
    focus_pr: int | None,
    date_from: datetime,
    date_to: datetime | None,
) -> TeamChoice:
    code_teams = _query_code_teams(curated) if author_teams else set()
    window_source = curated.team_review_requests_source(created_floor=True)
    if not author_teams or window_source is None:
        return choose_comparison_teams(
            author_teams=author_teams, code_teams=code_teams, requested_prs={}, focus_requested=set()
        )
    teams = ast.Constant(value=sorted(author_teams))
    placeholders: dict[str, ast.Expr] = {
        "author": ast.Constant(value=author),
        "teams": teams,
        "date_from": ast.Constant(value=date_from),
        "event_created_floor": run_started_floor_constant(date_from - CI_LOOKBACK),
    }
    requested_to = ""
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)
        requested_to = "AND requested_at <= {date_to}"
    window = curated.run(
        _WINDOW_REQUESTS_SELECT.replace("__REQUESTS_SOURCE__", window_source)
        .replace("__PR_SOURCE__", curated.pr_source())
        .replace("__REQUESTED_TO__", requested_to),
        query_type="engineering_analytics.delivery_comparison_requests",
        placeholders=placeholders,
    )
    focus_requested: set[str] = set()
    focus_source = curated.team_review_requests_source()
    if focus_pr is not None and focus_source is not None:
        focus = curated.run(
            _FOCUS_REQUESTS_SELECT.replace("__REQUESTS_SOURCE__", focus_source).replace(
                "__PR_SOURCE__", curated.pr_source()
            ),
            query_type="engineering_analytics.delivery_comparison_focus_requests",
            placeholders={
                "teams": teams,
                "focus_pr": ast.Constant(value=focus_pr),
                "author": ast.Constant(value=author),
            },
        )
        focus_requested = {team for (team,) in focus.results or []}
    return choose_comparison_teams(
        author_teams=author_teams,
        code_teams=code_teams,
        requested_prs={team: int(prs) for team, prs in window.results or []},
        focus_requested=focus_requested,
    )


def _team_medians(facts: list[MergedPRFacts], *, members: set[str], author: str) -> ReadyToMergeMedians | None:
    team_facts = [fact for fact in facts if fact.author in members]

    def enough_others(contributing: list[MergedPRFacts]) -> bool:
        return len({fact.author for fact in contributing} - {author}) >= MIN_OTHER_TEAM_AUTHORS

    # A pull request without an observed ready time adds nothing to the median, so it does not count.
    if not enough_others([fact for fact in team_facts if fact.ready_to_merge_seconds is not None]):
        return None
    medians = ready_to_merge_medians(team_facts)
    if enough_others([fact for fact in team_facts if fact.ready_at is not None and fact.first_approval_at is not None]):
        return medians
    return replace(
        medians,
        ready_to_first_approval_seconds=None,
        first_approval_to_merge_seconds=None,
        before_first_approval_share=None,
    )


def query_delivery_comparison(
    *,
    curated: CuratedGitHubSource,
    author: str,
    focus_pr: int | None,
    date_from: datetime,
    date_to: datetime | None,
) -> DeliveryComparison:
    author_teams = _query_author_teams(curated, author=author)
    choice = _choose_teams(
        curated,
        author=author,
        author_teams=set(author_teams),
        focus_pr=focus_pr,
        date_from=date_from,
        date_to=date_to,
    )

    scope = DeliveryScope(kind=DeliveryScopeKind.AUTHOR, author=author)
    facts = query_ready_to_merge_facts(curated, scope=scope, date_from=date_from, date_to=date_to)
    focus_fact = next((fact for fact in facts if fact.in_scope and fact.number == focus_pr), None)
    # The pull request in focus is what the baselines are compared with, so it stays out of them.
    baseline = [fact for fact in facts if fact is not focus_fact]
    return DeliveryComparison(
        author=author,
        has_membership_data=curated.members_source() is not None,
        review_data_available=curated.reviews_source() is not None,
        ready_data_available=curated.ready_to_merge_sql().observable,
        team_basis=choice.basis,
        author_medians=ready_to_merge_medians([fact for fact in baseline if fact.in_scope]),
        teams=[
            TeamReadyToMergeMedians(
                github_team=team,
                medians=_team_medians(baseline, members=author_teams[team], author=author),
            )
            for team in choice.teams
        ],
        repo_medians=ready_to_merge_medians(baseline),
        pull_request=pull_request_ready_to_merge(focus_fact) if focus_fact else None,
    )
