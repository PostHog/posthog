import re
import hmac
import time
import base64
import hashlib
import secrets
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import requests
from requests import PreparedRequest, Response
from requests.auth import AuthBase
from structlog.types import FilteringBoundLogger
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.settings import (
    NETSUITE_ENDPOINTS,
    NetSuiteEndpointConfig,
)

SUITEQL_PATH = "/services/rest/query/v1/suiteql"

# NetSuite account IDs are alphanumeric with an optional environment suffix (`1234567`, `1234567_SB1`,
# `TSTDRV1234567`). The character set is intentionally narrow: anything else — a dot, slash, `@`, or `:` —
# could break out of the host label the account ID is interpolated into and point the credentialed
# request at an attacker-controlled host. Reject it before it reaches a URL.
_ACCOUNT_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]*\Z")

# SuiteQL caps a single response at 1000 rows.
PAGE_SIZE = 1000

REQUEST_TIMEOUT = 120.0

# SuiteQL is a POST, which the shared DEFAULT_RETRY deliberately excludes (POSTs are not
# idempotent in general). A SuiteQL query *is* idempotent — it is a read — so retry it on the
# throttle/transient statuses NetSuite uses for its concurrency governor.
SUITEQL_RETRY = Retry(
    total=5,
    backoff_factor=1.0,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "POST"]),
    raise_on_status=False,
    respect_retry_after_header=True,
)

# Backstop against a NetSuite response that ignores the keyset predicate and re-serves page one
# forever. Keyset paging only advances on a strictly greater cursor, so this should be unreachable.
MAX_PAGES = 100_000


class NetSuiteAPIError(Exception):
    """A SuiteQL request that came back with a non-2xx status.

    Message text is deliberately stable and account-agnostic (the host embeds the account ID) so
    `get_non_retryable_errors` can match on it.
    """


@dataclasses.dataclass
class NetSuiteResumeConfig:
    # Highest keyset value already yielded. A resumed run restarts at `WHERE <keyset> > last_key`.
    # `None` means "start from the beginning of the table".
    last_key: int | None = None


def account_slug(account_id: str) -> str:
    """Host label for a NetSuite account ID: lowercase, underscores become hyphens.

    NetSuite writes sandbox/release-preview account IDs as `1234567_SB1`, but the SuiteTalk host
    for the same account is `1234567-sb1.suitetalk.api.netsuite.com`.
    """
    return account_id.strip().lower().replace("_", "-")


def account_realm(account_id: str) -> str:
    """OAuth `realm` for a NetSuite account ID: uppercase, hyphens become underscores.

    The inverse of the host spelling — NetSuite rejects the signature if the realm is not the
    account ID in its canonical `1234567_SB1` form.
    """
    return account_id.strip().upper().replace("-", "_")


def _validated_account_id(account_id: str) -> str:
    candidate = account_id.strip()
    if not _ACCOUNT_ID_RE.match(candidate):
        raise ValueError(f"Invalid NetSuite account ID: {account_id!r}")
    return candidate


def base_url(account_id: str) -> str:
    # Validating here means every URL builder (`suiteql_url`, the probe, the pager) inherits the guard —
    # the host is always `<slug>.suitetalk.api.netsuite.com`, never something the account ID smuggled in.
    return f"https://{account_slug(_validated_account_id(account_id))}.suitetalk.api.netsuite.com"


def suiteql_url(account_id: str) -> str:
    return f"{base_url(account_id)}{SUITEQL_PATH}"


def _percent_encode(value: str) -> str:
    """RFC 3986 percent-encoding as OAuth 1.0a requires (only A-Za-z0-9-._~ stay literal)."""
    return quote(value, safe="")


