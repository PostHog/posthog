from typing import Literal

from posthog.dataclasses import frozen
from posthog.egress.github.transport import github_request, raise_if_github_rate_limited
from posthog.egress.limiter.policies import Priority
from posthog.models.integration.github import GitHubIntegration

_SOURCE = "reaperhog"
_TIMEOUT = 30.0


@frozen
class PullRequestState:
    number: int
    state: Literal["open", "merged", "closed"]


def parse_pr_number(pr_url: str) -> int | None:
    tail = pr_url.rstrip("/").rsplit("/pull/", 1)
    if len(tail) != 2 or not tail[1].isdigit():
        return None
    return int(tail[1])


def pull_request_state(*, team_id: int, repository: str, number: int) -> PullRequestState:
    github = GitHubIntegration.first_for_team_repository(team_id, repository)
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
