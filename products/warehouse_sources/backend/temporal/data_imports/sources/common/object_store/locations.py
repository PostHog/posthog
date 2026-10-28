"""Parse the files URL of an object storage source into a bucket and the key glob after it.

Each provider accepts only its own hosts. The endpoint the stored credentials go to is rebuilt from
the parsed bucket, region and account, never taken from the URL's host as written. An S3 URL can
leave out the region, and the source then looks the region up from S3.
"""

import re
from urllib.parse import unquote

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    INVALID_CONFIG_ERROR,
    ObjectStorageError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.globs import (
    compile_clickhouse_glob,
    glob_listing_prefix,
    has_glob,
)

S3_EXAMPLE_URL = "https://my-company-exports.s3.us-east-1.amazonaws.com/orders/**/*.parquet"
GCS_EXAMPLE_URL = "https://storage.googleapis.com/my-company-exports/orders/**/*.parquet"
R2_EXAMPLE_URL = "https://<account-id>.r2.cloudflarestorage.com/my-company-exports/orders/**/*.parquet"
AZURE_EXAMPLE_URL = "https://mycompanystorage.blob.core.windows.net/exports/orders/**/*.parquet"

_URL = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?P<host>[^/]*)(?P<path>.*)", re.DOTALL)
# No user name, port, or other character that could make a client read the authority differently.
_HOST = re.compile(r"[a-z0-9._-]+")
_REGION = r"[a-z]{2}(?:-[a-z0-9]+)+-\d+"
_S3_VIRTUAL_HOSTED = re.compile(rf"(?P<bucket>[a-z0-9.-]+)\.s3\.(?P<region>{_REGION})\.amazonaws\.com")
_S3_PATH_STYLE = re.compile(rf"s3\.(?P<region>{_REGION})\.amazonaws\.com")
_S3_WITHOUT_REGION = re.compile(r"(?:(?P<bucket>[a-z0-9.-]+)\.)?s3\.amazonaws\.com")
_GCS_HOST = "storage.googleapis.com"
_R2_HOST = re.compile(r"(?P<account>[0-9a-f]{32})\.r2\.cloudflarestorage\.com")
_AZURE_HOST = re.compile(r"(?P<account>[a-z0-9]{3,24})\.blob\.core\.windows\.net")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


@frozen
class StorageUrl:
    # The bucket, or the container for Azure.
    bucket: str
    # The decoded object key after the bucket. It can hold ClickHouse glob syntax.
    key: str
    region: str | None = None
    # The Cloudflare account ID for R2, or the storage account name for Azure.
    account: str | None = None


@frozen
class KeySelection:
    """The keys under a bucket that a files URL selects."""

    # The folder the store is rooted at. Table names and table paths are relative to it.
    prefix: str
    # The one folder or file under `prefix` that discovery lists, or "" to list all of `prefix`.
    listing_prefix: str
    # A ClickHouse glob over paths relative to `prefix`, or None to keep every listed file.
    pattern: str | None


@frozen
class _UrlParts:
    scheme: str
    host: str
    # The raw path after the host, still percent-encoded.
    path: str


def _invalid(detail: str) -> ObjectStorageError:
    return ObjectStorageError(f"{INVALID_CONFIG_ERROR}: {detail}")


def _split(url: str, schemes: tuple[str, ...], example: str) -> _UrlParts:
    """The scheme, host and raw path of a URL, after refusing what could change where it points."""
    match = _URL.fullmatch(url.strip())
    if match is None:
        raise _invalid(f"enter the full URL of the files, such as {example}")
    scheme = match.group("scheme").lower()
    if scheme not in schemes:
        raise _invalid(f"the URL must start with {' or '.join(f'{allowed}://' for allowed in schemes)}.")
    host = match.group("host").lower()
    if not _HOST.fullmatch(host):
        raise _invalid("the URL host can't contain a user name, a port, or special characters.")
    path = match.group("path")
    if "#" in path or "\\" in path:
        raise _invalid("the URL can't contain '#' or '\\'.")
    return _UrlParts(scheme=scheme, host=host, path=path)


def _key(raw_key: str) -> str:
    key = unquote(raw_key)
    if _CONTROL_CHARACTERS.search(key):
        raise _invalid("the URL path can't contain control characters.")
    segments = key.split("/")
    if any(segment in (".", "..") for segment in (*segments, *raw_key.split("/"))):
        raise _invalid("the URL path can't contain '.' or '..' folders.")
    if "" in segments[:-1]:
        raise _invalid("the URL path can't contain an empty folder ('//').")
    return key


