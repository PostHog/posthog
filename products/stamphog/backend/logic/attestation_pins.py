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

from products.stamphog.backend.logic.attestation_policy import WORKFLOW_PROOF_KEY
from products.stamphog.backend.logic.github_client import GitObjectId, StamphogGitHubClient

_MARKER_TAG = "stamphog:v1"
_MARKER_RE = re.compile(r"<!--\s*stamphog:v1\s+(\{.*?\})\s*-->", re.DOTALL)
# A job of any PR can post a check run as this App, and the policy refuses it as a publisher, so
# its check runs are never read for pins.
_GITHUB_ACTIONS_APP_ID = 15368
# Another App's workflow can still post a check run with a marker, so both limits bound what the
# server reads. A marker over a limit is recorded as stale.
MAX_PINNED_PATHS = 64
_MAX_PINNING_CHECK_RUNS = 5


def object_marker(check_run: dict) -> tuple[str, dict] | None:
    """The check run's one object marker: its JSON exactly as the summary holds it, and the parsed object.

    The engine accepts exactly one marker. Counting the tag first keeps the pattern from scanning a
    summary of many unclosed markers once per marker.
    """
    summary = (check_run.get("output") or {}).get("summary") or ""
    if summary.count(_MARKER_TAG) != 1:
        return None
    markers = _MARKER_RE.findall(summary)
    if len(markers) != 1:
        return None
    try:
        payload = json.loads(markers[0])
    except (ValueError, RecursionError):
        # Anyone can post a marker. An integer past Python's 4300-digit limit raises a plain
        # ValueError, and deep nesting raises RecursionError. Either must read as no marker.
        return None
    return (markers[0], payload) if isinstance(payload, dict) else None


def pin_holds(path: str, pinned_sha: str | None, current: GitObjectId | None) -> bool:
    """True when the default branch holds what the pin names, including its type.

    A directory pinned as a file, or a file pinned as a directory, does not hold, even when the ids
    happen to match.
    """
    if current is None:
        return pinned_sha is None
    expected_kind = "Tree" if path.endswith("/") else "Blob"
    return current.kind == expected_kind and current.oid == pinned_sha


def _pins_hold(client: StamphogGitHubClient, repo: str, pinned: dict[str, str | None]) -> bool:
    current = client.get_default_branch_objects(repo, sorted(pinned))
    return all(pin_holds(path, sha, current.get(path)) for path, sha in pinned.items())


def _pinned_blobs(check_run: dict) -> dict[str, str | None] | None:
    """The marker's `blobs`, `{}` when they are malformed, or None for a check run that pins nothing."""
    if (check_run.get("app") or {}).get("id") == _GITHUB_ACTIONS_APP_ID:
        return None
    marker = object_marker(check_run)
    if marker is None or "blobs" not in marker[1]:
        return None
    blobs = marker[1]["blobs"]
    if not isinstance(blobs, dict) or not all(sha is None or isinstance(sha, str) for sha in blobs.values()):
        return {}
    return blobs


def check_runs_with_pins(client: StamphogGitHubClient, repo: str, check_runs: list[dict]) -> list[dict]:
    """Mark each App's check run that pins blobs with whether the pins still hold.

    A workflow publisher's verified result is skipped, because `workflow_proofs.py` already checked
    its pins against the run's own commit as well.
    """
    budget = _MAX_PINNING_CHECK_RUNS
    publishers: set[tuple[object, object]] = set()
    # The engine reads only the newest completed run of a check from its App, so an older run of
    # the same check must not spend the budget.
    for check_run in sorted(check_runs, key=lambda run: run.get("id") or 0, reverse=True):
        if WORKFLOW_PROOF_KEY in check_run:
            continue
        pinned = _pinned_blobs(check_run)
        publisher = (check_run.get("name"), (check_run.get("app") or {}).get("id"))
        if pinned is None or check_run.get("status") != "completed" or publisher in publishers:
            continue
        publishers.add(publisher)
        budget -= 1
        check_run["pinned_blobs_current"] = (
            budget >= 0 and 0 < len(pinned) <= MAX_PINNED_PATHS and _pins_hold(client, repo, pinned)
        )
    return check_runs
