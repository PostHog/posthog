import io
import re
import time
import tempfile
import contextvars
import dataclasses
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from typing import IO, Any
from urllib.parse import quote, urlsplit

import pyarrow as pa
import fastavro
import pyarrow.compute as pc
import pyarrow.parquet as pq
from botocore.auth import S3SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from requests import Response, Session

from products.warehouse_sources.sources.r2_data_catalog.settings import (
    ACCESS_DELEGATION_HEADER,
    BATCH_ROWS,
    CLOUDFLARE_STORAGE_DOMAIN,
    CREDENTIAL_REFRESH_MARGIN_SECONDS,
    DEFAULT_CATALOG_HOST,
    DEFAULT_CREDENTIAL_LIFETIME_SECONDS,
    DISCOVERY_CONCURRENCY,
    DOWNLOAD_CHUNK_BYTES,
    INCREMENTAL_TYPES,
    MAX_DISCOVERED_TABLES,
    MAX_NAMESPACE_DEPTH,
    R2_STORAGE_DOMAIN,
    REQUEST_TIMEOUT,
    SPOOL_MEMORY_BYTES,
    VENDED_CREDENTIALS,
)
from products.warehouse_sources.sources.sdk import (
    IncrementalFieldType,
    ResumableSourceManager,
    coerce_date,
    frozen,
    make_tracked_session,
    parse_datetime_or_epoch,
)

INVALID_TOKEN_MESSAGE = (
    "Cloudflare rejected the API token. Create an R2 API token with Admin Read only permission, then reconnect."
)
PERMISSION_MESSAGE = "The API token can't read this catalog. Give it R2 Data Catalog read and R2 storage read permission, then reconnect."
NOT_FOUND_MESSAGE = (
    "Cloudflare couldn't find a catalog for that bucket. Check the account ID and bucket name, and that the catalog "
    "is turned on for the bucket, then reconnect."
)
TABLE_NOT_FOUND_MESSAGE = "The Iceberg table no longer exists in the catalog. Remove it from the source or recreate it."
STORAGE_PERMISSION_MESSAGE = (
    "The API token can't read the table's files in R2. Give it R2 storage read permission, then reconnect."
)
NO_CREDENTIALS_MESSAGE = (
    "The catalog didn't return storage credentials for the table. Check that the API token has R2 storage read "
    "permission, then reconnect."
)
UNSUPPORTED_DELETES_MESSAGE = (
    "The Iceberg table has equality deletes or deletion vectors, which the import can't read yet. "
    "Compact the table to remove them, then sync again."
)
UNSUPPORTED_FORMAT_MESSAGE = "The Iceberg table has data files that aren't Parquet, which the import can't read."
INVALID_URI_MESSAGE = (
    "Enter the catalog URI from the Cloudflare dashboard, for example "
    "https://catalog.cloudflarestorage.com/<account ID>/<bucket name>."
)
INVALID_ACCOUNT_MESSAGE = "Enter the Cloudflare account ID as shown in the dashboard, without a URL."
INVALID_BUCKET_MESSAGE = "Enter the name of the R2 bucket that holds the catalog, as shown in the dashboard."
INCREMENTAL_COLUMN_MISSING_MESSAGE = (
    "The incremental column is no longer in the Iceberg table, or its type can't be a cursor. "
    "Pick another incremental column in the table's sync settings."
)
INVALID_WATERMARK_MESSAGE = (
    "The saved incremental value doesn't fit the type of the incremental column. Resync the table to start again."
)
UNREACHABLE_MESSAGE = "Couldn't reach Cloudflare to check the catalog. Try again in a moment."

# Manifest list `content` and data file `content` values from the Iceberg spec.
_DATA = 0
_POSITION_DELETES = 1
_EQUALITY_DELETES = 2
# Manifest entry `status`: 2 means the file was removed in that snapshot.
_DELETED_ENTRY = 2
_NAMESPACE_SEPARATOR = "\x1f"
_ACCOUNT_ID_RE = re.compile(r"[A-Za-z0-9]{1,64}")
_BUCKET_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# Byte widths of an Iceberg bound whose value is in the column's own unit. An int promoted to long keeps 4-byte bounds.
_BOUND_WIDTHS: dict[str, tuple[int, ...]] = {
    "int": (4,),
    "long": (4, 8),
    "date": (4,),
    "timestamp": (8,),
    "timestamptz": (8,),
    "timestamp_ns": (8,),
    "timestamptz_ns": (8,),
}
_EPOCH_DATE = date(1970, 1, 1)
_PARQUET_FIELD_ID = b"PARQUET:field_id"

