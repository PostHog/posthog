"""Whether the check that a policy `attestations` entry pins has reported on a head.

The review re-run after an attestation WAIT and reviewer routing of a fully attested pull request both
poll this, so each one reads the check the way the engine does.
"""

from __future__ import annotations

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.limiter.policies import Priority

from products.stamphog.backend.logic.github_client import StamphogGitHubClient


@frozen
class PendingCheck:
    """The check name and publishing App id that a policy ``attestations`` entry pins."""

    name: str
    app_id: int

    @classmethod
    def from_entry(cls, entry: object) -> PendingCheck | None:
        """The check that a ``{"check": ..., "app_id": ...}`` entry names, or None when the entry is malformed."""
        if not isinstance(entry, dict):
            return None
        name = entry.get("check")
        app_id = entry.get("app_id")
        # `type` and not `isinstance`, because a JSON `true` would otherwise pass as App id 1.
        if not isinstance(name, str) or type(app_id) is not int:
            return None
        return cls(name=name, app_id=app_id)

    def to_entry(self) -> dict[str, object]:
        return {"check": self.name, "app_id": self.app_id}


def _has_reported(client: StamphogGitHubClient, repository: str, head_sha: str, check: PendingCheck) -> bool:
    # The engine's own test for a pending check, so the new review finds every check it waited for.
    check_runs = client.get_check_runs(
        repository, head_sha, check_name=check.name, app_id=check.app_id, priority=Priority.BATCH
    )
    return any(
        check_run.get("name") == check.name
        and (check_run.get("app") or {}).get("id") == check.app_id
        and check_run.get("status") == "completed"
        for check_run in check_runs
    )


def all_reported(client: StamphogGitHubClient, repository: str, head_sha: str, checks: list[PendingCheck]) -> bool:
    """Whether every check reported on the head. A shed or rate-limited read answers False, so the poll tries again."""
    try:
        return all(_has_reported(client, repository, head_sha, check) for check in checks)
    except (GitHubRateLimitError, GitHubEgressBudgetExhausted):
        return False
