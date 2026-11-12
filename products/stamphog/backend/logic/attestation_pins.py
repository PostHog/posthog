"""Confirm that the files an attestation check ran from are still the default branch's.

A publisher that proves a PR from default-branch files lists the blob sha of each one under `blobs`
in its `<!-- stamphog:v1 {...} -->` marker. The proof is stale once the default branch holds another
version of any of them, because the rules it checked have changed or someone re-ran an old publisher
run. The engine has no network, so the server compares the blobs and records the answer on the check
run as `pinned_blobs_current`, and the engine refuses a lift without it.
"""

import re
import json

from products.stamphog.backend.logic.github_client import StamphogGitHubClient

_MARKER_TAG = "stamphog:v1"
_MARKER_RE = re.compile(r"<!--\s*stamphog:v1\s+(\{.*?\})\s*-->", re.DOTALL)
# A job of any PR can post a check run as this App, and the policy refuses it as a publisher, so
# its check runs are never read for pins.
_GITHUB_ACTIONS_APP_ID = 15368
# Another App's workflow can still post a check run with a marker, so both limits bound what the
# server reads. A marker over a limit is recorded as stale.
_MAX_PINNED_PATHS = 64
_MAX_PINNING_CHECK_RUNS = 5


def get_check_runs_with_pins(client: StamphogGitHubClient, repo: str, head_sha: str) -> list[dict]:
    """The head's check runs, each one that pins blobs marked with whether the pins still hold."""
    check_runs = client.get_check_runs(repo, head_sha)
    budget = _MAX_PINNING_CHECK_RUNS
    publishers: set[tuple[object, object]] = set()
    # The engine reads only the newest completed run of a check from its App, so an older run of
    # the same check must not spend the budget.
    for check_run in sorted(check_runs, key=lambda run: run.get("id") or 0, reverse=True):
        pinned = _pinned_blobs(check_run)
        publisher = (check_run.get("name"), (check_run.get("app") or {}).get("id"))
        if pinned is None or check_run.get("status") != "completed" or publisher in publishers:
            continue
        publishers.add(publisher)
        budget -= 1
        check_run["pinned_blobs_current"] = (
            budget >= 0
            and 0 < len(pinned) <= _MAX_PINNED_PATHS
            and client.get_default_branch_blob_shas(repo, sorted(pinned)) == pinned
        )
    return check_runs


def _pinned_blobs(check_run: dict) -> dict[str, str | None] | None:
    """The marker's `blobs`, `{}` when they are malformed, or None for a check run that pins nothing."""
    if (check_run.get("app") or {}).get("id") == _GITHUB_ACTIONS_APP_ID:
        return None
    summary = (check_run.get("output") or {}).get("summary") or ""
    # The engine accepts exactly one marker. Counting the tag first keeps the pattern from scanning
    # a summary of many unclosed markers once per marker.
    if summary.count(_MARKER_TAG) != 1:
        return None
    markers = _MARKER_RE.findall(summary)
    if len(markers) != 1:
        return None
    try:
        payload = json.loads(markers[0])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or "blobs" not in payload:
        return None
    blobs = payload["blobs"]
    if not isinstance(blobs, dict) or not all(sha is None or isinstance(sha, str) for sha in blobs.values()):
        return {}
    return blobs
