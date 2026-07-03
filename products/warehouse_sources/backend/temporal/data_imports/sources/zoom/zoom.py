import base64
import dataclasses
from collections.abc import Callable, Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.zoom.settings import (
    ZOOM_ENDPOINTS,
    ZoomEndpointConfig,
)

ZOOM_API_BASE = "https://api.zoom.us/v2"
ZOOM_OAUTH_URL = "https://zoom.us/oauth/token"

# Bound the number of pages we fetch for a single user during fan-out so a
# pathological account can't trigger an unbounded scan.
MAX_PAGES_PER_USER = 1000


class ZoomRetryableError(Exception):
    pass


@dataclasses.dataclass
class ZoomResumeConfig:
    # Cursor for the list endpoint currently being paginated.
    next_page_token: str = ""
    # Fan-out only: number of users fully processed so far. Top-level endpoints
    # leave this at 0.
    user_index: int = 0


class ZoomClient:
    """Server-to-server OAuth client for the Zoom REST API.

    Zoom access tokens expire after ~1 hour, so the token is fetched lazily and
    refreshed once on a mid-sync 401 before giving up.
    """

    def __init__(
        self,
        account_id: str,
        client_id: str,
        client_secret: str,
        logger: Optional[FilteringBoundLogger] = None,
    ) -> None:
        self.account_id = account_id
        self.client_id = client_id
        self.client_secret = client_secret
        self._logger = logger
        # Disable session-level retries — retry/backoff is handled explicitly by
        # tenacity below so we can honour Zoom's 429 semantics deterministically.
        self._session = make_tracked_session(retry=Retry(total=0), redact_values=(client_secret,))
        self._token: Optional[str] = None

    def _basic_auth_header(self) -> str:
        raw = f"{self.client_id}:{self.client_secret}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    def fetch_token(self) -> str:
        params = {"grant_type": "account_credentials", "account_id": self.account_id}
        url = f"{ZOOM_OAUTH_URL}?{urlencode(params)}"
        response = self._session.post(url, headers={"Authorization": self._basic_auth_header()}, timeout=30)
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise ValueError("Zoom OAuth response did not include an access token")
        return token

    def _ensure_token(self) -> str:
        if self._token is None:
            self._token = self.fetch_token()
        return self._token

    @retry(
        retry=retry_if_exception_type((ZoomRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def _get(self, url: str, token: str) -> requests.Response:
        response = self._session.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=60)
        if response.status_code == 429 or response.status_code >= 500:
            raise ZoomRetryableError(f"Zoom API error (retryable): status={response.status_code}, url={url}")
        return response

    def request(self, path: str, params: Optional[dict[str, Any]] = None) -> requests.Response:
        url = f"{ZOOM_API_BASE}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"

        token = self._ensure_token()
        response = self._get(url, token)

        # The token may have expired mid-sync — refresh once and retry.
        if response.status_code == 401:
            self._token = None
            token = self._ensure_token()
            response = self._get(url, token)

        return response


def _paginate(
    client: ZoomClient,
    path: str,
    config: ZoomEndpointConfig,
    logger: FilteringBoundLogger,
    start_token: str,
    on_page: Callable[[str], None],
) -> Iterator[list[dict[str, Any]]]:
    """Yield each page of records for a single list endpoint.

    ``on_page(next_token)`` is invoked after each page is yielded so the caller
    can persist resume state *after* the batch is handed to the pipeline.
    """
    token = start_token
    pages = 0
    while True:
        params: dict[str, Any] = {"page_size": config.page_size, **config.params}
        if token:
            params["next_page_token"] = token

        response = client.request(path, params)
        if not response.ok:
            logger.error(f"Zoom API error: status={response.status_code}, body={response.text}, path={path}")
            response.raise_for_status()

        body = response.json()
        records = body.get(config.data_key) or []
        next_token = body.get("next_page_token") or ""

        if records:
            yield records

        pages += 1
        if not next_token or pages >= MAX_PAGES_PER_USER:
            if next_token:
                logger.warning(f"Zoom: hit page cap ({MAX_PAGES_PER_USER}) for {config.name} at path={path}")
            break

        token = next_token
        on_page(next_token)


def _list_all_user_ids(client: ZoomClient, logger: FilteringBoundLogger) -> list[str]:
    user_ids: list[str] = []
    token = ""
    while True:
        params: dict[str, Any] = {"page_size": ZOOM_ENDPOINTS["users"].page_size}
        if token:
            params["next_page_token"] = token

        response = client.request("/users", params)
        if not response.ok:
            logger.error(f"Zoom API error listing users: status={response.status_code}, body={response.text}")
            response.raise_for_status()

        body = response.json()
        # Direct access: a user without an id is a malformed response that should
        # fail loudly rather than silently drop the user (and its meetings/webinars).
        for user in body.get("users") or []:
            user_ids.append(user["id"])

        token = body.get("next_page_token") or ""
        if not token:
            break

    return user_ids


def _top_level_rows(
    client: ZoomClient,
    config: ZoomEndpointConfig,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[ZoomResumeConfig],
    resume: Optional[ZoomResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    start_token = resume.next_page_token if resume else ""

    def checkpoint(next_token: str) -> None:
        manager.save_state(ZoomResumeConfig(next_page_token=next_token))

    yield from _paginate(client, config.path, config, logger, start_token, checkpoint)


def _fan_out_rows(
    client: ZoomClient,
    config: ZoomEndpointConfig,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[ZoomResumeConfig],
    resume: Optional[ZoomResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    # Fan-out resumes at user granularity. The user list isn't guaranteed to be
    # stable across a 24h resume window, but primary-key merge dedupes any rows
    # re-yielded after the list shifts, so resuming by index is safe.
    user_ids = _list_all_user_ids(client, logger)
    start_index = resume.user_index if resume else 0
    start_token = resume.next_page_token if resume else ""

    for index in range(start_index, len(user_ids)):
        user_id = user_ids[index]
        path = config.path.format(user_id=user_id)
        token = start_token if index == start_index else ""

        # Probe the first page so we can skip users that lack the feature
        # (e.g. no webinar license → 400) without aborting the whole sync.
        params: dict[str, Any] = {"page_size": config.page_size, **config.params}
        if token:
            params["next_page_token"] = token
        first = client.request(path, params)
        if first.status_code in (400, 404):
            logger.info(f"Zoom: skipping user {user_id} for {config.name} (status={first.status_code})")
            manager.save_state(ZoomResumeConfig(next_page_token="", user_index=index + 1))
            continue
        if not first.ok:
            logger.error(f"Zoom API error: status={first.status_code}, body={first.text}, path={path}")
            first.raise_for_status()

        body = first.json()
        records = body.get(config.data_key) or []
        next_token = body.get("next_page_token") or ""
        if records:
            yield records

        if next_token:

            def checkpoint(tok: str, _index: int = index) -> None:
                manager.save_state(ZoomResumeConfig(next_page_token=tok, user_index=_index))

            checkpoint(next_token)
            yield from _paginate(client, path, config, logger, next_token, checkpoint)

        manager.save_state(ZoomResumeConfig(next_page_token="", user_index=index + 1))


def get_rows(
    client: ZoomClient,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZoomResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = ZOOM_ENDPOINTS[endpoint]
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        logger.debug(f"Zoom: resuming {endpoint} from state {resume}")

    if config.fan_out:
        yield from _fan_out_rows(client, config, logger, resumable_source_manager, resume)
    else:
        yield from _top_level_rows(client, config, logger, resumable_source_manager, resume)


def zoom_source(
    account_id: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZoomResumeConfig],
) -> SourceResponse:
    config = ZOOM_ENDPOINTS[endpoint]
    client = ZoomClient(account_id, client_id, client_secret, logger)

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            client=client,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(
    account_id: str,
    client_id: str,
    client_secret: str,
    schema_name: Optional[str] = None,
) -> tuple[bool, str | None]:
    client = ZoomClient(account_id, client_id, client_secret)

    try:
        client.fetch_token()
    except requests.HTTPError:
        return False, "Invalid Zoom account ID, client ID, or client secret"
    except requests.RequestException as e:
        return False, str(e)
    except ValueError as e:
        return False, str(e)

    # At source-create (no specific schema) a genuine token is enough — users
    # may only grant scopes for the endpoints they intend to sync.
    if schema_name is None:
        return True, None

    response = client.request("/users", {"page_size": 1})
    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return (
            False,
            "Zoom credentials are valid but lack the required scopes. Grant user/meeting/webinar read scopes and retry.",
        )
    return False, f"Zoom API returned an unexpected status ({response.status_code})"
