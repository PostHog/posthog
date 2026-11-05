"""Read the check attestations that the repository's policy trusts, for the poll that wakes a WAIT.

An attestation is a CI check that lifts named deny categories for the files it lists (the engine's
``attestations.py`` holds the model). The engine reads it from the head commit's check runs, and
this module answers the one question the server asks between reviews: has it reported yet?
"""

import yaml

from posthog.dataclasses import frozen

from .github_client import StamphogGitHubClient


@frozen
class CheckAttestation:
    name: str
    check: str
    app: str


def check_attestations(policy_text: str | None) -> list[CheckAttestation]:
    """The check attestations a repository's default-branch policy declares."""
    # The engine validates the whole policy and fails the review on a malformed one, so an entry
    # this cannot read is skipped here rather than reported twice.
    try:
        raw = yaml.safe_load(policy_text or "")
    except yaml.YAMLError:
        return []
    if not isinstance(raw, dict):
        return []
    return [
        CheckAttestation(name=entry["name"], check=entry["check"], app=entry["app"])
        for key in ("attestations", "extend_attestations")
        if isinstance(listed := raw.get(key), list)
        for entry in listed
        if isinstance(entry, dict) and all(isinstance(entry.get(field), str) for field in ("name", "check", "app"))
    ]


def check_attestations_reported(
    client: StamphogGitHubClient, repo: str, head_sha: str, checks: list[CheckAttestation]
) -> bool:
    """True when each check has a completed run at ``head_sha`` from its pinned App.

    This mirrors the engine's ``_check_result``, which reads only the pinned App's check. A wake that
    disagrees with the engine queues the same WAIT again, so keep both sides in step.
    """
    return all(
        any(
            run.get("status") == "completed" and (run.get("app") or {}).get("slug") == check.app
            for run in client.get_check_runs(repo, head_sha, check_name=check.check)
        )
        for check in checks
    )
