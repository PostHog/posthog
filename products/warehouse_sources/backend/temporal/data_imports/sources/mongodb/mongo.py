from __future__ import annotations

import math
import uuid
import base64
import contextlib
import collections
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

import certifi
import structlog
from bson import Binary, DatetimeMS, ObjectId
from bson.codec_options import DatetimeConversion
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import PyMongoError
from pymongo.server_description import ServerDescription
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.consts import DEFAULT_CHUNK_SIZE
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MongoDBSourceConfig
from products.warehouse_sources.backend.types import IncrementalFieldType, PartitionSettings

# Schema inference settings
SCHEMA_INFERENCE_LIMIT = 10_000  # First 10k documents
SCHEMA_INFERENCE_TIMEOUT_MS = 45_000  # 45 seconds

# Mongo yields whole documents (the full doc rides along under `data`), so a collection of large
# documents can OOM the worker when a chunk is materialised into a PyArrow table — before any Delta
# merge. Size the extraction chunk to a fixed byte budget: rows-per-chunk are derived from the average
# document size and clamped, and a chunk flushes at whichever of the byte/row limit is hit first.
MONGO_CHUNK_SIZE_BYTES = 100 * 1024 * 1024  # 100 MiB
MONGO_MIN_CHUNK_ROWS = 100
# Ceiling reuses the pipeline default so tiny documents keep the large, efficient chunk. The 100 MiB
# byte budget is the real OOM guard; this only caps row count when documents are small enough that
# many fit in that budget.
MONGO_MAX_CHUNK_ROWS = DEFAULT_CHUNK_SIZE


def _adaptive_chunk_size(avg_obj_size: int | None) -> int:
    """Rows per extraction chunk, sized so one chunk holds roughly MONGO_CHUNK_SIZE_BYTES of documents.

    Small documents keep the default (large, efficient) chunk; large documents get a small chunk so the
    conversion of a chunk into a PyArrow table stays bounded. Falls back to the default when the average
    document size is unknown.
    """
    if not avg_obj_size or avg_obj_size <= 0:
        return DEFAULT_CHUNK_SIZE
    rows = MONGO_CHUNK_SIZE_BYTES // avg_obj_size
    return max(MONGO_MIN_CHUNK_ROWS, min(MONGO_MAX_CHUNK_ROWS, rows))


def _convert_binary(value: Binary) -> str:
    """Convert a bson.Binary to a safe string representation.

    Subtype 4 (standard UUID) is decoded to uuid.UUID by PyMongo's
    uuidRepresentation=standard codec option before documents reach this helper,
    so only legacy subtype 3 (16-byte UUIDs from older drivers) is handled here
    as a UUID. Byte ordering may differ from the application's encoding but a
    canonical string is preferable to a Python bytes repr, which is ambiguous
    and unparseable in SQL. Any other subtype falls back to base64 so the raw
    bytes round-trip safely.
    """
    if len(value) == 16 and value.subtype == 3:
        return str(uuid.UUID(bytes=bytes(value)))
    return base64.b64encode(bytes(value)).decode("ascii")


def _convert_datetime_ms(value: DatetimeMS) -> Any:
    """Convert a bson.DatetimeMS (used for out-of-range BSON datetimes under
    DATETIME_AUTO) to a native datetime when possible, else None.

    DATETIME_AUTO returns DatetimeMS only when the value cannot be represented
    as a Python datetime (year <1 or >9999). In-range values arrive as
    datetime directly and never enter this branch. Returning None for the
    unrepresentable cases means a single malformed row does not fail the sync
    and preserves nullability on downstream date columns.
    """
    # as_datetime uses the default codec (non-AUTO) and raises bson.errors.InvalidBSON
    # on out-of-range values. We intentionally swallow any conversion failure —
    # the helper's job is "represent as datetime or null" and we never want a
    # malformed date to abort a sync.
    try:
        return value.as_datetime()
    except Exception:
        return None


def _safe_doc_id_repr(doc: Any) -> str:
    """Best-effort stringification of _id for logging purposes only. Must never raise."""
    try:
        return str(doc.get("_id"))
    except Exception:
        return "<unavailable>"


def _process_doc_with_field_logging(
    doc: dict[str, Any], collection_name: str, logger: FilteringBoundLogger
) -> dict[str, Any]:
    """Apply _process_nested_value to each top-level field. If conversion fails for
    any field, log the collection, document _id, and field name to give the error a
    precise location, then re-raise so the sync fails fast. We do NOT substitute
    failed fields with None — silently nulling would hide data loss.
    """
    processed: dict[str, Any] = {}
    for key, value in doc.items():
        try:
            processed[key] = _process_nested_value(value)
        except Exception as e:
            logger.exception(
                f"MongoDB sync: failed to process field '{key}' in collection={collection_name} "
                f"_id={_safe_doc_id_repr(doc)}: {type(e).__name__}: {e}",
            )
            raise
    return processed


