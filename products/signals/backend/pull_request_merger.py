from __future__ import annotations

from posthog.dataclasses import frozen


@frozen
class PullRequestMerger:
    """The GitHub account that merged a pull request."""

    login: str
    github_id: int | None = None

    @classmethod
    def from_github(cls, account: object) -> PullRequestMerger | None:
        """Read the `merged_by` object of a GitHub pull request, from a webhook payload or the REST API."""
        if not isinstance(account, dict):
            return None
        login = account.get("login")
        if not isinstance(login, str) or not login:
            return None
        github_id = account.get("id")
        return cls(login=login, github_id=github_id if isinstance(github_id, int) else None)
