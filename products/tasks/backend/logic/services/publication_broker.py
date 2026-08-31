from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from posthog.dataclasses import frozen


class PublicationScanError(ValueError):
    pass


_SECRET_PATTERNS = (
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bphx_[A-Za-z0-9]{20,}"),
    re.compile(r"bearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
_BINARY_SUFFIXES = frozenset(
    {".bin", ".dll", ".dylib", ".exe", ".gif", ".ico", ".jpg", ".jpeg", ".pdf", ".png", ".so", ".zip"}
)
_GENERATED_PATH_SEGMENTS = frozenset({"generated", "dist", "build", "vendor"})
_MAX_PUBLICATION_PATHS = 10_000
_MAX_PUBLICATION_PATH_LENGTH = 512
_MAX_PUBLICATION_TEXT_BYTES = 1_000_000
_MAX_PUBLICATION_ADDED_TEXT_BYTES = 8_000_000
_REGULAR_FILE_MODES = frozenset({"100644", "100755"})


@frozen
class PublicationTextFile:
    path: str
    mode: str
    object_type: str
    content: str


@frozen
class PublicationScanRequest:
    branch: str
    commit_message: str
    pr_title: str
    pr_body: str
    unified_diff: str
    changed_paths: tuple[str, ...]
    expected_added_paths: tuple[str, ...]
    added_files: tuple[PublicationTextFile, ...]


def scan_publication_text(fields: Mapping[str, str]) -> None:
    for text in fields.values():
        if (
            not isinstance(text, str)
            or "\x00" in text
            or _publication_text_byte_count(text) > _MAX_PUBLICATION_TEXT_BYTES
        ):
            raise PublicationScanError("publication contains invalid text")
        for pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                raise PublicationScanError("publication contains a registered secret pattern")


def validate_publication_paths(paths: Iterable[str]) -> None:
    count = 0
    for path in paths:
        count += 1
        if count > _MAX_PUBLICATION_PATHS:
            raise PublicationScanError("publication contains too many changed paths")
        if (
            not path
            or len(path) > _MAX_PUBLICATION_PATH_LENGTH
            or path.startswith("/")
            or "\x00" in path
            or "\\" in path
            or any(component in {"", ".", ".."} for component in path.split("/"))
        ):
            raise PublicationScanError("publication contains an invalid path")
        suffix = path.rpartition(".")[2]
        if suffix and f".{suffix.lower()}" in _BINARY_SUFFIXES:
            raise PublicationScanError("publication contains a binary file")
        if _GENERATED_PATH_SEGMENTS.intersection(path.split("/")):
            raise PublicationScanError("publication contains a generated file")


def scan_draft_publication(request: PublicationScanRequest) -> None:
    fields = {
        "branch": request.branch,
        "commit_message": request.commit_message,
        "pr_title": request.pr_title,
        "pr_body": request.pr_body,
        "unified_diff": request.unified_diff,
    }
    scan_publication_text(fields)
    validate_publication_paths(request.changed_paths)
    validate_publication_paths(request.expected_added_paths)
    changed_paths = set(request.changed_paths)
    expected_added_paths = set(request.expected_added_paths)
    if len(expected_added_paths) != len(request.expected_added_paths):
        raise PublicationScanError("publication contains duplicate canonical upsert paths")
    added_paths = tuple(file.path for file in request.added_files)
    if len(set(added_paths)) != len(added_paths):
        raise PublicationScanError("publication contains duplicate added file paths")
    if not expected_added_paths.issubset(changed_paths):
        raise PublicationScanError("publication canonical upsert paths are not changed paths")
    if set(added_paths) != expected_added_paths:
        raise PublicationScanError("publication added files do not match the canonical upsert set")
    total_added_text_bytes = 0
    for file in request.added_files:
        if file.mode not in _REGULAR_FILE_MODES or file.object_type != "blob":
            raise PublicationScanError("publication contains a non-regular text file")
        if not isinstance(file.content, str):
            raise PublicationScanError("publication contains a non-text file")
        total_added_text_bytes += _publication_text_byte_count(file.content)
        if total_added_text_bytes > _MAX_PUBLICATION_ADDED_TEXT_BYTES:
            raise PublicationScanError("publication contains too much added text")
        scan_publication_text({file.path: file.content})


def _publication_text_byte_count(text: str) -> int:
    try:
        return len(text.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise PublicationScanError("publication contains invalid text") from error
