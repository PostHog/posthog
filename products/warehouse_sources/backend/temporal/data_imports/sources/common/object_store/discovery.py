import re
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.csv_types import (
    csv_column_types_from_metadata,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.globs import (
    ClickHouseGlob,
    compile_clickhouse_glob,
    glob_key_prefix,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.settings import (
    MAX_TABLE_OBJECTS,
    MAX_TABLES,
)

TableKind = Literal["files", "delta"]
# Which files a `files` table reads: one file, a folder and its hive partitions, every file, or the
# files a ClickHouse-style glob in `pattern` matches. Discovery never makes a `glob` table: it keeps
# the file set of a table that ClickHouse read from a URL pattern before it was imported.
FileScope = Literal["file", "folder", "all", "glob"]
_FILE_SCOPES: frozenset[str] = frozenset(get_args(FileScope))

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
_HIVE_PARTITION_FOLDER = re.compile(r"[^.=][^=]*=.*")


@frozen
class TableDefinition:
    name: str
    kind: TableKind
    # Relative to the store root. For a `file` scope it is the file itself. For an `all` scope it is the
    # folder or file the source lists, or "" for the whole store root.
    path: str
    scope: FileScope | None
    # "delta" for a Delta table. For files: the format the files are read with, or "infer" when one
    # combined table mixes formats and each file is read by its extension.
    file_format: FileFormatChoice
    csv: CsvOptions
    # A ClickHouse glob over paths relative to the store root, from the source's files URL.
    pattern: str | None
    # The source's configured format at discovery, replayed at sync so the same files group together.
    source_format: FileFormatChoice
    files: tuple[StoredObject, ...] = ()
    # Keep the column names as the files write them, so queries written against them keep working.
    preserve_column_names: bool = False

    def same_location(self, other: "TableDefinition") -> bool:
        return (
            self.kind == other.kind
            and self.scope == other.scope
            and self.path == other.path
            and self.file_format == other.file_format
        )

    def schema_metadata(self) -> dict[str, Any]:
        csv: dict[str, Any] = {"has_header": self.csv.has_header, "allow_double_quotes": self.csv.allow_double_quotes}
        if self.csv.column_types:
            csv["column_types"] = {column.name: column.to_metadata() for column in self.csv.column_types}
        if self.csv.null_marker:
            csv["null_marker"] = True
        if self.csv.delimiter is not None:
            csv["delimiter"] = self.csv.delimiter
        metadata: dict[str, Any] = {
            "kind": self.kind,
            "scope": self.scope,
            "path": self.path,
            "pattern": self.pattern,
            "format": self.file_format,
            "source_format": self.source_format,
            "csv": csv,
        }
        if self.preserve_column_names:
            metadata["preserve_column_names"] = True
        return metadata

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
        delimiter = csv.get("delimiter") if isinstance(csv, dict) else None
        if (
            kind not in ("files", "delta")
            or (kind == "files" and scope not in _FILE_SCOPES)
            or (kind == "files" and scope == "glob" and not isinstance(pattern, str))
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
                column_types=csv_column_types_from_metadata(csv.get("column_types")),
                null_marker=csv.get("null_marker") is True,
                delimiter=delimiter if isinstance(delimiter, str) and len(delimiter) == 1 else None,
            ),
            pattern=pattern,
            source_format=cast(FileFormatChoice, source_format),
            preserve_column_names=metadata.get("preserve_column_names") is True,
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


def _is_hidden_name(segment: str) -> bool:
    # `_SUCCESS`, `_committed_*`, `.crc` and `_temporary/` are Spark and Hadoop bookkeeping, not data.
    return segment.startswith(("_", "."))


def _is_hidden_directory(segment: str) -> bool:
    # A hive partition folder such as `_ph_partition_key=2026-w36` holds data, even when its key starts with `_`.
    return _is_hidden_name(segment) and _HIVE_PARTITION_FOLDER.fullmatch(segment) is None


def _is_hidden(path: str) -> bool:
    *directories, file_name = path.split("/")
    return _is_hidden_name(file_name) or any(_is_hidden_directory(directory) for directory in directories)


def _delta_roots(objects: Iterable[StoredObject]) -> list[str]:
    roots: set[str] = set()
    for stored in objects:
        segments = stored.path.split("/")
        if DELTA_LOG_DIRECTORY in segments[:-1]:
            root_segments = segments[: segments.index(DELTA_LOG_DIRECTORY)]
            if not any(_is_hidden_directory(segment) for segment in root_segments):
                roots.add("/".join(root_segments))
    return sorted(roots)


def _is_under(path: str, roots: frozenset[str]) -> bool:
    if not roots:
        return False
    if "" in roots:
        return True
    segments = path.split("/")[:-1]
    return any("/".join(segments[:depth]) in roots for depth in range(1, len(segments) + 1))


def _roots_with_matching_file(objects: Iterable[StoredObject], roots: frozenset[str], glob: ClickHouseGlob) -> set[str]:
    """The roots that hold at least one file the glob matches, found in one pass over the listing."""
    matched: set[str] = set()
    if not roots:
        return matched
    for stored in objects:
        if not glob.matches(stored.path):
            continue
        if "" in roots:
            matched.add("")
        segments = stored.path.split("/")[:-1]
        for depth in range(1, len(segments) + 1):
            folder = "/".join(segments[:depth])
            if folder in roots:
                matched.add(folder)
        if matched == roots:
            break
    return matched


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
    pattern: str | None = None,
    listing_prefix: str = "",
    logger: FilteringBoundLogger | None = None,
    max_tables: int | None = MAX_TABLES,
) -> list[TableDefinition]:
    """Turn a bucket listing into tables.

    - A folder holding `_delta_log/` is one Delta table, and none of its files are offered again.
    - Other files group by their folder, with hive partition folders folded into the table above.
    - A file directly under the root is a table of its own.
    - `combined_table_name` puts every file into one table.
    - `pattern` keeps only the data files it matches, and only the Delta tables it matches a file of.

    The same listing and options always give the same tables, which is what lets a sync find its
    table again from `schema_metadata`.
    """
    ordered = sorted(objects, key=lambda stored: stored.path)
    delta_roots = frozenset(_delta_roots(ordered))
    choice = options.file_format
    glob = compile_clickhouse_glob(pattern) if pattern else None
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
        offered_roots = sorted(delta_roots if glob is None else _roots_with_matching_file(ordered, delta_roots, glob))
        for root in offered_roots:
            candidates.append(definition(root.replace("/", "_") or root_name, "delta", root, None, "delta", []))

    if choice != "delta":
        data_files: list[tuple[StoredObject, FileFormatChoice]] = []
        for stored in ordered:
            segments = stored.path.split("/")
            if not segments[-1] or _is_hidden(stored.path) or _is_under(stored.path, delta_roots):
                continue
            if glob is not None and not glob.matches(stored.path):
                continue
            file_format = _table_format(stored.path, choice)
            if file_format is not None:
                data_files.append((stored, file_format))

        if combined_name is not None:
            if data_files:
                formats = {file_format for _, file_format in data_files}
                combined_format = formats.pop() if len(formats) == 1 else "infer"
                candidates.append(
                    definition(
                        combined_name, "files", listing_prefix, "all", combined_format, [f for f, _ in data_files]
                    )
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
    if table.scope == "glob":
        listing_prefix = glob_key_prefix(table.pattern or "")
        objects = store.list_key_prefix(listing_prefix, max_objects + 1)
    else:
        listing_prefix = table.path
        objects = store.list_objects(listing_prefix, max_objects + 1)
    if len(objects) > max_objects:
        raise ObjectStorageError(
            f"{TOO_MANY_FILES_ERROR} ({max_objects:,} files) in '{listing_prefix or '/'}'. Point the URL at a "
            "narrower folder, or use a pattern that matches fewer files."
        )
    if table.scope == "glob":
        return _resolve_glob_files(objects, table)
    options = DiscoveryOptions(
        file_format=table.source_format,
        allow_double_quotes=table.csv.allow_double_quotes,
        combined_table_name=table.name if table.scope == "all" else None,
    )
    for candidate in group_tables(
        objects,
        options,
        root_name=table.name,
        pattern=table.pattern,
        listing_prefix=table.path if table.scope == "all" else "",
        logger=logger,
        max_tables=None,
    ):
        # A combined table keeps its identity when a new file changes which formats it mixes.
        if candidate.same_location(table) or (table.scope == "all" and candidate.scope == "all"):
            return dataclasses.replace(candidate, name=table.name)
    raise ObjectStorageError(
        f"{NO_TABLE_FILES_ERROR} '{table.name}'. The files it was discovered from may have been renamed, moved, "
        "or removed from the bucket."
    )


def _resolve_glob_files(objects: list[StoredObject], table: TableDefinition) -> TableDefinition:
    """Every listed file the table's glob matches, with no other filter.

    Hidden files, Delta folders and file extensions are not checked, because the files ClickHouse
    read for the same pattern were not filtered either.
    """
    glob = compile_clickhouse_glob(table.pattern or "")
    files = tuple(stored for stored in objects if glob.matches(stored.path))
    if not files:
        raise ObjectStorageError(
            f"{NO_TABLE_FILES_ERROR} '{table.name}'. No file in the bucket matches '{table.pattern}'."
        )
    return dataclasses.replace(table, files=files)
