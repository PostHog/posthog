import dataclasses
from datetime import UTC, datetime
from typing import IO, Any, cast

import s3fs
import boto3
from adlfs import AzureBlobFileSystem
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ResourceNotFoundError
from azure.storage.blob import ContainerClient
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
from fsspec import AbstractFileSystem
from s3fs.errors import translate_boto_error

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import (
    AzureBlobConfig,
    ObjectStoreConfig,
    StoreConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    TOO_MANY_FILES_ERROR,
    ObjectStorageError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.settings import (
    CONNECT_TIMEOUT_SECONDS,
    MAX_LISTED_KEYS,
    MAX_REQUEST_ATTEMPTS,
    READ_TIMEOUT_SECONDS,
)

S3_MAX_PAGE_SIZE = 1000
AZURE_PAGE_SIZE = 1000


@frozen
class StoredObject:
    # Relative to the store root, '/'-separated.
    path: str
    size: int
    modified_at: datetime


@frozen
class ObjectStore:
    """A filesystem rooted at the configured bucket folder, plus what deltalake needs to read it.

    Delta tables are read by delta-rs, which does not use the fsspec filesystem, so the store also
    carries the URI prefix and the storage options for it.
    """

    fs: AbstractFileSystem
    # The fsspec path of the folder: `bucket/prefix` for S3.
    root: str
    delta_uri_prefix: str
    delta_storage_options: dict[str, str] = dataclasses.field(repr=False)

    def path(self, relative: str) -> str:
        return f"{self.root}/{relative}" if relative else self.root

    def delta_uri(self, relative: str) -> str:
        return f"{self.delta_uri_prefix}{self.path(relative)}"

    def list_objects(self, relative_prefix: str, max_objects: int) -> list[StoredObject]:
        """List up to `max_objects` files under the prefix, in path order.

        The prefix is a folder, or one file. This generic version walks the whole fsspec tree, so
        stores with a large remote listing override it with a paginated, capped one.
        """
        found = cast(dict[str, dict[str, Any]], self.fs.find(self.path(relative_prefix), detail=True))
        root_prefix = f"{self.root}/"
        objects: list[StoredObject] = []
        for name in sorted(found):
            info = found[name]
            if info.get("type") != "file" or not name.startswith(root_prefix):
                continue
            objects.append(
                StoredObject(
                    path=name[len(root_prefix) :], size=int(info.get("size") or 0), modified_at=_modified_at(info)
                )
            )
            if len(objects) >= max_objects:
                break
        return objects

    def list_key_prefix(self, key_prefix: str, max_objects: int) -> list[StoredObject]:
        """List files whose relative paths start with the key prefix, in path order."""
        folder = key_prefix.rpartition("/")[0]
        found = cast(dict[str, dict[str, Any]], self.fs.find(self.path(folder), detail=True))
        root_prefix = f"{self.root}/"
        objects: list[StoredObject] = []
        for name in sorted(found):
            info = found[name]
            if info.get("type") != "file" or not name.startswith(root_prefix):
                continue
            relative = name[len(root_prefix) :]
            if not relative.startswith(key_prefix):
                continue
            objects.append(StoredObject(path=relative, size=int(info.get("size") or 0), modified_at=_modified_at(info)))
            if len(objects) >= max_objects:
                break
        return objects

    def open(self, relative: str) -> IO[bytes]:
        return cast(IO[bytes], self.fs.open(self.path(relative), "rb"))


def _modified_at(info: dict[str, Any]) -> datetime:
    last_modified = info.get("LastModified") or info.get("last_modified")
    if isinstance(last_modified, datetime):
        return last_modified if last_modified.tzinfo else last_modified.replace(tzinfo=UTC)
    return datetime.fromtimestamp(float(info.get("mtime") or 0), tz=UTC)


def _request_config(config: ObjectStoreConfig) -> dict[str, Any]:
    request_config: dict[str, Any] = {
        "connect_timeout": CONNECT_TIMEOUT_SECONDS,
        "read_timeout": READ_TIMEOUT_SECONDS,
        "retries": {"max_attempts": MAX_REQUEST_ATTEMPTS, "mode": "standard"},
    }
    if config.endpoint_url:
        # botocore asks for and sends CRC checksums by default. S3-compatible stores do not all
        # accept the extra headers, so they are limited to the operations that require them.
        request_config["request_checksum_calculation"] = "when_required"
        request_config["response_checksum_validation"] = "when_required"
    return request_config


def build_s3_filesystem(config: ObjectStoreConfig) -> s3fs.S3FileSystem:
    client_kwargs: dict[str, Any] = {"region_name": config.region}
    return s3fs.S3FileSystem(
        key=config.access_key_id,
        secret=config.secret_access_key,
        endpoint_url=config.endpoint_url,
        client_kwargs=client_kwargs,
        config_kwargs=_request_config(config),
        # fsspec caches instances by their arguments, which would keep every customer's credentials
        # alive in the worker. Directory listings are re-read on every run anyway.
        skip_instance_cache=True,
        use_listings_cache=False,
    )


def delta_storage_options(config: ObjectStoreConfig) -> dict[str, str]:
    options = {
        "AWS_ACCESS_KEY_ID": config.access_key_id,
        "AWS_SECRET_ACCESS_KEY": config.secret_access_key,
        "AWS_REGION": config.region,
        "connect_timeout": f"{CONNECT_TIMEOUT_SECONDS}s",
        "timeout": f"{READ_TIMEOUT_SECONDS}s",
    }
    if config.endpoint_url:
        options["AWS_ENDPOINT_URL"] = config.endpoint_url
    return options


@frozen
class S3ObjectStore(ObjectStore):
    """Lists through a boto3 client and reads through s3fs.

    s3fs caps a listing by asking for a page of twice the cap, which S3-compatible stores reject
    above their own page limit. The boto3 paginator keeps pages at the S3 maximum and stops at the cap.
    """

    client: Any = dataclasses.field(repr=False)
    bucket: str
    prefix: str

    def list_objects(self, relative_prefix: str, max_objects: int) -> list[StoredObject]:
        key = "/".join(part for part in (self.prefix, relative_prefix) if part)
        objects = self._list(f"{key}/" if key else "", max_objects)
        if not objects and relative_prefix:
            # The prefix may name one file rather than a folder.
            objects = [stored for stored in self._list(key, 1) if stored.path == relative_prefix]
        return objects

    def list_key_prefix(self, key_prefix: str, max_objects: int) -> list[StoredObject]:
        key = "/".join(part for part in (self.prefix, key_prefix) if part)
        if self.prefix and not key_prefix:
            key = f"{self.prefix}/"
        return self._list(key, max_objects)

    def _list(self, key_prefix: str, max_objects: int) -> list[StoredObject]:
        root_key = f"{self.prefix}/" if self.prefix else ""
        paginator = self.client.get_paginator("list_objects_v2")
        # The file cap counts files, not keys: folder marker keys are skipped, so stopping after a fixed
        # number of keys could hide that the folder holds more files than the cap. A separate cap on
        # the keys walked keeps a prefix full of marker keys from running the listing without end.
        pages = paginator.paginate(
            Bucket=self.bucket, Prefix=key_prefix, PaginationConfig={"PageSize": S3_MAX_PAGE_SIZE}
        )
        objects: list[StoredObject] = []
        walked_keys = 0
        try:
            for page in pages:
                for item in page.get("Contents", []):
                    walked_keys += 1
                    if walked_keys > MAX_LISTED_KEYS:
                        raise ObjectStorageError(
                            f"{TOO_MANY_FILES_ERROR} ({MAX_LISTED_KEYS:,} keys) under '{key_prefix or '/'}'. Point "
                            "the source at a narrower folder."
                        )
                    object_key: str = item["Key"]
                    if not object_key.startswith(root_key) or object_key.endswith("/"):
                        continue
                    objects.append(
                        StoredObject(
                            path=object_key[len(root_key) :],
                            size=int(item.get("Size") or 0),
                            modified_at=_modified_at(item),
                        )
                    )
                    if len(objects) >= max_objects:
                        return objects
        except ClientError as e:
            raise translate_boto_error(e) from e
        return objects


def build_s3_client(config: ObjectStoreConfig) -> Any:
    return boto3.client(
        "s3",
        aws_access_key_id=config.access_key_id,
        aws_secret_access_key=config.secret_access_key,
        region_name=config.region,
        endpoint_url=config.endpoint_url,
        config=BotoConfig(**_request_config(config)),
    )


def open_s3_store(config: ObjectStoreConfig) -> S3ObjectStore:
    return S3ObjectStore(
        fs=build_s3_filesystem(config),
        root=f"{config.bucket}/{config.prefix}" if config.prefix else config.bucket,
        delta_uri_prefix="s3://",
        delta_storage_options=delta_storage_options(config),
        client=build_s3_client(config),
        bucket=config.bucket,
        prefix=config.prefix,
    )


@frozen
class AzureObjectStore(ObjectStore):
    """Lists through the Azure SDK and reads through adlfs.

    adlfs lists a whole prefix before it returns. The SDK pager fetches one page at a time, so the
    listing stops at the cap.
    """

    container_client: Any = dataclasses.field(repr=False)
    prefix: str

    def list_objects(self, relative_prefix: str, max_objects: int) -> list[StoredObject]:
        name = "/".join(part for part in (self.prefix, relative_prefix) if part)
        objects = self._list(f"{name}/" if name else "", max_objects)
        if not objects and relative_prefix:
            # The prefix may name one file rather than a folder.
            objects = [stored for stored in self._list(name, 1) if stored.path == relative_prefix]
        return objects

    def list_key_prefix(self, key_prefix: str, max_objects: int) -> list[StoredObject]:
        key = "/".join(part for part in (self.prefix, key_prefix) if part)
        if self.prefix and not key_prefix:
            key = f"{self.prefix}/"
        return self._list(key, max_objects)

    def _list(self, name_prefix: str, max_objects: int) -> list[StoredObject]:
        root_name = f"{self.prefix}/" if self.prefix else ""
        objects: list[StoredObject] = []
        # Folder blobs are skipped before the file cap counts them, so the blobs walked have their own cap.
        walked_blobs = 0
        try:
            blobs = self.container_client.list_blobs(
                name_starts_with=name_prefix or None, include=["metadata"], results_per_page=AZURE_PAGE_SIZE
            )
            for blob in blobs:
                walked_blobs += 1
                if walked_blobs > MAX_LISTED_KEYS:
                    raise ObjectStorageError(
                        f"{TOO_MANY_FILES_ERROR} ({MAX_LISTED_KEYS:,} keys) under '{name_prefix or '/'}'. Point "
                        "the source at a narrower folder."
                    )
                blob_name: str = blob.name
                # Accounts with a hierarchical namespace list each folder as an empty blob.
                is_folder = (blob.metadata or {}).get("hdi_isfolder") == "true"
                if is_folder or not blob_name.startswith(root_name) or blob_name.endswith("/"):
                    continue
                objects.append(
                    StoredObject(
                        path=blob_name[len(root_name) :],
                        size=int(blob.size or 0),
                        modified_at=_modified_at({"LastModified": blob.last_modified}),
                    )
                )
                if len(objects) >= max_objects:
                    break
        except ResourceNotFoundError as e:
            raise FileNotFoundError(str(e)) from e
        except ClientAuthenticationError as e:
            raise PermissionError(str(e)) from e
        except HttpResponseError as e:
            if e.status_code in (401, 403):
                raise PermissionError(str(e)) from e
            raise
        return objects


def azure_delta_storage_options(config: AzureBlobConfig) -> dict[str, str]:
    return {
        "azure_storage_account_name": config.account_name,
        "azure_storage_account_key": config.account_key,
        "connect_timeout": f"{CONNECT_TIMEOUT_SECONDS}s",
        "timeout": f"{READ_TIMEOUT_SECONDS}s",
    }


def open_azure_store(config: AzureBlobConfig) -> AzureObjectStore:
    # Both clients take the connection string, because adlfs otherwise prefers a connection string
    # from the worker's environment over the account name and key it is given.
    return AzureObjectStore(
        fs=AzureBlobFileSystem(
            connection_string=config.connection_string,
            anon=False,
            connection_timeout=CONNECT_TIMEOUT_SECONDS,
            read_timeout=READ_TIMEOUT_SECONDS,
            skip_instance_cache=True,
            use_listings_cache=False,
        ),
        root=f"{config.container}/{config.prefix}" if config.prefix else config.container,
        delta_uri_prefix="az://",
        delta_storage_options=azure_delta_storage_options(config),
        container_client=ContainerClient.from_connection_string(
            config.connection_string,
            config.container,
            connection_timeout=CONNECT_TIMEOUT_SECONDS,
            read_timeout=READ_TIMEOUT_SECONDS,
            retry_total=MAX_REQUEST_ATTEMPTS,
        ),
        prefix=config.prefix,
    )


def open_store(config: StoreConfig) -> ObjectStore:
    if isinstance(config, AzureBlobConfig):
        return open_azure_store(config)
    return open_s3_store(config)
