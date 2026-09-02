import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.pardot.settings import (
    PARDOT_ENDPOINTS,
    PardotEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.auth import (
    salesforce_refresh_access_token,
)

# Account Engagement runs on its own host per environment. Demos, developer orgs and
# sandboxes are served from the demo host, everything else from the production host. This
# is a separate axis from the Salesforce login host — a developer org signs in at
# login.salesforce.com but its business units still live on pi.demo.pardot.com.
PARDOT_HOSTS = {
    "production": "https://pi.pardot.com",
    "sandbox": "https://pi.demo.pardot.com",
}
# v5 caps a query page at 200 records.
PAGE_SIZE = 200
REQUEST_TIMEOUT_SECONDS = 60


@dataclasses.dataclass
class PardotResumeConfig:
    # v5 pages via an opaque `nextPageToken` that encapsulates the filters, limit and
    # orderBy of the original query, so the token alone is enough to resume.
    next_page_token: str


class PardotPageTokenExpiredError(Exception):
    """A saved `nextPageToken` was rejected — page tokens expire after 4 hours."""


def _api_host(environment: str) -> str:
    api_host = PARDOT_HOSTS.get(environment)
    if api_host is None:
        raise ValueError(f"Invalid Account Engagement environment: {environment}")
    return api_host


def _get_session(business_unit_id: str, access_token: str, refresh_token: str | None) -> requests.Session:
    # capture=False: prospect/visitor records carry PII (emails, addresses, phones, free-text
    # notes, visitor IPs) the name-based sample scrubber can't reliably redact, and the token
    # exchange returns a secret, so every request path must opt out of HTTP sample capture while
    # staying metered and logged.
    return make_tracked_session(
        headers={"Pardot-Business-Unit-Id": business_unit_id, "Accept": "application/json"},
        redact_values=tuple(value for value in (access_token, refresh_token) if value),
        capture=False,
    )


def _refresh_token(refresh_token: str | None, instance_url: str | None) -> str:
    """Mint a fresh access token part-way through a sync that outlived the current one.

    Account Engagement and the Salesforce CRM share one connected app and one token endpoint,
    so this rides the Salesforce source's helper — including its retry for Salesforce
    serializing concurrent refreshes of the same app.
    """
    if not refresh_token or not instance_url:
        raise ValueError("Reconnect the Account Engagement integration: it has no refresh token")
    # capture=False for the same reason as the source session: the refresh request carries the
    # refresh token and shared client secret, and its response a minted access token.
    return salesforce_refresh_access_token(refresh_token, instance_url, capture=False)


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor as the ISO 8601 UTC timestamp v5 filters expect."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        return str(value)

    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _cursor_field(config: PardotEndpointConfig, incremental_field: str | None) -> str | None:
    """The user's chosen cursor, if this endpoint actually advertises it."""
    advertised = {f["field"] for f in config.incremental_fields}
    if incremental_field and incremental_field in advertised:
        return incremental_field
    return None


def _build_query_params(
    config: PardotEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_SIZE, "fields": ",".join(config.fields)}

    cursor = _cursor_field(config, incremental_field) if should_use_incremental_field else None
    if cursor is not None:
        # Sort on the cursor field for every incremental run, including the first one
        # that has no watermark yet, so rows always arrive in the ascending order the
        # pipeline checkpoints against.
        params["orderBy"] = cursor
        if db_incremental_field_last_value is not None:
            # The inclusive variant re-reads the boundary record, which merge dedupes,
            # rather than risking a same-second row being skipped.
            params[f"{cursor}AfterOrEqualTo"] = _format_datetime(db_incremental_field_last_value)
    elif config.order_by is not None:
        params["orderBy"] = config.order_by

    return params


def _is_expired_page_token(response: requests.Response) -> bool:
    """Whether a 400 is the API rejecting our page token rather than the query itself.

    v5 page tokens expire after 4 hours; the rejection is a 400 whose body names the
    token. Matching on the message is the only signal documented, so keep it broad.
    """
    if response.status_code != 400:
        return False
    return "pagetoken" in response.text.lower().replace(" ", "").replace("_", "")


def validate_credentials(
    environment: str,
    business_unit_id: str,
    access_token: str,
    refresh_token: str | None = None,
    instance_url: str | None = None,
) -> tuple[bool, str | None]:
    """Read one campaign — the cheapest proof the token, business unit and host all line up."""
    try:
        api_host = _api_host(environment)
    except ValueError as e:
        return False, str(e)

    session = _get_session(business_unit_id, access_token, refresh_token)

    try:
        response = session.get(
            f"{api_host}/api/v5/objects/campaigns",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"limit": "1", "fields": "id"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception:
        return False, "Could not reach the Account Engagement API"

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        # The stored token can be older than its lifetime, so a 401 is expected rather than a
        # rejection. Mint a fresh one and try again before telling the user to reconnect.
        try:
            access_token = _refresh_token(refresh_token, instance_url)
            response = session.get(
                f"{api_host}/api/v5/objects/campaigns",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"limit": "1", "fields": "id"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except Exception:
            return False, "Salesforce rejected the connection. Reconnect your Account Engagement account."
        if response.status_code == 200:
            return True, None
    if response.status_code in (401, 403):
        return (
            False,
            "Account Engagement rejected the connection. Check the business unit ID, and that the connected "
            "user has API access to it.",
        )
    return False, f"Account Engagement returned an unexpected status ({response.status_code})"


def get_rows(
    environment: str,
    business_unit_id: str,
    access_token: str,
    refresh_token: str | None,
    instance_url: str | None,
    endpoint: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[PardotResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = PARDOT_ENDPOINTS[endpoint]
    api_host = _api_host(environment)
    url = f"{api_host}/api/{api_version}/objects/{config.path}"

    session = _get_session(business_unit_id, access_token, refresh_token)
    token = access_token

    query_params = _build_query_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )
    # Only `fields` may ride along with a page token — sending limit/orderBy/filters
    # alongside one is a 400.
    page_params = {"fields": query_params["fields"]}

    def request(params: dict[str, Any]) -> dict[str, Any]:
        nonlocal token

        def _do() -> requests.Response:
            return session.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

        response = _do()
        # Salesforce access tokens are short lived; re-mint once if the sync outlives one.
        if response.status_code == 401:
            token = _refresh_token(refresh_token, instance_url)
            response = _do()

        if _is_expired_page_token(response):
            raise PardotPageTokenExpiredError(response.text)

        if not response.ok:
            logger.error(f"Account Engagement API error: status={response.status_code}, body={response.text}")
            response.raise_for_status()

        return response.json()

    next_page_token: str | None = None
    resumed = False
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page_token:
            next_page_token = resume.next_page_token
            resumed = True

    while True:
        params = {**page_params, "nextPageToken": next_page_token} if next_page_token else query_params
        try:
            data = request(params)
        except PardotPageTokenExpiredError:
            if not resumed:
                raise
            # The resumed token aged out of its 4h window: drop it and restart the
            # endpoint from the first page rather than failing the job.
            logger.warning("Account Engagement page token expired, restarting the sync from the first page")
            resumable_source_manager.clear_state()
            next_page_token = None
            resumed = False
            continue

        values = data.get("values") or []
        if values:
            yield values

        next_page_token = data.get("nextPageToken")
        if not next_page_token:
            break

        # Save after yielding so a crash re-yields the last page (merge dedupes)
        # instead of skipping it.
        resumable_source_manager.save_state(PardotResumeConfig(next_page_token=next_page_token))

    resumable_source_manager.clear_state()


def pardot_source(
    environment: str,
    business_unit_id: str,
    access_token: str,
    refresh_token: str | None,
    instance_url: str | None,
    endpoint: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[PardotResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = PARDOT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            environment=environment,
            business_unit_id=business_unit_id,
            access_token=access_token,
            refresh_token=refresh_token,
            instance_url=instance_url,
            endpoint=endpoint,
            api_version=api_version,
            resumable_source_manager=resumable_source_manager,
            logger=logger,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=[config.primary_key],
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