class NetSuiteTBAAuth(AuthBase):
    """OAuth 1.0a request signing for NetSuite Token-Based Authentication (HMAC-SHA256).

    TBA is the credential NetSuite issues for server-to-server integrations: it never expires on a
    timer (unlike NetSuite's OAuth 2.0 refresh tokens, which are only valid for seven days), so it
    is the only auth that survives an unattended nightly sync.

    The signature base string covers the method, the URL without its query, and the query params
    merged with the `oauth_*` params — the JSON body is not signed.
    """

    def __init__(
        self,
        account_id: str,
        consumer_key: str,
        consumer_secret: str,
        token_id: str,
        token_secret: str,
        nonce_factory: Callable[[], str] | None = None,
        timestamp_factory: Callable[[], int] | None = None,
    ) -> None:
        self._realm = account_realm(account_id)
        self._consumer_key = consumer_key
        self._consumer_secret = consumer_secret
        self._token_id = token_id
        self._token_secret = token_secret
        self._nonce_factory = nonce_factory or (lambda: secrets.token_hex(16))
        self._timestamp_factory = timestamp_factory or (lambda: int(time.time()))

    def signature_base_string(self, method: str, url: str, oauth_params: dict[str, str]) -> str:
        split = urlsplit(url)
        base_uri = urlunsplit((split.scheme, split.netloc, split.path, "", ""))
        # Query params and oauth params share one namespace, sorted by encoded key then value.
        pairs = [(_percent_encode(k), _percent_encode(v)) for k, v in oauth_params.items()]
        for raw_pair in split.query.split("&") if split.query else []:
            if not raw_pair:
                continue
            raw_key, _, raw_value = raw_pair.partition("=")
            pairs.append((raw_key, raw_value))
        normalized = "&".join(f"{k}={v}" for k, v in sorted(pairs))
        return "&".join([method.upper(), _percent_encode(base_uri), _percent_encode(normalized)])

    def _sign(self, base_string: str) -> str:
        key = f"{_percent_encode(self._consumer_secret)}&{_percent_encode(self._token_secret)}".encode()
        digest = hmac.new(key, base_string.encode(), hashlib.sha256).digest()
        return base64.b64encode(digest).decode()

    def authorization_header(self, method: str, url: str) -> str:
        oauth_params = {
            "oauth_consumer_key": self._consumer_key,
            "oauth_nonce": self._nonce_factory(),
            "oauth_signature_method": "HMAC-SHA256",
            "oauth_timestamp": str(self._timestamp_factory()),
            "oauth_token": self._token_id,
            "oauth_version": "1.0",
        }
        signature = self._sign(self.signature_base_string(method, url, oauth_params))
        signed = {**oauth_params, "oauth_signature": signature}
        rendered = ", ".join(f'{key}="{_percent_encode(value)}"' for key, value in sorted(signed.items()))
        return f'OAuth realm="{self._realm}", {rendered}'

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["Authorization"] = self.authorization_header(request.method or "GET", request.url or "")
        return request


def make_auth(
    account_id: str,
    consumer_key: str,
    consumer_secret: str,
    token_id: str,
    token_secret: str,
) -> NetSuiteTBAAuth:
    return NetSuiteTBAAuth(account_id, consumer_key, consumer_secret, token_id, token_secret)


def make_session(consumer_secret: str, token_secret: str) -> requests.Session:
    # The signature rides an Authorization header the name-based scrubbers already mask, but the
    # raw secrets must never surface in a captured sample either.
    return make_tracked_session(
        retry=SUITEQL_RETRY,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            # SuiteQL rejects requests without it: `transient` opts out of server-side result caching.
            "Prefer": "transient",
        },
        redact_values=(consumer_secret, token_secret),
        # Keep the credentialed request pointed at the host we validated — never let a redirect chain
        # carry the signed Authorization header somewhere else.
        allow_redirects=False,
    )


def format_timestamp(value: Any) -> str | None:
    """Render an incremental cursor as the `YYYY-MM-DD HH24:MI:SS` literal SuiteQL's TO_TIMESTAMP wants.

    Returns `None` for anything that isn't a recognisable timestamp, which drops the filter rather
    than risk splicing an unparsed value into the query.
    """
    parsed: datetime | None = None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed is None:
        return None
    utc = parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return utc.strftime("%Y-%m-%d %H:%M:%S")


def build_query(
    config: NetSuiteEndpointConfig,
    last_key: int | None = None,
    incremental_field: str | None = None,
    incremental_value: Any = None,
) -> str:
    """Build the SuiteQL statement for one page.

    Rows are always ordered by the keyset column so pagination is total and stable while NetSuite
    users keep writing to the table underneath us. Every interpolated value is either drawn from the
    static endpoint catalog, coerced to `int`, or rendered by `format_timestamp` — nothing reaches
    the statement unvalidated.
    """
    predicates: list[str] = []

    if incremental_field:
        # Only a column this endpoint actually advertises may be filtered on.
        allowed = {f["field"] for f in config.incremental_fields}
        formatted = format_timestamp(incremental_value)
        if incremental_field in allowed and formatted is not None:
            predicates.append(f"{incremental_field} >= TO_TIMESTAMP('{formatted}', 'YYYY-MM-DD HH24:MI:SS')")

    if last_key is not None:
        predicates.append(f"{config.keyset_column} > {int(last_key)}")

    where = f" WHERE {' AND '.join(predicates)}" if predicates else ""
    return f"SELECT * FROM {config.table}{where} ORDER BY {config.keyset_column} ASC"


def _raise_for_status(response: Response) -> None:
    if response.status_code < 400:
        return
    detail = response.text[:500]
    raise NetSuiteAPIError(f"NetSuite SuiteQL request returned {response.status_code}: {detail}")


