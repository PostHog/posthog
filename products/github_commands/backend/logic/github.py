"""The GitHub calls dispatch makes, through the PostHog GitHub App installation the comment came from.

Reads raise ``GitHubCallFailed`` so dispatch can fail closed. Reactions and replies are best effort:
a lost acknowledgement must not stop a command or turn a run that started into a failure.
"""

from typing import Literal, Protocol

import requests
import structlog

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models.integration import GitHubIntegration, GitHubIntegrationError, Integration

from .commands import PullRequestFacts

logger = structlog.get_logger(__name__)

Reaction = Literal["eyes", "rocket"]

_SOURCE = "github_commands"

_CALL_ERRORS = (GitHubIntegrationError, GitHubRateLimitError, requests.RequestException)


class GitHubCallFailed(Exception):
    """A read GitHub did not answer, so the caller cannot tell what the answer would have been."""


class CommandGitHub(Protocol):
    def collaborator_permission(self, repository: str, login: str, github_user_id: int) -> str: ...

    def pull_request(self, repository: str, number: int) -> PullRequestFacts | None: ...

    def react(self, repository: str, comment_id: int, reaction: Reaction) -> None: ...

    def reply(self, repository: str, number: int, body: str) -> None: ...


class InstallationGitHub:
    def __init__(self, client: GitHubIntegration) -> None:
        self._client = client

    @classmethod
    def for_installation(cls, installation_id: str) -> "InstallationGitHub | None":
        # Every row on the installation mints the same installation token, so any one will do.
        integration = Integration.objects.filter(kind="github", integration_id=installation_id).order_by("id").first()
        if integration is None:
            return None
        return cls(GitHubIntegration(integration, source=_SOURCE))

    def collaborator_permission(self, repository: str, login: str, github_user_id: int) -> str:
        try:
            return self._client.get_collaborator_permission(repository, login, expected_user_id=github_user_id)
        except _CALL_ERRORS as error:
            raise GitHubCallFailed from error

    def pull_request(self, repository: str, number: int) -> PullRequestFacts | None:
        try:
            pr = self._client.get_pull_request(repository, number)
        except _CALL_ERRORS as error:
            raise GitHubCallFailed from error
        if not pr.get("success"):
            return None
        head_repository = pr.get("head_repository")
        head_sha = pr.get("head_sha")
        head_branch = pr.get("head_branch")
        url = pr.get("url")
        if not (isinstance(head_sha, str) and isinstance(head_branch, str) and isinstance(url, str)):
            return None
        return PullRequestFacts(
            repository=repository,
            number=number,
            url=url,
            state="merged" if pr.get("merged") else str(pr.get("state") or ""),
            draft=bool(pr.get("draft")),
            head_sha=head_sha,
            head_branch=head_branch,
            # A deleted fork reports no head repository, which is no more trustworthy than a fork.
            is_fork=not isinstance(head_repository, str) or head_repository.lower() != repository.lower(),
        )

    def react(self, repository: str, comment_id: int, reaction: Reaction) -> None:
        try:
            response = self._client.api_request(
                "POST",
                f"/repos/{repository}/issues/comments/{comment_id}/reactions",
                endpoint="/repos/{owner}/{repo}/issues/comments/{comment_id}/reactions",
                json_body={"content": reaction},
            )
        except _CALL_ERRORS:
            logger.warning("github_command_reaction_failed", exc_info=True)
            return
        if response.status_code not in (200, 201):
            logger.warning("github_command_reaction_failed", status_code=response.status_code)

    def reply(self, repository: str, number: int, body: str) -> None:
        try:
            result = self._client.comment_on_pull_request(repository, number, body)
        except _CALL_ERRORS:
            logger.warning("github_command_reply_failed", exc_info=True)
            return
        if not result.get("success"):
            logger.warning("github_command_reply_failed", status_code=result.get("status_code"))
