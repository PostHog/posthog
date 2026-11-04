"""Whether the check attestations a WAIT waits on have reported, for the poll that wakes it."""

from posthog.dataclasses import frozen

from .github_client import StamphogGitHubClient
from .repo_policy import policy_list


@frozen
class CheckAttestation:
    name: str
    check: str
    app_id: int


def check_attestations(policy_text: str | None) -> list[CheckAttestation]:
    """The check attestations a repository's default-branch policy declares."""
    return [
        CheckAttestation(name=entry["name"], check=entry["check"], app_id=entry["app_id"])
        for entry in policy_list(policy_text, "attestations")
        if all(isinstance(entry.get(key), str) for key in ("name", "check")) and type(entry.get("app_id")) is int
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
