"""Which of an author's teams a delivery comparison shows.

An author can be in several GitHub teams, so membership alone does not say whose pace to compare with.
A team review request does: the repository's owner resolution asks the teams that own the changed files
to review, so the teams an author's pull requests ask most often are the teams the author works for.
"""

from posthog.dataclasses import frozen

from products.engineering_analytics.backend.facade.contracts import ComparisonTeamBasis


@frozen
class TeamChoice:
    teams: list[str]
    basis: ComparisonTeamBasis


def _most_requested(teams: list[str], requested_prs: dict[str, int]) -> list[str]:
    top = max(requested_prs.get(team, 0) for team in teams)
    return [team for team in teams if requested_prs.get(team, 0) == top]


def choose_comparison_teams(
    *, author_teams: set[str], code_teams: set[str], requested_prs: dict[str, int], focus_requested: set[str]
) -> TeamChoice:
    """Pick the teams from ``author_teams``.

    ``requested_prs`` counts, per team, the author's pull requests that asked the team to review in the
    window. ``focus_requested`` holds the teams that the pull request in focus asked, if there is one.
    ``code_teams`` holds the teams the ownership census counts. The census only sees test files, so a
    review request is evidence of owning code too.

    The members table also holds groups that own no code, such as approver groups, so the candidates
    are the author's teams with that evidence. An author with no such team keeps every team.
    """
    owning = {team for team in author_teams if team in code_teams or requested_prs.get(team) or team in focus_requested}
    ranked = sorted(owning or author_teams)
    if not ranked:
        return TeamChoice(teams=[], basis=ComparisonTeamBasis.NO_TEAM)
    if len(ranked) == 1:
        return TeamChoice(teams=ranked, basis=ComparisonTeamBasis.ONLY_TEAM)
    focus = [team for team in ranked if team in focus_requested]
    if focus:
        return TeamChoice(teams=focus, basis=ComparisonTeamBasis.PULL_REQUEST)
    requested = [team for team in ranked if requested_prs.get(team)]
    if requested:
        return TeamChoice(teams=_most_requested(requested, requested_prs), basis=ComparisonTeamBasis.REVIEW_REQUESTS)
    return TeamChoice(teams=ranked, basis=ComparisonTeamBasis.ALL_TEAMS)
