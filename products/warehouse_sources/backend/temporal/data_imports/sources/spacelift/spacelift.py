import re
import time
import dataclasses
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.spacelift.settings import (
    RUNS_INCREMENTAL_LOOKBACK_SECONDS,
    SPACELIFT_ENDPOINTS,
    SPACELIFT_HOST_TEMPLATE,
    SpaceliftEndpointConfig,
)

# Spacelift publishes no rate limits; ride out transient 429/5xx bursts in-process
# before letting Temporal reschedule the activity (which resumes from the saved cursor).
SPACELIFT_MAX_RETRY_ATTEMPTS = 5
# Refresh the ~10h API-key JWT this long before its reported expiry.
TOKEN_REFRESH_MARGIN_SECONDS = 5 * 60

_ACCOUNT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

TOKEN_EXCHANGE_MUTATION = """
mutation GetSpaceliftToken($id: ID!, $secret: String!) {
    apiKeyUser(id: $id, secret: $secret) {
        jwt
        validUntil
    }
}
"""


class SpaceliftRetryableError(Exception):
    pass


class SpaceliftAuthError(Exception):
    pass


class SpaceliftPermissionError(Exception):
    pass


@dataclasses.dataclass
class SpaceliftResumeConfig:
    # Relay `after` cursor of the next page to fetch for the current endpoint.
    cursor: str


def normalize_account_name(account_name: str) -> str:
    """Validate and normalize the Spacelift account subdomain.

    The account name is interpolated into the request host, so anything that isn't a
    plain DNS label must be rejected — otherwise a crafted value could redirect the
    stored API secret to an attacker-controlled host.
    """
    normalized = account_name.strip().lower()
    if not normalized or not _ACCOUNT_NAME_RE.match(normalized):
        raise ValueError(f"Invalid Spacelift account name: {account_name!r}")
    return normalized


def _graphql_url(account_name: str) -> str:
    return SPACELIFT_HOST_TEMPLATE.format(account_name=normalize_account_name(account_name))


def build_query(config: SpaceliftEndpointConfig) -> str:
    if not config.is_connection:
        return f"query {{ {config.graphql_field} {{ {config.node_selection} }} }}"

    if config.flatten_run_with_stack:
        node_selection = f"isModule run {{ {config.node_selection} }} stack {{ id name }}"
    else:
        node_selection = config.node_selection

    return f"""
query Search($input: SearchInput!) {{
    {config.graphql_field}(input: $input) {{
        edges {{
            cursor
            node {{ {node_selection} }}
        }}
        pageInfo {{
            endCursor
            hasNextPage
        }}
    }}
}}
"""