def _process_nested_value(value: Any) -> Any:
    """Process a nested value, converting ObjectIds/UUIDs/Binary to strings
    and normalising out-of-range BSON datetimes to None."""
    if isinstance(value, ObjectId):
        return str(value)
    # Binary must be checked before bytes — bson.Binary subclasses bytes.
    elif isinstance(value, Binary):
        return _convert_binary(value)
    elif isinstance(value, uuid.UUID):
        return str(value)
    elif isinstance(value, DatetimeMS):
        return _convert_datetime_ms(value)
    elif isinstance(value, dict):
        return {key: _process_nested_value(val) for key, val in value.items()}
    elif isinstance(value, list):
        return [_process_nested_value(item) for item in value]
    else:
        return value


def get_indexes(collection: Collection) -> list[str]:
    """Get all indexes for a MongoDB collection."""
    try:
        index_cursor = collection.list_indexes()
        return [field for index in index_cursor for field in index["key"].keys()]
    except Exception:
        return []


def get_leading_index_keys(collection: Collection) -> set[str] | None:
    """Return the set of fields that are the first key of any index.

    `WHERE field >= last_max` queries are only accelerated by indexes whose
    leading key is `field`; non-leading positions in compound indexes don't
    support this access pattern. Returns None when index discovery fails so
    the caller can default to no warning.
    """
    try:
        index_cursor = collection.list_indexes()
        result: set[str] = set()
        for index in index_cursor:
            keys = index.get("key")
            if not keys:
                continue
            leading = next(iter(keys.keys()), None)
            if leading is not None:
                result.add(leading)
        return result
    except Exception as e:
        structlog.get_logger().warning("Failed to detect leading index keys for MongoDB collection", exc_info=e)
        return None


def filter_mongo_incremental_fields(
    columns: list[tuple[str, str]], collection: Collection
) -> list[tuple[str, IncrementalFieldType]]:
    results: list[tuple[str, IncrementalFieldType]] = []
    indexed_fields = get_indexes(collection)

    for column_name, type in columns:
        # Only include fields that have indexes
        if column_name not in indexed_fields:
            continue

        type = type.lower()
        if type == "timestamp":
            results.append((column_name, IncrementalFieldType.Timestamp))
        elif type == "integer":
            results.append((column_name, IncrementalFieldType.Integer))
        elif type == "double":
            results.append((column_name, IncrementalFieldType.Numeric))
        elif column_name == "_id" and type == "string":
            results.append((column_name, IncrementalFieldType.ObjectID))

    return results


def _build_query(
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    incremental_field_type: Optional[IncrementalFieldType],
    db_incremental_field_last_value: Optional[Any],
) -> dict[str, Any]:
    query: dict[str, Any] = {}

    if not should_use_incremental_field:
        return query

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    if db_incremental_field_last_value is None:
        db_incremental_field_last_value = incremental_type_to_initial_value(incremental_field_type)

    if incremental_field_type == IncrementalFieldType.ObjectID:
        query = {incremental_field: {"$gt": _coerce_object_id_cursor(db_incremental_field_last_value), "$exists": True}}
    else:
        query = {incremental_field: {"$gt": db_incremental_field_last_value, "$exists": True}}

    return query


def _coerce_object_id_cursor(last_value: Any) -> Any:
    """`_id` is offered as an ObjectID incremental cursor, but MongoDB `_id` values aren't
    always ObjectIds — collections frequently key on UUIDs or other strings. Only wrap the
    cursor in ObjectId when it's a valid 24-char hex id; otherwise compare the raw string so
    a non-ObjectId `_id` doesn't raise InvalidId and permanently break every incremental sync.
    """
    value = str(last_value)
    return ObjectId(value) if ObjectId.is_valid(value) else value


def _make_safe_server_selector(team_id: int) -> Callable[[list[ServerDescription]], list[ServerDescription]]:
    """Create a PyMongo server_selector that rejects servers resolving to internal IPs.

    Runs on every topology update (including SRV re-resolution), preventing
    TOCTOU attacks where DNS records change after initial validation.
    """

    def selector(server_descriptions: list[ServerDescription]) -> list[ServerDescription]:
        safe = []
        for server in server_descriptions:
            host = server.address[0]
            is_safe, _ = _is_host_safe(host, team_id)
            if is_safe:
                safe.append(server)
        return safe

    return selector