_PRIMITIVE_ARROW_TYPES: dict[str, pa.DataType] = {
    "boolean": pa.bool_(),
    "int": pa.int32(),
    "long": pa.int64(),
    "float": pa.float32(),
    "double": pa.float64(),
    "date": pa.date32(),
    "time": pa.time64("us"),
    "timestamp": pa.timestamp("us"),
    "timestamptz": pa.timestamp("us", tz="UTC"),
    "timestamp_ns": pa.timestamp("ns"),
    "timestamptz_ns": pa.timestamp("ns", tz="UTC"),
    "string": pa.string(),
    "uuid": pa.binary(16),
    "binary": pa.binary(),
}


class R2DataCatalogError(Exception):
    pass


@frozen
class TableIdentifier:
    namespace: tuple[str, ...]
    name: str

    @property
    def display_name(self) -> str:
        return ".".join((*self.namespace, self.name))


@frozen
class IcebergColumn:
    field_id: int
    name: str
    type: Any
    required: bool

    @property
    def type_name(self) -> str:
        return self.type if isinstance(self.type, str) else str(self.type.get("type", "unknown"))


@frozen
class IcebergTable:
    identifier: TableIdentifier
    metadata: dict[str, Any]
    columns: list[IcebergColumn]
    primary_keys: list[str]
    snapshot: dict[str, Any] | None

    @property
    def total_records(self) -> int | None:
        if self.snapshot is None:
            return 0
        summary = self.snapshot.get("summary") or {}
        try:
            # Equality deletes can't be counted without reading them, so the count would only guess.
            if int(summary.get("total-equality-deletes") or 0):
                return None
            records = summary.get("total-records")
            if records is None:
                return None
            # total-records counts the rows in the data files, before position deletes remove any.
            return max(int(records) - int(summary.get("total-position-deletes") or 0), 0)
        except (TypeError, ValueError):
            return None

    def column(self, name: str) -> IcebergColumn | None:
        return next((column for column in self.columns if column.name == name), None)

    def snapshot_by_id(self, snapshot_id: int) -> dict[str, Any] | None:
        return next((s for s in self.metadata.get("snapshots") or [] if s.get("snapshot-id") == snapshot_id), None)


@frozen
class StorageCredentials:
    access_key_id: str = dataclasses.field(repr=False)
    secret_access_key: str = dataclasses.field(repr=False)
    session_token: str | None = dataclasses.field(repr=False)
    endpoint: str
    region: str
    expires_at: float


@frozen
class DataFile:
    path: str
    record_count: int
    # Iceberg single-value bound of each column, keyed by field id.
    upper_bounds: dict[int, bytes]


@dataclasses.dataclass
class R2DataCatalogResumeConfig:
    """The snapshot being read, the index of the data file in path order, and the rows of it already read."""

    snapshot_id: int
    file_index: int
    rows_done: int


def normalize_catalog_uri(uri: str) -> str:
    parts = urlsplit(uri.strip())
    host = (parts.hostname or "").lower()
    if (
        parts.scheme != "https"
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or (parts.port not in (None, 443))
        or not (host == CLOUDFLARE_STORAGE_DOMAIN or host.endswith(f".{CLOUDFLARE_STORAGE_DOMAIN}"))
        or not parts.path.strip("/")
    ):
        raise ValueError(INVALID_URI_MESSAGE)
    return f"https://{host}/{parts.path.strip('/')}"


