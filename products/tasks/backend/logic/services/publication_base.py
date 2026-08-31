"""Read and verify the protected GitHub base needed to validate a publication bundle."""

from __future__ import annotations

import re
import json
import base64
import hashlib
import unicodedata
from typing import Literal

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority

from products.tasks.backend.logic.services.publication_transport import GitHubPublicationClient

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_MODE_RE = re.compile(r"^[0-7]{6}$")
_GENERATED_PARTS = frozenset({"node_modules", "__pycache__", "dist", "build", ".next", ".git"})
_GENERATED_SUFFIXES = (".pyc", ".pyo", ".so", ".a", ".o", ".class", ".dll", ".dylib", ".exe", ".min.js")
_SAFE_CHANGED_MODES = frozenset({"100644", "100755"})


class PublicationBaseError(ValueError):
    """The protected GitHub base cannot safely validate a publication bundle."""


@frozen
class PublicationBaseLimits:
    max_tree_entries: int = 20_000
    max_tree_response_bytes: int = 4 * 1024 * 1024
    max_total_tree_entries: int = 20_000
    max_total_tree_response_bytes: int = 4 * 1024 * 1024
    max_changed_paths: int = 200
    max_path_bytes: int = 240
    max_blob_bytes: int = 512 * 1024
    max_total_blob_bytes: int = 2 * 1024 * 1024

    def __post_init__(self) -> None:
        if any(
            value <= 0
            for value in (
                self.max_tree_entries,
                self.max_tree_response_bytes,
                self.max_total_tree_entries,
                self.max_total_tree_response_bytes,
                self.max_changed_paths,
                self.max_path_bytes,
                self.max_blob_bytes,
                self.max_total_blob_bytes,
            )
        ):
            raise ValueError("publication base limits must be positive")


_DEFAULT_LIMITS = PublicationBaseLimits()


@frozen
class TrustedBaseTreeEntry:
    path: str
    mode: str
    object_type: Literal["blob", "tree", "commit"]
    object_sha: str


@frozen
class TrustedBaseTextBlob:
    path: str
    object_sha: str
    text: str


@frozen
class TrustedBaseManifest:
    repository: str
    base_sha: str
    tree_sha: str
    entries: tuple[TrustedBaseTreeEntry, ...]
    old_text_blobs: tuple[TrustedBaseTextBlob, ...]

    def entry_for(self, path: str) -> TrustedBaseTreeEntry | None:
        return next((entry for entry in self.entries if entry.path == path), None)

    def old_text_for(self, path: str) -> str | None:
        blob = next((item for item in self.old_text_blobs if item.path == path), None)
        return blob.text if blob is not None else None


def load_trusted_base_manifest(
    client: GitHubPublicationClient,
    *,
    repository: str,
    base_sha: str,
    changed_paths: tuple[str, ...],
    limits: PublicationBaseLimits = _DEFAULT_LIMITS,
) -> TrustedBaseManifest:
    """Fetch the protected base and only trusted old text for requested changed paths."""
    _validate_repository(repository)
    _validate_sha(base_sha, "base_sha")
    paths = _validate_changed_paths(changed_paths, limits)

    tree_sha = _read_protected_tree_sha(client, repository, base_sha)
    entries = _read_path_entries(client, repository, tree_sha, paths, limits)
    entries_by_path = {entry.path: entry for entry in entries}
    old_text_blobs = _read_changed_text_blobs(client, repository, paths, entries_by_path, limits)
    return TrustedBaseManifest(
        repository=repository,
        base_sha=base_sha,
        tree_sha=tree_sha,
        entries=entries,
        old_text_blobs=old_text_blobs,
    )


def _request(
    client: GitHubPublicationClient,
    path: str,
    *,
    endpoint: str,
    params: dict[str, str | int] | None = None,
) -> object:
    response = client.api_request(
        "GET",
        path,
        endpoint=endpoint,
        params=params,
        priority=Priority.CRITICAL,
        retry_transient=False,
    )
    if response.status_code != 200:
        raise PublicationBaseError(f"GitHub rejected protected base read ({response.status_code})")
    return response.json()


def _read_protected_tree_sha(client: GitHubPublicationClient, repository: str, base_sha: str) -> str:
    payload = _request(
        client,
        f"/repos/{repository}/git/commits/{base_sha}",
        endpoint="/repos/{owner}/{repo}/git/commits/{commit_sha}",
    )
    tree = payload.get("tree") if isinstance(payload, dict) else None
    tree_sha = tree.get("sha") if isinstance(tree, dict) else None
    if not isinstance(payload, dict) or payload.get("sha") != base_sha or not isinstance(tree_sha, str):
        raise PublicationBaseError("GitHub returned a mismatched protected base commit")
    _validate_sha(tree_sha, "base tree SHA")
    return tree_sha


