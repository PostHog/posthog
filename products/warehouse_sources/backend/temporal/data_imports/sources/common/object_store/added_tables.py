"""Turn the path a user gives for a new table into a location under the source's store root.

A source can read tables from anywhere under its files URL, such as a source that holds the migrated
self-managed tables of one bucket. A user adds each table by its path, relative to that root or as a
full URL into the same bucket.
"""

import re
import dataclasses

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import (
    AzureBlobConfig,
    CsvOptions,
    DiscoveryOptions,
    FileFormatChoice,
    StoreConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.discovery import (
    DELTA_LOG_DIRECTORY,
    TableDefinition,
    explain_no_tables,
    group_tables,
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


def _store_identity(config: StoreConfig) -> tuple[str | None, ...]:
    # A bucket name is unique per provider (per account and jurisdiction for R2), so the region is
    # left out. A URL with another region for the same bucket still names the same keys.
    if isinstance(config, AzureBlobConfig):
        return ("azure", config.account_name, config.container)
    return (str(config.provider), config.bucket, config.account_id, config.jurisdiction)


def _url_key(config: StoreConfig) -> str:
    rest = config.pattern if config.pattern is not None else config.listing_prefix
    return "/".join(part for part in (config.prefix, rest) if part)


def table_root_label(container: str, prefix: str) -> str:
    """The folder that relative table paths start at, as `<bucket>/<prefix>/`."""
    return "".join(f"{part}/" for part in (container, prefix) if part)


def table_root_of_url(url: StorageUrl) -> str:
    """The table root of a files URL. It reads only the URL, so it makes no network call."""
    return table_root_label(url.bucket, select_keys(url.key).prefix)


def display_root(config: StoreConfig) -> str:
    return table_root_label(config.root_name, config.prefix)


def relative_key(source_config: StoreConfig, url_config: StoreConfig) -> str:
    """The key a full URL names, relative to the source's store root."""
    if _store_identity(url_config) != _store_identity(source_config):
        raise ObjectStorageError("This path is in another bucket. Add a new source for that bucket.")
    key = _url_key(url_config)
    root = source_config.prefix
    if not root:
        return key
    if key == root:
        return ""
    if not key.startswith(f"{root}/"):
        raise ObjectStorageError(
            f"This path is outside {display_root(source_config)}. Change the source's files URL to a parent "
            "folder, or add a new source."
        )
    return key[len(root) + 1 :]


def parse_added_location(relative: str, file_format: FileFormatChoice) -> AddedLocation:
    """Check a path relative to the store root, and split it into the keys to list and a glob.

    An empty path selects the whole store root.
    """
    path = relative.strip().removeprefix("/")
    if _CONTROL_CHARACTERS.search(path):
        raise ObjectStorageError("The path can't contain control characters.")
    segments = path.split("/")
    if any(segment in (".", "..") for segment in segments):
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


def holds_delta_log(objects: list[StoredObject], location: AddedLocation) -> bool:
    """Whether the listed folder is itself a Delta table."""
    if location.pattern is not None:
        return False
    log_prefix = f"{location.path}/{DELTA_LOG_DIRECTORY}/" if location.path else f"{DELTA_LOG_DIRECTORY}/"
    return any(stored.path.startswith(log_prefix) for stored in objects)


def files_table(
    objects: list[StoredObject], name: str, location: AddedLocation, options: DiscoveryOptions
) -> TableDefinition:
    """One table of every file the location selects, defined as `resolve_table_files` finds it again at sync."""
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
