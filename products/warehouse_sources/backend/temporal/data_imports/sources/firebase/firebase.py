import json
import time
import datetime
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import quote, urlparse

from django.core.cache import cache

import jwt
import requests
import structlog
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    incremental_field,
    rank_incremental_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.firebase.settings import (
    AUTH_USERS_PAGE_SIZE,
    AUTH_USERS_PRIMARY_KEY,
    AUTH_USERS_TABLE,
    FIRESTORE_API_ROOT,
    FIRESTORE_COLLECTION_IDS_PAGE_SIZE,
    FIRESTORE_CREATE_TIME_COLUMN,
    FIRESTORE_DISCOVERY_CACHE_TTL_SECONDS,
    FIRESTORE_DOCUMENT_ID_FIELD,
    FIRESTORE_ID_COLUMN,
    FIRESTORE_INCREMENTAL_DISCOVERY_LIMIT,
    FIRESTORE_INCREMENTAL_VALUE_TYPES,
    FIRESTORE_MAX_INTEGER,
    FIRESTORE_MAX_SUBCOLLECTION_DEPTH,
    FIRESTORE_MAX_TIMESTAMP,
    FIRESTORE_METADATA_COLUMNS,
    FIRESTORE_PAGE_SIZE,
    FIRESTORE_PATH_COLUMN,
    FIRESTORE_SCHEMA_SAMPLE_DOCUMENTS,
    FIRESTORE_SUBCOLLECTION_SAMPLE_DOCUMENTS,
    FIRESTORE_UPDATE_TIME_COLUMN,
    GOOGLE_TOKEN_URI,
    IDENTITY_TOOLKIT_API_ROOT,
    JWT_ASSERTION_LIFETIME_SECONDS,
    JWT_GRANT_TYPE,
    MAX_ERROR_BODY_BYTES,
    MAX_PAGES,
    MAX_RESPONSE_BYTES,
    MAX_TOKEN_RESPONSE_BYTES,
    OAUTH_SCOPES,
    REALTIME_DATABASE_HOST_SUFFIXES,
    REALTIME_DATABASE_KEY_COLUMN,
    REALTIME_DATABASE_PAGE_SIZE,
    REALTIME_DATABASE_PATH_COLUMN,
    REALTIME_DATABASE_VALUE_COLUMN,
    REDACTED_AUTH_USER_FIELDS,
    REQUEST_TIMEOUT_SECONDS,
    RESPONSE_TOO_LARGE_ERROR,
    TOKEN_EXPIRY_SKEW_SECONDS,
    firestore_collection_group_table_name,
    firestore_table_name,
    is_supported_incremental_field_name,
    realtime_database_table_name,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

LOGGER: FilteringBoundLogger = structlog.get_logger(__name__)


class FirebaseAuthError(Exception):
    """Raised when Google refuses to issue an access token for the service account."""


class FirebaseConfigError(Exception):
    """Raised when the source form describes something the transport cannot act on."""


class FirebaseResponseTooLargeError(Exception):
    """Raised when a response body exceeds the byte cap for its endpoint."""


@frozen
class FirebaseResumeConfig:
    """Resume cursor: a Firestore/Identity Platform page token, or a Realtime Database key."""

    cursor: str
    # An incremental Firestore read has no page token. It pages on the last row's position instead,
    # which is the ordered pair (cursor field value, document name), so `cursor` holds the document
    # name and this holds the JSON-encoded Firestore value beside it. Every other surface pages on a
    # single opaque token and leaves this unset, which is also what a cursor saved before this field
    # existed decodes to.
    incremental_value: Optional[str] = None


@frozen
class FirestoreIncrementalCursor:
    """The cursor field the user picked for one collection, and the watermark to read past."""

    field_name: str
    field_type: IncrementalFieldType
    last_value: Any


@dataclasses.dataclass(frozen=True, kw_only=True)
class FirebaseCredentials:
    project_id: str
    client_email: str
    private_key: str = dataclasses.field(repr=False)
    private_key_id: Optional[str] = None
    # Kept as it was read from the key file, but never used as a request target — see `token_endpoint`.
    token_uri: Optional[str] = None
    database_id: str = "(default)"
    realtime_database_url: Optional[str] = None
    realtime_database_paths: tuple[str, ...] = ()

    @property
    def token_endpoint(self) -> str:
        # Pinned to Google rather than read from the uploaded file. `token_uri` is user-supplied
        # input, and honoring it would let anyone who can configure a source aim the worker — and
        # the signed assertion — at an arbitrary host, including an internal one. Google-generated
        # service account keys always carry exactly this endpoint, so nothing legitimate is lost.
        return GOOGLE_TOKEN_URI

    @property
    def secret_values(self) -> tuple[str, ...]:
        return (self.private_key,) if self.private_key else ()


def validate_realtime_database_url(url: str) -> str:
    """Return the normalized Realtime Database base URL, or raise if it is not a Firebase host."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host.endswith(REALTIME_DATABASE_HOST_SUFFIXES):
        raise FirebaseConfigError(
            "The Realtime Database URL has to be an https URL on firebaseio.com or firebasedatabase.app, "
            "for example https://my-project-default-rtdb.firebaseio.com."
        )
    return f"https://{host}"


def _auth_session(credentials: FirebaseCredentials) -> requests.Session:
    # The token exchange carries the private key in the request and a bearer token in the
    # response, so it stays out of HTTP sample capture entirely.
    return make_tracked_session(redact_values=credentials.secret_values, capture=False)


def _api_session(credentials: FirebaseCredentials, *, capture: bool = True) -> requests.Session:
    return make_tracked_session(
        headers={"Accept": "application/json"},
        redact_values=credentials.secret_values,
        capture=capture,
    )


def build_jwt_assertion(credentials: FirebaseCredentials) -> str:
    issued_at = int(time.time())
    claims: dict[str, Any] = {
        "iss": credentials.client_email,
        "scope": OAUTH_SCOPES,
        "aud": credentials.token_endpoint,
        "iat": issued_at,
        "exp": issued_at + JWT_ASSERTION_LIFETIME_SECONDS,
    }
    headers = {"kid": credentials.private_key_id} if credentials.private_key_id else None
    try:
        return jwt.encode(claims, credentials.private_key, algorithm="RS256", headers=headers)
    except Exception as e:
        raise FirebaseAuthError(
            "Your Firebase service account private key could not be read. Upload the JSON key file "
            "exactly as Google generated it."
        ) from e


def mint_access_token(session: requests.Session, credentials: FirebaseCredentials) -> tuple[str, int]:
    """Exchange the service-account assertion for a short-lived token and its lifetime in seconds."""
    # stream=True so the body isn't buffered before _read_capped_body bounds it.
    response = session.post(
        credentials.token_endpoint,
        data={"grant_type": JWT_GRANT_TYPE, "assertion": build_jwt_assertion(credentials)},
        timeout=REQUEST_TIMEOUT_SECONDS,
        stream=True,
    )
    if not response.ok:
        detail = _error_detail(response, _read_truncated_body(response, MAX_ERROR_BODY_BYTES))
        raise FirebaseAuthError(f"Google refused to issue an access token: {detail}")

    raw = _read_capped_body(response, MAX_TOKEN_RESPONSE_BYTES)
    try:
        body = json.loads(raw)
    except ValueError:
        raise FirebaseAuthError("Google's token response could not be read as JSON.")
    if not isinstance(body, dict):
        raise FirebaseAuthError("Google's token response did not contain an access token.")
    token = body.get("access_token")
    if not token:
        raise FirebaseAuthError("Google's token response did not contain an access token.")
    # A literal `0` is a meaningful lifetime; folding it into the default with `or` would cache a
    # token that has already expired. Only a missing or unreadable value falls back.
    try:
        expires_in = int(body["expires_in"])
    except (KeyError, TypeError, ValueError):
        expires_in = JWT_ASSERTION_LIFETIME_SECONDS
    return str(token), expires_in


class AccessTokenProvider:
    """Mints Google access tokens and reuses them until they are close to expiring.

    Tokens last about an hour and a sync can run longer, so the token is refreshed on demand
    rather than minted once per job.
    """

    def __init__(self, session: requests.Session, credentials: FirebaseCredentials) -> None:
        self._session = session
        self._credentials = credentials
        self._token: Optional[str] = None
        self._expires_at: float = 0.0

    def token(self, force_refresh: bool = False) -> str:
        if force_refresh or self._token is None or time.time() >= self._expires_at:
            token, expires_in = mint_access_token(self._session, self._credentials)
            self._token = token
            self._expires_at = time.time() + max(expires_in - TOKEN_EXPIRY_SKEW_SECONDS, 0)
        return self._token


def _read_capped_body(response: requests.Response, cap: int) -> bytes:
    """Read one response body under a fixed cap on its decompressed size.

    Every request is issued with ``stream=True``, so nothing is materialised until this read. We
    ask for one byte past the cap: that detects an oversized body without ever buffering more than
    the cap itself, and ``decode_content=True`` applies the cap after decompression so a compressed
    payload can't expand past it. The connection is released either way.
    """
    try:
        raw: bytes = response.raw.read(cap + 1, decode_content=True)
    finally:
        response.close()
    if len(raw) > cap:
        raise FirebaseResponseTooLargeError(f"{RESPONSE_TOO_LARGE_ERROR}: exceeded {cap} bytes")
    return raw


def _read_truncated_body(response: requests.Response, cap: int) -> bytes:
    """Read at most ``cap`` bytes of a failed response, discarding the rest.

    The error paths exist to explain an HTTP failure that already happened, so an oversized body is
    truncated here instead of raising — otherwise a huge error page would mask the 401/403 the
    caller actually needs to see and turn a diagnosable failure into a size complaint.
    """
    try:
        return response.raw.read(cap, decode_content=True)
    finally:
        response.close()


def _error_detail(response: requests.Response, raw: bytes) -> str:
    """Google reports permanent problems in the body (`invalid_grant`, `PERMISSION_DENIED`)."""
    try:
        body = json.loads(raw)
    except ValueError:
        return f"status={response.status_code}"
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return f"status={response.status_code} status_code={error.get('status')} message={error.get('message')}"
        if error:
            return f"status={response.status_code} error={error} description={body.get('error_description')}"
    return f"status={response.status_code}"


def _request(
    session: requests.Session,
    tokens: AccessTokenProvider,
    method: str,
    url: str,
    *,
    params: Optional[dict[str, Any]] = None,
    json_body: Optional[dict[str, Any]] = None,
) -> Any:
    def _do(token: str) -> requests.Response:
        # stream=True so a page isn't buffered before _read_capped_body bounds it.
        return session.request(
            method,
            url,
            params=params,
            json=json_body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
            stream=True,
        )

    response = _do(tokens.token())
    # A token that expired mid-sync looks exactly like a bad one; re-mint once before giving up.
    if response.status_code == 401:
        # Release the connection without pulling a body we're about to discard.
        response.close()
        response = _do(tokens.token(force_refresh=True))

    if not response.ok:
        # `raise_for_status` reports status and URL only, so drain a tightly bounded prefix purely
        # to release the connection — the error path never needs a full page's worth of bytes.
        detail_body = _read_truncated_body(response, MAX_ERROR_BODY_BYTES)
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            # Google's structured error (status/message) lets callers tell a permanent,
            # database-configuration failure apart from a transient or unexpected one.
            e.args = (f"{e.args[0]} ({_error_detail(response, detail_body)})",)
            raise

    raw = _read_capped_body(response, MAX_RESPONSE_BYTES)
    if not raw:
        return None
    return json.loads(raw)


def decode_firestore_value(value: Any) -> Any:
    """Unwrap one Firestore typed value (`{"stringValue": "x"}`) into a plain Python value."""
    if not isinstance(value, dict):
        return None
    if "nullValue" in value:
        return None
    if "booleanValue" in value:
        return bool(value["booleanValue"])
    if "integerValue" in value:
        # Firestore encodes int64 as a JSON string to survive JavaScript's number range.
        try:
            return int(value["integerValue"])
        except (TypeError, ValueError):
            return None
    if "doubleValue" in value:
        try:
            return float(value["doubleValue"])
        except (TypeError, ValueError):
            return None
    for key in ("timestampValue", "stringValue", "bytesValue", "referenceValue"):
        if key in value:
            return value[key]
    if "geoPointValue" in value:
        point = value["geoPointValue"] or {}
        return {"latitude": point.get("latitude"), "longitude": point.get("longitude")}
    if "arrayValue" in value:
        return [decode_firestore_value(item) for item in (value["arrayValue"] or {}).get("values") or []]
    if "mapValue" in value:
        fields = (value["mapValue"] or {}).get("fields") or {}
        return {name: decode_firestore_value(item) for name, item in fields.items()}
    # Pipeline and expression wrappers exist in the API surface but never in a stored document.
    return None


def _as_column(value: Any) -> Any:
    """Give a column one stable type.

    Firestore and the Realtime Database are schemaless, so a nested value's shape varies document
    to document. Scalars land in their natural type; anything structured is serialized to JSON so
    the column stays a string no matter what the next document holds.
    """
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return value


def _relative_document_path(document_name: str) -> str:
    """Turn a full document resource name into the path Firestore addresses it by (`rooms/room1`)."""
    return document_name.split("/documents/", 1)[1] if "/documents/" in document_name else document_name


def flatten_firestore_document(document: dict[str, Any]) -> dict[str, Any]:
    """Turn one Firestore document into a flat row of top-level fields plus metadata columns."""
    path = _relative_document_path(str(document.get("name") or ""))
    fields = document.get("fields")
    if not isinstance(fields, dict):
        fields = {}

    row: dict[str, Any] = {field: _as_column(decode_firestore_value(value)) for field, value in fields.items()}
    row[FIRESTORE_ID_COLUMN] = path.rsplit("/", 1)[-1]
    row[FIRESTORE_PATH_COLUMN] = path
    row[FIRESTORE_CREATE_TIME_COLUMN] = document.get("createTime")
    row[FIRESTORE_UPDATE_TIME_COLUMN] = document.get("updateTime")
    return row


def flatten_auth_user(user: dict[str, Any]) -> dict[str, Any]:
    return {key: _as_column(value) for key, value in user.items() if key not in REDACTED_AUTH_USER_FIELDS}


def flatten_realtime_database_child(path: str, key: str, value: Any) -> dict[str, Any]:
    """Turn one Realtime Database child node into a row.

    Object children get their top-level entries promoted to columns; scalars land in `value`.
    """
    row: dict[str, Any] = {}
    if isinstance(value, dict):
        row = {name: _as_column(item) for name, item in value.items()}
    else:
        row[REALTIME_DATABASE_VALUE_COLUMN] = _as_column(value)
    row[REALTIME_DATABASE_KEY_COLUMN] = key
    row[REALTIME_DATABASE_PATH_COLUMN] = f"{path}/{key}"
    return row


def _firestore_documents_root(credentials: FirebaseCredentials) -> str:
    return f"{FIRESTORE_API_ROOT}/projects/{credentials.project_id}/databases/{credentials.database_id}/documents"


def list_collection_ids(
    session: requests.Session,
    tokens: AccessTokenProvider,
    credentials: FirebaseCredentials,
    parent_document_path: Optional[str] = None,
) -> list[str]:
    """List the Firestore collection ids directly under a parent.

    With no parent this lists the root-level collections. With a document path (`rooms/room1`) it
    lists that document's subcollection ids — the only way Firestore exposes subcollections.
    """
    root = _firestore_documents_root(credentials)
    if parent_document_path:
        url = f"{root}/{quote(parent_document_path, safe='/')}:listCollectionIds"
    else:
        url = f"{root}:listCollectionIds"
    collection_ids: list[str] = []
    page_token: Optional[str] = None

    for _ in range(MAX_PAGES):
        body: dict[str, Any] = {"pageSize": FIRESTORE_COLLECTION_IDS_PAGE_SIZE}
        if page_token:
            body["pageToken"] = page_token
        payload = _request(session, tokens, "POST", url, json_body=body) or {}
        collection_ids.extend(str(c) for c in payload.get("collectionIds") or [])
        page_token = payload.get("nextPageToken")
        if not page_token:
            break

    return collection_ids


def sample_firestore_incremental_fields(
    session: requests.Session,
    tokens: AccessTokenProvider,
    credentials: FirebaseCredentials,
    collection_id: str,
) -> list[IncrementalField]:
    """Find the fields of one collection that can carry an incremental sync's cursor.

    Firestore holds no schema to read, so the candidates come from a sample of real documents. A
    field qualifies only when every sampled document carries it with the same orderable type:
    Firestore drops a document from an ordered read when the ordered field is missing, so a field
    that only part of the collection sets would strand the rest of it permanently.
    """
    url = f"{_firestore_documents_root(credentials)}/{quote(collection_id, safe='')}"
    payload = _request(session, tokens, "GET", url, params={"pageSize": FIRESTORE_SCHEMA_SAMPLE_DOCUMENTS}) or {}
    documents = [document for document in payload.get("documents") or [] if isinstance(document, dict)]
    if not documents:
        return []

    shared = _orderable_field_types(documents[0])
    for document in documents[1:]:
        present = _orderable_field_types(document)
        shared = {name: field_type for name, field_type in shared.items() if present.get(name) == field_type}

    return rank_incremental_fields([incremental_field(name, field_type) for name, field_type in sorted(shared.items())])


def _orderable_field_types(document: dict[str, Any]) -> dict[str, IncrementalFieldType]:
    """Map the document's top-level fields to the cursor type each one could drive."""
    fields = document.get("fields")
    if not isinstance(fields, dict):
        return {}

    types: dict[str, IncrementalFieldType] = {}
    for name, value in fields.items():
        if not isinstance(value, dict) or not is_supported_incremental_field_name(name):
            continue
        # `flatten_firestore_document` writes the metadata columns last, so a document field of the
        # same name never reaches the row. The query would filter on the document field while the
        # watermark tracked the metadata column, and the two would drift apart.
        if name in FIRESTORE_METADATA_COLUMNS:
            continue
        for value_type, field_type in FIRESTORE_INCREMENTAL_VALUE_TYPES.items():
            if value_type in value:
                types[name] = field_type
                break
    return types


def get_incremental_fields(
    credentials: FirebaseCredentials, table_names: list[str]
) -> dict[str, list[IncrementalField]]:
    """Candidate cursor fields for each Firestore collection among `table_names`.

    Auth users and Realtime Database paths never appear: Identity Platform's `accounts:batchGet` and
    the Realtime Database REST API both page on a key and expose no timestamp filter to sync against.
    """
    collections = [
        (table, collection_id)
        for table, collection_id in ((table, _resolve_firestore_collection(table)) for table in table_names)
        if collection_id is not None
    ]
    if not collections:
        return {}

    if len(collections) > FIRESTORE_INCREMENTAL_DISCOVERY_LIMIT:
        # A specific sync-settings request already narrows `table_names` to the one table it's asking
        # about, so this only fires for a "list every table" request against a project with an unusually
        # large number of collections. Sampling every one of them, one synchronous request at a time,
        # would tie up a worker for the length of the request; the tables past the limit still appear in
        # the schema list, just without incremental candidates, and get sampled if a later request asks
        # about one of them by name.
        LOGGER.warning(
            f"Sampling incremental fields for the first {FIRESTORE_INCREMENTAL_DISCOVERY_LIMIT} of "
            f"{len(collections)} Firestore collections; the rest offer full refresh only until asked "
            "about individually."
        )
        collections = collections[:FIRESTORE_INCREMENTAL_DISCOVERY_LIMIT]

    tokens = AccessTokenProvider(_auth_session(credentials), credentials)
    api_session = _api_session(credentials)

    fields: dict[str, list[IncrementalField]] = {}
    for table, collection_id in collections:
        try:
            candidates = sample_firestore_incremental_fields(api_session, tokens, credentials, collection_id)
        except requests.HTTPError as e:
            # One unreadable collection must not empty the whole schema picker. That table offers
            # full refresh, and the sync itself still reports the failure.
            LOGGER.warning(f"Skipping incremental field discovery for Firestore collection {collection_id}: {e}")
            continue
        if candidates:
            fields[table] = candidates
    return fields


def _rfc3339(value: Any) -> str:
    """Render a watermark the way Firestore renders its own timestamps: UTC, `Z`-suffixed.

    The stored watermark is normally a datetime, but `process_incremental_value` passes a number
    through unchanged for a datetime cursor, so a numeric watermark is read as a Unix epoch.
    """
    if isinstance(value, datetime.datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=datetime.UTC)
    elif isinstance(value, int | float) and not isinstance(value, bool):
        moment = datetime.datetime.fromtimestamp(value, tz=datetime.UTC)
    else:
        raise FirebaseConfigError(
            "PostHog couldn't read the last value this table synced up to. Reset the table's sync to "
            "start it again from the beginning."
        )
    return moment.astimezone(datetime.UTC).isoformat().replace("+00:00", "Z")


def _firestore_cursor_value(field_type: IncrementalFieldType, value: Any) -> dict[str, Any]:
    if field_type == IncrementalFieldType.Integer:
        # Firestore orders integers and doubles together, so a field sampled as an integer can still
        # carry a fractional value on some document. Truncating that watermark with int() would send
        # a lower bound the fractional row is still above, importing it again on every later run.
        if isinstance(value, float) and not value.is_integer():
            return {"doubleValue": value}
        # The REST API carries int64 as a JSON string so the value survives a JavaScript parser.
        return {"integerValue": str(int(value))}
    return {"timestampValue": _rfc3339(value)}


def _firestore_type_ceiling(field_type: IncrementalFieldType) -> dict[str, Any]:
    if field_type == IncrementalFieldType.Integer:
        return {"integerValue": str(FIRESTORE_MAX_INTEGER)}
    return {"timestampValue": FIRESTORE_MAX_TIMESTAMP}


def _incremental_filter(field_name: str, field_type: IncrementalFieldType, last_value: Any) -> dict[str, Any]:
    """Bound a read to the rows after the watermark, and to the cursor field's own type.

    Both bounds are needed. See `FIRESTORE_MAX_TIMESTAMP` for what a lone lower bound would match.
    """
    field = {"fieldPath": field_name}
    return {
        "compositeFilter": {
            "op": "AND",
            "filters": [
                {
                    "fieldFilter": {
                        "field": field,
                        "op": "GREATER_THAN",
                        "value": _firestore_cursor_value(field_type, last_value),
                    }
                },
                {
                    "fieldFilter": {
                        "field": field,
                        "op": "LESS_THAN_OR_EQUAL",
                        "value": _firestore_type_ceiling(field_type),
                    }
                },
            ],
        }
    }


def _document_cursor(document: dict[str, Any], field_name: str) -> Optional[tuple[dict[str, Any], str]]:
    """Position of one row in the ordered read: its cursor field value, then its document name."""
    fields = document.get("fields")
    value = fields.get(field_name) if isinstance(fields, dict) else None
    name = document.get("name")
    if not isinstance(value, dict) or not isinstance(name, str):
        return None
    return value, name


def iter_firestore_documents_incremental(
    session: requests.Session,
    tokens: AccessTokenProvider,
    credentials: FirebaseCredentials,
    collection_id: str,
    field_name: str,
    field_type: IncrementalFieldType,
    last_value: Any,
    resumable_source_manager: ResumableSourceManager[FirebaseResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Read the documents of one collection that changed after the watermark, oldest first.

    `runQuery` is the only Firestore read that filters, and it answers with no page token, so each
    page starts after the position of the previous page's last row. Ordering by the cursor field and
    then the document id keeps that position unambiguous when documents share a cursor value.
    """
    url = f"{_firestore_documents_root(credentials)}:runQuery"
    query: dict[str, Any] = {
        "from": [{"collectionId": collection_id}],
        "where": _incremental_filter(field_name, field_type, last_value),
        "orderBy": [
            {"field": {"fieldPath": field_name}, "direction": "ASCENDING"},
            {"field": {"fieldPath": FIRESTORE_DOCUMENT_ID_FIELD}, "direction": "ASCENDING"},
        ],
        "limit": FIRESTORE_PAGE_SIZE,
    }
    cursor = _resume_incremental_cursor(resumable_source_manager, logger, collection_id)

    for _ in range(MAX_PAGES):
        page_query = dict(query)
        if cursor is not None:
            value, name = cursor
            page_query["startAt"] = {"values": [value, {"referenceValue": name}], "before": False}
        payload = _request(session, tokens, "POST", url, json_body={"structuredQuery": page_query}) or []

        # A `runQuery` stream also carries entries that only report read progress and hold no document.
        documents = [
            entry["document"]
            for entry in payload
            if isinstance(entry, dict) and isinstance(entry.get("document"), dict)
        ]
        if documents:
            yield [flatten_firestore_document(document) for document in documents]

        if len(documents) < FIRESTORE_PAGE_SIZE:
            break

        cursor = _document_cursor(documents[-1], field_name)
        if cursor is None:
            # The query orders on this field, so Firestore cannot return a document without it.
            logger.warning(f"Stopping Firestore collection {collection_id}: last document has no {field_name}")
            break
        # Saved after yielding so a crash re-yields the last page instead of skipping it.
        resumable_source_manager.save_state(
            FirebaseResumeConfig(cursor=cursor[1], incremental_value=json.dumps(cursor[0]))
        )

    resumable_source_manager.clear_state()


def _resume_incremental_cursor(
    resumable_source_manager: ResumableSourceManager[FirebaseResumeConfig],
    logger: FilteringBoundLogger,
    collection_id: str,
) -> Optional[tuple[dict[str, Any], str]]:
    if not resumable_source_manager.can_resume():
        return None
    resume = resumable_source_manager.load_state()
    # A cursor saved with no field value beside it came from a full-refresh read and names a page
    # token rather than a document, so it cannot position an ordered query.
    if resume is None or resume.incremental_value is None:
        return None
    logger.debug(f"Resuming incremental Firestore collection {collection_id} from cursor={resume.cursor}")
    return json.loads(resume.incremental_value), resume.cursor


def iter_firestore_documents(
    session: requests.Session,
    tokens: AccessTokenProvider,
    credentials: FirebaseCredentials,
    collection_id: str,
    resumable_source_manager: ResumableSourceManager[FirebaseResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{_firestore_documents_root(credentials)}/{quote(collection_id, safe='')}"
    page_token = _resume_cursor(resumable_source_manager, logger, f"Firestore collection {collection_id}")

    for _ in range(MAX_PAGES):
        params: dict[str, Any] = {"pageSize": FIRESTORE_PAGE_SIZE}
        if page_token:
            params["pageToken"] = page_token
        payload = _request(session, tokens, "GET", url, params=params) or {}

        documents = [doc for doc in payload.get("documents") or [] if isinstance(doc, dict)]
        if documents:
            yield [flatten_firestore_document(document) for document in documents]

        page_token = payload.get("nextPageToken")
        if not page_token:
            break
        # Saved after yielding so a crash re-yields the last page instead of skipping it.
        resumable_source_manager.save_state(FirebaseResumeConfig(cursor=page_token))

    resumable_source_manager.clear_state()


def _run_query_documents(results: Any) -> list[dict[str, Any]]:
    """Pull the documents out of a `runQuery` response, skipping readTime-only entries."""
    return [
        result["document"]
        for result in results
        if isinstance(result, dict) and isinstance(result.get("document"), dict)
    ]


def iter_firestore_collection_group(
    session: requests.Session,
    tokens: AccessTokenProvider,
    credentials: FirebaseCredentials,
    collection_id: str,
    resumable_source_manager: ResumableSourceManager[FirebaseResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Read every document in a Firestore subcollection.

    `listDocuments` reads only a collection under a fixed path, so a subcollection like `messages`
    that lives under many parent documents needs a collection-group query instead. `runQuery` with
    `allDescendants=true` returns every document in any collection with this id, at any depth.
    """
    url = f"{_firestore_documents_root(credentials)}:runQuery"
    # `runQuery` has no page token, so paging is done by ordering on the document name and resuming
    # after the last one read. The cursor is that full document resource name.
    cursor = _resume_cursor(resumable_source_manager, logger, f"Firestore collection group {collection_id}")

    for _ in range(MAX_PAGES):
        query: dict[str, Any] = {
            "from": [{"collectionId": collection_id, "allDescendants": True}],
            "orderBy": [{"field": {"fieldPath": "__name__"}, "direction": "ASCENDING"}],
            "limit": FIRESTORE_PAGE_SIZE,
        }
        if cursor:
            query["startAt"] = {"values": [{"referenceValue": cursor}], "before": False}
        results = _request(session, tokens, "POST", url, json_body={"structuredQuery": query}) or []

        documents = _run_query_documents(results)
        if documents:
            yield [flatten_firestore_document(document) for document in documents]

        if len(documents) < FIRESTORE_PAGE_SIZE:
            break
        next_cursor = documents[-1].get("name")
        if not next_cursor:
            break
        cursor = str(next_cursor)
        # Saved after yielding so a crash re-yields the last page instead of skipping it.
        resumable_source_manager.save_state(FirebaseResumeConfig(cursor=cursor))

    resumable_source_manager.clear_state()


def iter_auth_users(
    session: requests.Session,
    tokens: AccessTokenProvider,
    credentials: FirebaseCredentials,
    resumable_source_manager: ResumableSourceManager[FirebaseResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{IDENTITY_TOOLKIT_API_ROOT}/projects/{credentials.project_id}/accounts:batchGet"
    page_token = _resume_cursor(resumable_source_manager, logger, "Firebase Auth users")

    for _ in range(MAX_PAGES):
        params: dict[str, Any] = {"maxResults": AUTH_USERS_PAGE_SIZE}
        if page_token:
            params["nextPageToken"] = page_token
        payload = _request(session, tokens, "GET", url, params=params) or {}

        users = [user for user in payload.get("users") or [] if isinstance(user, dict)]
        if users:
            yield [flatten_auth_user(user) for user in users]

        page_token = payload.get("nextPageToken")
        if not page_token or not users:
            break
        resumable_source_manager.save_state(FirebaseResumeConfig(cursor=page_token))

    resumable_source_manager.clear_state()


def iter_realtime_database(
    session: requests.Session,
    tokens: AccessTokenProvider,
    credentials: FirebaseCredentials,
    path: str,
    resumable_source_manager: ResumableSourceManager[FirebaseResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    if not credentials.realtime_database_url:
        raise FirebaseConfigError("This table needs a Realtime Database URL on the source.")

    base_url = validate_realtime_database_url(credentials.realtime_database_url)
    url = f"{base_url}/{quote(path, safe='/')}.json"
    cursor = _resume_cursor(resumable_source_manager, logger, f"Realtime Database path {path}")

    for _ in range(MAX_PAGES):
        # Ordering by "$key" is always indexed, so paging a large node never needs a rules change.
        # JSON-quoted values are what the REST API expects for orderBy/startAt.
        params: dict[str, Any] = {"orderBy": '"$key"', "limitToFirst": REALTIME_DATABASE_PAGE_SIZE}
        if cursor is not None:
            params["startAt"] = json.dumps(cursor)
        payload = _request(session, tokens, "GET", url, params=params)

        children = _realtime_database_children(payload)
        if children is None:
            # A scalar node has no children to page through; it is the single row.
            if payload is not None:
                scalar_row: dict[str, Any] = {
                    REALTIME_DATABASE_VALUE_COLUMN: _as_column(payload),
                    REALTIME_DATABASE_KEY_COLUMN: path.rsplit("/", 1)[-1],
                    REALTIME_DATABASE_PATH_COLUMN: path,
                }
                yield [scalar_row]
            break

        # `startAt` is inclusive, so each page after the first repeats the cursor row.
        rows = [(key, value) for key, value in children if cursor is None or key > cursor]
        if rows:
            yield [flatten_realtime_database_child(path, key, value) for key, value in rows]

        if len(children) < REALTIME_DATABASE_PAGE_SIZE or not rows:
            break
        cursor = rows[-1][0]
        resumable_source_manager.save_state(FirebaseResumeConfig(cursor=cursor))

    resumable_source_manager.clear_state()


def _realtime_database_children(payload: Any) -> Optional[list[tuple[str, Any]]]:
    """Normalize a Realtime Database node into sorted (key, value) pairs, or None if it has none.

    A node whose keys are consecutive integers comes back as a JSON array, so the index is the key.
    """
    if isinstance(payload, dict):
        # JSON object keys are always strings, but say so explicitly so the row's key column
        # keeps one type regardless of what the decoder handed back.
        children: list[tuple[str, Any]] = [(str(key), value) for key, value in payload.items()]
        return sorted(children)
    if isinstance(payload, list):
        return [(str(index), value) for index, value in enumerate(payload) if value is not None]
    return None


def _resume_cursor(
    resumable_source_manager: ResumableSourceManager[FirebaseResumeConfig],
    logger: FilteringBoundLogger,
    label: str,
) -> Optional[str]:
    if not resumable_source_manager.can_resume():
        return None
    resume = resumable_source_manager.load_state()
    if resume is None:
        return None
    # A checkpoint carrying a field value came from an ordered incremental read, so its cursor names
    # a document rather than a page token. Every surface here pages on a token, which Firestore and
    # Identity Platform would both reject.
    if resume.incremental_value is not None:
        return None
    logger.debug(f"Resuming {label} from cursor={resume.cursor}")
    return resume.cursor


def get_rows(
    credentials: FirebaseCredentials,
    table_name: str,
    resumable_source_manager: ResumableSourceManager[FirebaseResumeConfig],
    logger: FilteringBoundLogger,
    incremental_cursor: Optional[FirestoreIncrementalCursor] = None,
) -> Iterator[list[dict[str, Any]]]:
    tokens = AccessTokenProvider(_auth_session(credentials), credentials)

    if table_name == AUTH_USERS_TABLE:
        # Identity Platform hands back `passwordHash`, `salt` and `rawPassword` in the raw response,
        # and a sample is captured before `flatten_auth_user` strips them — so this surface is read
        # over a session that never captures at all.
        auth_session = _api_session(credentials, capture=False)
        yield from iter_auth_users(auth_session, tokens, credentials, resumable_source_manager, logger)
        return

    api_session = _api_session(credentials)

    # Incremental sync isn't supported for a collection group yet, so it always reads in full —
    # `firebase_source` never resolves an incremental cursor for one either.
    collection_group_id = _resolve_firestore_collection_group(table_name)
    if collection_group_id is not None:
        yield from iter_firestore_collection_group(
            api_session, tokens, credentials, collection_group_id, resumable_source_manager, logger
        )
        return

    collection_id = _resolve_firestore_collection(table_name)
    if collection_id is not None:
        if incremental_cursor is not None:
            yield from iter_firestore_documents_incremental(
                api_session,
                tokens,
                credentials,
                collection_id,
                incremental_cursor.field_name,
                incremental_cursor.field_type,
                incremental_cursor.last_value,
                resumable_source_manager,
                logger,
            )
        else:
            yield from iter_firestore_documents(
                api_session, tokens, credentials, collection_id, resumable_source_manager, logger
            )
        return

    path = _resolve_realtime_database_path(credentials, table_name)
    if path is not None:
        yield from iter_realtime_database(api_session, tokens, credentials, path, resumable_source_manager, logger)
        return

    raise FirebaseConfigError(f"Firebase table {table_name} is not configured on this source.")


def _resolve_firestore_collection(table_name: str) -> Optional[str]:
    """Recover the root Firestore collection id a table name was built from (`rooms`)."""
    prefix = firestore_table_name("")
    if not table_name.startswith(prefix) or len(table_name) == len(prefix):
        return None
    collection_id = table_name[len(prefix) :]
    # A root collection id can never contain `/`, so a remaining slash marks a collection-group table.
    if "/" in collection_id:
        return None
    return collection_id


def _resolve_firestore_collection_group(table_name: str) -> Optional[str]:
    """Recover the collection-group id a subcollection table was built from (`messages`)."""
    prefix = firestore_collection_group_table_name("")
    if not table_name.startswith(prefix) or len(table_name) == len(prefix):
        return None
    return table_name[len(prefix) :]


def _resolve_realtime_database_path(credentials: FirebaseCredentials, table_name: str) -> Optional[str]:
    for path in credentials.realtime_database_paths:
        if realtime_database_table_name(path) == table_name:
            return path
    return None


def _sample_firestore_document_paths(
    session: requests.Session,
    tokens: AccessTokenProvider,
    credentials: FirebaseCredentials,
    collection_id: str,
    *,
    as_collection_group: bool,
    limit: int,
) -> list[str]:
    """Return the paths of a few documents in a collection, to probe them for subcollections."""
    if as_collection_group:
        # A subcollection spans many parents, so a collection-group query samples it. Only the
        # document names are needed here, so `select` keeps the response small.
        query = {
            "from": [{"collectionId": collection_id, "allDescendants": True}],
            "select": {"fields": [{"fieldPath": "__name__"}]},
            "limit": limit,
        }
        results = (
            _request(
                session,
                tokens,
                "POST",
                f"{_firestore_documents_root(credentials)}:runQuery",
                json_body={"structuredQuery": query},
            )
            or []
        )
        documents = _run_query_documents(results)
    else:
        # `showMissing` surfaces parent documents that exist only to hold a subcollection. Without it
        # `listDocuments` hides them, so a collection written only under `parent/{id}/child` is never
        # sampled and stays invisible. A missing document returns a name and no fields, which is all
        # this probe reads. The flag is incompatible with `where`/`orderBy`, which this call omits.
        url = f"{_firestore_documents_root(credentials)}/{quote(collection_id, safe='')}"
        payload = _request(session, tokens, "GET", url, params={"pageSize": limit, "showMissing": "true"}) or {}
        documents = [doc for doc in payload.get("documents") or [] if isinstance(doc, dict)]

    return [_relative_document_path(str(doc["name"])) for doc in documents if doc.get("name")]


@frozen
class FirestoreCollections:
    """The Firestore collections a source can read: root collections and subcollection groups."""

    root_ids: list[str]
    subcollection_ids: list[str]


def discover_firestore_collections(
    session: requests.Session, tokens: AccessTokenProvider, credentials: FirebaseCredentials
) -> FirestoreCollections:
    """Return the Firestore collections this source can read.

    Root collections come from `listCollectionIds`. Subcollections are found by sampling documents
    and asking each for its child collection ids, following nesting down to the depth cap. A
    subcollection reads as a collection group keyed by its id, so each subcollection id is surfaced
    once even when it lives under more than one parent — but a subcollection is kept separate from a
    root collection of the same id, because the two read through different queries.
    """
    root_ids: list[str] = []
    seen_root_ids: set[str] = set()
    for collection_id in list_collection_ids(session, tokens, credentials):
        if collection_id not in seen_root_ids:
            seen_root_ids.add(collection_id)
            root_ids.append(collection_id)

    subcollection_ids: list[str] = []
    seen_subcollection_ids: set[str] = set()
    # Each frontier entry is (collection id, whether it is sampled as a collection group).
    frontier: list[tuple[str, bool]] = [(collection_id, False) for collection_id in root_ids]

    for _ in range(FIRESTORE_MAX_SUBCOLLECTION_DEPTH):
        next_frontier: list[tuple[str, bool]] = []
        for collection_id, as_collection_group in frontier:
            child_ids: set[str] = set()
            for document_path in _sample_firestore_document_paths(
                session,
                tokens,
                credentials,
                collection_id,
                as_collection_group=as_collection_group,
                limit=FIRESTORE_SUBCOLLECTION_SAMPLE_DOCUMENTS,
            ):
                child_ids.update(list_collection_ids(session, tokens, credentials, parent_document_path=document_path))
            for child_id in sorted(child_ids):
                if child_id in seen_subcollection_ids:
                    continue
                seen_subcollection_ids.add(child_id)
                subcollection_ids.append(child_id)
                next_frontier.append((child_id, True))
        if not next_frontier:
            break
        frontier = next_frontier

    return FirestoreCollections(root_ids=root_ids, subcollection_ids=subcollection_ids)


def _firestore_discovery_cache_key(credentials: FirebaseCredentials) -> str:
    # What discovery returns is fixed by the project, the database, and the service account's read
    # scope, so those three identify the entry. All are non-secret identifiers.
    return f"@dwh/firebase/{credentials.project_id}/{credentials.database_id}/{credentials.client_email}/collections"


def _discover_firestore_collections_cached(
    session: requests.Session,
    tokens: AccessTokenProvider,
    credentials: FirebaseCredentials,
    force_refresh: bool = False,
) -> FirestoreCollections:
    """Cached wrapper around `discover_firestore_collections`.

    Discovery fires many sequential requests on the synchronous schema-lookup path, so callers that
    don't need fresh data read through this cache; the user-triggered refresh passes
    `force_refresh=True`. A failed walk raises before the cache is written, so the previous value
    survives. See `FIRESTORE_DISCOVERY_CACHE_TTL_SECONDS` for why this mirrors the Slack source's
    channel-discovery cache.
    """
    cache_key = _firestore_discovery_cache_key(credentials)
    if not force_refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
    discovered = discover_firestore_collections(session, tokens, credentials)
    cache.set(cache_key, discovered, FIRESTORE_DISCOVERY_CACHE_TTL_SECONDS)
    return discovered


def _dedupe_by_storage_name(table_names: list[str]) -> list[str]:
    """Drop any later table whose normalized storage name repeats an earlier one.

    Downstream naming flattens distinct source names onto one warehouse table, and two schemas that
    share a storage name would fight over one `DataWarehouseTable` row. Keeping the first occurrence
    stops that silent overwrite.
    """
    seen: set[str] = set()
    unique: list[str] = []
    for name in table_names:
        storage_name = NamingConvention.normalize_identifier(name)
        if storage_name in seen:
            LOGGER.warning(f"Skipping Firebase table {name}: storage name {storage_name} is already taken")
            continue
        seen.add(storage_name)
        unique.append(name)
    return unique


def get_tables(credentials: FirebaseCredentials, force_refresh: bool = False) -> list[str]:
    """List every table this source can sync: Auth users, Firestore collections, configured paths."""
    firestore_tables: list[str] = []

    tokens = AccessTokenProvider(_auth_session(credentials), credentials)
    api_session = _api_session(credentials)
    try:
        collections = _discover_firestore_collections_cached(
            api_session, tokens, credentials, force_refresh=force_refresh
        )
        firestore_tables = [firestore_table_name(collection_id) for collection_id in collections.root_ids]
        firestore_tables += [
            firestore_collection_group_table_name(collection_id) for collection_id in collections.subcollection_ids
        ]
    except requests.HTTPError as e:
        # A project with no Firestore database answers 404, a service account without the
        # Datastore role answers 403, and a default database provisioned in Datastore mode
        # (rather than Native mode) answers 400 — the Documents API this source reads is
        # Native-mode only. None of these should hide the tables the source can still read.
        status = e.response.status_code if e.response is not None else None
        if status not in (403, 404) and not (status == 400 and "datastore mode" in str(e).lower()):
            raise
        LOGGER.warning(f"Skipping Firestore collections for Firebase project {credentials.project_id}: {status}")

    rtdb_tables = [realtime_database_table_name(path) for path in credentials.realtime_database_paths]
    return _dedupe_by_storage_name([AUTH_USERS_TABLE, *firestore_tables, *rtdb_tables])


def validate_credentials(credentials: FirebaseCredentials) -> tuple[bool, Optional[str]]:
    """Mint a token — the cheapest end-to-end proof the service account key works."""
    if credentials.realtime_database_url:
        try:
            validate_realtime_database_url(credentials.realtime_database_url)
        except FirebaseConfigError as e:
            return False, str(e)
        if not credentials.realtime_database_paths:
            return False, "Add at least one Realtime Database path to sync, for example `rooms`."

    try:
        mint_access_token(_auth_session(credentials), credentials)
    except FirebaseAuthError as e:
        return False, str(e)
    except Exception:
        return False, "Could not reach Google with the provided Firebase service account key."
    return True, None


def resolve_incremental_cursor(
    table_name: str,
    should_use_incremental_field: bool,
    field_name: Optional[str],
    field_type: Optional[IncrementalFieldType],
    last_value: Any,
) -> Optional[FirestoreIncrementalCursor]:
    """The cursor to read this table with, or None to read all of it.

    Only Firestore collections filter server-side. An incremental setting on any other table would
    otherwise read every row while the pipeline merged the result as if it were a delta.
    """
    if not should_use_incremental_field or _resolve_firestore_collection(table_name) is None:
        return None
    if not field_name or field_type is None:
        raise FirebaseConfigError(
            f"The table {table_name} is set to sync incrementally but has no field to sync on. "
            "Pick one in the table's sync settings, or switch the table to full refresh."
        )
    if field_type not in FIRESTORE_INCREMENTAL_VALUE_TYPES.values():
        raise FirebaseConfigError(
            f"Firestore can't sync on {field_name} because it isn't a timestamp or a number. "
            "Pick a different field in the table's sync settings, or switch the table to full refresh."
        )
    if not is_supported_incremental_field_name(field_name):
        raise FirebaseConfigError(
            f"Firestore can't sort on a field named {field_name}. It reads the dots and other punctuation "
            "in a field name as a path into a nested field. Pick a different field in the table's sync "
            "settings, or switch the table to full refresh."
        )
    if last_value is None:
        last_value = incremental_type_to_initial_value(field_type)
    return FirestoreIncrementalCursor(field_name=field_name, field_type=field_type, last_value=last_value)


def firebase_source(
    credentials: FirebaseCredentials,
    table_name: str,
    resumable_source_manager: ResumableSourceManager[FirebaseResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    incremental_field_name: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    collection_group_id = _resolve_firestore_collection_group(table_name)
    collection_id = _resolve_firestore_collection(table_name)
    is_firestore = collection_group_id is not None or collection_id is not None
    # `resolve_incremental_cursor` resolves a cursor only for a root collection: it recovers the
    # collection id through `_resolve_firestore_collection`, which returns None for a collection
    # group's own `firestore_collection_group/` prefix, and `get_rows` never takes a cursor down the
    # collection-group path either — incremental sync isn't supported for a collection group yet.
    incremental_cursor = resolve_incremental_cursor(
        table_name,
        should_use_incremental_field,
        incremental_field_name,
        incremental_field_type,
        db_incremental_field_last_value,
    )

    if table_name == AUTH_USERS_TABLE:
        primary_keys = AUTH_USERS_PRIMARY_KEY
    elif collection_group_id is not None:
        # A collection group can hold documents with the same id under different parents, so the
        # full document path is the only unique key.
        primary_keys = [FIRESTORE_PATH_COLUMN]
    elif collection_id is not None:
        primary_keys = [FIRESTORE_ID_COLUMN]
    else:
        primary_keys = [REALTIME_DATABASE_KEY_COLUMN]

    return SourceResponse(
        name=table_name,
        items=lambda: get_rows(
            credentials=credentials,
            table_name=table_name,
            resumable_source_manager=resumable_source_manager,
            logger=logger,
            incremental_cursor=incremental_cursor,
        ),
        primary_keys=primary_keys,
        # An incremental read is ordered by the cursor field, so the pipeline can advance the
        # watermark after every page. Every other read arrives ordered by document key, which is no
        # watermark at all, and declaring one would freeze the sync at the highest key it had seen.
        sort_mode="asc" if incremental_cursor is not None else None,
        # Firestore documents run to 1 MiB each, so chunks are capped tighter than the default.
        chunk_size=2000,
        chunk_size_bytes=100 * 1024 * 1024,
        partition_count=1 if is_firestore else None,
        partition_size=1 if is_firestore else None,
        partition_mode="datetime" if is_firestore else None,
        partition_format="month" if is_firestore else None,
        partition_keys=[FIRESTORE_CREATE_TIME_COLUMN] if is_firestore else None,
    )
