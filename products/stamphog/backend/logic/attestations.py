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
    app_id: int


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
        CheckAttestation(name=entry["name"], check=entry["check"], app_id=entry["app_id"])
        for key in ("attestations", "extend_attestations")
        if isinstance(listed := raw.get(key), list)
        for entry in listed
        if isinstance(entry, dict)
        and all(isinstance(entry.get(field), str) for field in ("name", "check"))
        and type(entry.get("app_id")) is int
    ]


def check_attestations_reported(
    client: StamphogGitHubClient, repo: str, head_sha: str, checks: list[CheckAttestation]
) -> bool:
    """True when the newest run of each check at ``head_sha`` from its pinned App has completed.

    This mirrors the engine's ``_check_result``. A wake that disagrees with the engine queues the
    same WAIT again, so keep both sides in step.
    """
    return all(
        _newest_run_completed(client.get_check_runs(repo, head_sha, check_name=check.check), check) for check in checks
    )


def _newest_run_completed(check_runs: list[dict], check: CheckAttestation) -> bool:
    runs = [run for run in check_runs if (run.get("app") or {}).get("id") == check.app_id]
    return bool(runs) and max(runs, key=lambda run: run.get("id") or 0).get("status") == "completed"