def _error_detail(response: Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    return ""


def catalog_error(response: Response, not_found_message: str = NOT_FOUND_MESSAGE) -> R2DataCatalogError:
    status = response.status_code
    if status == 401:
        return R2DataCatalogError(INVALID_TOKEN_MESSAGE)
    if status == 403:
        return R2DataCatalogError(PERMISSION_MESSAGE)
    if status == 404:
        return R2DataCatalogError(not_found_message)
    detail = _error_detail(response)
    return R2DataCatalogError(f"R2 Data Catalog request failed ({status}){': ' + detail if detail else ''}")


def _encode_namespace(namespace: tuple[str, ...]) -> str:
    return quote(_NAMESPACE_SEPARATOR.join(namespace), safe="")


class CatalogClient:
    """A client for the Iceberg REST catalog API that R2 Data Catalog serves."""

    def __init__(self, account_id: str, bucket_name: str, api_token: str, catalog_uri: str | None = None) -> None:
        self.account_id = account_id.strip()
        bucket = bucket_name.strip()
        if not _ACCOUNT_ID_RE.fullmatch(self.account_id):
            raise ValueError(INVALID_ACCOUNT_MESSAGE)
        if not _BUCKET_RE.fullmatch(bucket):
            raise ValueError(INVALID_BUCKET_MESSAGE)
        # Cloudflare names the warehouse of a bucket's catalog `<account ID>_<bucket name>`.
        self.warehouse = f"{self.account_id}_{bucket}"
        self.base_url = (
            normalize_catalog_uri(catalog_uri)
            if catalog_uri and catalog_uri.strip()
            else f"https://{DEFAULT_CATALOG_HOST}/{self.account_id}/{bucket}"
        )
        token = api_token.strip()
        self._session: Session = make_tracked_session(
            headers={"Authorization": f"Bearer {token}"},
            redact_values=(token,),
            allow_redirects=False,
            # Load-table answers carry vended storage keys under `s3.*` names that the sample scrubber can't spot.
            capture=False,
        )
        self._properties: dict[str, str] | None = None

    def _get(
        self,
        path: str,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        not_found_message: str = NOT_FOUND_MESSAGE,
    ) -> dict[str, Any]:
        response = self._session.get(
            f"{self.base_url}/v1/{path}", params=params, headers=headers, timeout=REQUEST_TIMEOUT
        )
        if response.status_code != 200:
            raise catalog_error(response, not_found_message)
        try:
            body = response.json()
        except ValueError as error:
            raise R2DataCatalogError("R2 Data Catalog returned a response that isn't JSON.") from error
        if not isinstance(body, dict):
            raise R2DataCatalogError("R2 Data Catalog returned an unexpected response.")
        return body

    @property
    def properties(self) -> dict[str, str]:
        """The catalog properties from `GET /v1/config`, with the overrides applied on top of the defaults."""
        if self._properties is None:
            body = self._get("config", params={"warehouse": self.warehouse})
            self._properties = {
                **{str(k): str(v) for k, v in (body.get("defaults") or {}).items()},
                **{str(k): str(v) for k, v in (body.get("overrides") or {}).items()},
            }
        return self._properties

    def _catalog_path(self, path: str) -> str:
        prefix = self.properties.get("prefix", "").strip("/")
        return f"{quote(prefix, safe='/')}/{path}" if prefix else path

    def _paginate(self, path: str, key: str, params: dict[str, str] | None = None) -> Iterator[Any]:
        page_params = dict(params or {})
        seen_tokens: set[str] = set()
        while True:
            body = self._get(self._catalog_path(path), params=page_params)
            yield from body.get(key) or []
            token = body.get("next-page-token")
            if not token or token in seen_tokens:
                return
            seen_tokens.add(token)
            page_params["pageToken"] = token

    def list_namespaces(self) -> list[tuple[str, ...]]:
        found: list[tuple[str, ...]] = []
        pending: list[tuple[str, ...]] = [()]
        visited: set[tuple[str, ...]] = set()
        while pending:
            parent = pending.pop(0)
            params = {"parent": _NAMESPACE_SEPARATOR.join(parent)} if parent else None
            for raw in self._paginate("namespaces", "namespaces", params):
                namespace = tuple(str(part) for part in raw) if isinstance(raw, list) else (str(raw),)
                # A server that ignores `parent` answers with the top level again, so only children count.
                if namespace in visited or len(namespace) <= len(parent) or namespace[: len(parent)] != parent:
                    continue
                visited.add(namespace)
                found.append(namespace)
                if len(namespace) < MAX_NAMESPACE_DEPTH:
                    pending.append(namespace)
        return found

    def list_tables(self, namespace: tuple[str, ...]) -> list[TableIdentifier]:
        tables: list[TableIdentifier] = []
        for raw in self._paginate(f"namespaces/{_encode_namespace(namespace)}/tables", "identifiers"):
            if isinstance(raw, dict) and raw.get("name"):
                parts = raw.get("namespace")
                table_namespace = tuple(str(p) for p in parts) if isinstance(parts, list) else namespace
                tables.append(TableIdentifier(namespace=table_namespace, name=str(raw["name"])))
        return tables

    def list_all_tables(self, limit: int | None = MAX_DISCOVERED_TABLES) -> list[TableIdentifier]:
        tables: list[TableIdentifier] = []
        for namespace in self.list_namespaces():
            tables.extend(self.list_tables(namespace))
            if limit is not None and len(tables) >= limit:
                return tables[:limit]
        return tables

    def close(self) -> None:
        self._session.close()

    def load_table_response(self, identifier: TableIdentifier, vend_credentials: bool = False) -> dict[str, Any]:
        path = f"namespaces/{_encode_namespace(identifier.namespace)}/tables/{quote(identifier.name, safe='')}"
        headers = {ACCESS_DELEGATION_HEADER: VENDED_CREDENTIALS} if vend_credentials else None
        return self._get(self._catalog_path(path), headers=headers, not_found_message=TABLE_NOT_FOUND_MESSAGE)

    def load_table(self, identifier: TableIdentifier) -> IcebergTable:
        return parse_table(identifier, self.load_table_response(identifier))

    def storage_credentials(self, identifier: TableIdentifier) -> StorageCredentials:
        response = self.load_table_response(identifier, vend_credentials=True)
        return parse_storage_credentials(response, self.properties, self.account_id)


def load_tables(client: CatalogClient, identifiers: list[TableIdentifier]) -> list[IcebergTable]:
    """Load the tables in order, a few at a time, so discovery of a large catalog fits in a web request."""
    # Pool threads start with an empty context, so each load runs in a copy of the caller's context.
    context = contextvars.copy_context()
    with ThreadPoolExecutor(max_workers=DISCOVERY_CONCURRENCY, thread_name_prefix="r2-catalog") as pool:
        return list(pool.map(lambda identifier: context.copy().run(client.load_table, identifier), identifiers))


def resolve_table(client: CatalogClient, display_name: str) -> IcebergTable:
    """Load a table by its `namespace.table` schema name.

    Each dot can split two namespace levels or sit inside a name, so each split is tried directly, the deepest
    namespace first. Only when none loads does the catalog's full list decide, which costs one request per namespace.
    """
    parts = display_name.split(".")
    for split in range(len(parts) - 1, 0, -1):
        identifier = TableIdentifier(namespace=tuple(parts[:split]), name=".".join(parts[split:]))
        try:
            return client.load_table(identifier)
        except R2DataCatalogError as error:
            if str(error) != TABLE_NOT_FOUND_MESSAGE:
                raise
    for identifier in client.list_all_tables(limit=None):
        if identifier.display_name == display_name:
            return client.load_table(identifier)
    raise R2DataCatalogError(f"{TABLE_NOT_FOUND_MESSAGE} Table: {display_name}")


def parse_table(identifier: TableIdentifier, response: Mapping[str, Any]) -> IcebergTable:
    metadata = response.get("metadata")
    if not isinstance(metadata, dict):
        raise R2DataCatalogError("R2 Data Catalog returned a table without metadata.")
    schemas = metadata.get("schemas") or ([metadata["schema"]] if isinstance(metadata.get("schema"), dict) else [])
    if not schemas:
        raise R2DataCatalogError("R2 Data Catalog returned a table without a schema.")
    current_id = metadata.get("current-schema-id")
    schema = next((s for s in schemas if s.get("schema-id") == current_id), schemas[-1])
    columns = [
        IcebergColumn(
            field_id=int(field["id"]),
            name=str(field["name"]),
            type=field.get("type"),
            required=bool(field.get("required")),
        )
        for field in schema.get("fields") or []
    ]
    identifier_ids = set(schema.get("identifier-field-ids") or [])
    primary_keys = [column.name for column in columns if column.field_id in identifier_ids]
    snapshot_id = metadata.get("current-snapshot-id")
    snapshot = None
    if snapshot_id is not None and snapshot_id != -1:
        snapshot = next((s for s in metadata.get("snapshots") or [] if s.get("snapshot-id") == snapshot_id), None)
    return IcebergTable(
        identifier=identifier, metadata=metadata, columns=columns, primary_keys=primary_keys, snapshot=snapshot
    )


def _storage_endpoint(properties: Mapping[str, str], account_id: str) -> str:
    endpoint = properties.get("s3.endpoint")
    if not endpoint:
        endpoint = f"https://{account_id}.{R2_STORAGE_DOMAIN}"
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host.endswith(f".{R2_STORAGE_DOMAIN}") or parts.username or parts.password:
        raise R2DataCatalogError("R2 Data Catalog returned a storage endpoint outside Cloudflare R2.")
    return f"https://{parts.netloc.lower()}"


def parse_storage_credentials(
    response: Mapping[str, Any], catalog_properties: Mapping[str, str], account_id: str
) -> StorageCredentials:
    properties: dict[str, str] = {
        **catalog_properties,
        **{k: str(v) for k, v in (response.get("config") or {}).items()},
    }
    location = str((response.get("metadata") or {}).get("location") or response.get("metadata-location") or "")
    # Newer catalogs return credentials per storage prefix. The longest prefix of the table location wins.
    matching = [
        credential
        for credential in response.get("storage-credentials") or []
        if isinstance(credential, dict) and location.startswith(str(credential.get("prefix") or ""))
    ]
    if matching:
        best = max(matching, key=lambda credential: len(str(credential.get("prefix") or "")))
        properties.update({k: str(v) for k, v in (best.get("config") or {}).items()})
    access_key_id = properties.get("s3.access-key-id")
    secret_access_key = properties.get("s3.secret-access-key")
    if not access_key_id or not secret_access_key:
        raise R2DataCatalogError(NO_CREDENTIALS_MESSAGE)
    expires_at = time.time() + DEFAULT_CREDENTIAL_LIFETIME_SECONDS
    expires_ms = properties.get("s3.session-token-expires-at-ms")
    if expires_ms:
        try:
            expires_at = int(expires_ms) / 1000
        except ValueError:
            pass
    return StorageCredentials(
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        session_token=properties.get("s3.session-token") or None,
        endpoint=_storage_endpoint(properties, account_id),
        region=properties.get("s3.region") or properties.get("client.region") or "auto",
        expires_at=expires_at,
    )


def _split_location(location: str) -> tuple[str, str]:
    parts = urlsplit(location)
    if parts.scheme not in ("s3", "s3a", "s3n", "r2") or not parts.netloc or not parts.path.strip("/"):
        raise R2DataCatalogError(f"R2 Data Catalog returned a file location the import can't read: {location}")
    return parts.netloc, parts.path.lstrip("/")


class StorageReader:
    """Reads table files from R2 with the catalog's vended credentials, renewing them before they expire."""

    def __init__(self, load_credentials: Callable[[], StorageCredentials]) -> None:
        self._load_credentials = load_credentials
        self._credentials: StorageCredentials | None = None
        self._session: Session | None = None
        self._signer: S3SigV4Auth | None = None

    def _ensure_credentials(self) -> tuple[StorageCredentials, Session, S3SigV4Auth]:
        if (
            self._credentials is None
            or self._session is None
            or self._signer is None
            or time.time() >= self._credentials.expires_at - CREDENTIAL_REFRESH_MARGIN_SECONDS
        ):
            if self._session is not None:
                self._session.close()
            credentials = self._load_credentials()
            self._credentials = credentials
            self._session = make_tracked_session(
                redact_values=tuple(
                    value for value in (credentials.secret_access_key, credentials.session_token) if value
                ),
                allow_redirects=False,
            )
            self._signer = S3SigV4Auth(
                Credentials(credentials.access_key_id, credentials.secret_access_key, credentials.session_token),
                "s3",
                credentials.region,
            )
        return self._credentials, self._session, self._signer

    def _signed_get(self, location: str, stream: bool) -> Response:
        credentials, session, signer = self._ensure_credentials()
        bucket, key = _split_location(location)
        url = f"{credentials.endpoint}/{quote(bucket, safe='')}/{quote(key, safe='/~')}"
        request = AWSRequest(method="GET", url=url)
        signer.add_auth(request)
        return session.get(url, headers=dict(request.headers), timeout=REQUEST_TIMEOUT, stream=stream)

    def get(self, location: str, stream: bool = False) -> Response:
        response = self._signed_get(location, stream)
        if response.status_code == 403:
            # R2 also answers 403 for vended credentials that expired early, so new ones get one more try.
            response.close()
            self._credentials = None
            response = self._signed_get(location, stream)
        if response.status_code == 403:
            response.close()
            raise R2DataCatalogError(STORAGE_PERMISSION_MESSAGE)
        if response.status_code != 200:
            response.close()
            raise R2DataCatalogError(f"R2 storage request failed ({response.status_code}) for {location}")
        return response

    def read_bytes(self, location: str) -> bytes:
        return self.get(location).content

    def open_file(self, location: str) -> IO[bytes]:
        spooled = tempfile.SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES)
        response = self.get(location, stream=True)
        try:
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                spooled.write(chunk)
        except BaseException:
            spooled.close()
            raise
        finally:
            response.close()
        spooled.seek(0)
        return spooled

    def close(self) -> None:
        if self._session is not None:
            self._session.close()


