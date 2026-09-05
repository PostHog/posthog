from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_intacct.settings import (
    INCREMENTAL_FIELD_QUERY_PATHS,
    SAGE_INTACCT_ENDPOINTS,
)

API_BASE_URL = "https://api.intacct.com/ia/api/v1"
TOKEN_URL = f"{API_BASE_URL}/oauth2/token"
QUERY_PATH = "/services/core/query"
# The query service caps a page at 2,000 rows, but Sage meters API transactions per call,
# so pages are deliberately large.
PAGE_SIZE = 1000
REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRY_ATTEMPTS = 5
MODIFIED_FIELD_PATH = "audit.modifiedDateTime"
# The query service rejects a request with no `fields`, and has no wildcard, so every query
# carries at least the record key, the document id, and the audit timestamps.
CORE_FIELDS: tuple[str, ...] = ("key", "id", "audit.createdDateTime", "audit.modifiedDateTime")
# Sage reference fields expand one level into `{key, id, href}`; anything deeper is a
# collection that belongs to its own object.
MAX_FIELD_DEPTH = 2


class SageIntacctRetryableError(Exception):
    pass


@frozen
class SageIntacctResumeConfig:
    # The query service pages with a numeric `start` offset.
    offset: int
    # Carried so a resumed attempt queries the exact same column set it started with —
    # re-discovering could widen the row shape mid-table.
    fields: list[str]


def _get_session(client_secret: str, refresh_token: Optional[str]) -> requests.Session:
    # capture=False: this session carries general-ledger, invoice, payment, and other
    # accounting response bodies that the generic scrubber does not redact.
    return make_tracked_session(redact_values=tuple(v for v in (client_secret, refresh_token) if v), capture=False)