def _path_style(path: str, example: str, region: str | None = None, account: str | None = None) -> StorageUrl:
    """Split `/<bucket>/<key>` into the bucket and the decoded key."""
    bucket, _, raw_key = path.removeprefix("/").partition("/")
    if not bucket:
        raise _invalid(f"the URL doesn't name a bucket. Use a URL such as {example}")
    if "%" in bucket or has_glob(bucket):
        raise _invalid("the bucket name in the URL must be exact. Put wildcards in the path after the bucket.")
    return StorageUrl(bucket=bucket, key=_key(raw_key), region=region, account=account)


def parse_s3_url(url: str) -> StorageUrl:
    """Parse an S3 object URL, or an `s3://` URI. A URL with no region gives a `StorageUrl` with no region."""
    parts = _split(url, ("https", "s3"), S3_EXAMPLE_URL)
    if parts.scheme == "s3":
        return _path_style(f"/{parts.host}{parts.path}", S3_EXAMPLE_URL)
    host = parts.host
    if (virtual_hosted := _S3_VIRTUAL_HOSTED.fullmatch(host)) is not None:
        return StorageUrl(
            bucket=virtual_hosted.group("bucket"),
            key=_key(parts.path.removeprefix("/")),
            region=virtual_hosted.group("region"),
        )
    if (path_style := _S3_PATH_STYLE.fullmatch(host)) is not None:
        return _path_style(parts.path, S3_EXAMPLE_URL, region=path_style.group("region"))
    if (without_region := _S3_WITHOUT_REGION.fullmatch(host)) is not None:
        if (bucket := without_region.group("bucket")) is not None:
            return StorageUrl(bucket=bucket, key=_key(parts.path.removeprefix("/")))
        return _path_style(parts.path, S3_EXAMPLE_URL)
    raise _invalid(f"'{host}' isn't an Amazon S3 URL. Use a URL such as {S3_EXAMPLE_URL}")


def parse_gcs_url(url: str) -> StorageUrl:
    parts = _split(url, ("https", "gs"), GCS_EXAMPLE_URL)
    if parts.scheme == "gs":
        return _path_style(f"/{parts.host}{parts.path}", GCS_EXAMPLE_URL)
    if parts.host != _GCS_HOST:
        raise _invalid(f"'{parts.host}' isn't a Google Cloud Storage URL. Use a URL such as {GCS_EXAMPLE_URL}")
    return _path_style(parts.path, GCS_EXAMPLE_URL)


def parse_r2_url(url: str) -> StorageUrl:
    parts = _split(url, ("https",), R2_EXAMPLE_URL)
    if (r2 := _R2_HOST.fullmatch(parts.host)) is None:
        raise _invalid(f"'{parts.host}' isn't a Cloudflare R2 URL. Use a URL such as {R2_EXAMPLE_URL}")
    return _path_style(parts.path, R2_EXAMPLE_URL, account=r2.group("account"))


def parse_azure_url(url: str) -> StorageUrl:
    parts = _split(url, ("https",), AZURE_EXAMPLE_URL)
    if (azure := _AZURE_HOST.fullmatch(parts.host)) is None:
        raise _invalid(f"'{parts.host}' isn't an Azure Blob Storage URL. Use a URL such as {AZURE_EXAMPLE_URL}")
    return _path_style(parts.path, AZURE_EXAMPLE_URL, account=azure.group("account"))


def select_keys(key: str) -> KeySelection:
    """Root the store at the literal folder before the first glob, and keep the glob for the rest.

    A key with no glob selects the folder it names, or the one file it names.
    """
    if has_glob(key):
        folder = glob_listing_prefix(key)
        pattern = key[len(folder) + 1 :] if folder else key
        if pattern.endswith("/"):
            # A glob that ends at a folder reads every file under the folders it matches.
            pattern = f"{pattern}**"
        compile_clickhouse_glob(pattern)
        return KeySelection(prefix=folder, listing_prefix="", pattern=pattern)
    if not key or key.endswith("/"):
        return KeySelection(prefix=key.rstrip("/"), listing_prefix="", pattern=None)
    folder, _, name = key.rpartition("/")
    return KeySelection(prefix=folder, listing_prefix=name, pattern=None)
