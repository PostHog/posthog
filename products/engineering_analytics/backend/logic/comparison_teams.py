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

    ``code_teams`` holds the teams that own code, from the ownership census. The members table also
    holds groups that own none, such as approver groups, so only code teams are candidates. Without a
    census, ``code_teams`` is empty and every team stays a candidate.
    ``requested_prs`` counts, per team, the author's pull requests in the window that asked the team to
    review. ``focus_requested`` holds the teams that the pull request in focus asked, if there is one.
    """
    ranked = sorted(team for team in author_teams if not code_teams or team in code_teams)
    if not ranked:
        return TeamChoice(teams=[], basis=ComparisonTeamBasis.NO_TEAM)
    if len(ranked) == 1:
        return TeamChoice(teams=ranked, basis=ComparisonTeamBasis.ONLY_TEAM)
    focus = [team for team in ranked if team in focus_requested]
    if focus:
        return TeamChoice(teams=_most_requested(focus, requested_prs), basis=ComparisonTeamBasis.PULL_REQUEST)
    requested = [team for team in ranked if requested_prs.get(team)]
    if requested:
        return TeamChoice(teams=_most_requested(requested, requested_prs), basis=ComparisonTeamBasis.REVIEW_REQUESTS)
    return TeamChoice(teams=ranked, basis=ComparisonTeamBasis.ALL_TEAMS)
