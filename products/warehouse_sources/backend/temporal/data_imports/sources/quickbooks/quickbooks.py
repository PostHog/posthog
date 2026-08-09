import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.quickbooks.settings import (
    CREATE_TIME_FIELD,
    LAST_UPDATED_FIELD,
    LAST_UPDATED_QUERY_PATH,
    METADATA_KEY,
    QUICKBOOKS_ENTITIES,
    QuickBooksEntityConfig,
)

# Intuit hosts sandbox companies on a separate API domain; one OAuth app covers both.
QUICKBOOKS_HOSTS = {
    "production": "https://quickbooks.api.intuit.com",
    "sandbox": "https://sandbox-quickbooks.api.intuit.com",
}

# Minor version of the Accounting API surface the queries below are written against. Omitting it
# pins the request to the oldest supported shape, which drops fields we want.
QUICKBOOKS_MINOR_VERSION = "65"

# MAXRESULTS caps at 1000; 500 keeps request counts low without making one page enormous for
# wide transaction entities that embed their full line items.
PAGE_SIZE = 500
REQUEST_TIMEOUT_SECONDS = 120

# Timestamp literals in the query language are ISO 8601; Intuit's own examples carry an offset.
_QUERY_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S+00:00"

_HOISTED_METADATA_FIELDS = (CREATE_TIME_FIELD, LAST_UPDATED_FIELD)


@dataclasses.dataclass
class QuickBooksResumeConfig:
    # `STARTPOSITION` is 1-based. The `WHERE` bound is saved alongside it because an offset only
    # identifies a row within the result set of the query that produced it.
    start_position: int
    since: Optional[str] = None


def _get_session(access_token: str) -> requests.Session:
    # `redact_values` masks the bearer token in logged URLs and captured HTTP samples. `capture=False`
    # keeps the response bodies themselves out of the shared HTTP sample store: every row here is
    # accounting data (amounts, document numbers, memos, tax identifiers, customer names) that the
    # generic scrubber has no way to recognize, and this session serves both credential validation
    # and full entity syncs.
    return make_tracked_session(
        headers={"Accept": "application/json"},
        redact_values=(access_token,),
        capture=False,
    )


def _host(environment: str) -> str:
    host = QUICKBOOKS_HOSTS.get(environment)
    if host is None:
        raise ValueError(f"Invalid QuickBooks environment: {environment}")
    return host


def company_url(environment: str, realm_id: str, api_version: str) -> str:
    return f"{_host(environment)}/{api_version}/company/{realm_id}"


def escape_query_literal(value: str) -> str:
    """Escape a string for a single-quoted literal in the QuickBooks query language."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def format_query_timestamp(value: Any) -> Optional[str]:
    """Render an incremental watermark as a UTC ISO 8601 literal, or `None` when unusable."""
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=UTC)
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
    else:
        return None

    return parsed.astimezone(UTC).strftime(_QUERY_TIMESTAMP_FORMAT)


def build_query(
    entity: QuickBooksEntityConfig,
    since: Optional[str] = None,
    start_position: int = 1,
    page_size: int = PAGE_SIZE,
) -> str:
    """Build the QueryService statement for one page of an entity."""
    if entity.singleton:
        return f"SELECT * FROM {entity.name}"

    clauses = [f"SELECT * FROM {entity.name}"]
    if since is not None:
        clauses.append(f"WHERE {LAST_UPDATED_QUERY_PATH} > '{escape_query_literal(since)}'")
    # `ORDERBY` is one word in this dialect and defaults to ascending, which is the order the
    # pipeline's watermark checkpointing assumes.
    clauses.append(f"ORDERBY {LAST_UPDATED_QUERY_PATH}")
    clauses.append(f"STARTPOSITION {start_position}")
    clauses.append(f"MAXRESULTS {page_size}")
    return " ".join(clauses)


def extract_rows(body: dict[str, Any], entity_name: str) -> list[dict[str, Any]]:
    """Pull an entity's rows out of a `QueryResponse` body.

    An empty result set comes back as an absent key rather than an empty list, and singleton
    entities can come back as a bare object.
    """
    query_response = body.get("QueryResponse")
    if not isinstance(query_response, dict):
        return []

    rows = query_response.get(entity_name)
    if isinstance(rows, dict):
        return [rows]
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Hoist the nested `MetaData` timestamps to the row root, leaving the rest of the row alone."""
    metadata = row.get(METADATA_KEY)
    if not isinstance(metadata, dict):
        return row

    normalized = dict(row)
    for key in _HOISTED_METADATA_FIELDS:
        value = metadata.get(key)
        if value is not None:
            normalized.setdefault(key, value)
    return normalized


