"""Lift deny categories for the files that a CI check named in the policy vouches for.

A policy `attestations` entry names a check run, the GitHub App or the default-branch workflow that
publishes it, the deny categories it may lift, and the paths it may lift them for. The engine knows nothing about what
a check proves, so a new kind of check needs a policy entry and no engine change.

The publisher embeds the files it vouched for in the check summary as a marker:

    <!-- stamphog:v1 ["path", ...] -->
    <!-- stamphog:v1 {"files": [...], "pr": N, "head_sha": "...", "merge_base": "...", "blobs": {"path": "sha"}} -->

The object form also names the PR, head and merge base it proved, and each of them must match the
review. `blobs` pins the default-branch paths the publisher ran from: a file to its blob sha, a
directory (a key ending in `/`) to its tree sha, or either to null when it was absent. When the entry
pins its publisher (`Attestation.pins_publisher`, through `publisher_files` or an `issuer`
manifest), a lift needs `blobs` to hold every required key (`Attestation.required_pins`), and the
server's confirmation that the default branch still holds every pinned object
(`pinned_blobs_current` on the check run). A proof from an older publisher, or one made before a rule
it read changed, therefore lifts nothing. An issuer entry whose manifest is missing or invalid has no
required keys and lifts nothing. The list form carries no identity, so it lifts only when the entry
does not pin its publisher and names no workflow.

A workflow entry reads only the check run that the server built from the publisher's signed result
(`WORKFLOW_PROOF_KEY`). It needs `pinned_blobs_current` even without pins of its own, because the
server checks there that the run executed the workflow file the default branch holds.

Each of these lifts nothing: a run from another App, a non-success conclusion, no marker or more
than one, a path outside the entry's `paths`, a file not in the diff.
"""

import re
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

from policy import Attestation

# The server sets this key on a check run it built from a workflow publisher's signed result, after it
# verified the token, the publishing job and the code the run executed. GitHub never sends it, so a
# check run that carries it came from the server. The backend's `workflow_proofs.py` writes the same key.
WORKFLOW_PROOF_KEY = "stamphog_workflow_proof"

_MARKER_RE = re.compile(r"<!--\s*stamphog:v1\s+(\[.*?\]|\{.*?\})\s*-->", re.DOTALL)


@dataclass(frozen=True, kw_only=True)
class ReviewedHead:
    """What stamphog is reviewing, for the object-form marker to match."""

    pr_number: int
    head_sha: str
    merge_base_sha: str


def lifted_files(
    attestations: Iterable[Attestation],
    check_runs: list[dict],
    pr_file_paths: list[str],
    reviewed: ReviewedHead,
) -> dict[str, set[str]]:
    """Each deny category with the files that a proven attestation lifts it for.

    A file is lifted for a category only by exact path, because Git paths are case-sensitive.
    """
    lifted: dict[str, set[str]] = {}
    pr_paths = set(pr_file_paths)
    for attestation in attestations:
        files = _attested_files(attestation, check_runs, pr_paths, reviewed)
        files |= _siblings(files, attestation, pr_paths)
        if not files:
            continue
        for category in attestation.lifts:
            lifted.setdefault(category, set()).update(files)
    return lifted


def pinned_files(
    attestations: Iterable[Attestation],
    check_runs: list[dict],
    pr_file_paths: list[str],
    reviewed: ReviewedHead,
) -> set[str]:
    """The files named in the proof of an attestation that pins its publisher.

    Only such a proof names this PR and head, and comes from a publisher the default branch pins.
    A `sibling_files` companion is not counted, because the publisher did not name it.
    """
    pr_paths = set(pr_file_paths)
    return set().union(
        *(
            _attested_files(attestation, check_runs, pr_paths, reviewed)
            for attestation in attestations
            if attestation.pins_publisher
        )
    )


def pending_attestations(
    attestations: Iterable[Attestation], check_runs: list[dict], pr_file_paths: list[str], pr_title: str
) -> list[Attestation]:
    """Attestations whose check has not completed for a PR that touches their paths.

    A publisher posts a result for every PR its paths and title cover, so a missing completed run
    means CI has not finished. An unusable entry is never pending, because its result could lift
    nothing.
    """
    return [
        attestation
        for attestation in attestations
        if attestation.usable
        and applies_to(attestation, pr_title)
        and any(covers(attestation, path) for path in pr_file_paths)
        and _latest_completed(check_runs, attestation) is None
    ]


