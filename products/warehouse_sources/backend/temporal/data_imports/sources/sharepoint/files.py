import re
import hashlib
import posixpath
from collections import Counter
from collections.abc import Iterator
from datetime import datetime
from typing import IO, Protocol, TypedDict, cast
from urllib.parse import quote

import re2
import requests
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.file_parsing import (
    FILE_MODIFIED_AT_COLUMN,
    FILE_PATH_COLUMN,
    FORMAT_ERROR,
    FileFormatError,
    iter_file_rows,
    resolve_file_format,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.sharepoint.settings import (
    ENDPOINTS,
    FILE_EXTENSIONS,
    FILE_NOT_FOUND_ERROR,
    MAX_FILES,
    PATTERN_ERROR,
    SharePointEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sharepoint.sharepoint import (
    SharePointClient,
    _list_sites,
    _parse_datetime,
    _site_parents,
    _status,
    _walk_child_collection,
    parse_site_urls,
)


@frozen
class SharePointFile:
    drive_id: str
    item_id: str
    path: str
    size: int
    modified_at: datetime | None


@frozen
class _Folder:
    name: str
    parent_id: str | None


class _ParentReference(TypedDict, total=False):
    id: str


class _DriveItem(TypedDict, total=False):
    id: str
    name: str
    parentReference: _ParentReference
    file: dict[str, object]
    folder: dict[str, object]
    root: dict[str, object]
    deleted: dict[str, object]
    size: int
    lastModifiedDateTime: str


class CompiledPattern(Protocol):
    def search(self, string: str) -> object | None: ...


class SharePointFilePatternError(ValueError):
    pass


def compile_file_pattern(pattern: str | None) -> CompiledPattern | None:
    if not pattern:
        return None
    # RE2 bounds matching time for user-supplied patterns.
    try:
        return cast(CompiledPattern, re2.compile(pattern))
    except re2.error as error:
        raise SharePointFilePatternError(f"{PATTERN_ERROR}: {error}") from error


def _without_compression(path: str) -> str:
    return path[:-3] if path.lower().endswith(".gz") else path


def _is_supported_file(name: str) -> bool:
    return posixpath.splitext(_without_compression(name))[1].lower() in FILE_EXTENSIONS


def _in_drive_path(name: str, parent_id: str | None, folders: dict[str, _Folder]) -> str:
    segments = [name]
    seen: set[str] = set()
    while parent_id:
        if parent_id in seen or parent_id not in folders:
            return name
        seen.add(parent_id)
        folder = folders[parent_id]
        if folder.name:
            segments.append(folder.name)
        parent_id = folder.parent_id
    return "/".join(reversed(segments))


def discover_files(
    client: SharePointClient,
    site_urls: str | None,
    file_pattern: str | None,
    logger: FilteringBoundLogger,
) -> list[SharePointFile]:
    pattern = compile_file_pattern(file_pattern)
    site_paths = parse_site_urls(site_urls)
    if not site_paths:
        raise ValueError("Enter at least one site URL to import CSV file contents.")
    sites = _list_sites(client, site_paths, logger)
    files: dict[str, SharePointFile] = {}
    for site in sites:
        drives = _site_parents(client, SharePointEndpoint.DRIVE_ITEMS, quote(site["id"], safe=",.-"), logger)
        for drive in drives:
            items: dict[str, _DriveItem] = {}
            path = f"/drives/{quote(drive['id'], safe='!-_')}/root/delta"
            params = {"$select": "id,name,parentReference,file,folder,root,deleted,size,lastModifiedDateTime"}
            # Delta omits parent paths and can repeat items, so resolve paths after the final page.
            for page in _walk_child_collection(client, path, params, None, lambda _: None, logger):
                for item in page:
                    if item.get("id"):
                        item.pop("@microsoft.graph.downloadUrl", None)
                        items[item["id"]] = cast(_DriveItem, item)

            folders = {
                item_id: _Folder(
                    name="" if "root" in item else item.get("name", ""),
                    parent_id=None if "root" in item else (item.get("parentReference") or {}).get("id"),
                )
                for item_id, item in items.items()
                if ("folder" in item or "root" in item) and item.get("deleted") is None
            }
            for item_id, item in items.items():
                name = item.get("name", "")
                if item.get("deleted") is not None or item.get("file") is None or not _is_supported_file(name):
                    continue
                in_drive_path = _in_drive_path(name, (item.get("parentReference") or {}).get("id"), folders)
                file_path = f"{drive['name']}/{in_drive_path}"
                if len(sites) > 1:
                    file_path = f"{site.get('displayName') or site.get('name') or site['id']}/{file_path}"
                if pattern is not None and not pattern.search(file_path):
                    continue
                resource_id = f"{drive['id']}:{item_id}"
                files[resource_id] = SharePointFile(
                    drive_id=drive["id"],
                    item_id=item_id,
                    path=file_path,
                    size=item.get("size") or 0,
                    modified_at=_parse_datetime(item.get("lastModifiedDateTime")),
                )
                if len(files) >= MAX_FILES:
                    logger.warning("Reached the SharePoint file limit; later files are ignored", max_files=MAX_FILES)
                    return list(files.values())
    return list(files.values())


def files_by_table(files: list[SharePointFile]) -> dict[str, SharePointFile]:
    bases = [
        (
            re.sub(r"[^0-9a-zA-Z]+", "_", posixpath.splitext(_without_compression(file.path))[0]).strip("_").lower()
            or "sharepoint_data"
        )[:100]
        for file in files
    ]
    counts = Counter(bases)
    colliding = {base for base in bases if counts[base] > 1 or base in ENDPOINTS}
    suffixes = [hashlib.sha1(f"{file.drive_id}:{file.item_id}".encode()).hexdigest()[:8] for file in files]
    while True:
        names = [f"{base[:91]}_{suffix}" if base in colliding else base for base, suffix in zip(bases, suffixes)]
        name_counts = Counter(names)
        # A literal filename can also match another file's generated suffix.
        additional = {base for base, name in zip(bases, names) if name_counts[name] > 1} - colliding
        if not additional:
            return dict(zip(names, files))
        colliding.update(additional)


def _get_file_rows(
    client: SharePointClient, schema_name: str, drive_id: str, item_id: str, logger: FilteringBoundLogger
) -> Iterator[list[dict[str, object]]]:
    path = f"/drives/{quote(drive_id, safe='!-_')}/items/{quote(item_id, safe='!-_')}"
    try:
        item = cast(_DriveItem, client.get(path, params={"$select": "name,size,lastModifiedDateTime"}))
    except requests.HTTPError as error:
        if _status(error) != 404:
            raise
        raise ValueError(
            f"{FILE_NOT_FOUND_ERROR} '{schema_name}' no longer exists. "
            "It may have been deleted. Refresh the source's tables."
        ) from None

    name = item["name"]
    if not _is_supported_file(name):
        raise FileFormatError(f"{FORMAT_ERROR} '{name}'. Use a CSV or TSV file, then refresh the source's tables.")
    resolved = resolve_file_format(name)
    modified_at = _parse_datetime(item.get("lastModifiedDateTime"))
    response = client.open_stream(f"{path}/content")
    try:
        response.raw.decode_content = True
        # TextIOWrapper must be able to read EOF without urllib3 closing its underlying stream.
        response.raw.auto_close = False
        for chunk in iter_file_rows(cast(IO[bytes], response.raw), resolved, name, logger=logger):
            yield [{**row, FILE_PATH_COLUMN: name, FILE_MODIFIED_AT_COLUMN: modified_at} for row in chunk]
    finally:
        response.close()


def sharepoint_file_source(
    client: SharePointClient, schema_name: str, resource_id: str | None, logger: FilteringBoundLogger
) -> SourceResponse:
    parts = resource_id.split(":", 1) if resource_id else []
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"{FILE_NOT_FOUND_ERROR} '{schema_name}' is not identified. Refresh the source's tables.")
    drive_id, item_id = parts
    return SourceResponse(
        name=schema_name,
        items=lambda: _get_file_rows(client, schema_name, drive_id, item_id, logger),
        primary_keys=None,
        supports_resume=False,
    )