def run_query(
    session: requests.Session,
    auth: NetSuiteTBAAuth,
    account_id: str,
    query: str,
    limit: int,
    offset: int = 0,
) -> dict[str, Any]:
    """POST one SuiteQL statement and return the parsed envelope."""
    url = f"{suiteql_url(account_id)}?{urlencode({'limit': limit, 'offset': offset})}"
    response = session.post(url, json={"q": query}, auth=auth, timeout=REQUEST_TIMEOUT)
    _raise_for_status(response)
    body = response.json()
    if not isinstance(body, dict):
        raise NetSuiteAPIError("NetSuite SuiteQL request returned an unexpected response body")
    return body


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Drop the per-row HATEOAS `links` array SuiteQL attaches — it carries no data."""
    return {key: value for key, value in row.items() if key != "links"}


def _extract_key(row: dict[str, Any], keyset_column: str) -> int | None:
    """SuiteQL returns numeric columns as strings, so the cursor has to be coerced back to int."""
    raw = row.get(keyset_column)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def validate_credentials(
    account_id: str,
    consumer_key: str,
    consumer_secret: str,
    token_id: str,
    token_secret: str,
) -> tuple[bool, str | None]:
    """Probe SuiteQL with a trivial statement.

    A 403 is fatal here rather than tolerated: every table this source syncs goes through the same
    SuiteQL endpoint, so a role that can't reach it can't sync anything.
    """
    if not account_id.strip():
        return False, "A NetSuite account ID is required"

    try:
        _validated_account_id(account_id)
    except ValueError:
        return False, (
            "That NetSuite account ID isn't valid. Use the account ID from Setup → Company → Company "
            "Information (for example 1234567 or 1234567_SB1)."
        )

    try:
        session = make_session(consumer_secret, token_secret)
        auth = make_auth(account_id, consumer_key, consumer_secret, token_id, token_secret)
        response = session.post(
            f"{suiteql_url(account_id)}?{urlencode({'limit': 1, 'offset': 0})}",
            json={"q": "SELECT 1 AS probe FROM dual"},
            auth=auth,
            timeout=30,
        )
    except Exception:  # noqa: BLE001 — a credential probe must never raise out of source creation
        return False, "Could not reach the NetSuite SuiteQL API. Check the account ID."

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, (
            "NetSuite rejected the token-based authentication signature. Check the account ID, "
            "consumer key/secret and token ID/secret."
        )
    if response.status_code == 403:
        return False, (
            "The NetSuite role behind this token cannot use SuiteQL. Grant it the REST Web Services "
            "and SuiteAnalytics Workbook permissions, then reconnect."
        )
    if response.status_code == 404:
        return False, f"No NetSuite account was found at {base_url(account_id)}. Check the account ID."
    return False, f"NetSuite API error: {response.status_code}"


def _iter_pages(
    account_id: str,
    consumer_key: str,
    consumer_secret: str,
    token_id: str,
    token_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NetSuiteResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> Iterator[list[dict[str, Any]]]:
    config = NETSUITE_ENDPOINTS[endpoint]
    session = make_session(consumer_secret, token_secret)
    auth = make_auth(account_id, consumer_key, consumer_secret, token_id, token_secret)

    last_key: int | None = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.last_key is not None:
            last_key = int(resume.last_key)
            logger.debug(f"NetSuite: resuming {endpoint} from {config.keyset_column} > {last_key}")

    cursor_field = incremental_field if should_use_incremental_field else None
    cursor_value = db_incremental_field_last_value if should_use_incremental_field else None

    for _ in range(MAX_PAGES):
        query = build_query(config, last_key, cursor_field, cursor_value)
        body = run_query(session, auth, account_id, query, limit=PAGE_SIZE)
        rows = body.get("items") or []

        if rows:
            yield [normalize_row(row) for row in rows]

            # Advance strictly: a page whose rows carry no usable keyset value can't be paged past,
            # so stop rather than re-request the same window forever.
            keys = [key for key in (_extract_key(row, config.keyset_column) for row in rows) if key is not None]
            next_key = max(keys) if keys else None
            if next_key is None or (last_key is not None and next_key <= last_key):
                logger.debug(f"NetSuite: {endpoint} keyset column did not advance, ending sync")
                break
            last_key = next_key

        # `hasMore` reflects the 1000-row page cap, not the keyset window, so a full page always
        # means "ask again". Save AFTER yielding so a crash re-yields the last page (merge dedupes
        # on the primary key) instead of skipping it.
        if len(rows) < PAGE_SIZE:
            break
        resumable_source_manager.save_state(NetSuiteResumeConfig(last_key=last_key))
    else:
        # Cap reached with pages still outstanding: keep the checkpoint so the next attempt picks up
        # where this one stopped instead of restarting the table.
        logger.warning(f"NetSuite: {endpoint} hit the {MAX_PAGES} page cap, ending sync")
        return

    resumable_source_manager.clear_state()


def netsuite_source(
    account_id: str,
    consumer_key: str,
    consumer_secret: str,
    token_id: str,
    token_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NetSuiteResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = NETSUITE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: _iter_pages(
            account_id=account_id,
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            token_id=token_id,
            token_secret=token_secret,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        # Rows arrive ordered by the keyset column, not by `lastmodifieddate`, so the cursor is not
        # monotonic across batches. `desc` makes the pipeline finalise the watermark once at job end
        # (from the run's max) rather than checkpointing it per batch, which would otherwise jump the
        # watermark past rows a later page still owes.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
