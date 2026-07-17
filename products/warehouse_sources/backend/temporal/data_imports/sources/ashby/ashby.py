import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.ashby.settings import ASHBY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

ASHBY_BASE_URL = "https://api.ashbyhq.com"
PAGE_SIZE = 100  # Ashby's documented max (and default).
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint to confirm a key is genuine when no specific schema is being validated.
DEFAULT_PROBE_PATH = "department.list"

AUTH_ERROR_HINT = "Ashby API authentication or permission error"


class AshbyRetryableError(Exception):
    pass


class AshbyAPIError(Exception):
    pass


@dataclasses.dataclass
class AshbyResumeConfig:
    cursor: str


def _auth(api_key: str) -> tuple[str, str]:
    # Ashby uses HTTP Basic auth: API key as username, empty password.
    return (api_key, "")


def _headers() -> dict[str, str]:
    return {"Content-Type": "application/json", "Accept": "application/json"}


def _classify_failure_message(errors: list[Any]) -> tuple[bool, str]:
    """Return ``(is_auth_related, joined_message)`` for an ``success: false`` payload.

    Ashby reports many failures as HTTP 200 with ``success: false`` and an ``errors`` array,
    so we sniff the messages to decide whether it's an unrecoverable auth/permission problem.
    """
    message = "; ".join(str(e) for e in errors) or "unknown error"
    lowered = message.lower()
    is_auth = any(
        hint in lowered
        for hint in ("unauthorized", "not authorized", "invalid api key", "permission", "forbidden", "authentication")
    )
    return is_auth, message


def _errors_from_payload(data: dict[str, Any]) -> list[Any]:
    errors = data.get("errors")
    if errors:
        return errors if isinstance(errors, list) else [errors]
    if data.get("error"):
        return [data["error"]]
    return []


@retry(
    retry=retry_if_exception_type((AshbyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    api_key: str,
    path: str,
    body: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.post(
        f"{ASHBY_BASE_URL}/{path}", json=body, auth=_auth(api_key), headers=_headers(), timeout=REQUEST_TIMEOUT_SECONDS
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise AshbyRetryableError(f"Ashby API error (retryable): status={response.status_code}, path={path}")

    if response.status_code in (401, 403):
        raise AshbyAPIError(f"{response.status_code} Client Error: {AUTH_ERROR_HINT} for path {path}")

    if not response.ok:
        logger.error(f"Ashby API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    if not data.get("success", False):
        is_auth, message = _classify_failure_message(_errors_from_payload(data))
        if is_auth:
            raise AshbyAPIError(f"{AUTH_ERROR_HINT} for path {path}: {message}")
        raise AshbyAPIError(f"Ashby API error for path {path}: {message}")

    return data


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AshbyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = ASHBY_ENDPOINTS[endpoint]
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor: Optional[str] = resume.cursor if resume else None
    if cursor:
        logger.debug(f"Ashby: resuming {endpoint} from cursor")

    while True:
        body: dict[str, Any] = {"limit": PAGE_SIZE}
        if cursor:
            body["cursor"] = cursor

        data = _fetch_page(session, api_key, config.path, body, logger)

        results = data.get("results") or []
        if results:
            yield results

        next_cursor = data.get("nextCursor")
        if not data.get("moreDataAvailable", False) or not next_cursor:
            break

        cursor = next_cursor
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages
        # are persisted); merge/replace dedupes on the primary key.
        resumable_source_manager.save_state(AshbyResumeConfig(cursor=cursor))


def ashby_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AshbyResumeConfig],
) -> SourceResponse:
    config = ASHBY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_key,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def check_access(api_key: str, path: str) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate credentials.

    Returns a normalized ``(status, message)`` where status mimics HTTP semantics even when
    Ashby reports the failure as HTTP 200 + ``success: false``:
      200 = reachable, 401 = bad key, 403 = valid key without scope, other = unexpected.
    """
    session = make_tracked_session()
    try:
        response = session.post(
            f"{ASHBY_BASE_URL}/{path}", json={"limit": 1}, auth=_auth(api_key), headers=_headers(), timeout=15
        )
    except Exception as e:
        return 0, f"Could not connect to Ashby: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Ashby returned HTTP {response.status_code}"

    try:
        data = response.json()
    except ValueError:
        # A 200 that isn't JSON (e.g. a proxy/maintenance HTML page) is not a valid Ashby
        # response — fail validation rather than reporting the credentials as good.
        return 0, "Ashby returned a non-JSON response"

    if data.get("success", False):
        return 200, None

    is_auth, message = _classify_failure_message(_errors_from_payload(data))
    if is_auth:
        # Can't distinguish bad-key from missing-scope purely from the message; treat as 403
        # (valid key, insufficient scope) so source-create accepts keys scoped to a subset of
        # endpoints. A genuinely invalid key surfaces as HTTP 401 above.
        return 403, message
    return 400, message
