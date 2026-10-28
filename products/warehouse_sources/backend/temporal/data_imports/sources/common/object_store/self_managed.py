"""Map a self-managed warehouse table onto the object storage sources that import the same files.

A self-managed table is a URL pattern that ClickHouse reads in place with the table's own access
key. Every mapping here is exact or refused: a table this module can't map is skipped with a reason,
never imported from files that differ from the ones ClickHouse read.
"""

import re
import dataclasses
from collections.abc import Iterable, Mapping
from typing import Any, Literal
from urllib.parse import unquote, urlparse

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import normalize_column_name
from products.warehouse_sources.backend.temporal.data_imports.sources.common.file_parsing import (
    FILE_MODIFIED_AT_COLUMN,
    FILE_PATH_COLUMN,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import (
    CsvOptions,
    FileFormatChoice,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.csv_types import (
    UnsupportedCsvColumnError,
    clickhouse_base_type,
    csv_column_types_from_columns,
    stored_clickhouse_types,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.discovery import (
    TableDefinition,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    ObjectStorageError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.globs import (
    compile_clickhouse_glob,
    glob_listing_prefix,
    has_glob,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.incremental import (
    FILE_ROW_NUMBER_COLUMN,
)

StorageService = Literal["s3", "gcs", "r2", "azure"]

_S3_HOST = re.compile(r"(?:(?P<bucket>.+)\.)?s3(?:[.-](?P<endpoint>[a-z0-9.-]+?))?\.amazonaws\.com(?:\.cn)?")
_S3_ENDPOINT = re.compile(r"(?:(?:dualstack|fips)\.)?(?P<region>[a-z]{2}(?:-[a-z0-9]+)+-\d+)")
# The legacy name of the us-east-1 endpoint.
_S3_EXTERNAL_ENDPOINT = "external-1"
_S3_EXTERNAL_REGION = "us-east-1"
_GCS_HOST = "storage.googleapis.com"
_R2_HOST = re.compile(r"(?P<account>[0-9a-f]{32})\.r2\.cloudflarestorage\.com")
_AZURE_HOST = re.compile(r"(?P<account>[a-z0-9]{3,24})\.blob\.core\.windows\.net")

# ClickHouse formats a self-managed table can have, and the source format that reads the same files.
_FORMATS: dict[str, FileFormatChoice] = {
    "CSV": "csv_no_header",
    "CSVWithNames": "csv",
    "Parquet": "parquet",
    "JSONEachRow": "jsonl",
    "Delta": "delta",
    "DeltaS3Wrapper": "delta",
}
# Column types the import pipeline writes as JSON strings, which breaks queries that read their parts.
_NESTED_TYPES = frozenset({"Array", "Map", "Tuple", "Nested", "JSON", "Object", "Variant", "Dynamic"})
# Types ClickHouse reads from JSON strings, which the JSON import keeps as strings.
_JSON_TEXT_TYPES = frozenset({"Date", "Date32", "DateTime", "DateTime64"})
# Columns the import adds to every row. A stored column of the same name would lose its values to them.
_FILE_COLUMNS = frozenset({FILE_PATH_COLUMN, FILE_MODIFIED_AT_COLUMN, FILE_ROW_NUMBER_COLUMN})


class UnmappableTableError(Exception):
    """The table can't be imported from exactly the files ClickHouse reads. The message says why."""


@frozen
class SelfManagedLocation:
    """Where a self-managed table's files are, split into the parts an object storage source takes."""

    service: StorageService
    # The bucket, or the container for Azure.
    bucket: str
    # The decoded object key after the bucket. It can hold ClickHouse glob syntax.
    key: str
    # The S3 region, or None when the URL names no region.
    region: str | None = None
    # The Cloudflare account ID for R2, or the storage account name for Azure.
    account: str | None = None

    @property
    def group_key(self) -> str:
        return "/".join((self.service, self.account or self.region or "", self.bucket))


@frozen
class SelfManagedCredential:
    """A self-managed table's key pair. For Azure the access key is the storage account name."""

    access_key: str = dataclasses.field(repr=False)
    access_secret: str = dataclasses.field(repr=False)


def _s3_location(host: str, path: str) -> SelfManagedLocation:
    match = _S3_HOST.fullmatch(host)
    if match is None:
        raise UnmappableTableError(f"'{host}' isn't an S3 endpoint PostHog can import from")
    endpoint = match.group("endpoint")
    region: str | None = None
    if endpoint == _S3_EXTERNAL_ENDPOINT:
        region = _S3_EXTERNAL_REGION
    elif endpoint is not None:
        region_match = _S3_ENDPOINT.fullmatch(endpoint)
        if region_match is None:
            raise UnmappableTableError(f"'{host}' isn't an S3 API endpoint, such as a website or access point endpoint")
        region = region_match.group("region")
    if match.group("bucket") is not None:
        return SelfManagedLocation(service="s3", bucket=match.group("bucket"), key=path, region=region)
    bucket, _, key = path.partition("/")
    return SelfManagedLocation(service="s3", bucket=bucket, key=key, region=region)


def parse_self_managed_url(url: str) -> SelfManagedLocation:
    """Split a self-managed table's URL pattern into its service, bucket, account and key."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("https", "http"):
        raise UnmappableTableError("the URL isn't an http or https URL")
    if parsed.query or parsed.fragment or "?" in url or "#" in url:
        raise UnmappableTableError("the URL has a '?' or '#', which PostHog can't map to a file pattern")
    if parsed.username or parsed.password or parsed.port:
        raise UnmappableTableError("the URL names a user or a port")
    host = (parsed.hostname or "").lower()
    # Only the separator after the host goes: a further slash is part of the object key.
    path = unquote(parsed.path).removeprefix("/")
    if host.endswith(".amazonaws.com") or host.endswith(".amazonaws.com.cn"):
        location = _s3_location(host, path)
    elif host == _GCS_HOST:
        bucket, _, key = path.partition("/")
        location = SelfManagedLocation(service="gcs", bucket=bucket, key=key)
    elif host.endswith(f".{_GCS_HOST}"):
        location = SelfManagedLocation(service="gcs", bucket=host[: -len(_GCS_HOST) - 1], key=path)
    elif (r2 := _R2_HOST.fullmatch(host)) is not None:
        bucket, _, key = path.partition("/")
        location = SelfManagedLocation(service="r2", bucket=bucket, key=key, account=r2.group("account"))
    elif (azure := _AZURE_HOST.fullmatch(host)) is not None:
        container, _, key = path.partition("/")
        location = SelfManagedLocation(service="azure", bucket=container, key=key, account=azure.group("account"))
    else:
        raise UnmappableTableError(f"'{host}' isn't a storage host PostHog can import from")
    if not location.bucket or has_glob(location.bucket) or has_glob(location.account or ""):
        raise UnmappableTableError("the URL doesn't name one bucket")
    if location.key.startswith("/") or "//" in location.key:
        raise UnmappableTableError("the URL path has an empty segment, which the import can't read")
    if any(segment in (".", "..") for segment in location.key.split("/")):
        raise UnmappableTableError("the URL path has a '.' or '..' segment")
    return location


def source_format_for(table_format: str) -> FileFormatChoice:
    choice = _FORMATS.get(table_format)
    if choice is None:
        raise UnmappableTableError(f"the '{table_format}' format has no import equivalent")
    return choice


def needs_preserved_column_names(column_names: Iterable[str]) -> bool:
    """Whether the import pipeline would rename a column that existing queries refer to."""
    return any(normalize_column_name(name) != name for name in column_names)


def _refuse_nested_columns(columns: Mapping[str, Any] | None) -> None:
    for name, clickhouse_type in stored_clickhouse_types(columns).items():
        base = clickhouse_base_type(clickhouse_type)
        if base in _NESTED_TYPES:
            raise UnmappableTableError(
                f"the column '{name}' is a {base}, and the import would store it as text, not as a {base}"
            )


def _refuse_file_column_names(columns: Mapping[str, Any] | None) -> None:
    for name in (columns or {}).keys():
        if name in _FILE_COLUMNS:
            raise UnmappableTableError(
                f"the column '{name}' has the name of a column the import adds, which would replace its values"
            )


def _refuse_padded_header_names(columns: Mapping[str, Any] | None) -> None:
    # The CSV reader trims spaces around header names, so a column ClickHouse read as ' id ' would be renamed.
    for name in (columns or {}).keys():
        if name != name.strip():
            raise UnmappableTableError(
                f"the column '{name}' has spaces around its name, which the CSV import doesn't keep"
            )


def _refuse_json_text_types(columns: Mapping[str, Any] | None) -> None:
    # A JSON file holds dates and times as strings, and the JSON import keeps them as strings.
    for name, clickhouse_type in stored_clickhouse_types(columns).items():
        base = clickhouse_base_type(clickhouse_type)
        if base in _JSON_TEXT_TYPES:
            raise UnmappableTableError(
                f"the column '{name}' is a {base}, and the JSON import would store it as text, not as a {base}"
            )


def refuse_columns_an_import_changes(columns: Mapping[str, Any] | None, file_format: FileFormatChoice) -> None:
    """Refuse a file whose import would change the columns a table read in place exposes."""
    _refuse_nested_columns(columns)
    _refuse_file_column_names(columns)
    if file_format == "csv":
        _refuse_padded_header_names(columns)
    if file_format == "jsonl":
        _refuse_json_text_types(columns)


def table_definition_for(
    name: str,
    location: SelfManagedLocation,
    table_format: str,
    columns: Mapping[str, Any] | None,
    csv_allow_double_quotes: bool | None,
) -> TableDefinition:
    """The schema contract that imports exactly the files the table's URL pattern reads."""
    file_format = source_format_for(table_format)
    _refuse_nested_columns(columns)
    _refuse_file_column_names(columns)
    preserve = needs_preserved_column_names((columns or {}).keys())
    if file_format == "delta":
        path = location.key.strip("/")
        if has_glob(path):
            raise UnmappableTableError("a Delta table URL can't hold a file pattern")
        return TableDefinition(
            name=name,
            kind="delta",
            path=path,
            scope=None,
            file_format="delta",
            csv=CsvOptions(),
            pattern=None,
            source_format="delta",
            preserve_column_names=preserve,
        )
    pattern = location.key
    if not pattern or pattern.endswith("/"):
        raise UnmappableTableError("the URL names a folder, not files")
    try:
        compile_clickhouse_glob(pattern)
    except ObjectStorageError as e:
        raise UnmappableTableError(str(e)) from e
    try:
        column_types = csv_column_types_from_columns(columns) if file_format in ("csv", "csv_no_header") else ()
    except UnsupportedCsvColumnError as e:
        raise UnmappableTableError(str(e)) from e
    if file_format == "csv":
        _refuse_padded_header_names(columns)
    if file_format == "jsonl":
        _refuse_json_text_types(columns)
    return TableDefinition(
        name=name,
        kind="files",
        path=glob_listing_prefix(pattern),
        scope="glob",
        file_format=file_format,
        csv=CsvOptions(
            has_header=file_format == "csv",
            # ClickHouse reads quotes as enclosing a field unless the table turned that off.
            allow_double_quotes=csv_allow_double_quotes is not False,
            column_types=column_types,
            # ClickHouse reads an unquoted `\N` as null in a CSV file.
            null_marker=True,
            # ClickHouse reads the declared format whatever the file is called, so a `.tsv` file is still CSV.
            delimiter=",",
        ),
        pattern=pattern,
        source_format=file_format,
        preserve_column_names=preserve,
    )
