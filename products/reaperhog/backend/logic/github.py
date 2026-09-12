import re
from typing import Literal

from posthog.dataclasses import frozen
from posthog.egress.github.transport import github_request, raise_if_github_rate_limited
from posthog.egress.limiter.policies import Priority
from posthog.models.integration.github import GitHubIntegration

_SOURCE = "reaperhog"
_TIMEOUT = 30.0
_PR_URL = re.compile(r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)/?$")
# ReaperCluster.pr_number is an IntegerField, and Django does not validate on save, so a larger number
# would reach Postgres and raise in the middle of the sync loop.
_MAX_PR_NUMBER = 2**31 - 1


@frozen
class PullRequestState:
    number: int
    state: Literal["open", "merged", "closed"]


def parse_pull_request_url(pr_url: str, repository: str) -> int | None:
    """The pull request number, but only when the URL points at ``repository`` itself.

    A run can report a pull request in another repository. Polling that number against
    ``repository`` reads an unrelated pull request and can bury or decline the wrong cluster.
    """
    match = _PR_URL.match(pr_url.strip())
    if match is None:
        return None
    owner, _, repo = repository.partition("/")
    if (match["owner"].lower(), match["repo"].lower()) != (owner.lower(), repo.lower()):
        return None
    number = int(match["number"])
    return number if 0 < number <= _MAX_PR_NUMBER else None


def pull_request_state(*, team_id: int, repository: str, number: int) -> PullRequestState:
    github = GitHubIntegration.first_for_team_repository(team_id, repository, source=_SOURCE, priority=Priority.BATCH)
    if github is None:
        raise RuntimeError(f"No GitHub App installation on team {team_id} can access {repository}")
    owner, _, repo = repository.partition("/")
    response = github_request(
        "GET",
        f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}",
        source=_SOURCE,
        headers={"Authorization": f"Bearer {github.get_access_token()}"},
        installation_id=github.github_installation_id,
        priority=Priority.BATCH,
        endpoint="/repos/{owner}/{repo}/pulls/{pull_number}",
        timeout=_TIMEOUT,
    )
    raise_if_github_rate_limited(response)
    if not response.ok:
        raise RuntimeError(f"GitHub returned {response.status_code} for {repository}#{number}")
    data = response.json()
    if data.get("merged"):
        return PullRequestState(number=number, state="merged")
    return PullRequestState(number=number, state="closed" if data.get("state") == "closed" else "open")
