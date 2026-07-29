import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.bill_com.settings import (
    BILL_COM_ENDPOINTS,
    CREATED_TIME_FIELD,
    UPDATED_TIME_FIELD,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# BILL runs the sandbox on a separate host, and a developer key is issued per environment.
BILL_COM_HOSTS = {
    "production": "https://gateway.prod.bill.com/connect",
    "sandbox": "https://gateway.stage.bill.com/connect",
}
# `max` is capped at 100 by the API (default 20).
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60


@dataclasses.dataclass
class BillComResumeConfig:
    next_page: str


class BillComAuthError(Exception):
    """Sign-in was rejected — the credentials are wrong, not a transient failure."""


def base_url(environment: str) -> str:
    host = BILL_COM_HOSTS.get(environment)
    if host is None:
        raise ValueError(f"Invalid BILL environment: {environment}")
    return host


def format_incremental_value(value: Any) -> str:
    """Format a cursor value as the ISO 8601 UTC date-time BILL's `filters` param expects."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        return str(value)

    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def error_message(response: requests.Response) -> str:
    """Pull the human-readable text out of BILL's error bodies.

    Failures arrive either as the gateway's `{"message": ...}` or as the API's
    `[{"message": ..., "code": ...}]` list.
    """
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]

    if isinstance(body, list) and body:
        first = body[0]
        if isinstance(first, dict):
            return str(first.get("message") or first.get("detail") or first)
    if isinstance(body, dict):
        return str(body.get("message") or body)
    return str(body)[:200]


class BillComClient:
    """Session-authenticated BILL v3 client.

    BILL has no bearer token: `POST /v3/login` exchanges the developer key plus the org sign-in for
    a `sessionId` that rides every subsequent request as a header. The session expires after 35
    minutes of inactivity, so a 401 mid-sync means "sign in again", not "bad credentials".
    """

    def __init__(
        self,
        *,
        username: str,
        password: str,
        organization_id: str,
        dev_key: str,
        environment: str,
        api_version: str,
    ) -> None:
        self._username = username
        self._password = password
        self._organization_id = organization_id
        self._dev_key = dev_key
        self._api_root = f"{base_url(environment)}/{api_version}"
        self._session_id: Optional[str] = None
        # capture=False keeps requests metered and logged but excludes them from HTTP sample
        # capture: BILL responses carry raw financial records (bank accounts, routing numbers,
        # payments, invoices, customers, vendors) and the login exchange returns a freshly minted
        # session ID in a generic field — content the name-based scrubbers can't reliably redact.
        self._session = make_tracked_session(redact_values=(password, dev_key), capture=False)

    @property
    def api_root(self) -> str:
        return self._api_root

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    def login(self) -> str:
        response = self._session.post(
            f"{self._api_root}/login",
            json={
                "username": self._username,
                "password": self._password,
                "organizationId": self._organization_id,
                "devKey": self._dev_key,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code in (400, 401, 403):
            raise BillComAuthError(f"BILL sign-in failed: {error_message(response)}")
        response.raise_for_status()

        session_id = response.json().get("sessionId")
        if not session_id:
            raise BillComAuthError("BILL sign-in did not return a session ID")

        self._session_id = str(session_id)
        return self._session_id

    def _get(self, path: str, params: dict[str, Any]) -> requests.Response:
        return self._session.get(
            f"{self._api_root}{path}",
            params=params,
            headers={"sessionId": self._session_id or "", "devKey": self._dev_key},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    def list_page(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._session_id is None:
            self.login()

        response = self._get(path, params)
        if response.status_code == 401:
            # The 35-minute inactivity expiry can bite a long sync; one re-login covers it.
            self.login()
            response = self._get(path, params)

        response.raise_for_status()
        body = response.json()
        return body if isinstance(body, dict) else {}


def build_params(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: Optional[str],
) -> dict[str, Any]:
    """Build the `max`/`sort`/`filters` query params shared by every BILL list endpoint.

    Sorting on the cursor field ascending is what makes `sort_mode="asc"` true, so the pipeline can
    advance its watermark after each page. Full-refresh syncs still sort (on the stable
    `createdTime`) so pagination can't skip or repeat rows as records are written mid-sync.
    """
    cursor_field = CREATED_TIME_FIELD
    if should_use_incremental_field:
        cursor_field = (
            incremental_field if incremental_field in (CREATED_TIME_FIELD, UPDATED_TIME_FIELD) else UPDATED_TIME_FIELD
        )

    params: dict[str, Any] = {"max": PAGE_SIZE, "sort": f"{cursor_field}:asc"}

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        params["filters"] = f"{cursor_field}:gte:{format_incremental_value(db_incremental_field_last_value)}"

    return params


def get_rows(
    client: BillComClient,
    endpoint: str,
    params: dict[str, Any],
    resumable_source_manager: ResumableSourceManager[BillComResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = BILL_COM_ENDPOINTS[endpoint]

    page: Optional[str] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page:
            page = resume.next_page

    while True:
        request_params = dict(params)
        if page:
            request_params["page"] = page

        body = client.list_page(config.path, request_params)
        results = body.get("results") or []
        if results:
            yield results

        next_page = str(body.get("nextPage") or "")
        if not next_page:
            resumable_source_manager.clear_state()
            return
        if next_page == page:
            # A repeated cursor would page forever; treat it as the end of the list.
            logger.warning(f"BILL returned a repeated page cursor for {endpoint}, stopping pagination")
            resumable_source_manager.clear_state()
            return

        # Saved after the page is yielded, so a crash re-yields the last page (merge dedupes on the
        # primary key) instead of skipping it.
        resumable_source_manager.save_state(BillComResumeConfig(next_page=next_page))
        page = next_page


def validate_credentials(
    username: str,
    password: str,
    organization_id: str,
    dev_key: str,
    environment: str,
    api_version: str,
) -> tuple[bool, Optional[str]]:
    try:
        client = BillComClient(
            username=username,
            password=password,
            organization_id=organization_id,
            dev_key=dev_key,
            environment=environment,
            api_version=api_version,
        )
        client.login()
    except (BillComAuthError, ValueError) as e:
        return False, str(e)
    except Exception:
        return False, "Could not reach BILL. Please check your credentials and try again."

    return True, None


def bill_com_source(
    username: str,
    password: str,
    organization_id: str,
    dev_key: str,
    environment: str,
    api_version: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BillComResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    client = BillComClient(
        username=username,
        password=password,
        organization_id=organization_id,
        dev_key=dev_key,
        environment=environment,
        api_version=api_version,
    )
    params = build_params(should_use_incremental_field, db_incremental_field_last_value, incremental_field)

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(client, endpoint, params, resumable_source_manager, logger),
        primary_keys=["id"],
        partition_mode="datetime",
        partition_format="month",
        # `createdTime` never changes, so partitions don't get rewritten on every sync.
        partition_keys=[CREATED_TIME_FIELD],
        sort_mode="asc",
    )