def _avro_records(content: bytes) -> Iterator[dict[str, Any]]:
    for record in fastavro.reader(io.BytesIO(content)):
        if isinstance(record, dict):
            yield record


def _bounds(raw: Any) -> dict[int, bytes]:
    # Iceberg writes maps with int keys as Avro arrays of key/value records.
    if isinstance(raw, dict):
        return {int(k): v for k, v in raw.items() if isinstance(v, bytes)}
    if isinstance(raw, list):
        return {int(item["key"]): item["value"] for item in raw if isinstance(item.get("value"), bytes)}
    return {}


@frozen
class ReadPlan:
    data_files: list[DataFile]
    # Deleted row positions of each data file, from the table's position delete files.
    deleted_positions: dict[str, pa.Array]


def plan_read(
    reader: StorageReader, snapshot: Mapping[str, Any], safe_point: Callable[[], None] | None = None
) -> ReadPlan:
    if snapshot.get("manifest-list"):
        manifests = list(_avro_records(reader.read_bytes(str(snapshot["manifest-list"]))))
    else:
        # Format v1 snapshots can list their manifests inline.
        manifests = [{"manifest_path": path, "content": _DATA} for path in snapshot.get("manifests") or []]

    data_files: dict[str, DataFile] = {}
    delete_files: list[str] = []
    for manifest in manifests:
        for entry in _avro_records(reader.read_bytes(str(manifest["manifest_path"]))):
            if entry.get("status") == _DELETED_ENTRY:
                continue
            data_file = entry.get("data_file") or {}
            content = data_file.get("content") or _DATA
            file_format = str(data_file.get("file_format") or "").upper()
            path = str(data_file.get("file_path"))
            if content == _EQUALITY_DELETES or (content == _POSITION_DELETES and file_format != "PARQUET"):
                raise R2DataCatalogError(UNSUPPORTED_DELETES_MESSAGE)
            if file_format != "PARQUET":
                raise R2DataCatalogError(UNSUPPORTED_FORMAT_MESSAGE)
            if content == _POSITION_DELETES:
                delete_files.append(path)
            else:
                data_files[path] = DataFile(
                    path=path,
                    record_count=int(data_file.get("record_count") or 0),
                    upper_bounds=_bounds(data_file.get("upper_bounds")),
                )
        if safe_point is not None:
            safe_point()

    deleted: dict[str, list[pa.Array]] = {}
    for path in sorted(delete_files):
        with reader.open_file(path) as handle:
            table = pq.read_table(handle, columns=["file_path", "pos"])
        for target in pc.unique(table.column("file_path")).to_pylist():
            mask = pc.equal(table.column("file_path"), pa.scalar(target, type=pa.string()))
            deleted.setdefault(str(target), []).append(table.filter(mask).column("pos").combine_chunks())
        if safe_point is not None:
            safe_point()

    return ReadPlan(
        data_files=sorted(data_files.values(), key=lambda data_file: data_file.path),
        deleted_positions={
            path: pa.concat_arrays([array.cast(pa.int64()) for array in arrays]) for path, arrays in deleted.items()
        },
    )


