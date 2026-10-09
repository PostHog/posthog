import re
import hashlib
import tempfile
import posixpath
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from typing import IO, Protocol, TypedDict, cast
from urllib.parse import quote

import re2
import requests
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.excel_parsing import (
    MAX_EXCEL_FILE_BYTES,
    ExcelFileError,
    iter_worksheet_rows,
    list_worksheets,
)
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
    EXCEL_EXTENSIONS,
    FILE_EXTENSIONS,
    FILE_NOT_FOUND_ERROR,
    MAX_EXCEL_FILES,
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
    worksheet: str | None = None

    @property
    def is_excel(self) -> bool:
        return posixpath.splitext(self.path)[1].lower() in EXCEL_EXTENSIONS

    @property
    def resource_id(self) -> str:
        resource_id = f"{self.drive_id}:{self.item_id}"
        return f"{resource_id}:{self.worksheet}" if self.worksheet is not None else resource_id

    @property
    def label(self) -> str:
        return f"{self.path} [{self.worksheet}]" if self.worksheet is not None else self.path

    @property
    def description(self) -> str:
        if self.worksheet is not None:
            return f"Rows of the worksheet {self.worksheet} in the Excel file {self.path}"
        return f"Rows of the CSV file {self.path}"


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
    return (
        posixpath.splitext(_without_compression(name))[1].lower() in FILE_EXTENSIONS
        or posixpath.splitext(name)[1].lower() in EXCEL_EXTENSIONS
    )


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
        raise ValueError("Enter at least one site URL to import file contents.")
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


def _item_path(drive_id: str, item_id: str) -> str:
    return f"/drives/{quote(drive_id, safe='!-_')}/items/{quote(item_id, safe='!-_')}"


@contextmanager
def _download_excel(client: SharePointClient, path: str, file_name: str, size: int) -> Iterator[IO[bytes]]:
    def check_size(size: int) -> None:
        if size > MAX_EXCEL_FILE_BYTES:
            raise ExcelFileError(f"'{file_name}' exceeds the 100 MB size limit. Split the workbook into smaller files.")

    check_size(size)
    temporary = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    try:
        response = client.open_stream(f"{path}/content")
        try:
            response.raw.decode_content = True
            copied = 0
            while block := response.raw.read(min(1024 * 1024, MAX_EXCEL_FILE_BYTES - copied + 1)):
                copied += len(block)
                check_size(copied)
                temporary.write(block)
        finally:
            response.close()
        temporary.seek(0)
        yield cast(IO[bytes], temporary)
    finally:
        temporary.close()


def expand_worksheets(
    client: SharePointClient, files: list[SharePointFile], logger: FilteringBoundLogger
) -> list[SharePointFile]:
    excel_count = sum(file.is_excel for file in files)
    if excel_count > MAX_EXCEL_FILES:
        logger.warning(
            "Reached the SharePoint Excel file limit; later workbooks are ignored",
            max_excel_files=MAX_EXCEL_FILES,
            skipped_files=excel_count - MAX_EXCEL_FILES,
        )
    expanded: list[SharePointFile] = []
    examined = 0
    for file in files:
        if not file.is_excel:
            expanded.append(file)
            continue
        examined += 1
        if examined > MAX_EXCEL_FILES:
            continue
        try:
            with _download_excel(client, _item_path(file.drive_id, file.item_id), file.path, file.size) as stream:
                worksheets = list_worksheets(stream, file.path)
            expanded.extend(replace(file, worksheet=title) for title in worksheets)
        except ExcelFileError as error:
            logger.warning("Skipping unreadable SharePoint workbook", path=file.path, reason=str(error))
        except requests.HTTPError as error:
            if _status(error) != 404:
                raise
            logger.warning("Skipping missing SharePoint workbook", path=file.path)
    return expanded


def _table_base(file: SharePointFile, limit: int) -> str:
    path = posixpath.splitext(_without_compression(file.path))[0]
    base = re.sub(r"[^0-9a-zA-Z]+", "_", path).strip("_").lower() or "sharepoint_data"
    if file.worksheet is None:
        return base[:limit]
    worksheet = re.sub(r"[^0-9a-zA-Z]+", "_", file.worksheet).strip("_").lower() or "worksheet"
    worksheet = worksheet[: limit - 2]
    return f"{base[: limit - len(worksheet) - 1]}_{worksheet}"


def files_by_table(files: list[SharePointFile]) -> dict[str, SharePointFile]:
    bases = [_table_base(file, 100) for file in files]
    counts = Counter(bases)
    colliding = {base for base in bases if counts[base] > 1 or base in ENDPOINTS}
    suffixes = [hashlib.sha256(file.resource_id.encode()).hexdigest()[:8] for file in files]
    while True:
        names = [
            f"{_table_base(file, 91)}_{suffix}" if base in colliding else base
            for file, base, suffix in zip(files, bases, suffixes)
        ]
        name_counts = Counter(names)
        # A literal filename can also match another file's generated suffix.
        additional = {base for base, name in zip(bases, names) if name_counts[name] > 1} - colliding
        if not additional:
            return dict(zip(names, files))
        colliding.update(additional)


def discover_file_tables(
    client: SharePointClient,
    site_urls: str | None,
    file_pattern: str | None,
    logger: FilteringBoundLogger,
) -> dict[str, SharePointFile]:
    files = discover_files(client, site_urls, file_pattern, logger)
    return files_by_table(expand_worksheets(client, files, logger))


def _get_file_rows(
    client: SharePointClient,
    schema_name: str,
    drive_id: str,
    item_id: str,
    logger: FilteringBoundLogger,
    worksheet: str | None = None,
) -> Iterator[list[dict[str, object]]]:
    path = _item_path(drive_id, item_id)
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
    modified_at = _parse_datetime(item.get("lastModifiedDateTime"))
    if worksheet is not None:
        if posixpath.splitext(name)[1].lower() not in EXCEL_EXTENSIONS:
            raise ExcelFileError(f"'{name}'. Save it as .xlsx again, then refresh the source's tables.")
        with _download_excel(client, path, name, item.get("size") or 0) as stream:
            for chunk in iter_worksheet_rows(stream, name, worksheet, logger=logger):
                yield [{**row, FILE_PATH_COLUMN: name, FILE_MODIFIED_AT_COLUMN: modified_at} for row in chunk]
        return
    if posixpath.splitext(_without_compression(name))[1].lower() not in FILE_EXTENSIONS:
        raise FileFormatError(
            f"{FORMAT_ERROR} '{name}'. Use a CSV, TSV, or XLSX file, then refresh the source's tables."
        )
    resolved = resolve_file_format(name)
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
    parts = resource_id.split(":", 2) if resource_id else []
    if len(parts) not in (2, 3) or not all(parts):
        raise ValueError(f"{FILE_NOT_FOUND_ERROR} '{schema_name}' is not identified. Refresh the source's tables.")
    drive_id, item_id = parts[:2]
    worksheet = parts[2] if len(parts) == 3 else None
    return SourceResponse(
        name=schema_name,
        items=lambda: _get_file_rows(client, schema_name, drive_id, item_id, logger, worksheet),
        primary_keys=None,
        supports_resume=False,
    )
