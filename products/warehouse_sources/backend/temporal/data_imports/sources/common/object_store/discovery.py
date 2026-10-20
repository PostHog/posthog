import re
import fnmatch
import posixpath
import dataclasses
from collections.abc import Iterable, Mapping
from typing import Any, Literal, cast, get_args

from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import (
    CsvOptions,
    DiscoveryOptions,
    FileFormat,
    FileFormatChoice,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    NO_TABLE_FILES_ERROR,
    TOO_MANY_FILES_ERROR,
    ObjectStorageError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.filesystem import (
    ObjectStore,
    StoredObject,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.settings import (
    MAX_TABLE_OBJECTS,
    MAX_TABLES,
)

TableKind = Literal["files", "delta"]
# Which files a `files` table reads: one file, a folder and its hive partitions, or every file.
FileScope = Literal["file", "folder", "all"]

DELTA_LOG_DIRECTORY = "_delta_log"
COMPRESSED_SUFFIX = ".gz"

EXTENSION_FORMATS: dict[str, FileFormat] = {
    ".csv": "csv",
    ".tsv": "csv",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    # Exports that land in buckets (Firehose, Spark, ClickHouse JSONEachRow) write one object per line
    # under a .json name, so .json files are read as JSON Lines.
    ".json": "jsonl",
    ".parquet": "parquet",
}

_FILE_FORMAT_CHOICES: frozenset[str] = frozenset(get_args(FileFormatChoice))


@frozen
class TableDefinition:
    name: str
    kind: TableKind
    # Relative to the store root. For a `file` scope it is the file itself.
    path: str
    scope: FileScope | None
    # "delta" for a Delta table. For files: the format the files are read with, or "infer" when one
    # combined table mixes formats and each file is read by its extension.
    file_format: FileFormatChoice
    csv: CsvOptions
    pattern: str | None
    # The source's configured format at discovery, replayed at sync so the same files group together.
    source_format: FileFormatChoice
    files: tuple[StoredObject, ...] = ()

    def same_location(self, other: "TableDefinition") -> bool:
        return (
            self.kind == other.kind
            and self.scope == other.scope
            and self.path == other.path
            and self.file_format == other.file_format
        )

    def schema_metadata(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "scope": self.scope,
            "path": self.path,
            "pattern": self.pattern,
            "format": self.file_format,
            "source_format": self.source_format,
            "csv": {"has_header": self.csv.has_header, "allow_double_quotes": self.csv.allow_double_quotes},
        }

    @classmethod
    def from_schema_metadata(cls, name: str, metadata: Mapping[str, Any] | None) -> "TableDefinition | None":
        """Rebuild a table from what `schema_metadata` persisted, or None when the keys are missing."""
        if not metadata:
            return None
        kind = metadata.get("kind")
        scope = metadata.get("scope")
        path = metadata.get("path")
        file_format = metadata.get("format")
        source_format = metadata.get("source_format", file_format)
        pattern = metadata.get("pattern")
        csv = metadata.get("csv") or {}
        if (
            kind not in ("files", "delta")
            or (kind == "files" and scope not in ("file", "folder", "all"))
            or not isinstance(path, str)
            or file_format not in _FILE_FORMAT_CHOICES
            or source_format not in _FILE_FORMAT_CHOICES
            or not (pattern is None or isinstance(pattern, str))
            or not isinstance(csv, dict)
        ):
            return None
        return cls(
            name=name,
            kind=cast(TableKind, kind),
            path=path,
            scope=cast(FileScope, scope) if kind == "files" else None,
            file_format=cast(FileFormatChoice, file_format),
            csv=CsvOptions(
                has_header=bool(csv.get("has_header", True)),
                allow_double_quotes=bool(csv.get("allow_double_quotes", True)),
            ),
            pattern=pattern,
            source_format=cast(FileFormatChoice, source_format),
        )


def sanitize_table_name(name: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()


def _strip_compression(path: str) -> str:
    return path[: -len(COMPRESSED_SUFFIX)] if path.lower().endswith(COMPRESSED_SUFFIX) else path


def is_compressed(path: str) -> bool:
    return path.lower().endswith(COMPRESSED_SUFFIX)


def infer_file_format(path: str) -> FileFormat | None:
    extension = posixpath.splitext(_strip_compression(path).lower())[1]
    return EXTENSION_FORMATS.get(extension)


def resolve_file_format(path: str, choice: FileFormatChoice) -> FileFormat | None:
    """The format one file is read with, or None when `infer` can't tell from its extension."""
    if choice in ("csv", "csv_no_header"):
        return "csv"
    if choice in ("jsonl", "parquet"):
        return cast(FileFormat, choice)
    return infer_file_format(path)


def _table_format(path: str, choice: FileFormatChoice) -> FileFormatChoice | None:
    if choice == "infer":
        return infer_file_format(path)
    return choice


def _is_hidden(segments: Iterable[str]) -> bool:
    # `_SUCCESS`, `_committed_*`, `.crc` and `_temporary/` are Spark and Hadoop bookkeeping, not data.
    return any(segment.startswith(("_", ".")) for segment in segments)


def _delta_roots(objects: Iterable[StoredObject]) -> list[str]:
    roots: set[str] = set()
    for stored in objects:
        segments = stored.path.split("/")
        if DELTA_LOG_DIRECTORY in segments[:-1]:
            root_segments = segments[: segments.index(DELTA_LOG_DIRECTORY)]
            if not _is_hidden(root_segments):
                roots.add("/".join(root_segments))
    return sorted(roots)


def _is_under(path: str, roots: frozenset[str]) -> bool:
    if not roots:
        return False
    if "" in roots:
        return True
    segments = path.split("/")[:-1]
    return any("/".join(segments[:depth]) in roots for depth in range(1, len(segments) + 1))


def _table_folder(path: str) -> str | None:
    """The folder a file's table is named after, or None for a file directly under the root.

    Hive partition folders (`year=2024/month=01`) belong to the table above them, so the folder ends
    at the first `key=value` segment.
    """
    directories = path.split("/")[:-1]
    if not directories:
        return None
    folder: list[str] = []
    for directory in directories:
        if "=" in directory:
            break
        folder.append(directory)
    return "/".join(folder)


def _format_suffix(file_format: FileFormatChoice) -> str:
    return "csv" if file_format == "csv_no_header" else file_format


def group_tables(
    objects: Iterable[StoredObject],
    options: DiscoveryOptions,
    root_name: str,
    logger: FilteringBoundLogger | None = None,
    max_tables: int | None = MAX_TABLES,
) -> list[TableDefinition]:
    """Turn a bucket listing into tables.

    - A folder holding `_delta_log/` is one Delta table, and none of its files are offered again.
    - Other files group by their folder, with hive partition folders folded into the table above.
    - A file directly under the root is a table of its own.
    - `combined_table_name` puts every file into one table.

    The same listing and options always give the same tables, which is what lets a sync find its
    table again from `schema_metadata`.
    """
    ordered = sorted(objects, key=lambda stored: stored.path)
    delta_roots = frozenset(_delta_roots(ordered))
    choice = options.file_format
    pattern = options.file_pattern or None
    combined_name = (options.combined_table_name or "").strip() or None

    def definition(
        name: str,
        kind: TableKind,
        path: str,
        scope: FileScope | None,
        file_format: FileFormatChoice,
        files: list[StoredObject],
    ) -> TableDefinition:
        return TableDefinition(
            name=name,
            kind=kind,
            path=path,
            scope=scope,
            file_format=file_format,
            csv=CsvOptions(has_header=file_format != "csv_no_header", allow_double_quotes=options.allow_double_quotes),
            pattern=pattern,
            source_format=choice,
            files=tuple(files),
        )

    candidates: list[TableDefinition] = []
    if choice in ("infer", "delta"):
        for root in sorted(delta_roots):
            candidates.append(definition(root.replace("/", "_") or root_name, "delta", root, None, "delta", []))

    if choice != "delta":
        data_files: list[tuple[StoredObject, FileFormatChoice]] = []
        for stored in ordered:
            segments = stored.path.split("/")
            if not segments[-1] or _is_hidden(segments) or _is_under(stored.path, delta_roots):
                continue
            if pattern is not None and not fnmatch.fnmatchcase(stored.path, pattern):
                continue
            file_format = _table_format(stored.path, choice)
            if file_format is not None:
                data_files.append((stored, file_format))

        if combined_name is not None:
            if data_files:
                formats = {file_format for _, file_format in data_files}
                combined_format = formats.pop() if len(formats) == 1 else "infer"
                candidates.append(
                    definition(combined_name, "files", "", "all", combined_format, [f for f, _ in data_files])
                )
        else:
            folders: dict[tuple[str, FileFormatChoice], list[StoredObject]] = {}
            for stored, file_format in data_files:
                folder = _table_folder(stored.path)
                if folder is None:
                    stem = posixpath.splitext(_strip_compression(stored.path))[0]
                    candidates.append(definition(stem, "files", stored.path, "file", file_format, [stored]))
                else:
                    folders.setdefault((folder, file_format), []).append(stored)
            formats_per_folder: dict[str, int] = {}
            for folder, _ in folders:
                formats_per_folder[folder] = formats_per_folder.get(folder, 0) + 1
            for (folder, file_format), files in folders.items():
                base = folder.replace("/", "_") or root_name
                name = f"{base}_{_format_suffix(file_format)}" if formats_per_folder[folder] > 1 else base
                candidates.append(definition(name, "files", folder, "folder", file_format, files))

    tables: list[TableDefinition] = []
    taken: set[str] = set()
    next_suffix: dict[str, int] = {}
    for candidate in candidates:
        base = sanitize_table_name(candidate.name) or "data"
        name = base
        suffix = next_suffix.get(base, 2)
        while name in taken:
            name = f"{base}_{suffix}"
            suffix += 1
        next_suffix[base] = suffix
        taken.add(name)
        tables.append(dataclasses.replace(candidate, name=name))

    if max_tables is not None and len(tables) > max_tables:
        if logger is not None:
            logger.warning("Reached the object storage table limit; later tables are ignored", max_tables=max_tables)
        tables = tables[:max_tables]
    return tables


def resolve_table_files(
    store: ObjectStore,
    table: TableDefinition,
    max_objects: int = MAX_TABLE_OBJECTS,
    logger: FilteringBoundLogger | None = None,
) -> TableDefinition:
    """List a `files` table's folder again and return the table with the files it holds now.

    The listing runs through `group_tables` with the options the table was discovered with, so a
    subfolder that is a table of its own, or a file another format claims, stays out.
    """
    if table.kind != "files":
        return table
    listing_prefix = "" if table.scope == "all" else table.path
    objects = store.list_objects(listing_prefix, max_objects + 1)
    if len(objects) > max_objects:
        raise ObjectStorageError(
            f"{TOO_MANY_FILES_ERROR} ({max_objects:,} files) in '{listing_prefix or '/'}'. Point the source at a "
            "narrower folder, or set a file pattern that matches fewer files."
        )
    options = DiscoveryOptions(
        file_format=table.source_format,
        file_pattern=table.pattern,
        allow_double_quotes=table.csv.allow_double_quotes,
        combined_table_name=table.name if table.scope == "all" else None,
    )
    for candidate in group_tables(objects, options, root_name=table.name, logger=logger, max_tables=None):
        # A combined table keeps its identity when a new file changes which formats it mixes.
        if candidate.same_location(table) or (table.scope == "all" and candidate.scope == "all"):
            return dataclasses.replace(candidate, name=table.name)
    raise ObjectStorageError(
        f"{NO_TABLE_FILES_ERROR} '{table.name}'. The files it was discovered from may have been renamed, moved, "
        "or removed from the bucket."
    )