def arrow_type(iceberg_type: Any) -> pa.DataType:
    if isinstance(iceberg_type, str):
        if iceberg_type in _PRIMITIVE_ARROW_TYPES:
            return _PRIMITIVE_ARROW_TYPES[iceberg_type]
        if iceberg_type.startswith("decimal(") and iceberg_type.endswith(")"):
            precision, scale = (int(part) for part in iceberg_type[len("decimal(") : -1].split(","))
            return pa.decimal128(precision, scale)
        if iceberg_type.startswith("fixed[") and iceberg_type.endswith("]"):
            return pa.binary(int(iceberg_type[len("fixed[") : -1]))
    return pa.null()


def align_to_schema(table: pa.Table, columns: list[IcebergColumn]) -> pa.Table:
    """Pick the current schema's columns out of a data file by field id, so renamed columns keep their data."""
    by_id: dict[int, int] = {}
    by_name: dict[str, int] = {}
    for index, field in enumerate(table.schema):
        by_name[field.name] = index
        field_id = (field.metadata or {}).get(_PARQUET_FIELD_ID)
        if field_id is not None:
            by_id[int(field_id)] = index
    arrays: list[pa.ChunkedArray | pa.Array] = []
    for column in columns:
        # Files written without field ids (imported from plain Parquet) fall back to names.
        found = by_id.get(column.field_id) if by_id else by_name.get(column.name)
        target = arrow_type(column.type)
        if found is None:
            arrays.append(pa.nulls(table.num_rows).cast(target))
        elif pa.types.is_null(target) or table.schema.field(found).type == target:
            arrays.append(table.column(found))
        else:
            # Files written before a type promotion (int to long, float to double) hold the old type, and every
            # batch must carry the current one.
            arrays.append(table.column(found).cast(target))
    return pa.Table.from_arrays(arrays, names=[column.name for column in columns])


