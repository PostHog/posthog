"""Confirm that the paths an attestation check ran from are still the default branch's.

A publisher that proves a PR from default-branch files lists each path under `blobs` in its
`<!-- stamphog:v1 {...} -->` marker: a file with its blob sha, a directory (a key ending in `/`) with
its tree sha, and an absent path with null. The proof is stale once the default branch holds another
version of any of them, because the rules it checked have changed or someone re-ran an old publisher
run. The engine has no network, so the server compares the objects and records the answer on the
check run as `pinned_blobs_current`, and the engine refuses a lift without it.
"""

import re
import json

from products.stamphog.backend.logic.github_client import GitObjectId, StamphogGitHubClient

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
            budget >= 0 and 0 < len(pinned) <= _MAX_PINNED_PATHS and _pins_hold(client, repo, pinned)
        )
    return check_runs


def _pins_hold(client: StamphogGitHubClient, repo: str, pinned: dict[str, str | None]) -> bool:
    current = client.get_default_branch_objects(repo, sorted(pinned))
    return all(_pin_holds(path, sha, current.get(path)) for path, sha in pinned.items())


def _pin_holds(path: str, pinned_sha: str | None, current: GitObjectId | None) -> bool:
    """True when the default branch holds what the pin names, including its type.

    A directory pinned as a file, or a file pinned as a directory, does not hold, even when the ids
    happen to match.
    """
    if current is None:
        return pinned_sha is None
    expected_kind = "Tree" if path.endswith("/") else "Blob"
    return current.kind == expected_kind and current.oid == pinned_sha


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