def _read_path_entries(
    client: GitHubPublicationClient,
    repository: str,
    root_tree_sha: str,
    paths: tuple[str, ...],
    limits: PublicationBaseLimits,
) -> tuple[TrustedBaseTreeEntry, ...]:
    """Read only changed paths and their trusted parent topology from GitHub trees."""
    cache: dict[str, dict[str, TrustedBaseTreeEntry]] = {}
    selected: dict[str, TrustedBaseTreeEntry] = {}
    total_entries = 0
    total_response_bytes = 0

    def read_tree(tree_sha: str) -> dict[str, TrustedBaseTreeEntry]:
        nonlocal total_entries, total_response_bytes
        cached = cache.get(tree_sha)
        if cached is not None:
            return cached
        payload = _request(
            client,
            f"/repos/{repository}/git/trees/{tree_sha}",
            endpoint="/repos/{owner}/{repo}/git/trees/{tree_sha}",
        )
        response_bytes = _response_size(payload)
        if response_bytes > limits.max_tree_response_bytes:
            raise PublicationBaseError("GitHub protected base tree response exceeds the byte limit")
        raw_entries = payload.get("tree") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get("sha") != tree_sha
            or payload.get("truncated") is not False
            or not isinstance(raw_entries, list)
            or len(raw_entries) > limits.max_tree_entries
        ):
            raise PublicationBaseError("GitHub returned an incomplete or oversized protected base tree")
        total_entries += len(raw_entries)
        total_response_bytes += response_bytes
        if total_entries > limits.max_total_tree_entries or total_response_bytes > limits.max_total_tree_response_bytes:
            raise PublicationBaseError("GitHub protected base tree walk exceeds the aggregate limit")

        entries: dict[str, TrustedBaseTreeEntry] = {}
        for raw_entry in raw_entries:
            entry = _parse_tree_entry(raw_entry, limits)
            if "/" in entry.path or entry.path in entries:
                raise PublicationBaseError("GitHub returned malformed or duplicate protected base tree paths")
            entries[entry.path] = entry
        cache[tree_sha] = entries
        return entries

    read_tree(root_tree_sha)
    for path in paths:
        tree_sha = root_tree_sha
        prefix: list[str] = []
        parts = path.split("/")
        for index, part in enumerate(parts):
            entry = read_tree(tree_sha).get(part)
            prefix.append(part)
            if entry is None:
                break
            selected["/".join(prefix)] = TrustedBaseTreeEntry(
                path="/".join(prefix),
                mode=entry.mode,
                object_type=entry.object_type,
                object_sha=entry.object_sha,
            )
            if index == len(parts) - 1:
                break
            if entry.object_type != "tree" or entry.mode != "040000":
                raise PublicationBaseError("changed path is below a protected special Git entry")
            tree_sha = entry.object_sha

    return tuple(sorted(selected.values(), key=lambda entry: entry.path))


def _parse_tree_entry(value: object, limits: PublicationBaseLimits) -> TrustedBaseTreeEntry:
    if not isinstance(value, dict):
        raise PublicationBaseError("GitHub returned a malformed protected base tree entry")
    path = value.get("path")
    mode = value.get("mode")
    object_type = value.get("type")
    object_sha = value.get("sha")
    if not isinstance(path, str) or not isinstance(mode, str) or not isinstance(object_sha, str):
        raise PublicationBaseError("GitHub returned a malformed protected base tree entry")
    if object_type == "blob":
        trusted_type: Literal["blob", "tree", "commit"] = "blob"
    elif object_type == "tree":
        trusted_type = "tree"
    elif object_type == "commit":
        trusted_type = "commit"
    else:
        raise PublicationBaseError("GitHub returned a malformed protected base tree entry")
    _validate_path(path, limits, generated_allowed=True)
    if not _MODE_RE.fullmatch(mode):
        raise PublicationBaseError("GitHub returned a malformed protected base tree mode")
    if (
        (trusted_type == "blob" and mode not in {"100644", "100755", "120000"})
        or (trusted_type == "tree" and mode != "040000")
        or (trusted_type == "commit" and mode != "160000")
    ):
        raise PublicationBaseError("GitHub returned an inconsistent protected base tree entry")
    _validate_sha(object_sha, "protected base object SHA")
    return TrustedBaseTreeEntry(path=path, mode=mode, object_type=trusted_type, object_sha=object_sha)