@frozen
class IncrementalFilter:
    column: IcebergColumn
    # The watermark in Iceberg's own representation: days for dates, micro- or nanoseconds for timestamps.
    threshold: int


def _internal_value(iceberg_type: str, value: Any) -> int:
    if iceberg_type in ("int", "long"):
        try:
            return int(value)
        except (TypeError, ValueError) as error:
            raise R2DataCatalogError(INVALID_WATERMARK_MESSAGE) from error
    if iceberg_type == "date":
        day = coerce_date(value)
        if day is None:
            raise R2DataCatalogError(INVALID_WATERMARK_MESSAGE)
        return (day - _EPOCH_DATE).days
    moment = parse_datetime_or_epoch(value)
    if moment is None:
        raise R2DataCatalogError(INVALID_WATERMARK_MESSAGE)
    unit = timedelta(microseconds=1) if not iceberg_type.endswith("_ns") else None
    delta = moment - _EPOCH
    if unit is not None:
        return delta // unit
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


def incremental_filter(table: IcebergTable, field: str | None, last_value: Any) -> IncrementalFilter | None:
    if field is None or last_value is None:
        return None
    column = table.column(field)
    if column is None or column.type_name not in INCREMENTAL_TYPES:
        raise R2DataCatalogError(INCREMENTAL_COLUMN_MISSING_MESSAGE)
    return IncrementalFilter(column=column, threshold=_internal_value(column.type_name, last_value))