def validate_credentials(
    environment: str,
    realm_id: str,
    access_token: str,
    api_version: str,
) -> bool:
    """Confirm the connected account's token can read the given company."""
    try:
        session = _get_session(access_token)
        response = session.get(
            f"{company_url(environment, realm_id, api_version)}/query",
            params={"query": "SELECT * FROM CompanyInfo", "minorversion": QUICKBOOKS_MINOR_VERSION},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    environment: str,
    realm_id: str,
    access_token: str,
    entity_name: str,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[QuickBooksResumeConfig],
    refresh_access_token: Optional[Callable[[], str]] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    entity = QUICKBOOKS_ENTITIES[entity_name]
    token = access_token
    session = _get_session(token)
    base_url = company_url(environment, realm_id, api_version)

    since = format_query_timestamp(db_incremental_field_last_value) if should_use_incremental_field else None
    start_position = 1

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        start_position = resume_config.start_position
        # The saved offset only means anything against the query that produced it.
        since = resume_config.since
        logger.debug(f"QuickBooks: resuming {entity_name} from STARTPOSITION {start_position}")

    def run_query(query: str) -> list[dict[str, Any]]:
        nonlocal token, session
        url = f"{base_url}/query?{urlencode({'query': query, 'minorversion': QUICKBOOKS_MINOR_VERSION})}"

        def _do() -> requests.Response:
            return session.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

        response = _do()
        # Intuit access tokens last an hour, which a large company's sync can outlive. Renew once
        # through the integration and rebuild the session so the new token is redacted too.
        if response.status_code == 401 and refresh_access_token is not None:
            token = refresh_access_token()
            session = _get_session(token)
            response = _do()

        if not response.ok:
            logger.error(f"QuickBooks API error: status={response.status_code}, body={response.text}, query={query}")
            response.raise_for_status()

        return extract_rows(response.json(), entity_name)

    while True:
        rows = run_query(build_query(entity, since=since, start_position=start_position, page_size=PAGE_SIZE))

        if rows:
            yield [normalize_row(row) for row in rows]

        # A short page is the only end-of-results signal the dialect gives.
        if entity.singleton or len(rows) < PAGE_SIZE:
            break

        start_position += PAGE_SIZE
        # Save state AFTER yielding so a crash re-yields the last page (the merge dedupes on
        # primary key) instead of skipping it.
        resumable_source_manager.save_state(
            QuickBooksResumeConfig(start_position=start_position, since=since),
        )


def quickbooks_source(
    environment: str,
    realm_id: str,
    access_token: str,
    entity_name: str,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[QuickBooksResumeConfig],
    refresh_access_token: Optional[Callable[[], str]] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    entity = QUICKBOOKS_ENTITIES[entity_name]

    return SourceResponse(
        name=entity_name,
        items=lambda: get_rows(
            environment=environment,
            realm_id=realm_id,
            access_token=access_token,
            entity_name=entity_name,
            api_version=api_version,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            refresh_access_token=refresh_access_token,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[entity.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if entity.partition_key else None,
        partition_format="month" if entity.partition_key else None,
        partition_keys=[entity.partition_key] if entity.partition_key else None,
        # `ORDERBY Metadata.LastUpdatedTime` is ascending by default.
        sort_mode="asc",
    )
