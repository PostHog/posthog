"""The PostHog GitHub App's installation, for the stamphog writes that go out as ``posthog[bot]``.

Stamphog's own judgment, and the state of that judgment, goes out as the stamphog App: the approval,
its dismissal, the verdict review, the 👀, the trigger label. Branch protection counts the approval
for that App. Coordinating who looks at a pull request goes out as the PostHog App: reviewer routing's
review requests, fork labels and routing comment.
"""

from posthog.egress.limiter.policies import Priority
from posthog.integrations import IntegrationManager
from posthog.models.instance_setting import get_instance_setting
from posthog.models.integration import GitHubIntegration

from products.stamphog.backend.facade.contracts import StamphogGitHubError
from products.stamphog.backend.logic.github_client import StamphogGitHubClient

_SOURCE = "stamphog"


class PostHogAppNotInstalled(StamphogGitHubError):
    """The project has no PostHog GitHub App installation on the repository owner."""


def posthog_app_bot_login() -> str | None:
    """The login the PostHog GitHub App acts under (``<slug>[bot]``), or None when no slug is set."""
    slug = get_instance_setting("GITHUB_APP_SLUG")
    return f"{slug}[bot]" if slug else None


class PostHogAppGitHubClient(StamphogGitHubClient):
    """The stamphog client's operations, sent with the token of a project's PostHog GitHub App integration."""

    def __init__(self, integration: GitHubIntegration, installation_id: str) -> None:
        super().__init__(installation_id)
        self._integration = integration

    @classmethod
    def for_repository(cls, team_id: int, repository: str) -> "PostHogAppGitHubClient":
        """The client for the installation on ``repository``'s owner, from ``team_id``'s own integrations.

        Only the repo config's project counts, so one project's routing never writes through another
        project's installation. Raises ``PostHogAppNotInstalled`` when the project has none.
        """
        # The routing comment is found again by this login, so without it every retry posts another one.
        if posthog_app_bot_login() is None:
            raise PostHogAppNotInstalled(
                "GITHUB_APP_SLUG is not set, so the PostHog GitHub App's comments cannot be found"
            )
        owner = repository.partition("/")[0].lower()
        for record in IntegrationManager.github.oauth.list(team_id):
            account_name = str((record.config.get("account") or {}).get("name") or "")
            if record.integration_id and account_name.lower() == owner:
                integration = GitHubIntegration(record, source=_SOURCE, priority=Priority.CRITICAL)
                return cls(integration, record.integration_id)
        raise PostHogAppNotInstalled(
            f"The PostHog GitHub App is not installed on {owner} in project {team_id}, "
            "so reviewer routing cannot request reviews on its repositories."
        )

    def _get_installation_token(self, *, force_refresh: bool = False) -> str:
        if force_refresh:
            self._integration.refresh_access_token()
        return self._integration.get_access_token()