def _decode_bound(raw: bytes) -> int:
    # Iceberg single-value serialization: little-endian, 4 bytes for int and date, 8 for long and timestamps.
    return int.from_bytes(raw, "little", signed=True)


def file_may_match(data_file: DataFile, row_filter: IncrementalFilter | None) -> bool:
    if row_filter is None:
        return True
    upper = data_file.upper_bounds.get(row_filter.column.field_id)
    # A bound written before a type promotion (date to timestamp in format v3) has another width and unit.
    if upper is None or len(upper) not in _BOUND_WIDTHS.get(row_filter.column.type_name, ()):
        return True
    return _decode_bound(upper) >= row_filter.threshold


def _internal_values(values: pa.ChunkedArray, iceberg_type: str) -> pa.ChunkedArray:
    if iceberg_type in ("int", "long"):
        return pc.cast(values, pa.int64())
    if iceberg_type == "date":
        return pc.cast(pc.cast(values, pa.date32()), pa.int32()).cast(pa.int64())
    nanos = iceberg_type.endswith("_ns")
    tz = getattr(values.type, "tz", None)
    target: pa.DataType
    if tz is None:
        target = pa.timestamp("ns") if nanos else pa.timestamp("us")
    else:
        target = pa.timestamp("ns", tz=str(tz)) if nanos else pa.timestamp("us", tz=str(tz))
    return pc.cast(pc.cast(values, target), pa.int64())