def _read_changed_text_blobs(
    client: GitHubPublicationClient,
    repository: str,
    paths: tuple[str, ...],
    entries_by_path: dict[str, TrustedBaseTreeEntry],
    limits: PublicationBaseLimits,
) -> tuple[TrustedBaseTextBlob, ...]:
    blobs: list[TrustedBaseTextBlob] = []
    total_bytes = 0
    for path in paths:
        entry = entries_by_path.get(path)
        if entry is None:
            continue
        _validate_changed_target(entry)
        content = _read_blob(client, repository, entry.object_sha, limits)
        total_bytes += len(content)
        if total_bytes > limits.max_total_blob_bytes:
            raise PublicationBaseError("protected base text exceeds the total byte limit")
        if b"\0" in content:
            raise PublicationBaseError("protected base changed target is binary")
        try:
            text = content.decode("utf-8", "strict")
        except UnicodeDecodeError as error:
            raise PublicationBaseError("protected base changed target is not UTF-8") from error
        blobs.append(TrustedBaseTextBlob(path=path, object_sha=entry.object_sha, text=text))
    return tuple(blobs)


def _validate_changed_target(entry: TrustedBaseTreeEntry) -> None:
    _validate_path(entry.path, None, generated_allowed=False)
    if entry.object_type != "blob" or entry.mode not in _SAFE_CHANGED_MODES:
        raise PublicationBaseError("protected base changed target has a special Git mode")


def _read_blob(
    client: GitHubPublicationClient, repository: str, expected_sha: str, limits: PublicationBaseLimits
) -> bytes:
    payload = _request(
        client,
        f"/repos/{repository}/git/blobs/{expected_sha}",
        endpoint="/repos/{owner}/{repo}/git/blobs/{file_sha}",
    )
    if (
        not isinstance(payload, dict)
        or payload.get("sha") != expected_sha
        or payload.get("encoding") != "base64"
        or not isinstance(payload.get("content"), str)
    ):
        raise PublicationBaseError("GitHub returned a mismatched protected base blob")
    content = _decode_base64_blob(payload["content"], limits.max_blob_bytes)
    # Git object IDs use SHA-1 by protocol, not for authentication.
    actual_sha = hashlib.sha1(  # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
        b"blob " + str(len(content)).encode("ascii") + b"\0" + content
    ).hexdigest()
    if actual_sha != expected_sha:
        raise PublicationBaseError("GitHub protected base blob did not match its Git object SHA")
    return content


def _decode_base64_blob(encoded: str, maximum: int) -> bytes:
    normalized = encoded.replace("\n", "").replace("\r", "")
    if not re.fullmatch(r"(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?", normalized):
        raise PublicationBaseError("GitHub returned malformed protected base blob encoding")
    if len(normalized) > 4 * ((maximum + 2) // 3):
        raise PublicationBaseError("protected base blob exceeds the byte limit")
    try:
        content = base64.b64decode(normalized, validate=True)
    except ValueError as error:
        raise PublicationBaseError("GitHub returned malformed protected base blob encoding") from error
    if len(content) > maximum:
        raise PublicationBaseError("protected base blob exceeds the byte limit")
    return content


def _validate_repository(repository: str) -> None:
    if not _REPOSITORY_RE.fullmatch(repository):
        raise PublicationBaseError("repository must be an exact owner/name value")


def _validate_sha(value: str, name: str) -> None:
    if not _SHA_RE.fullmatch(value):
        raise PublicationBaseError(f"{name} must be a full lowercase SHA")


def _validate_changed_paths(paths: tuple[str, ...], limits: PublicationBaseLimits) -> tuple[str, ...]:
    if len(paths) > limits.max_changed_paths:
        raise PublicationBaseError("too many changed paths")
    seen_paths: set[str] = set()
    for path in paths:
        _validate_path(path, limits, generated_allowed=False)
        if path in seen_paths:
            raise PublicationBaseError("duplicate changed path")
        seen_paths.add(path)
    return tuple(sorted(paths))


def _validate_path(path: str, limits: PublicationBaseLimits | None, *, generated_allowed: bool) -> None:
    if unicodedata.normalize("NFC", path) != path:
        raise PublicationBaseError("GitHub path is not canonical Unicode")
    try:
        encoded = path.encode("utf-8", "strict")
    except UnicodeEncodeError as error:
        raise PublicationBaseError("GitHub path is not valid UTF-8") from error
    parts = path.split("/")
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or "\0" in path
        or any(part in {"", ".", ".."} for part in parts)
        or ".git" in parts
        or (
            not generated_allowed
            and (any(part in _GENERATED_PARTS for part in parts) or path.endswith(_GENERATED_SUFFIXES))
        )
    ):
        raise PublicationBaseError("GitHub path is not safe for publication")
    if limits is not None and len(encoded) > limits.max_path_bytes:
        raise PublicationBaseError("GitHub path exceeds the byte limit")


def _response_size(payload: object) -> int:
    try:
        return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, UnicodeEncodeError) as error:
        raise PublicationBaseError("GitHub returned a malformed protected base tree") from error
