"""Parse the URL of a self-managed warehouse table into the parts an object storage source reads.

A self-managed table is a URL pattern that ClickHouse reads in place with the table's own access
key. Every parse here is exact or refused: a URL this module can't map raises `UnmappableTableError`
with the reason.
"""

import re
from collections.abc import Iterable
from typing import Literal
from urllib.parse import unquote, urlparse

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import normalize_column_name
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.globs import has_glob
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.locations import R2_HOST

StorageService = Literal["s3", "gcs", "r2", "azure"]

_S3_HOST = re.compile(r"(?:(?P<bucket>.+)\.)?s3(?:[.-](?P<endpoint>[a-z0-9.-]+?))?\.amazonaws\.com(?:\.cn)?")
_S3_ENDPOINT = re.compile(r"(?:(?:dualstack|fips)\.)?(?P<region>[a-z]{2}(?:-[a-z0-9]+)+-\d+)")
# The legacy name of the us-east-1 endpoint.
_S3_EXTERNAL_ENDPOINT = "external-1"
_S3_EXTERNAL_REGION = "us-east-1"
_GCS_HOST = "storage.googleapis.com"
_AZURE_HOST = re.compile(r"(?P<account>[a-z0-9]{3,24})\.blob\.core\.windows\.net")


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
    # The R2 jurisdiction, such as eu, when the URL names one.
    jurisdiction: str | None = None

    @property
    def group_key(self) -> str:
        # Migration markers store this key, so a location without a jurisdiction keeps its old key.
        account = f"{self.account}.{self.jurisdiction}" if self.account and self.jurisdiction else self.account
        return "/".join((self.service, account or self.region or "", self.bucket))


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
    elif (r2 := R2_HOST.fullmatch(host)) is not None:
        bucket, _, key = path.partition("/")
        location = SelfManagedLocation(
            service="r2", bucket=bucket, key=key, account=r2.group("account"), jurisdiction=r2.group("jurisdiction")
        )
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


def needs_preserved_column_names(column_names: Iterable[str]) -> bool:
    """Whether the import pipeline would rename a column that existing queries refer to."""
    return any(normalize_column_name(name) != name for name in column_names)