def filter_rows(
    table: pa.Table, first_position: int, deleted: pa.Array | None, row_filter: IncrementalFilter | None
) -> pa.Table:
    if deleted is not None and len(deleted):
        positions = pa.array(range(first_position, first_position + table.num_rows), type=pa.int64())
        table = table.filter(pc.invert(pc.is_in(positions, value_set=deleted)))
    if row_filter is not None and table.num_rows:
        values = _internal_values(table.column(row_filter.column.name), row_filter.column.type_name)
        table = table.filter(pc.greater_equal(values, pa.scalar(row_filter.threshold, type=pa.int64())))
    return table


def iter_table_rows(
    client: CatalogClient,
    table: IcebergTable,
    row_filter: IncrementalFilter | None,
    manager: ResumableSourceManager[R2DataCatalogResumeConfig],
    logger: Any,
) -> Iterator[pa.Table]:
    resume = manager.load_state() if manager.can_resume() else None
    snapshot = table.snapshot
    file_index = 0
    rows_done = 0
    if resume is not None:
        resumed_snapshot = table.snapshot_by_id(resume.snapshot_id)
        if resumed_snapshot is not None:
            snapshot = resumed_snapshot
            file_index, rows_done = resume.file_index, resume.rows_done
        else:
            logger.warning("R2 Data Catalog: the saved snapshot has expired, reading the table from the start")

    if snapshot is None:
        client.close()
        yield pa.schema([pa.field(c.name, arrow_type(c.type)) for c in table.columns]).empty_table()
        return

    snapshot_id = int(snapshot["snapshot-id"])
    reader = StorageReader(lambda: client.storage_credentials(table.identifier))
    try:
        plan = plan_read(reader, snapshot, safe_point=manager.safe_point)
        yielded_any = False
        for index in range(file_index, len(plan.data_files)):
            data_file = plan.data_files[index]
            start = rows_done if index == file_index else 0
            if not file_may_match(data_file, row_filter):
                continue
            with reader.open_file(data_file.path) as handle:
                parquet_file = pq.ParquetFile(handle)
                file_rows = parquet_file.metadata.num_rows
                position = 0
                for batch in parquet_file.iter_batches(batch_size=BATCH_ROWS, use_threads=False):
                    batch_start = position
                    position += batch.num_rows
                    if position <= start:
                        continue
                    raw = pa.Table.from_batches([batch])
                    if batch_start < start:
                        raw = raw.slice(start - batch_start)
                        batch_start = start
                    rows = filter_rows(
                        align_to_schema(raw, table.columns),
                        batch_start,
                        plan.deleted_positions.get(data_file.path),
                        row_filter,
                    )
                    # The last batch of a file points the cursor at the next file, so a resume skips this one.
                    done = position >= file_rows
                    manager.save_state(
                        R2DataCatalogResumeConfig(
                            snapshot_id=snapshot_id,
                            file_index=index + 1 if done else index,
                            rows_done=0 if done else position,
                        )
                    )
                    if rows.num_rows:
                        yielded_any = True
                        yield rows
                    else:
                        manager.safe_point()
            manager.safe_point()
        if not yielded_any:
            # The pipeline needs a schema to create the table, even when no row matched.
            yield pa.schema([pa.field(c.name, arrow_type(c.type)) for c in table.columns]).empty_table()
    finally:
        reader.close()
        client.close()


def incremental_type(column: IcebergColumn) -> IncrementalFieldType | None:
    return INCREMENTAL_TYPES.get(column.type_name) if isinstance(column.type, str) else None