@contextlib.contextmanager
def mongo_client(connection_string: str, team_id: int) -> Iterator[MongoClient]:
    kwargs: dict[str, Any] = {
        "serverSelectionTimeoutMS": 10000,
        "tls": True,
        "tlsCAFile": certifi.where(),
        "server_selector": _make_safe_server_selector(team_id),
        # Decode BSON Binary subtype 4 as native uuid.UUID instead of bson.Binary,
        # so UUID primary keys don't leak as Python bytes repr downstream.
        # Subtype 3 stays as Binary under STANDARD and is handled in _convert_binary.
        # MongoClient's uuidRepresentation kwarg rejects the UuidRepresentation enum
        # and only accepts the lowercase string form, unlike datetime_conversion which
        # accepts the DatetimeConversion enum directly.
        "uuidRepresentation": "standard",
        # Out-of-range dates (e.g. year 0, year > 9999) become DatetimeMS instead
        # of raising InvalidBSON during cursor iteration. We then convert DatetimeMS
        # to None in _process_nested_value so a single bad row doesn't fail the sync.
        "datetime_conversion": DatetimeConversion.DATETIME_AUTO,
    }
    client: MongoClient = MongoClient(connection_string, **kwargs)
    try:
        yield client
    finally:
        client.close()


def _get_partition_settings(
    collection: Collection, collection_name: str, partition_size_bytes: int = DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES
) -> PartitionSettings | None:
    """Get partition settings for given MongoDB collection."""
    try:
        # Get collection stats
        stats = collection.database.command("collStats", collection_name)

        collection_size = stats.get("size", 0)  # size in bytes
        row_count = stats.get("count", 0)

        if collection_size == 0 or row_count == 0:
            return None

        # Calculate partition count based on size
        partition_count = max(1, math.ceil(collection_size / partition_size_bytes))

        # Cap at reasonable limit
        partition_count = min(partition_count, 100)

        partition_size = math.ceil(row_count / partition_count)

        return PartitionSettings(
            partition_count=partition_count,
            partition_size=partition_size,
        )
    except Exception:
        return None


DATABASE_NAME_REQUIRED_ERROR = (
    "Database name is required. Add it to your connection string "
    "(e.g. ...mongodb.net/my_database) or fill in the Database name field."
)


def _parse_connection_string(connection_string: str, database_override: str | None = None) -> dict[str, Any]:
    """Parse MongoDB connection string and extract connection parameters.

    ``database_override`` is the value of the separate "Database name" field. Atlas
    ``mongodb+srv://...`` strings routinely omit the database from the path, so we fall
    back to the override when the string doesn't carry one — an explicit database in the
    connection string still wins.
    """
    from urllib.parse import parse_qs, urlparse

    # TODO require TLS
    # nosemgrep: trailofbits.generic.mongodb-insecure-transport.mongodb-insecure-transport
    # Handle mongodb:// and mongodb+srv:// schemes
    parsed = urlparse(connection_string)

    if parsed.scheme not in ["mongodb", "mongodb+srv"]:
        # TODO require TLS
        # nosemgrep: trailofbits.generic.mongodb-insecure-transport.mongodb-insecure-transport
        raise ValueError("Connection string must start with mongodb:// or mongodb+srv://")

    # Extract basic connection info
    host = parsed.hostname or "localhost"
    port = parsed.port or (27017 if parsed.scheme == "mongodb" else None)
    database = parsed.path.lstrip("/") if parsed.path else None
    if not database and database_override:
        database = database_override.strip() or None
    user = parsed.username
    password = parsed.password

    # Parse query parameters
    query_params = parse_qs(parsed.query)

    # Extract common parameters
    auth_source = query_params.get("authSource", ["admin"])[0]
    direct_connection = query_params.get("directConnection", ["false"])[0].lower() in ["true", "1"]
    tls = query_params.get("tls", ["false"])[0].lower() in ["true", "1"]
    ssl = query_params.get("ssl", ["false"])[0].lower() in ["true", "1"]

    # TLS can be specified as either tls or ssl
    use_tls = tls or ssl

    return {
        "host": host,
        "port": port,
        "database": database,
        "user": user,
        "password": password,
        "auth_source": auth_source,
        "direct_connection": direct_connection,
        "tls": use_tls,
        "connection_string": connection_string,
        "is_srv": parsed.scheme == "mongodb+srv",
    }


