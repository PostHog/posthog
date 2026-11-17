"""Whether the check that a policy `attestations` entry pins has reported on a head.

The review re-run after an attestation WAIT and reviewer routing of a fully attested pull request both
poll this, so each one reads the check the way the engine does.
"""

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority

from products.stamphog.backend.logic.github_client import StamphogGitHubClient


@frozen
class PendingCheck:
    """The check name and publishing App id that a policy ``attestations`` entry pins."""

    name: str
    app_id: int


def has_reported(client: StamphogGitHubClient, repository: str, head_sha: str, check: PendingCheck) -> bool:
    # The engine's own test for a pending check, so the new review finds every check it waited for.
    # GitHub filters by name and App, so a poll does not page through every check run of the head.
    check_runs = client.get_check_runs(
        repository, head_sha, check_name=check.name, app_id=check.app_id, priority=Priority.BATCH
    )
    return any(
        check_run.get("name") == check.name
        and (check_run.get("app") or {}).get("id") == check.app_id
        and check_run.get("status") == "completed"
        for check_run in check_runs
    )