def _mint_token(session: requests.Session, client_id: str, client_secret: str, refresh_token: Optional[str]) -> str:
    """Exchange the customer's OAuth app credentials for a 12h Sage Intacct access token."""
    payload: dict[str, str] = {"client_id": client_id, "client_secret": client_secret}
    if refresh_token:
        payload["grant_type"] = "refresh_token"
        payload["refresh_token"] = refresh_token
    else:
        payload["grant_type"] = "client_credentials"

    response = session.post(TOKEN_URL, data=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return str(response.json()["access_token"])


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor for a Sage audit-timestamp filter."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def _is_row_metadata(name: str) -> bool:
    return name == "href" or name.startswith("ia::")


def _field_paths(record: dict[str, Any], prefix: str = "", depth: int = 1) -> list[str]:
    """Dotted query-service field paths for the scalar leaves of a sample record."""
    paths: list[str] = []
    for name, value in record.items():
        if _is_row_metadata(name):
            continue
        path = f"{prefix}{name}"
        if isinstance(value, dict):
            if depth < MAX_FIELD_DEPTH:
                paths.extend(_field_paths(value, f"{path}.", depth + 1))
        elif not isinstance(value, list):
            paths.append(path)
    return paths


def _flatten(record: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten a Sage record's nested blocks into underscore-joined columns."""
    flat: dict[str, Any] = {}
    for name, value in record.items():
        if _is_row_metadata(name):
            continue
        column = f"{prefix}{name}"
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{column}_"))
        else:
            flat[column] = value
    return flat


def _query_fields(discovered: list[str]) -> list[str]:
    fields = list(CORE_FIELDS)
    seen = set(fields)
    for path in discovered:
        if path not in seen:
            seen.add(path)
            fields.append(path)
    return fields


def validate_credentials(client_id: str, client_secret: str, refresh_token: Optional[str]) -> bool:
    """Confirm the OAuth app credentials mint a token and reach the company's REST API."""
    try:
        session = _get_session(client_secret, refresh_token)
        token = _mint_token(session, client_id, client_secret, refresh_token)
        response = session.get(
            f"{API_BASE_URL}/objects/general-ledger/account",
            headers={"Authorization": f"Bearer {token}"},
            params={"size": 1},
            timeout=30,
        )
        # A 403 means the token is genuine but this user has no GL access — the customer may
        # only intend to sync other objects, so it must not block source creation.
        return response.status_code in (200, 403)
    except Exception:
        return False


def get_rows(
    client_id: str,
    client_secret: str,
    refresh_token: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SageIntacctResumeConfig],
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SAGE_INTACCT_ENDPOINTS[endpoint]
    session = _get_session(client_secret, refresh_token)
    token = _mint_token(session, client_id, client_secret, refresh_token)

    @retry(
        retry=retry_if_exception_type((SageIntacctRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=5, max=120),
        reraise=True,
    )
    def request(
        method: str,
        path: str,
        body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        nonlocal token
        url = f"{API_BASE_URL}{path}"

        def _do() -> requests.Response:
            headers = {"Authorization": f"Bearer {token}"}
            if method == "POST":
                return session.post(url, json=body, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
            return session.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

        response = _do()
        # Access tokens last 12h; re-mint once if a long sync outlives one.
        if response.status_code == 401:
            token = _mint_token(session, client_id, client_secret, refresh_token)
            response = _do()

        if response.status_code == 429 or response.status_code >= 500:
            raise SageIntacctRetryableError(
                f"Sage Intacct API error (retryable): status={response.status_code}, url={url}"
            )

        if not response.ok:
            logger.error(f"Sage Intacct API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        result = response.json()
        return result if isinstance(result, dict) else {}

    def discover_fields() -> list[str]:
        """Learn the company's field set for this object from one sample record.

        The query service has no wildcard and every company can add custom fields, so the
        column set is read off a real record instead of a hardcoded catalog.
        """
        listing = request("GET", f"/objects/{config.object_name}", params={"size": 1})
        results = listing.get("ia::result") or []
        if not results:
            return list(CORE_FIELDS)

        record_key = results[0].get("key") or results[0].get("id")
        if not record_key:
            return list(CORE_FIELDS)

        detail = request("GET", f"/objects/{config.object_name}/{record_key}")
        sample = detail.get("ia::result") or {}
        if not isinstance(sample, dict):
            return list(CORE_FIELDS)

        return _query_fields(_field_paths(sample))

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        offset = resume_config.offset
        fields = list(resume_config.fields)
        logger.debug(f"Sage Intacct: resuming {endpoint} from offset {offset}")
    else:
        offset = 0
        fields = discover_fields()

    cursor_path: Optional[str] = None
    if should_use_incremental_field:
        cursor_path = INCREMENTAL_FIELD_QUERY_PATHS.get(incremental_field or "", MODIFIED_FIELD_PATH)

    while True:
        body: dict[str, Any] = {
            "object": config.object_name,
            "fields": fields,
            "orderBy": [{cursor_path or config.primary_key: "asc"}],
            "start": offset,
            "size": PAGE_SIZE,
        }
        if cursor_path is not None and db_incremental_field_last_value is not None:
            body["filters"] = [{"$gte": {cursor_path: _format_datetime(db_incremental_field_last_value)}}]

        data = request("POST", QUERY_PATH, body=body)
        results = data.get("ia::result") or []
        rows = [_flatten(record) for record in results if isinstance(record, dict)]

        if rows:
            yield rows

        meta = data.get("ia::meta") or {}
        total_count = meta.get("totalCount")
        offset += len(results)

        if len(results) < PAGE_SIZE or (isinstance(total_count, int) and offset >= total_count):
            break

        # Saved AFTER the yield so a crash re-yields the last page (merge dedupes on the
        # primary key) rather than skipping it.
        resumable_source_manager.save_state(SageIntacctResumeConfig(offset=offset, fields=fields))


def sage_intacct_source(
    client_id: str,
    client_secret: str,
    refresh_token: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SageIntacctResumeConfig],
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SAGE_INTACCT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["audit_createdDateTime"],
        sort_mode="asc",
    )