def _get_schema_from_query(collection: Collection) -> list[tuple[str, str]]:
    """Infer schema from MongoDB collection using aggregation to get document keys and types."""
    try:
        # Use aggregation pipeline with limit to avoid full collection scan
        pipeline: list[dict[str, Any]] = [
            # Limit documents to avoid scanning entire collection (uses _id index)
            {"$limit": SCHEMA_INFERENCE_LIMIT},
            # Convert each document to an array of key-value pairs
            {"$project": {"arrayofkeyvalue": {"$objectToArray": "$$ROOT"}}},
            # Unwind the array to get individual key-value pairs
            {"$unwind": "$arrayofkeyvalue"},
            # Group by key name and collect unique types
            {
                "$group": {
                    "_id": "$arrayofkeyvalue.k",
                    "types": {"$addToSet": {"$type": "$arrayofkeyvalue.v"}},
                }
            },
        ]

        result = list(collection.aggregate(pipeline, maxTimeMS=SCHEMA_INFERENCE_TIMEOUT_MS))

        if not result:
            return [("_id", "string")]

        schema_info = []
        for field_info in result:
            field_name = field_info["_id"]
            types = field_info["types"]

            # Determine the most appropriate type
            # MongoDB $type returns BSON type names, map them to our type system
            field_type = _determine_field_type_from_bson_types(types)
            schema_info.append((field_name, field_type))

        return schema_info

    except Exception:
        # Fallback to basic schema if aggregation fails
        return [("_id", "string")]


def _determine_field_type_from_bson_types(bson_types: list[str]) -> str:
    """Determine field type from BSON types."""
    # If multiple types exist, prioritize based on hierarchy
    type_priority = {
        "objectId": "string",
        "string": "string",
        "int": "integer",
        "long": "integer",
        "double": "double",
        "decimal": "double",
        "bool": "boolean",
        "date": "timestamp",
        "timestamp": "timestamp",
        "object": "object",
        "array": "array",
        "null": "string",
    }

    # Find the highest priority type
    for bson_type in [
        "objectId",
        "timestamp",
        "date",
        "double",
        "decimal",
        "long",
        "int",
        "bool",
        "array",
        "object",
        "string",
    ]:
        if bson_type in bson_types:
            return type_priority.get(bson_type, "string")

    return "string"


# MongoDB reserves the `system.*` namespace for internal collections (system.keys,
# system.views, system.profile, ...). They're never user data and reads against them fail with
# an "Unauthorized" OperationFailure, so they must never be offered for import.
_RESERVED_COLLECTION_PREFIX = "system."


def _list_importable_collection_names(db: Database) -> list[str]:
    return [
        name
        for name in db.list_collection_names(authorizedCollections=True)
        if not name.startswith(_RESERVED_COLLECTION_PREFIX)
    ]


def get_schemas(
    config: MongoDBSourceConfig, team_id: int, names: list[str] | None = None
) -> dict[str, list[tuple[str, str]]]:
    """Get all collections from MongoDB source database to sync."""

    connection_params = _parse_connection_string(config.connection_string, config.database_name)

    with mongo_client(config.connection_string, team_id=team_id) as client:
        if not connection_params["database"]:
            raise ValueError(DATABASE_NAME_REQUIRED_ERROR)

        db = client[connection_params["database"]]
        schema_list: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)

        # Get collection names
        collection_names = _list_importable_collection_names(db)

        if names is not None:
            names_set = set(names)
            collection_names = [n for n in collection_names if n in names_set]

        if not collection_names:
            return schema_list

        with ThreadPoolExecutor(max_workers=min(len(collection_names), 4)) as executor:
            results = executor.map(
                _get_schema_from_query, [db[collection_name] for collection_name in collection_names]
            )
            for collection_name, schema_info in zip(collection_names, results):
                schema_list[collection_name].extend(schema_info)

    return schema_list


def get_collection_names(config: MongoDBSourceConfig, team_id: int) -> list[str]:
    connection_params = _parse_connection_string(config.connection_string, config.database_name)
    with mongo_client(config.connection_string, team_id=team_id) as client:
        if not connection_params["database"]:
            raise ValueError(DATABASE_NAME_REQUIRED_ERROR)
        db = client[connection_params["database"]]
        return _list_importable_collection_names(db)


def _get_primary_keys(collection: Collection, collection_name: str) -> list[str] | None:
    # MongoDB always has _id as primary key
    return ["_id"]


