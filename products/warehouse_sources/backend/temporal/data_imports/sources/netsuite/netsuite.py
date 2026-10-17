import re
import time
import datetime as dt
import dataclasses
from collections.abc import Callable, Iterator
from typing import Any

import jwt
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from oauthlib.oauth1 import SIGNATURE_HMAC_SHA256
from requests_oauthlib import OAuth1

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.settings import (
    ENDPOINT_CONFIGS,
    PAGE_SIZE,
    PARTITION_SIZE,
    NetSuiteEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 120
MAX_ATTEMPTS = 5
MAX_RETRY_DELAY_SECONDS = 60
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
JWT_LIFETIME_SECONDS = 300
TOKEN_REFRESH_MARGIN_SECONDS = 60
# The watermark is UTC but the index-friendly pre-filter compares in the NetSuite session time zone.
# A one-day margin covers every time zone offset.
SESSION_TIMEZONE_MARGIN = dt.timedelta(days=1)

# The account ID becomes a subdomain of suitetalk.api.netsuite.com, so it must stay a bare DNS label.
_ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)?$")
_SESSION_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_SESSION_TS_FORMAT = "YYYY-MM-DD HH24:MI:SS"
_UTC_TS_FORMAT = 'YYYY-MM-DD"T"HH24:MI:SS"Z"'
_CURSOR_TS_ALIAS = "ph_cursor_ts"

AUTH_FAILED_MESSAGE = (
    "NetSuite rejected the credentials. Check the account ID and credentials, "
    "and make sure the integration record and its token or certificate are active."
)
REST_PERMISSION_MESSAGE = (
    "Your NetSuite role can't use REST web services. Give the role the REST Web Services permission "
    "and the login permission for your authentication method (Log in using OAuth 2.0 Access Tokens, "
    "or Log in using Access Tokens)."
)
RECORD_PERMISSION_MESSAGE = (
    "Your NetSuite role can't read one of the selected tables. Give the role view permission for that record, "
    "or deselect the table."
)
OAUTH_REJECTED_PREFIX = "NetSuite rejected the OAuth 2.0 token request"
INVALID_ACCOUNT_ID_MESSAGE = (
    "Invalid NetSuite account ID. Enter the account ID from Setup > Company > Company Information, "
    "for example 1234567 or 1234567_SB1."
)


class NetSuiteError(Exception):
    pass


class NetSuiteTokenError(NetSuiteError):
    pass


@dataclasses.dataclass(frozen=True)
class NetSuiteOAuth2Credentials:
    client_id: str
    certificate_id: str
    private_key: str = dataclasses.field(repr=False)


@dataclasses.dataclass(frozen=True)
class NetSuiteTBACredentials:
    consumer_key: str
    consumer_secret: str = dataclasses.field(repr=False)
    token_id: str
    token_secret: str = dataclasses.field(repr=False)


NetSuiteCredentials = NetSuiteOAuth2Credentials | NetSuiteTBACredentials


@dataclasses.dataclass(frozen=True)
class NetSuiteAccount:
    # TBA signs requests with the account ID in its canonical form (`1234567_SB1`), while the host uses
    # the DNS form (`1234567-sb1`).
    realm: str
    host: str

    @classmethod
    def parse(cls, account_id: str) -> "NetSuiteAccount":
        value = account_id.strip()
        if not _ACCOUNT_ID_RE.match(value):
            raise NetSuiteError(INVALID_ACCOUNT_ID_MESSAGE)
        return cls(
            realm=value.upper().replace("-", "_"),
            host=f"{value.lower().replace('_', '-')}.suitetalk.api.netsuite.com",
        )

    @property
    def base_url(self) -> str:
        return f"https://{self.host}"


@dataclasses.dataclass(frozen=True)
class NetSuiteResumeConfig:
    # Keyset cursor of the last row yielded: the session timestamp first when the sync is incremental,
    # then the primary key values.
    cursor: list[str]
    incremental_field: str | None = None


@dataclasses.dataclass(frozen=True)
class NetSuiteProbeResult:
    error: str | None = None
    # The credentials work, but the role can't read the probed record.
    record_denied: bool = False


