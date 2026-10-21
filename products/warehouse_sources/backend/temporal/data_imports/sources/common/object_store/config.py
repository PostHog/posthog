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


class ObjectStoreProvider(StrEnum):
    S3 = "s3"
    GCS = "gcs"
    R2 = "r2"


# The region S3-compatible stores expect in the request signature when they have no AWS-style regions.
AUTO_REGION = "auto"
GCS_ENDPOINT_URL = "https://storage.googleapis.com"

# Each provider's bucket naming rules. Holding the bucket to them keeps it from injecting a host or
# a path into the URLs built from it. GCS also allows underscores.
_BUCKET_NAMES: dict[ObjectStoreProvider, re.Pattern[str]] = {
    ObjectStoreProvider.S3: re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]"),
    # GCS allows up to 222 characters in a dotted name; `_valid_bucket` checks the length of each part.
    ObjectStoreProvider.GCS: re.compile(r"[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]"),
    ObjectStoreProvider.R2: re.compile(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]"),
}
_MAX_BUCKET_NAME_PART_LENGTH = 63
_REGION_NAME = re.compile(r"[a-z]{2}(-[a-z0-9]+)+-\d+")
_R2_ACCOUNT_ID = re.compile(r"[0-9a-f]{32}")
_AZURE_ACCOUNT_NAME = re.compile(r"[a-z0-9]{3,24}")
_AZURE_CONTAINER_NAME = re.compile(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]")
# Storage account keys are base64. Nothing else may reach the connection string the key is put in,
# where a ';' would start a new setting such as another endpoint.
_AZURE_ACCOUNT_KEY = re.compile(r"[A-Za-z0-9+/]+={0,2}")


def _valid_bucket(provider: ObjectStoreProvider, bucket: str) -> bool:
    if not _BUCKET_NAMES[provider].fullmatch(bucket) or ".." in bucket:
        return False
    # A GCS name without dots is at most 63 characters, and so is each dot-separated part of one with dots.
    return all(len(part) <= _MAX_BUCKET_NAME_PART_LENGTH for part in bucket.split("."))


def _validate_prefix(prefix: str) -> None:
    if any(segment in (".", "..") for segment in prefix.split("/")):
        raise ObjectStorageError(f"{INVALID_CONFIG_ERROR}: the folder can't contain '.' or '..' segments.")


@frozen
class ObjectStoreConfig:
    """Where a bucket lives in an S3-compatible store, and the credentials to read it.

    The endpoint is derived from the provider and the account ID, so no caller can point the stored
    credentials at a host of its own choosing.
    """

    provider: ObjectStoreProvider
    bucket: str
    region: str
    access_key_id: str = dataclasses.field(repr=False)
    secret_access_key: str = dataclasses.field(repr=False)
    prefix: str = ""
    # The Cloudflare account that owns an R2 bucket. Other providers leave it unset.
    account_id: str | None = None

    def __post_init__(self) -> None:
        if not _valid_bucket(self.provider, self.bucket):
            raise ObjectStorageError(
                f"{INVALID_CONFIG_ERROR}: '{self.bucket}' isn't a valid bucket name. Enter only the bucket "
                "name, without a URL or a folder."
            )
        if self.provider == ObjectStoreProvider.S3:
            if not _REGION_NAME.fullmatch(self.region):
                raise ObjectStorageError(
                    f"{INVALID_CONFIG_ERROR}: '{self.region}' isn't a valid region, such as us-east-1."
                )
        elif self.region != AUTO_REGION:
            raise ObjectStorageError(f"{INVALID_CONFIG_ERROR}: this storage provider has no region setting.")
        if self.provider == ObjectStoreProvider.R2:
            if self.account_id is None or not _R2_ACCOUNT_ID.fullmatch(self.account_id):
                raise ObjectStorageError(
                    f"{INVALID_CONFIG_ERROR}: the account ID isn't valid. Enter the 32-character Cloudflare "
                    "account ID, without a URL."
                )
        elif self.account_id is not None:
            raise ObjectStorageError(f"{INVALID_CONFIG_ERROR}: this storage provider has no account ID setting.")
        # Without both keys the SDKs fall back to the worker's own AWS credentials, which must
        # never be used to read a customer-chosen bucket.
        if not self.access_key_id.strip() or not self.secret_access_key.strip():
            raise ObjectStorageError(f"{INVALID_CONFIG_ERROR}: enter both the access key ID and the secret access key.")
        _validate_prefix(self.prefix)

    @property
    def endpoint_url(self) -> str | None:
        """None for AWS S3, where the SDKs build the regional endpoint themselves."""
        if self.provider == ObjectStoreProvider.GCS:
            return GCS_ENDPOINT_URL
        if self.provider == ObjectStoreProvider.R2:
            return f"https://{self.account_id}.r2.cloudflarestorage.com"
        return None

    @property
    def location_url(self) -> str:
        """The https URL of the folder, in the form the warehouse table URL checks accept."""
        path = f"/{self.prefix}/" if self.prefix else "/"
        if self.endpoint_url:
            return f"{self.endpoint_url}/{self.bucket}{path}"
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com{path}"

    @property
    def root_name(self) -> str:
        return self.bucket

    @property
    def display_location(self) -> str:
        return f"{self.bucket}/{self.prefix}" if self.prefix else self.bucket


@frozen
class AzureBlobConfig:
    """Where a container lives in Azure Blob Storage, and the account key to read it."""

    account_name: str
    account_key: str = dataclasses.field(repr=False)
    container: str
    prefix: str = ""

    def __post_init__(self) -> None:
        if not _AZURE_ACCOUNT_NAME.fullmatch(self.account_name):
            raise ObjectStorageError(
                f"{INVALID_CONFIG_ERROR}: '{self.account_name}' isn't a valid storage account name. Enter only "
                "the account name, without a URL."
            )
        if not _AZURE_CONTAINER_NAME.fullmatch(self.container) or "--" in self.container:
            raise ObjectStorageError(
                f"{INVALID_CONFIG_ERROR}: '{self.container}' isn't a valid container name. Enter only the "
                "container name, without a URL or a folder."
            )
        if not _AZURE_ACCOUNT_KEY.fullmatch(self.account_key):
            raise ObjectStorageError(
                f"{INVALID_CONFIG_ERROR}: the account key isn't valid. Copy one of the storage account's access keys."
            )
        _validate_prefix(self.prefix)

    @property
    def location_url(self) -> str:
        path = f"/{self.prefix}/" if self.prefix else "/"
        return f"https://{self.account_name}.blob.core.windows.net/{self.container}{path}"

    @property
    def root_name(self) -> str:
        return self.container

    @property
    def display_location(self) -> str:
        return f"{self.container}/{self.prefix}" if self.prefix else self.container

    @property
    def connection_string(self) -> str:
        return (
            f"DefaultEndpointsProtocol=https;AccountName={self.account_name};AccountKey={self.account_key};"
            "EndpointSuffix=core.windows.net"
        )


StoreConfig = ObjectStoreConfig | AzureBlobConfig


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
