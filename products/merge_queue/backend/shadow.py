"""Shadow harness.

Shadow mode is the rollout mechanism: the engine runs its full logic against real PRs and
**records what it would do, acting on nothing**. Every queue side effect that touches the
outside world (merging a PR, posting a commit status) goes through a `ShadowGuard`.

Currently the whole engine is shadow — `ShadowGuard(github=None)` — so the engine never mutates
GitHub. The `QueueEvent` recording the decision is still emitted by the lifecycle, which is
exactly what lets us compare shadow decisions to actual human/direct-merge outcomes before
promoting a partition to live (promotion will be per-partition).
"""

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class GitHubOut(Protocol):
    """The outbound side of the GitHub adapter (merges, statuses)."""

    def merge(self, repo: str, number: int, sha: str) -> None: ...
    def set_status(self, repo: str, sha: str, *, state: str, context: str, description: str) -> None: ...


class ShadowGuard:
    """Gates outbound side effects. With `github=None` (shadow) it records and does nothing."""

    def __init__(self, github: GitHubOut | None) -> None:
        self._github = github

    @property
    def is_shadow(self) -> bool:
        return self._github is None

    def merge(self, *, repo: str, number: int, sha: str) -> None:
        if self._github is None:
            logger.info("[shadow] would merge %s#%s @ %s", repo, number, sha)
            return
        self._github.merge(repo, number, sha)

    def set_status(self, *, repo: str, sha: str, state: str, context: str, description: str = "") -> None:
        if self._github is None:
            logger.info("[shadow] would set status %s on %s@%s", state, repo, sha)
            return
        self._github.set_status(repo, sha, state=state, context=context, description=description)