def to_unix_seconds(value: Any) -> int | None:
    """Coerce an incremental watermark into the Unix-seconds Int Spacelift timestamps use."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time()).timestamp())
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
        try:
            return int(datetime.fromisoformat(stripped).timestamp())
        except ValueError:
            return None
    return None


def build_incremental_predicates(incremental_field: str, last_value: Any) -> list[dict[str, Any]] | None:
    """Build the server-side `timeInRange` predicate for an incremental sync.

    Mirrors the filter the Spacelift UI itself sends to `searchRuns`. The watermark is
    shifted back by a lookback window so runs that changed state after first being
    synced are re-pulled; the delta merge dedupes them on the primary key. (The
    framework-level lookback only applies to datetime cursors, and Spacelift's are
    epoch-second ints, so the overlap is applied here.)
    """
    start = to_unix_seconds(last_value)
    if start is None:
        return None
    start = max(0, start - RUNS_INCREMENTAL_LOOKBACK_SECONDS)
    return [{"field": incremental_field, "constraint": {"timeInRange": {"start": start}}}]


class SpaceliftClient:
    def __init__(self, account_name: str, api_key_id: str, api_key_secret: str) -> None:
        self._graphql_url = _graphql_url(account_name)
        self._api_key_id = api_key_id
        self._api_key_secret = api_key_secret
        # The token exchange sends the API-key secret in a GraphQL `secret` variable and
        # receives a minted JWT — field names the sample scrubber's denylist can't
        # recognise — so keep this session's traffic out of HTTP sample capture entirely
        # (still metered and logged) and mask the static secret wherever it appears.
        self._session = make_tracked_session(
            headers={"Content-Type": "application/json"},
            redact_values=(api_key_secret,),
            capture=False,
        )
        self._jwt: str | None = None
        self._jwt_valid_until: float = 0.0

    def close(self) -> None:
        self._session.close()

    @retry(
        retry=retry_if_exception_type(SpaceliftRetryableError),
        stop=stop_after_attempt(SPACELIFT_MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def _post(self, body: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            response = self._session.post(self._graphql_url, json=body, headers=headers, timeout=60)
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError) as e:
            # POSTs get no transport-level retry from urllib3, so route transient
            # network failures through the same backoff path as 429/5xx.
            raise SpaceliftRetryableError(f"Spacelift: transient network error - {e}") from e

        if response.status_code == 429 or response.status_code >= 500:
            raise SpaceliftRetryableError(f"Spacelift: retryable HTTP error {response.status_code}")

        try:
            payload = response.json()
        except Exception as e:
            if not response.ok:
                raise Exception(f"{response.status_code} Client Error: {response.reason} (Spacelift API)") from e
            # A 2xx that won't parse is almost always a truncated transfer, not a
            # stable response — ride it out on the backoff path.
            raise SpaceliftRetryableError(f"Spacelift: incomplete JSON response ({e})") from e

        if not isinstance(payload, dict):
            raise Exception(f"Unexpected Spacelift response format: {type(payload).__name__}")

        return payload

    def _exchange_token(self) -> None:
        payload = self._post(
            {"query": TOKEN_EXCHANGE_MUTATION, "variables": {"id": self._api_key_id, "secret": self._api_key_secret}}
        )

        errors = payload.get("errors")
        if errors:
            messages = "; ".join(e.get("message", "") for e in errors)
            raise SpaceliftAuthError(f"Invalid Spacelift API key: token exchange failed ({messages})")

        # Spacelift signals a bad key id/secret with a null user, not a GraphQL error.
        user = (payload.get("data") or {}).get("apiKeyUser")
        jwt = user.get("jwt") if isinstance(user, dict) else None
        if not jwt:
            raise SpaceliftAuthError("Invalid Spacelift API key: the API key ID or secret is incorrect")

        self._jwt = jwt
        valid_until = to_unix_seconds(user.get("validUntil"))
        # The JWT lasts ~10h; fall back to a conservative window if the API omits the expiry.
        self._jwt_valid_until = float(valid_until) if valid_until else time.time() + 8 * 60 * 60

    def _ensure_token(self) -> str:
        if self._jwt is None or time.time() >= self._jwt_valid_until - TOKEN_REFRESH_MARGIN_SECONDS:
            self._exchange_token()
        assert self._jwt is not None
        return self._jwt

    def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run an authenticated GraphQL query, refreshing the JWT once if it expired mid-sync."""
        for attempt in range(2):
            jwt = self._ensure_token()
            payload = self._post(
                {"query": query, "variables": variables or {}}, headers={"Authorization": f"Bearer {jwt}"}
            )

            errors = payload.get("errors")
            if errors:
                messages = "; ".join(e.get("message", "") for e in errors)
                if "unauthorized" in messages.lower():
                    if attempt == 0:
                        self._jwt = None
                        continue
                    raise SpaceliftPermissionError(
                        f"Spacelift API returned unauthorized: the API key lacks access to this data ({messages})"
                    )
                raise Exception(f"Spacelift GraphQL error: {messages}")

            data = payload.get("data")
            if not isinstance(data, dict):
                raise Exception(f"Unexpected Spacelift response format. Keys: {list(payload.keys())}")
            return data

        raise SpaceliftPermissionError("Spacelift API returned unauthorized: the API key lacks access to this data")


