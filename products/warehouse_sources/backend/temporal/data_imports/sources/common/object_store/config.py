import re
import dataclasses
from enum import StrEnum
from typing import Literal, get_args

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    INVALID_CONFIG_ERROR,
    ObjectStorageError,
)

FileFormatChoice = Literal["infer", "csv", "csv_no_header", "jsonl", "parquet", "delta"]
# The format one file is read with. A CSV file's header choice lives in `CsvOptions`.
FileFormat = Literal["csv", "jsonl", "parquet"]

# S3 bucket naming rules: 3-63 characters of lowercase letters, digits, dots and hyphens. Holding
# the bucket to this keeps it from injecting a host or a path into the URLs built from it.
_BUCKET_NAME = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]")
_REGION_NAME = re.compile(r"[a-z]{2}(-[a-z0-9]+)+-\d+")


class ObjectStoreProvider(StrEnum):
    S3 = "s3"


@frozen
class ObjectStoreConfig:
    """Where a bucket lives and the credentials to read it.

    `endpoint_url` stays `None` for AWS S3. S3-compatible stores that take HMAC keys (GCS, R2) set it.
    """

    provider: ObjectStoreProvider
    bucket: str
    region: str
    access_key_id: str = dataclasses.field(repr=False)
    secret_access_key: str = dataclasses.field(repr=False)
    prefix: str = ""
    endpoint_url: str | None = None

    def __post_init__(self) -> None:
        if not _BUCKET_NAME.fullmatch(self.bucket) or ".." in self.bucket:
            raise ObjectStorageError(
                f"{INVALID_CONFIG_ERROR}: '{self.bucket}' isn't a valid bucket name. Enter only the bucket "
                "name, without s3:// or a folder."
            )
        if not _REGION_NAME.fullmatch(self.region):
            raise ObjectStorageError(
                f"{INVALID_CONFIG_ERROR}: '{self.region}' isn't a valid region, such as us-east-1."
            )
        # Without both keys the SDKs fall back to the worker's own AWS credentials, which must
        # never be used to read a customer-chosen bucket.
        if not self.access_key_id.strip() or not self.secret_access_key.strip():
            raise ObjectStorageError(f"{INVALID_CONFIG_ERROR}: enter both the access key ID and the secret access key.")
        if any(segment in (".", "..") for segment in self.prefix.split("/")):
            raise ObjectStorageError(f"{INVALID_CONFIG_ERROR}: the folder can't contain '.' or '..' segments.")

    @property
    def location_url(self) -> str:
        """The https URL of the folder, in the form the warehouse table URL checks accept."""
        path = f"/{self.prefix}/" if self.prefix else "/"
        if self.endpoint_url:
            return f"{self.endpoint_url.rstrip('/')}/{self.bucket}{path}"
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com{path}"

    @property
    def display_location(self) -> str:
        return f"{self.bucket}/{self.prefix}" if self.prefix else self.bucket


@frozen
class CsvOptions:
    has_header: bool = True
    # Mirrors ClickHouse's `format_csv_allow_double_quotes`: off means a double quote is an ordinary
    # character and never encloses a field.
    allow_double_quotes: bool = True


@frozen
class DiscoveryOptions:
    """The settings that decide which files exist as tables, and how each one is read."""

    file_format: FileFormatChoice = "infer"
    file_pattern: str | None = None
    allow_double_quotes: bool = True
    combined_table_name: str | None = None

    def __post_init__(self) -> None:
        # The API checks the shape of a payload, not that a `Literal` field holds one of its values.
        if self.file_format not in get_args(FileFormatChoice):
            raise ObjectStorageError(f"{INVALID_CONFIG_ERROR}: '{self.file_format}' isn't a supported file format.")


def normalize_prefix(path: str | None) -> str:
    """Drop empty segments only. A '.' or '..' segment stays, so `ObjectStoreConfig` rejects it."""
    return "/".join(segment for segment in (path or "").strip().split("/") if segment)