def pending_check_names(pending: Iterable[Attestation]) -> str:
    """The check names for a verdict's text, backticked and joined: `A` and `B`."""
    return " and ".join(f"`{attestation.check}`" for attestation in pending)


def pending_entry(attestation: Attestation) -> dict:
    """What the server needs to poll for a pending check: its name and who may publish it."""
    if attestation.workflow:
        return {
            "check": attestation.check,
            "app_id": None,
            "name": attestation.name,
            "workflow": attestation.workflow,
            "job": attestation.job,
            "events": list(attestation.events),
        }
    return {"check": attestation.check, "app_id": attestation.app_id}


def _attested_files(
    attestation: Attestation, check_runs: list[dict], pr_paths: set[str], reviewed: ReviewedHead
) -> set[str]:
    """The files in the diff that the entry's newest completed run names, within the entry's `paths`."""
    if not attestation.usable:
        return set()
    latest = _latest_completed(check_runs, attestation)
    if latest is None or latest.get("conclusion") != "success":
        return set()
    proven = _proven_files(latest, attestation, reviewed)
    if proven is None:
        return set()
    return {path for path in proven & pr_paths if covers(attestation, path)}


def applies_to(attestation: Attestation, pr_title: str) -> bool:
    """False when the entry's publisher posts no result for a PR with this title."""
    return not attestation.title or re.search(attestation.title, pr_title) is not None


def covers(attestation: Attestation, path: str) -> bool:
    return any(re.search(pattern, path) for pattern in attestation.paths)


def _siblings(files: set[str], attestation: Attestation, pr_paths: set[str]) -> set[str]:
    """Companion files in the diff that sit beside a lifted file, such as a migration's max_migration.txt."""
    return {
        sibling
        for path in files
        for name in attestation.sibling_files
        if (sibling := str(PurePosixPath(path).parent / name)) in pr_paths
    }


def _proven_files(check_run: dict, attestation: Attestation, reviewed: ReviewedHead) -> set[str] | None:
    """The files the marker vouches for, or None when the marker does not prove this review."""
    summary = (check_run.get("output") or {}).get("summary") or ""
    markers = _MARKER_RE.findall(summary)
    if len(markers) != 1:
        return None
    try:
        payload = json.loads(markers[0])
    except json.JSONDecodeError:
        return None
    if isinstance(payload, list):
        # A workflow's signed list names no PR, so it could be posted again on any head.
        if attestation.pins_publisher or attestation.workflow:
            return None
        return _string_set(payload)
    if not isinstance(payload, dict):
        return None
    if (
        payload.get("pr") != reviewed.pr_number
        or payload.get("head_sha") != reviewed.head_sha
        or payload.get("merge_base") != reviewed.merge_base_sha
        or not reviewed.head_sha
        or not reviewed.merge_base_sha
    ):
        return None
    if attestation.pins_publisher:
        blobs = payload.get("blobs")
        required = attestation.required_pins
        if not required or not isinstance(blobs, dict) or not set(required) <= set(blobs):
            return None
    # The server sets this on a workflow's result whether or not the entry pins more, because the
    # workflow file itself must be the one the run executed and the one the default branch holds.
    if (attestation.pins_publisher or attestation.workflow) and check_run.get("pinned_blobs_current") is not True:
        return None
    return _string_set(payload.get("files"))


def _string_set(value: object) -> set[str] | None:
    if not isinstance(value, list):
        return None
    return {item for item in value if isinstance(item, str)}


def _published_by(check_run: dict, attestation: Attestation) -> bool:
    """True when the entry's own publisher made this check run.

    An App entry trusts the App GitHub names. A workflow entry trusts only a check run the server
    built from a result the publishing job signed, because any job can post a check run under any name.
    """
    if check_run.get("name") != attestation.check:
        return False
    if attestation.workflow:
        return check_run.get(WORKFLOW_PROOF_KEY) == attestation.name
    return (check_run.get("app") or {}).get("id") == attestation.app_id


def _latest_completed(check_runs: list[dict], attestation: Attestation) -> dict | None:
    """The newest completed run of the entry's check from its publisher, tolerating duplicates from re-runs."""
    completed = [cr for cr in check_runs if _published_by(cr, attestation) and cr.get("status") == "completed"]
    if not completed:
        return None
    # The publisher sets `completed_at`, so only the id, which GitHub assigns in creation order, orders runs.
    return max(completed, key=lambda cr: cr.get("id") or 0)
