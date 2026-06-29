"""Resolving git refs from GitHub (the master HEAD a trial projects onto).

Reuses the GitHub App integration model that `products/tasks` uses (`github_integration`).
"""

from posthog.models.integration import GitHubIntegration, Integration


def master_head(repo: str, *, integration_id: int) -> str:
    """Return the current HEAD sha of `repo`'s default branch.

    TODO: the integration lookup is wired but the default-branch resolution and any
    caching belong with the CI/affected-target work; for now callers pass an explicit sha in
    tests and the adapter supplies it from the webhook in production.
    """
    integration = Integration.objects.get(id=integration_id)
    gh = GitHubIntegration(integration)
    if gh.access_token_expired():
        gh.refresh_access_token()
    raise NotImplementedError("master_head resolution lands with the GitHub adapter wiring")
