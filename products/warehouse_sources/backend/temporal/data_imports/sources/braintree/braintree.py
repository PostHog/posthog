import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.braintree.settings import (
    BRAINTREE_ENDPOINTS,
    BraintreeEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

BRAINTREE_HOSTS = {
    "production": "https://payments.braintree-api.com/graphql",
    "sandbox": "https://payments.sandbox.braintree-api.com/graphql",
}
# Pinned GraphQL API version (date-versioned header, required).
BRAINTREE_VERSION = "2019-01-01"
PAGE_SIZE = 100
# Braintree recommends generous timeouts due to async transaction processing.
REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRY_ATTEMPTS = 5


class BraintreeRetryableError(Exception):
    pass


class BraintreeGraphQLError(Exception):
    pass


@dataclasses.dataclass
class BraintreeResumeConfig:
    # Relay-style pagination: `after` is the cursor of the last edge consumed;
    # the search input is rebuilt deterministically from job inputs on resume.
    after: str


def _get_session(public_key: str, private_key: str) -> requests.Session:
    session = make_tracked_session(
        headers={"Braintree-Version": BRAINTREE_VERSION},
        redact_values=(private_key,),
    )
    session.auth = (public_key, private_key)
    return session


def _base_url(environment: str) -> str:
    host = BRAINTREE_HOSTS.get(environment)
    if host is None:
        raise ValueError(f"Invalid Braintree environment: {environment}")
    return host


def _format_created_at(value: Any) -> str:
    """Format an incremental cursor for a createdAt greaterThanOrEqualTo filter (ISO 8601 UTC)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def _build_query(config: BraintreeEndpointConfig) -> str:
    return f"""
query ($input: {config.input_type}, $first: Int!, $after: String) {{
  search {{
    {config.search_field} (input: $input, first: $first, after: $after) {{
      pageInfo {{ hasNextPage }}
      edges {{
        cursor
        node {{
{config.node_fields}
        }}
      }}
    }}
  }}
}}
"""


def _execute(
    session: requests.Session,
    url: str,
    query: str,
    variables: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.post(url, json={"query": query, "variables": variables}, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise BraintreeRetryableError(f"Braintree API error (retryable): status={response.status_code}")

    if not response.ok:
        logger.error(f"Braintree API error: status={response.status_code}, body={response.text}")
        response.raise_for_status()

    body = response.json()
    errors = body.get("errors")
    if errors:
        message = "; ".join(str(error.get("message", error)) for error in errors)
        raise BraintreeGraphQLError(f"Braintree GraphQL error: {message}")

    return body.get("data") or {}


class _NoopLogger:
    def error(self, *args: Any, **kwargs: Any) -> None:
        return None


def validate_credentials(environment: str, public_key: str, private_key: str) -> bool:
    """Confirm the key pair is valid with the GraphQL ping query."""
    try:
        session = _get_session(public_key, private_key)
        data = _execute(session, _base_url(environment), "query { ping }", {}, _NoopLogger())  # type: ignore[arg-type]
        return data.get("ping") == "pong"
    except Exception:
        return False


def get_rows(
    environment: str,
    public_key: str,
    private_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BraintreeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = BRAINTREE_ENDPOINTS[endpoint]
    session = _get_session(public_key, private_key)
    url = _base_url(environment)
    query = _build_query(config)

    search_input: dict[str, Any] = {}
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        # `greaterThanOrEqualTo` re-fetches the boundary row (merge dedupes on
        # primary key) so records sharing the watermark are never skipped.
        search_input = {"createdAt": {"greaterThanOrEqualTo": _format_created_at(db_incremental_field_last_value)}}

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    after: Optional[str] = resume_config.after if resume_config is not None else None
    if after is not None:
        logger.debug(f"Braintree: resuming {endpoint} from cursor")

    @retry(
        retry=retry_if_exception_type((BraintreeRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=90),
        reraise=True,
    )
    def execute(variables: dict[str, Any]) -> dict[str, Any]:
        return _execute(session, url, query, variables, logger)

    while True:
        data = execute({"input": search_input or None, "first": PAGE_SIZE, "after": after})
        connection = ((data.get("search") or {}).get(config.search_field)) or {}
        edges = connection.get("edges") or []
        items = [edge.get("node") for edge in edges if edge.get("node")]

        if items:
            yield items

        has_next = bool((connection.get("pageInfo") or {}).get("hasNextPage"))
        last_cursor = edges[-1].get("cursor") if edges else None
        if not has_next or not last_cursor or not items:
            break

        after = last_cursor
        # Save state AFTER yielding the page so a crash re-yields the last page
        # (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(BraintreeResumeConfig(after=after))


def braintree_source(
    environment: str,
    public_key: str,
    private_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BraintreeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = BRAINTREE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            environment=environment,
            public_key=public_key,
            private_key=private_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        # Search result ordering is undocumented, so the pipeline defers the
        # watermark commit until a run completes.
        sort_mode="desc",
    )
