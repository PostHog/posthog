import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.memberful.settings import (
    MEMBERFUL_ENDPOINTS,
    PAGE_SIZE,
    MemberfulEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    make_tracked_session,
    max_retry_after_seconds,
    retry_with_deadline,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_ATTEMPTS = 5

# A Memberful account subdomain is one DNS label. Checking it before the URL is built keeps a
# crafted value (one with `/`, `@`, `#` or `.`) from sending the API key to another host.
_VALID_SUBDOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

INVALID_SUBDOMAIN_MESSAGE = (
    "Invalid Memberful account subdomain. Use the part before .memberful.com, for example your-account."
)
ACCOUNT_NOT_FOUND_MESSAGE = "Memberful account not found. Check the account subdomain."
INVALID_API_KEY_MESSAGE = "Invalid Memberful API key. Create an API key under Settings → Custom applications."

VALIDATE_CREDENTIALS_QUERY = "query MemberfulValidate { members(first: 1) { pageInfo { hasNextPage } } }"


class MemberfulRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class MemberfulAccountNotFoundError(Exception):
    pass


class MemberfulGraphQLError(Exception):
    def __init__(self, status_code: int, messages: list[str]) -> None:
        self.status_code = status_code
        self.messages = messages
        super().__init__(f"Memberful API error (status {status_code}): {'; '.join(messages)}")


@dataclasses.dataclass(frozen=True)
class MemberfulResumeConfig:
    # Relay `endCursor` of the next page to read.
    cursor: str | None = None
    # The createdAt lower bound the cursor was issued under, so a resumed run sends the same filter.
    created_at_gte: int | None = None
    # The run read every row, so a retry of the same run reads nothing.
    completed: bool = False


def normalize_subdomain(value: str) -> str:
    """Reduce `acme`, `acme.memberful.com` or `https://acme.memberful.com/admin` to `acme`."""
    subdomain = value.strip().lower()
    subdomain = subdomain.removeprefix("https://").removeprefix("http://")
    subdomain = subdomain.split("/", 1)[0]
    return subdomain.removesuffix(".memberful.com")


def graphql_url(subdomain: str) -> str:
    normalized = normalize_subdomain(subdomain)
    if not _VALID_SUBDOMAIN.match(normalized):
        raise ValueError(INVALID_SUBDOMAIN_MESSAGE)
    return f"https://{normalized}.memberful.com/api/graphql"


def _make_session(api_key: str) -> requests.Session:
    # The host comes from a user field, so never follow a redirect that could carry the key elsewhere.
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        redact_values=(api_key,),
        allow_redirects=False,
    )


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a delta-seconds `Retry-After` header. Anything else falls back to exponential backoff."""
    if not value:
        return None
    try:
        delay = float(value.strip())
    except ValueError:
        return None
    return delay if delay >= 0 else None


_backoff = wait_exponential_jitter(initial=1, max=30)


def _server_delay(retry_state: RetryCallState) -> float | None:
    exc = retry_state.outcome.exception() if retry_state.outcome is not None else None
    return exc.retry_after if isinstance(exc, MemberfulRetryableError) else None


def _wait(retry_state: RetryCallState) -> float:
    retry_after = _server_delay(retry_state)
    if retry_after is not None:
        return min(retry_after, max_retry_after_seconds())
    return _backoff(retry_state)


@retry_with_deadline(
    retry=retry_if_exception_type(MemberfulRetryableError),
    stop=stop_after_attempt(MAX_ATTEMPTS),
    wait=_wait,
    requested_wait=_server_delay,
    reraise=True,
)
def _execute_query(session: requests.Session, url: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    try:
        response = session.post(url, json={"query": query, "variables": variables}, timeout=REQUEST_TIMEOUT_SECONDS)
    except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError) as e:
        # The transport adapter does not retry a POST, so transient network failures retry here.
        raise MemberfulRetryableError(f"Memberful API error (retryable): {e}") from e

    if response.status_code == 429 or response.status_code >= 500:
        raise MemberfulRetryableError(
            f"Memberful API error (retryable): status {response.status_code}",
            retry_after=_parse_retry_after(response.headers.get("Retry-After")),
        )

    # An unknown subdomain answers with an HTML 404 page.
    if response.status_code == 404:
        raise MemberfulAccountNotFoundError(ACCOUNT_NOT_FOUND_MESSAGE)

    try:
        payload = response.json()
    except ValueError:
        payload = None

    errors = payload.get("errors") if isinstance(payload, dict) else None
    messages = [str(error.get("message", error)) for error in errors or []]

    if not response.ok:
        # Keep the standard "401 Client Error: ..." text that the non-retryable keys match, and add
        # the vendor's own message, such as "Invalid authentication token.".
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            detail = f" (Memberful API: {'; '.join(messages)})" if messages else ""
            raise requests.HTTPError(f"{e}{detail}", response=response) from None

    if errors:
        raise MemberfulGraphQLError(response.status_code, messages)
    if not isinstance(payload, dict):
        raise MemberfulRetryableError("Memberful API error (retryable): response is not JSON")
    return payload.get("data") or {}


def _flatten_row(node: dict[str, Any], config: MemberfulEndpointConfig) -> dict[str, Any]:
    row = dict(node)
    for source_field, key, column in config.nested_values:
        nested = node.get(source_field)
        row[column] = nested.get(key) if isinstance(nested, dict) else None
    for source_field, column in config.nested_id_lists:
        items = node.get(source_field)
        row[column] = [item["id"] for item in items if item and "id" in item] if isinstance(items, list) else None
    for source_field in {*(f for f, _, _ in config.nested_values), *(f for f, _ in config.nested_id_lists)}:
        row.pop(source_field, None)
    return row


def _connection_query(config: MemberfulEndpointConfig) -> str:
    if config.created_at_filter:
        return (
            f"query MemberfulPage($first: Int!, $after: String, $createdAt: CreatedAtFilter) {{ "
            f"{config.root_field}(first: $first, after: $after, createdAt: $createdAt) {{ "
            f"nodes {{ {config.fields} }} pageInfo {{ endCursor hasNextPage }} }} }}"
        )
    return (
        f"query MemberfulPage($first: Int!, $after: String) {{ "
        f"{config.root_field}(first: $first, after: $after) {{ "
        f"nodes {{ {config.fields} }} pageInfo {{ endCursor hasNextPage }} }} }}"
    )


def _list_query(config: MemberfulEndpointConfig) -> str:
    return f"query MemberfulList {{ {config.root_field} {{ {config.fields} }} }}"


def _to_unix_seconds(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, datetime):
        return int((value if value.tzinfo else value.replace(tzinfo=UTC)).timestamp())
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lstrip("-").isdigit():
            return int(stripped)
        try:
            parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        except ValueError:
            return None
        return int((parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).timestamp())
    return None


def _iter_connection(
    session: requests.Session,
    url: str,
    config: MemberfulEndpointConfig,
    manager: ResumableSourceManager[MemberfulResumeConfig],
    created_at_gte: int | None,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    query = _connection_query(config)
    after: str | None = None

    resume = manager.load_state() if manager.can_resume() else None
    if resume is not None:
        if resume.completed:
            return
        if resume.cursor:
            after = resume.cursor
            created_at_gte = resume.created_at_gte
            logger.debug(f"Memberful: resuming {config.root_field} from a saved cursor")

    while True:
        variables: dict[str, Any] = {"first": PAGE_SIZE, "after": after}
        if config.created_at_filter:
            variables["createdAt"] = {"gte": created_at_gte} if created_at_gte is not None else None

        data = _execute_query(session, url, query, variables)
        connection = data.get(config.root_field) or {}
        rows = [_flatten_row(node, config) for node in connection.get("nodes") or [] if node]
        page_info = connection.get("pageInfo") or {}
        next_cursor = page_info.get("endCursor") if page_info.get("hasNextPage") else None
        if next_cursor is not None and next_cursor == after:
            raise ValueError(f"Memberful pagination for {config.root_field} is not advancing (repeated cursor)")

        manager.save_state(
            MemberfulResumeConfig(cursor=next_cursor, created_at_gte=created_at_gte, completed=next_cursor is None)
        )
        if rows:
            yield rows
        else:
            manager.safe_point()

        if next_cursor is None:
            return
        after = next_cursor


def _iter_list(
    session: requests.Session,
    url: str,
    config: MemberfulEndpointConfig,
    manager: ResumableSourceManager[MemberfulResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = manager.load_state() if manager.can_resume() else None
    if resume is not None and resume.completed:
        return

    data = _execute_query(session, url, _list_query(config), {})
    rows = [_flatten_row(node, config) for node in data.get(config.root_field) or [] if node]
    manager.save_state(MemberfulResumeConfig(completed=True))
    if rows:
        yield rows


def memberful_source(
    subdomain: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MemberfulResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = MEMBERFUL_ENDPOINTS.get(endpoint)
    if config is None:
        raise ValueError(f"Unknown Memberful endpoint: {endpoint}")
    url = graphql_url(subdomain)

    created_at_gte = (
        _to_unix_seconds(db_incremental_field_last_value)
        if should_use_incremental_field and config.created_at_filter
        else None
    )

    def get_rows() -> Iterator[list[dict[str, Any]]]:
        session = _make_session(api_key)
        try:
            if config.paginated:
                yield from _iter_connection(session, url, config, resumable_source_manager, created_at_gte, logger)
            else:
                yield from _iter_list(session, url, config, resumable_source_manager)
        finally:
            session.close()

    return SourceResponse(
        name=endpoint,
        items=get_rows,
        primary_keys=[config.primary_key],
        partition_count=1 if config.partition_keys else None,
        partition_size=1 if config.partition_keys else None,
        partition_mode="datetime" if config.partition_keys else None,
        partition_format="month" if config.partition_keys else None,
        partition_keys=config.partition_keys,
        # Memberful documents no order for its connections, so the watermark moves only when a run completes.
        sort_mode=None,
    )


def validate_credentials(subdomain: str, api_key: str) -> tuple[bool, str | None]:
    try:
        url = graphql_url(subdomain)
    except ValueError as e:
        return False, str(e)

    session = _make_session(api_key)
    try:
        _execute_query(session, url, VALIDATE_CREDENTIALS_QUERY, {})
    except MemberfulAccountNotFoundError:
        return False, ACCOUNT_NOT_FOUND_MESSAGE
    except MemberfulGraphQLError as e:
        if any("authentication" in message.lower() for message in e.messages):
            return False, INVALID_API_KEY_MESSAGE
        return False, str(e)
    except requests.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else None
        if status_code == 401:
            return False, INVALID_API_KEY_MESSAGE
        if status_code == 403:
            return (
                False,
                "This Memberful API key has no API access. Check the custom application settings in Memberful.",
            )
        return False, f"Could not connect to Memberful: {e}"
    except MemberfulRetryableError as e:
        return False, f"Could not reach Memberful. Try again later. ({e})"
    finally:
        session.close()
    return True, None
