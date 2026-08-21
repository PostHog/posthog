import json
import time
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import quote, urlparse

import jwt
import requests
import structlog
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.firebase.settings import (
    AUTH_USERS_PAGE_SIZE,
    AUTH_USERS_PRIMARY_KEY,
    AUTH_USERS_TABLE,
    FIRESTORE_API_ROOT,
    FIRESTORE_COLLECTION_IDS_PAGE_SIZE,
    FIRESTORE_CREATE_TIME_COLUMN,
    FIRESTORE_ID_COLUMN,
    FIRESTORE_PAGE_SIZE,
    FIRESTORE_PATH_COLUMN,
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
    firestore_table_name,
    realtime_database_table_name,
)

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


def flatten_firestore_document(document: dict[str, Any]) -> dict[str, Any]:
    """Turn one Firestore document into a flat row of top-level fields plus metadata columns."""
    name = str(document.get("name") or "")
    path = name.split("/documents/", 1)[1] if "/documents/" in name else name
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
    session: requests.Session, tokens: AccessTokenProvider, credentials: FirebaseCredentials
) -> list[str]:
    """List the root-level Firestore collections in the project's database."""
    url = f"{_firestore_documents_root(credentials)}:listCollectionIds"
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
    logger.debug(f"Resuming {label} from cursor={resume.cursor}")
    return resume.cursor


def get_rows(
    credentials: FirebaseCredentials,
    table_name: str,
    resumable_source_manager: ResumableSourceManager[FirebaseResumeConfig],
    logger: FilteringBoundLogger,
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

    collection_id = _resolve_firestore_collection(table_name)
    if collection_id is not None:
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
    """Recover the Firestore collection id a table name was built from."""
    prefix = firestore_table_name("")
    if not table_name.startswith(prefix) or len(table_name) == len(prefix):
        return None
    return table_name[len(prefix) :]


def _resolve_realtime_database_path(credentials: FirebaseCredentials, table_name: str) -> Optional[str]:
    for path in credentials.realtime_database_paths:
        if realtime_database_table_name(path) == table_name:
            return path
    return None


def get_tables(credentials: FirebaseCredentials) -> list[str]:
    """List every table this source can sync: Auth users, Firestore collections, configured paths."""
    tables: list[str] = [AUTH_USERS_TABLE]

    tokens = AccessTokenProvider(_auth_session(credentials), credentials)
    api_session = _api_session(credentials)
    try:
        collection_ids = list_collection_ids(api_session, tokens, credentials)
        tables.extend(firestore_table_name(collection_id) for collection_id in collection_ids)
    except requests.HTTPError as e:
        # A project with no Firestore database answers 404, a service account without the
        # Datastore role answers 403, and a default database provisioned in Datastore mode
        # (rather than Native mode) answers 400 — the Documents API this source reads is
        # Native-mode only. None of these should hide the tables the source can still read.
        status = e.response.status_code if e.response is not None else None
        if status not in (403, 404) and not (status == 400 and "datastore mode" in str(e).lower()):
            raise
        LOGGER.warning(f"Skipping Firestore collections for Firebase project {credentials.project_id}: {status}")

    tables.extend(realtime_database_table_name(path) for path in credentials.realtime_database_paths)
    return tables


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


def firebase_source(
    credentials: FirebaseCredentials,
    table_name: str,
    resumable_source_manager: ResumableSourceManager[FirebaseResumeConfig],
    logger: FilteringBoundLogger,
) -> SourceResponse:
    is_firestore = _resolve_firestore_collection(table_name) is not None

    if table_name == AUTH_USERS_TABLE:
        primary_keys = AUTH_USERS_PRIMARY_KEY
    elif is_firestore:
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
        ),
        primary_keys=primary_keys,
        # Rows arrive ordered by document key, not by time, and no surface here filters on a
        # timestamp, so there is no ascending watermark to declare.
        sort_mode=None,
        # Firestore documents run to 1 MiB each, so chunks are capped tighter than the default.
        chunk_size=2000,
        chunk_size_bytes=100 * 1024 * 1024,
        partition_count=1 if is_firestore else None,
        partition_size=1 if is_firestore else None,
        partition_mode="datetime" if is_firestore else None,
        partition_format="month" if is_firestore else None,
        partition_keys=[FIRESTORE_CREATE_TIME_COLUMN] if is_firestore else None,
    )
