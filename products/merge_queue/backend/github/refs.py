"""Resolving git refs from GitHub (the master HEAD a trial projects onto).

Will reuse the GitHub App integration model that `products/tasks` uses (`github_integration`).
"""


def master_head(repo: str, *, integration_id: int) -> str:
    """Return the current HEAD sha of `repo`'s default branch.

    TODO: not wired yet — callers pass an explicit sha in tests and the adapter supplies it
    from the webhook in production. The real implementation resolves the default branch via the
    repo's GitHub integration (looked up team-scoped) when the CI/affected-target work lands.
    """
    raise NotImplementedError("master_head resolution lands with the GitHub adapter wiring")
