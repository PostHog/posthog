import json
import base64
import binascii
from collections.abc import Mapping

from posthog.dataclasses import frozen

from ..settings import DEFAULT_DOCS_PATHS, WriterSettings

WRITER_CHANGE_ARTIFACT_NAME = "writer-change.json"
MAX_WRITER_CHANGE_BYTES = 30 * 1024 * 1024
MAX_PATH_BYTES = 255
COMPANION_PATHS = frozenset({"vercel.json", "src/navs/index.js"})


def docs_folders_of(writer: WriterSettings, docs_content_root: object) -> tuple[str, ...]:
    if writer.docs_paths:
        return writer.docs_paths
    content_root = docs_content_root.strip("/") if isinstance(docs_content_root, str) else ""
    return (content_root or DEFAULT_DOCS_PATHS.strip("/"),)


@frozen
class WriterChange:
    written: Mapping[str, bytes]
    deleted: frozenset[str]

    @property
    def paths(self) -> frozenset[str]:
        return frozenset(self.written) | self.deleted


class WriterChangeRefused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def writer_change_artifact(artifacts: list) -> dict | None:
    candidates = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, dict)
        and artifact.get("name") == WRITER_CHANGE_ARTIFACT_NAME
        and artifact.get("type") == "output"
        and artifact.get("source") == "agent_output"
        and isinstance(artifact.get("storage_path"), str)
        and not artifact.get("dismissed_at")
    ]
    return max(candidates, key=lambda artifact: str(artifact.get("uploaded_at", "")), default=None)


def parse_writer_change(raw: bytes) -> WriterChange:
    if len(raw) > MAX_WRITER_CHANGE_BYTES:
        raise WriterChangeRefused("change_too_large")
    try:
        manifest = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as error:
        raise WriterChangeRefused("manifest_unreadable") from error
    written_entries = manifest.get("written") if isinstance(manifest, dict) else None
    deleted_entries = manifest.get("deleted") if isinstance(manifest, dict) else None
    if not isinstance(written_entries, dict) or not isinstance(deleted_entries, list):
        raise WriterChangeRefused("manifest_unreadable")
    if not all(isinstance(path, str) for path in deleted_entries):
        raise WriterChangeRefused("manifest_unreadable")
    all_paths = [*written_entries, *deleted_entries]
    if any(is_unsafe_path(path) for path in all_paths) or has_colliding_paths(all_paths):
        raise WriterChangeRefused("unsafe_path")
    written = {path: decoded_content(content) for path, content in written_entries.items()}
    return WriterChange(written=written, deleted=frozenset(deleted_entries))


def decoded_content(content: object) -> bytes:
    if not isinstance(content, str):
        raise WriterChangeRefused("manifest_unreadable")
    try:
        return base64.b64decode(content, validate=True)
    except (binascii.Error, ValueError) as error:
        raise WriterChangeRefused("manifest_unreadable") from error


def is_unsafe_path(path: str) -> bool:
    try:
        encoded_path = path.encode("utf-8")
    except UnicodeEncodeError:
        return True
    if not path or path.startswith("/") or len(encoded_path) > MAX_PATH_BYTES:
        return True
    if "\\" in path or any(ord(character) < 0x20 or ord(character) == 0x7F for character in path):
        return True
    return any(segment in ("", ".", "..") or segment.lower() == ".git" for segment in path.split("/"))


def has_colliding_paths(paths: list[str]) -> bool:
    return len({path.casefold() for path in paths}) != len(paths)
