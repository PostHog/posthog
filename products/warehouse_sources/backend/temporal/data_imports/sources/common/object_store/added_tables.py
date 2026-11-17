"""Turn the path a user gives for a new table into a location under the source's store root.

A source can read tables from anywhere under its files URL, such as a source that holds the migrated
self-managed tables of one bucket. A user adds each table by its path, relative to that root or as a
full URL into the same bucket.
"""

import re
import dataclasses
from urllib.parse import unquote

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import (
    AzureBlobConfig,
    CsvOptions,
    DiscoveryOptions,
    FileFormatChoice,
    StoreConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.discovery import (
    TableDefinition,
    explain_no_tables,
    group_tables,
    infer_file_format,
    resolve_file_format,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    ObjectStorageError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.filesystem import StoredObject
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.globs import (
    compile_clickhouse_glob,
    glob_listing_prefix,
    has_glob,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.locations import (
    KeySelection,
    StorageUrl,
    select_keys,
)

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


@frozen
class AddedLocation:
    """The keys an added table reads, relative to the store root."""

    # The folder or file to list, or "" for the whole store root.
    path: str
    # A ClickHouse glob over paths relative to the store root, or None to read every listed file.
    pattern: str | None


def is_full_url(location: str) -> bool:
    return "://" in location


def store_identity(config: StoreConfig) -> tuple[str | None, ...]:
    """The bucket a store reads, with its account. Two sources with the same identity read the same keys."""
    # A bucket name is unique per provider (per account and jurisdiction for R2), so the region is
    # left out. A URL with another region for the same bucket still names the same keys.
    if isinstance(config, AzureBlobConfig):
        return ("azure", config.account_name, config.container)
    return (str(config.provider), config.bucket, config.account_id, config.jurisdiction)


def _url_key(config: StoreConfig) -> str:
    rest = config.pattern if config.pattern is not None else config.listing_prefix
    return "/".join(part for part in (config.prefix, rest) if part)


NOT_A_FOLDER_REFUSAL = (
    "This source reads one file or the files that match a pattern, so a table can't be added to it. Change its "
    "files URL to a folder, then add the table."
)


def added_table_base(keys: KeySelection | StoreConfig) -> str | None:
    """The folder under the store root that the files URL selects, or None when it selects one file or a pattern.

    A table added by path reads only keys under this folder. The source's owner chose the files URL, so a path
    must not reach other files in the parent folder, or the whole bucket, without the key being entered again.
    """
    if keys.pattern is not None:
        return None
    if keys.listing_prefix and infer_file_format(keys.listing_prefix) is not None:
        return None
    return keys.listing_prefix


def table_root_label(container: str, *folders: str) -> str:
    """The folder that relative table paths start at, as `<bucket>/<folder>/`."""
    return "".join(f"{part}/" for part in (container, *folders) if part)


def table_root_of_url(url: StorageUrl) -> str | None:
    """The table root of a files URL, or None when no table can be added. It reads only the URL, so no network call."""
    keys = select_keys(url.key)
    base = added_table_base(keys)
    return None if base is None else table_root_label(url.bucket, keys.prefix, base)


def display_root(config: StoreConfig) -> str | None:
    base = added_table_base(config)
    return None if base is None else table_root_label(config.root_name, config.prefix, base)


def added_relative_path(source_config: StoreConfig, location: str) -> str:
    """A path the user gave relative to the source's files URL, as a path relative to the store root."""
    base = added_table_base(source_config)
    if base is None:
        raise ObjectStorageError(NOT_A_FOLDER_REFUSAL)
    return "/".join(part for part in (base, location.strip().removeprefix("/")) if part)


def relative_key(source_config: StoreConfig, url_config: StoreConfig) -> str:
    """The key a full URL names, relative to the source's store root. It must be inside the source's files URL."""
    if store_identity(url_config) != store_identity(source_config):
        raise ObjectStorageError("This path is in another bucket. Add a new source for that bucket.")
    base = added_table_base(source_config)
    if base is None:
        raise ObjectStorageError(NOT_A_FOLDER_REFUSAL)
    key = _url_key(url_config)
    root = source_config.prefix
    allowed = "/".join(part for part in (root, base) if part)
    if allowed and key != allowed and not key.startswith(f"{allowed}/"):
        raise ObjectStorageError(
            f"This path is outside {display_root(source_config)}. Change the source's files URL to a parent "
            "folder, or add a new source."
        )
    if not root:
        return key
    return "" if key == root else key[len(root) + 1 :]


def parse_added_location(relative: str, file_format: FileFormatChoice) -> AddedLocation:
    """Check a path relative to the store root, and split it into the keys to list and a glob.

    An empty path selects the whole store root.
    """
    path = relative.strip().removeprefix("/")
    if _CONTROL_CHARACTERS.search(path):
        raise ObjectStorageError("The path can't contain control characters.")
    segments = path.split("/")
    # A Delta read parses the path as a URL, which resolves an encoded `%2e%2e` folder as `..`.
    if any(segment in (".", "..") or unquote(segment) in (".", "..") for segment in segments):
        raise ObjectStorageError("The path can't contain '.' or '..' folders.")
    if "" in segments[:-1]:
        raise ObjectStorageError("The path can't contain an empty folder ('//').")
    if not has_glob(path):
        return AddedLocation(path=path.rstrip("/"), pattern=None)
    if file_format == "delta":
        raise ObjectStorageError("A Delta table path can't contain wildcards. Enter the folder of the Delta table.")
    # A glob that ends at a folder reads every file under the folders it matches, as in a files URL.
    pattern = f"{path}**" if path.endswith("/") else path
    compile_clickhouse_glob(pattern)
    return AddedLocation(path=glob_listing_prefix(pattern), pattern=pattern)


def delta_table(name: str, location: AddedLocation, file_format: FileFormatChoice) -> TableDefinition:
    return TableDefinition(
        name=name,
        kind="delta",
        path=location.path,
        scope=None,
        file_format="delta",
        csv=CsvOptions(),
        pattern=None,
        source_format=file_format,
    )


def files_table(
    objects: list[StoredObject], name: str, location: AddedLocation, options: DiscoveryOptions
) -> TableDefinition:
    """One table of every file under a folder, or of one file, defined as `resolve_table_files` finds it again at sync."""
    combined = dataclasses.replace(options, combined_table_name=name)
    for table in group_tables(
        objects,
        combined,
        root_name=name,
        pattern=location.pattern,
        listing_prefix=location.path,
        max_tables=None,
    ):
        if table.scope == "all":
            return dataclasses.replace(table, name=name)
    raise ObjectStorageError(explain_no_tables(objects, combined, location.pattern))


def glob_table(
    objects: list[StoredObject], name: str, location: AddedLocation, options: DiscoveryOptions
) -> TableDefinition:
    """One table of the files a wildcard path matches.

    The sync lists only the literal key prefix of the pattern, so a key scoped to that prefix can read the table.
    """
    pattern = location.pattern or ""
    glob = compile_clickhouse_glob(pattern)
    files = tuple(stored for stored in objects if glob.matches(stored.path))
    if not any(resolve_file_format(stored.path, options.file_format) is not None for stored in files):
        raise ObjectStorageError(explain_no_tables(objects, options, pattern))
    return TableDefinition(
        name=name,
        kind="files",
        path=location.path,
        scope="glob",
        file_format=options.file_format,
        csv=CsvOptions(
            has_header=options.file_format != "csv_no_header", allow_double_quotes=options.allow_double_quotes
        ),
        pattern=pattern,
        source_format=options.file_format,
        files=files,
    )
