"""Lift deny categories for the files that a CI check named in the policy vouches for.

A policy `attestations` entry names a check run, the GitHub App that publishes it, the deny
categories it may lift, and the paths it may lift them for. The engine knows nothing about what
a check proves, so a new kind of check needs a policy entry and no engine change.

The publisher embeds the files it vouched for in the check summary as a marker:

    <!-- stamphog:v1 ["path", ...] -->
    <!-- stamphog:v1 {"files": [...], "pr": N, "head_sha": "...", "merge_base": "...", "blobs": {"path": "sha"}} -->

The object form also names the PR, head and merge base it proved, and each of them must match the
review. `blobs` pins the default-branch files the publisher ran from, each to its blob sha or to null
when the file was absent. When the entry declares `publisher_files`, a lift needs `blobs` to cover
all of them, and the server's confirmation that the default branch still holds every pinned blob
(`pinned_blobs_current` on the check run). A proof from an older publisher, or one made before a rule
it read changed, therefore lifts nothing. The list form carries no identity, so it lifts only when
the entry declares no `publisher_files`.

Each of these lifts nothing: a run from another App, a non-success conclusion, no marker or more
than one, a path outside the entry's `paths`, a file not in the diff.
"""

import re
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

from policy import Attestation

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
    """The files named in the proof of an attestation that declares `publisher_files`.

    Only such a proof names this PR and head, and comes from a publisher the default branch pins.
    A `sibling_files` companion is not counted, because the publisher did not name it.
    """
    pr_paths = set(pr_file_paths)
    return set().union(
        *(
            _attested_files(attestation, check_runs, pr_paths, reviewed)
            for attestation in attestations
            if attestation.publisher_files
        )
    )


def pending_attestations(
    attestations: Iterable[Attestation], check_runs: list[dict], pr_file_paths: list[str]
) -> list[Attestation]:
    """Attestations whose check has not completed for a PR that touches their paths.

    A publisher posts a result for every PR, so a missing completed run means CI has not finished.
    """
    return [
        attestation
        for attestation in attestations
        if any(covers(attestation, path) for path in pr_file_paths)
        and _latest_completed(check_runs, attestation) is None
    ]


def pending_check_names(pending: Iterable[Attestation]) -> str:
    """The check names for a verdict's text, backticked and joined: `A` and `B`."""
    return " and ".join(f"`{attestation.check}`" for attestation in pending)


def _attested_files(
    attestation: Attestation, check_runs: list[dict], pr_paths: set[str], reviewed: ReviewedHead
) -> set[str]:
    """The files in the diff that the entry's newest completed run names, within the entry's `paths`."""
    latest = _latest_completed(check_runs, attestation)
    if latest is None or latest.get("conclusion") != "success":
        return set()
    proven = _proven_files(latest, attestation, reviewed)
    if proven is None:
        return set()
    return {path for path in proven & pr_paths if covers(attestation, path)}


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
        if attestation.publisher_files:
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
    if attestation.publisher_files:
        blobs = payload.get("blobs")
        if not isinstance(blobs, dict) or not set(attestation.publisher_files) <= set(blobs):
            return None
        if check_run.get("pinned_blobs_current") is not True:
            return None
    return _string_set(payload.get("files"))


def _string_set(value: object) -> set[str] | None:
    if not isinstance(value, list):
        return None
    return {item for item in value if isinstance(item, str)}


def _latest_completed(check_runs: list[dict], attestation: Attestation) -> dict | None:
    """The newest completed run of the entry's check from its App, tolerating duplicates from re-runs."""
    completed = [
        cr
        for cr in check_runs
        if cr.get("name") == attestation.check
        and (cr.get("app") or {}).get("id") == attestation.app_id
        and cr.get("status") == "completed"
    ]
    if not completed:
        return None
    # The publisher sets `completed_at`, so only the id, which GitHub assigns in creation order, orders runs.
    return max(completed, key=lambda cr: cr.get("id") or 0)