def _normalize_run_node(node: dict[str, Any]) -> dict[str, Any]:
    """Flatten a `RunWithStack` node into a run row carrying its stack context."""
    row = dict(node.get("run") or {})
    stack = node.get("stack") or {}
    row["isModule"] = node.get("isModule")
    row["stackId"] = stack.get("id")
    row["stackName"] = stack.get("name")
    return row


def _get_rows(
    client: SpaceliftClient,
    endpoint_config: SpaceliftEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SpaceliftResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> Iterator[list[dict[str, Any]]]:
    query = build_query(endpoint_config)

    try:
        if not endpoint_config.is_connection:
            data = client.execute(query)
            rows = data.get(endpoint_config.graphql_field) or []
            if rows:
                yield rows
            return

        search_input: dict[str, Any] = {"first": endpoint_config.page_size, "after": None}

        if should_use_incremental_field and incremental_field:
            predicates = build_incremental_predicates(incremental_field, db_incremental_field_last_value)
            if predicates:
                search_input["predicates"] = predicates
                logger.debug(f"Spacelift: incremental sync for {endpoint_config.name} with predicates {predicates}")

        resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        if resume_config is not None and resume_config.cursor:
            search_input["after"] = resume_config.cursor
            logger.debug(f"Spacelift: resuming {endpoint_config.name} from saved cursor")

        while True:
            data = client.execute(query, {"input": search_input})
            connection = data.get(endpoint_config.graphql_field) or {}
            edges = connection.get("edges") or []
            page_info = connection.get("pageInfo") or {}

            if endpoint_config.flatten_run_with_stack:
                rows = [_normalize_run_node(edge.get("node") or {}) for edge in edges]
            else:
                rows = [edge.get("node") for edge in edges if edge.get("node") is not None]

            if rows:
                yield rows

            if not page_info.get("hasNextPage"):
                break

            end_cursor = page_info.get("endCursor")
            if not end_cursor:
                # A hasNextPage=True page with no cursor would loop forever on itself;
                # fail loudly instead of silently returning partial results.
                raise Exception(f"Spacelift: hasNextPage=True but endCursor is empty for {endpoint_config.name}")

            # Save AFTER yielding so a crash re-yields the last page rather than
            # skipping it — the merge dedupes on the primary key.
            resumable_source_manager.save_state(SpaceliftResumeConfig(cursor=end_cursor))
            search_input["after"] = end_cursor
    finally:
        client.close()


def spacelift_source(
    account_name: str,
    api_key_id: str,
    api_key_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SpaceliftResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = SPACELIFT_ENDPOINTS.get(endpoint)
    if endpoint_config is None:
        raise ValueError(f"Unknown Spacelift endpoint: {endpoint}")

    def get_rows() -> Iterator[list[dict[str, Any]]]:
        client = SpaceliftClient(account_name, api_key_id, api_key_secret)
        yield from _get_rows(
            client=client,
            endpoint_config=endpoint_config,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        )

    return SourceResponse(
        name=endpoint,
        items=get_rows,
        primary_keys=endpoint_config.primary_keys,
        sort_mode=endpoint_config.sort_mode,
        partition_count=1 if endpoint_config.partition_mode else None,
        partition_size=1 if endpoint_config.partition_mode else None,
        partition_mode=endpoint_config.partition_mode,
        partition_format=endpoint_config.partition_format,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def validate_credentials(account_name: str, api_key_id: str, api_key_secret: str) -> tuple[bool, str | None]:
    try:
        client = SpaceliftClient(account_name, api_key_id, api_key_secret)
    except ValueError as e:
        return False, str(e)

    try:
        client._ensure_token()
        return True, None
    except SpaceliftAuthError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Could not verify Spacelift credentials: {e}"
    finally:
        client.close()