def _error_detail(response: requests.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    details = [
        item["detail"] for item in body.get("o:errorDetails") or [] if isinstance(item, dict) and item.get("detail")
    ]
    if details:
        return " ".join(details)
    if body.get("error"):
        return ": ".join(part for part in (body.get("error"), body.get("error_description")) if part)
    title = body.get("title")
    return title if isinstance(title, str) else None


def _load_signing_key(private_key: str) -> tuple[rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey, str]:
    try:
        key = serialization.load_pem_private_key(private_key.strip().encode(), password=None)
    except (ValueError, TypeError) as error:
        raise NetSuiteTokenError(
            "The private key isn't a valid PEM private key. Paste the unencrypted key that matches the "
            "certificate you uploaded to NetSuite, including the BEGIN and END lines."
        ) from error
    if isinstance(key, rsa.RSAPrivateKey):
        return key, "PS256"
    if isinstance(key, ec.EllipticCurvePrivateKey):
        algorithm = {"secp256r1": "ES256", "secp384r1": "ES384", "secp521r1": "ES512"}.get(key.curve.name)
        if algorithm:
            return key, algorithm
    raise NetSuiteTokenError("NetSuite only accepts RSA keys or EC keys on the P-256, P-384, or P-521 curves.")


class NetSuiteOAuth2Auth(requests.auth.AuthBase):
    """OAuth 2.0 client credentials (machine-to-machine) flow with a signed JWT assertion.

    NetSuite issues no refresh token in this flow, so a new assertion is signed when the access token
    nears expiry.
    """

    def __init__(self, account: NetSuiteAccount, credentials: NetSuiteOAuth2Credentials) -> None:
        self._key, self._algorithm = _load_signing_key(credentials.private_key)
        self._client_id = credentials.client_id.strip()
        self._certificate_id = credentials.certificate_id.strip()
        self._token_url = f"{account.base_url}/services/rest/auth/oauth2/v1/token"
        # Token responses carry the access token in a generic field, so keep them out of sample capture.
        self._session = make_tracked_session(
            allow_redirects=False, redact_values=(credentials.private_key,), capture=False
        )
        self._access_token: str | None = None
        self._expires_at = 0.0

    def __call__(self, request: requests.PreparedRequest) -> requests.PreparedRequest:
        request.headers["Authorization"] = f"Bearer {self._get_access_token()}"
        return request

    def _get_access_token(self) -> str:
        if self._access_token is None or time.monotonic() >= self._expires_at - TOKEN_REFRESH_MARGIN_SECONDS:
            self._refresh()
        assert self._access_token is not None
        return self._access_token

    def _refresh(self) -> None:
        now = int(time.time())
        assertion = jwt.encode(
            {
                "iss": self._client_id,
                "scope": ["rest_webservices"],
                "aud": self._token_url,
                "iat": now,
                "exp": now + JWT_LIFETIME_SECONDS,
            },
            self._key,
            algorithm=self._algorithm,
            headers={"kid": self._certificate_id, "typ": "JWT"},
        )
        response = self._session.post(
            self._token_url,
            data={
                "grant_type": "client_credentials",
                "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                "client_assertion": assertion,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if 400 <= response.status_code < 500:
            detail = _error_detail(response) or f"HTTP {response.status_code}"
            raise NetSuiteTokenError(
                f"{OAUTH_REJECTED_PREFIX} ({detail}). Check the client ID, certificate ID, and private key, "
                "and make sure the certificate is active in Setup > Integration > OAuth 2.0 Client Credentials (M2M) Setup."
            )
        response.raise_for_status()
        body = response.json()
        access_token = body.get("access_token")
        if not access_token:
            raise NetSuiteTokenError(f"{OAUTH_REJECTED_PREFIX}: the response had no access token.")
        self._access_token = access_token
        self._expires_at = time.monotonic() + float(body.get("expires_in") or 3600)


class NetSuiteClient:
    def __init__(
        self, account_id: str, credentials: NetSuiteCredentials, sleep: Callable[[float], None] = time.sleep
    ) -> None:
        self.account = NetSuiteAccount.parse(account_id)
        self._suiteql_url = f"{self.account.base_url}/services/rest/query/v1/suiteql"
        self._sleep = sleep

        auth: requests.auth.AuthBase
        redact_values: tuple[str, ...]
        if isinstance(credentials, NetSuiteOAuth2Credentials):
            auth = NetSuiteOAuth2Auth(self.account, credentials)
            redact_values = (credentials.private_key,)
        else:
            auth = OAuth1(
                client_key=credentials.consumer_key.strip(),
                client_secret=credentials.consumer_secret.strip(),
                resource_owner_key=credentials.token_id.strip(),
                resource_owner_secret=credentials.token_secret.strip(),
                signature_method=SIGNATURE_HMAC_SHA256,
                realm=self.account.realm,
            )
            redact_values = (credentials.consumer_secret, credentials.token_id, credentials.token_secret)

        self._session = make_tracked_session(
            allow_redirects=False, headers={"Prefer": "transient"}, redact_values=redact_values
        )
        self._session.auth = auth

    def query(self, query: str, limit: int = PAGE_SIZE) -> dict[str, Any]:
        # SuiteQL is a POST, which the tracked transport doesn't retry. Retry here instead: each attempt
        # goes back through the session auth, so TBA signs it with a fresh nonce rather than replaying one.
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self._session.post(
                    self._suiteql_url, params={"limit": limit}, json={"q": query}, timeout=REQUEST_TIMEOUT_SECONDS
                )
            except (requests.ConnectionError, requests.Timeout):
                if attempt == MAX_ATTEMPTS:
                    raise
                self._sleep(min(2**attempt, MAX_RETRY_DELAY_SECONDS))
                continue

            if response.status_code in RETRYABLE_STATUSES and attempt < MAX_ATTEMPTS:
                self._sleep(_retry_delay(response, attempt))
                continue

            _raise_for_status(response)
            return response.json()

        raise NetSuiteError("NetSuite query failed after retries")


def _retry_delay(response: requests.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after and retry_after.isdigit():
        return min(float(retry_after), MAX_RETRY_DELAY_SECONDS)
    return min(2**attempt, MAX_RETRY_DELAY_SECONDS)


def _raise_for_status(response: requests.Response) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        # Keep the "<status> Client Error" prefix: `get_non_retryable_errors` matches on it.
        detail = _error_detail(response)
        if detail:
            raise requests.HTTPError(f"{error}. {detail}", response=response, request=error.request) from None
        raise


def _session_timestamp_literal(value: str) -> str:
    if not _SESSION_TS_RE.match(value):
        raise NetSuiteError(f"Unexpected NetSuite timestamp in pagination cursor: {value!r}")
    return f"TO_DATE('{value}', '{_SESSION_TS_FORMAT}')"


def _utc_alias(field: str) -> str:
    return f"ph_{field}_utc"


def _cursor_columns(config: NetSuiteEndpointConfig, incremental_field: str | None) -> list[str]:
    columns = [f"t.{key}" for key in config.primary_keys]
    return [f"t.{incremental_field}", *columns] if incremental_field else columns


def _keyset_predicate(columns: list[str], literals: list[str]) -> str:
    clauses = []
    for index, column in enumerate(columns):
        parts = [f"{columns[i]} = {literals[i]}" for i in range(index)]
        parts.append(f"{column} > {literals[index]}")
        clauses.append(f"({' AND '.join(parts)})")
    return f"({' OR '.join(clauses)})"


def _cursor_literals(cursor: list[str], incremental_field: str | None) -> list[str]:
    if incremental_field:
        return [_session_timestamp_literal(cursor[0]), *(str(int(value)) for value in cursor[1:])]
    return [str(int(value)) for value in cursor]


def _watermark_to_utc(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.UTC).replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time.min)
    if isinstance(value, str):
        return _watermark_to_utc(dt.datetime.fromisoformat(value.replace("Z", "+00:00")))
    raise NetSuiteError(f"Unsupported incremental value for NetSuite: {value!r}")


def build_query(
    config: NetSuiteEndpointConfig,
    incremental_field: str | None,
    watermark: Any | None,
    cursor: list[str] | None,
) -> str:
    # SuiteQL formats datetimes with the user's date preference and drops the time, so every
    # incremental-capable field is also selected as an exact UTC timestamp.
    select = ["t.*"]
    for field in config.incremental_fields:
        select.append(f"TO_CHAR(SYS_EXTRACT_UTC(t.{field}), '{_UTC_TS_FORMAT}') AS {_utc_alias(field)}")

    where: list[str] = []
    if incremental_field:
        # The cursor keeps the session-time value so the keyset compares the column with itself.
        select.append(f"TO_CHAR(t.{incremental_field}, '{_SESSION_TS_FORMAT}') AS {_CURSOR_TS_ALIAS}")
        where.append(f"t.{incremental_field} IS NOT NULL")
        if watermark is not None:
            watermark_utc = _watermark_to_utc(watermark)
            prefilter = (watermark_utc - SESSION_TIMEZONE_MARGIN).strftime("%Y-%m-%d %H:%M:%S")
            where.append(f"t.{incremental_field} >= TO_DATE('{prefilter}', '{_SESSION_TS_FORMAT}')")
            where.append(
                f"SYS_EXTRACT_UTC(t.{incremental_field}) >= "
                f"TO_TIMESTAMP('{watermark_utc.strftime('%Y-%m-%d %H:%M:%S')}', '{_SESSION_TS_FORMAT}')"
            )

    columns = _cursor_columns(config, incremental_field)
    if cursor:
        where.append(_keyset_predicate(columns, _cursor_literals(cursor, incremental_field)))

    query = f"SELECT {', '.join(select)} FROM {config.table} t"
    if where:
        query += f" WHERE {' AND '.join(where)}"
    return f"{query} ORDER BY {', '.join(columns)}"


def _row_cursor(item: dict[str, Any], config: NetSuiteEndpointConfig, incremental_field: str | None) -> list[str]:
    values = [str(int(item[key])) for key in config.primary_keys]
    return [str(item[_CURSOR_TS_ALIAS]), *values] if incremental_field else values


def normalize_row(item: dict[str, Any], config: NetSuiteEndpointConfig) -> dict[str, Any]:
    row = {key: value for key, value in item.items() if key not in ("links", _CURSOR_TS_ALIAS)}
    for key in config.primary_keys:
        row[key] = int(row[key])
    for field in config.incremental_fields:
        utc_value = row.pop(_utc_alias(field), None)
        row[field] = dt.datetime.strptime(utc_value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC) if utc_value else None
    return row


def iter_rows(
    client: NetSuiteClient,
    config: NetSuiteEndpointConfig,
    incremental_field: str | None,
    watermark: Any | None,
    resumable_source_manager: ResumableSourceManager[NetSuiteResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    # Keyset pagination instead of `offset`: SuiteQL stops returning rows past offset 100,000.
    cursor: list[str] | None = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if (
            resume is not None
            and resume.incremental_field == incremental_field
            and len(resume.cursor) == len(_cursor_columns(config, incremental_field))
        ):
            cursor = resume.cursor

    while True:
        data = client.query(build_query(config, incremental_field, watermark, cursor))
        items = data.get("items") or []
        if not items:
            return

        next_cursor = _row_cursor(items[-1], config, incremental_field)
        if next_cursor == cursor:
            raise NetSuiteError(f"NetSuite pagination did not advance past {cursor} for {config.table}")

        normalized_items = [normalize_row(item, config) for item in items]
        has_more = bool(data.get("hasMore")) and len(items) >= PAGE_SIZE
        if has_more:
            resumable_source_manager.save_state(
                NetSuiteResumeConfig(cursor=next_cursor, incremental_field=incremental_field)
            )
        yield normalized_items

        if not has_more:
            return
        cursor = next_cursor


def probe(client: NetSuiteClient, table: str) -> NetSuiteProbeResult:
    config = ENDPOINT_CONFIGS[table]
    try:
        client.query(f"SELECT {', '.join(config.primary_keys)} FROM {config.table}", limit=1)
    except NetSuiteError as error:
        return NetSuiteProbeResult(error=str(error))
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return NetSuiteProbeResult(error=AUTH_FAILED_MESSAGE)
        if status == 403:
            return NetSuiteProbeResult(error=REST_PERMISSION_MESSAGE)
        if status == 400:
            detail = _error_detail(error.response) if error.response is not None else None
            message = f"Your NetSuite role can't read the {table} table."
            return NetSuiteProbeResult(error=f"{message} {detail}" if detail else message, record_denied=True)
        return NetSuiteProbeResult(error=f"NetSuite returned an error: {error}")
    except requests.RequestException as error:
        return NetSuiteProbeResult(error=f"Could not reach NetSuite: {error}")
    return NetSuiteProbeResult()


def netsuite_source(
    account_id: str,
    credentials: NetSuiteCredentials,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[NetSuiteResumeConfig],
    incremental_field: str | None = None,
    db_incremental_field_last_value: Any | None = None,
) -> SourceResponse:
    config = ENDPOINT_CONFIGS.get(endpoint)
    if config is None:
        raise NetSuiteError(f"Unknown NetSuite table: {endpoint}")
    if incremental_field is not None and incremental_field not in config.incremental_fields:
        raise NetSuiteError(f"{incremental_field} isn't an incremental field for the NetSuite {endpoint} table")

    def items() -> Iterator[list[dict[str, Any]]]:
        client = NetSuiteClient(account_id, credentials)
        yield from iter_rows(
            client, config, incremental_field, db_incremental_field_last_value, resumable_source_manager
        )

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=list(config.primary_keys),
        partition_keys=[config.primary_keys[0]],
        partition_mode="numerical",
        partition_size=PARTITION_SIZE,
        sort_mode="asc",
    )