def _get_avg_document_size(collection: Collection, logger: FilteringBoundLogger) -> int | None:
    """Average BSON document size in bytes from collStats, used to size the extraction chunk.

    Returns None if unavailable (permissions, sharded stats, etc.) — the caller falls back to the
    default chunk size. Never raises: chunk sizing is best-effort tuning, not correctness.
    """
    try:
        stats = collection.database.command("collStats", collection.name)
        avg_obj_size = stats.get("avgObjSize")
        return int(avg_obj_size) if avg_obj_size else None
    except Exception as e:
        logger.debug(f"MongoDB: could not read collStats avgObjSize ({e}); using default chunk size")
        return None


def _get_rows_to_sync(collection: Collection, query: dict[str, Any], logger: FilteringBoundLogger) -> int:
    try:
        rows_to_sync = collection.count_documents(query)
        logger.debug(f"_get_rows_to_sync: rows_to_sync={rows_to_sync}")
        return rows_to_sync
    except PyMongoError as e:
        # rows_to_sync is only a progress estimate, so a failed count degrades to 0
        # rather than failing the sync. Connectivity/auth failures here are expected
        # operational errors — the real data read fails and is classified by
        # get_non_retryable_errors — so log and move on instead of flooding error
        # tracking with non-actionable noise.
        logger.warning(f"_get_rows_to_sync: could not count documents ({e}). Using 0 as rows to sync")
        return 0
    except Exception as e:
        # Unexpected, non-PyMongo error — surface it so genuine bugs aren't hidden.
        logger.debug(f"_get_rows_to_sync: Error: {e}. Using 0 as rows to sync", exc_info=e)
        capture_exception(e)
        return 0


def mongo_source(
    connection_string: str,
    collection_name: str,
    logger: FilteringBoundLogger,
    team_id: int,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
    database_name: Optional[str] = None,
) -> SourceResponse:
    connection_params = _parse_connection_string(connection_string, database_name)

    if not connection_params["database"]:
        raise ValueError(DATABASE_NAME_REQUIRED_ERROR)

    # Create MongoDB client
    with mongo_client(connection_string, team_id=team_id) as client:
        db = client[connection_params["database"]]
        collection = db[collection_name]

        query = _build_query(
            should_use_incremental_field,
            incremental_field,
            incremental_field_type,
            db_incremental_field_last_value,
        )

        # Get collection metadata
        primary_keys = _get_primary_keys(collection, collection_name)
        partition_settings = (
            _get_partition_settings(collection, collection_name) if should_use_incremental_field else None
        )
        rows_to_sync = _get_rows_to_sync(collection, query, logger)
        avg_obj_size = _get_avg_document_size(collection, logger)

    # Bound the extraction chunk to the collection's document size so large documents don't OOM the
    # source->Arrow conversion (the merge is never reached for such collections).
    chunk_size = _adaptive_chunk_size(avg_obj_size)
    logger.debug(f"MongoDB: chunk_size={chunk_size} rows (avg_obj_size={avg_obj_size}, rows_to_sync={rows_to_sync})")

    def get_rows() -> Iterator[dict[str, Any]]:
        # New connection for data reading
        with mongo_client(connection_string, team_id=team_id) as read_client:
            read_db = read_client[connection_params["database"]]
            read_collection = read_db[collection_name]

            query = _build_query(
                should_use_incremental_field,
                incremental_field,
                incremental_field_type,
                db_incremental_field_last_value,
            )

            cursor = read_collection.find(query, batch_size=chunk_size)

            for doc in cursor:
                # Convert BSON types (ObjectId, Binary, UUID, DatetimeMS) to SQL-safe
                # values. _process_doc_with_field_logging logs the offending field name
                # before re-raising, so any exception here fails the sync with precise
                # diagnostic context rather than silently dropping rows.
                processed_doc = _process_doc_with_field_logging(doc, collection_name, logger)

                # Stringify _id so it's always a scalar string downstream,
                # regardless of BSON type (ObjectId, UUID Binary, numeric, etc.).
                result: dict[str, Any] = {
                    "_id": str(processed_doc["_id"]),
                }
                # extract incremental field from the document if it exists
                if incremental_field:
                    incremental_value = processed_doc.get(incremental_field, None)
                    if incremental_value is None:
                        continue
                    result[incremental_field] = incremental_value

                result["data"] = processed_doc

                yield result

    name = NamingConvention.normalize_identifier(collection_name)

    return SourceResponse(
        name=name,
        items=get_rows,
        primary_keys=primary_keys,
        partition_count=partition_settings.partition_count if partition_settings else None,
        partition_size=partition_settings.partition_size if partition_settings else None,
        rows_to_sync=rows_to_sync,
        chunk_size=chunk_size,
        chunk_size_bytes=MONGO_CHUNK_SIZE_BYTES,
    )
