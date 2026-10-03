import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
import structlog
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.power_bi_admin.settings import (
    ACTIVITY_EVENTS_ENDPOINT,
    ACTIVITY_EVENTS_RETENTION_DAYS,
    BASE_URL,
    LOGIN_BASE_URL,
    MAX_CONTINUATION_PAGES,
    MAX_ODATA_PAGES,
    ODATA_PAGE_SIZE,
    POWER_BI_ADMIN_ENDPOINTS,
    TOKEN_SCOPE,
)

REQUEST_TIMEOUT_SECONDS = 120
VALIDATE_TIMEOUT_SECONDS = 30

_module_logger: FilteringBoundLogger = structlog.get_logger(__name__)

ADMIN_API_DENIED_ERROR = (
    "Power BI denied access to the admin APIs. Enable service principal access to the read-only "
    "admin APIs in the Fabric admin portal and grant the app Tenant.Read.All."
)


@dataclasses.dataclass(frozen=True)
class PowerBiAdminResumeConfig:
    """Cursor for whichever endpoint the job is walking.

    Activity events walk one UTC day at a time, with `continuation_token` holding the
    mid-day cursor. Inventory endpoints walk an OData `$skip` offset. Both live in one
    dataclass, and the manager is namespaced per endpoint so the formats never mix.
    """

    next_day: Optional[str] = None
    continuation_token: Optional[str] = None
    skip: Optional[int] = None


def _coerce_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.astimezone(UTC).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            # Power BI stamps activity events as `2026-07-25T07:55:15Z`; `fromisoformat`
            # handles the trailing Z from Python 3.11 on.
            return datetime.fromisoformat(stripped).date()
        except ValueError:
            return None
    return None


def _parse_creation_time(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _normalize_activity_event(row: dict[str, Any]) -> dict[str, Any]:
    """Type `CreationTime` as a real datetime so it works as a cursor and partition key."""
    parsed = _parse_creation_time(row.get("CreationTime"))
    if parsed is not None:
        row["CreationTime"] = parsed
    return row


class PowerBiAdminClient:
    """Minimal Power BI admin API client: mints an Entra ID token and issues GETs.

    Access tokens last about an hour, so a long sync re-mints on the first 401 rather than
    failing the job.
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        logger: FilteringBoundLogger,
    ) -> None:
        self._tenant_id = tenant_id.strip()
        self._client_id = client_id.strip()
        self._client_secret = client_secret
        self._logger = logger
        self._session = make_tracked_session(redact_values=(client_secret,))
        self._token: Optional[str] = None

    @property
    def token_url(self) -> str:
        return f"{LOGIN_BASE_URL}/{self._tenant_id}/oauth2/v2.0/token"

    def mint_token(self) -> str:
        response = self._session.post(
            self.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": TOKEN_SCOPE,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise ValueError("Entra ID did not return an access token for the service principal")
        self._token = token
        return token

    def get(self, path: str, params: Optional[dict[str, str]] = None, timeout: int = REQUEST_TIMEOUT_SECONDS) -> Any:
        url = f"{BASE_URL}{path}"
        if self._token is None:
            self.mint_token()

        def _do() -> requests.Response:
            return self._session.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=timeout,
            )

        response = _do()
        # Tokens expire mid-sync; re-mint once before treating a 401 as a real denial.
        if response.status_code == 401:
            self.mint_token()
            response = _do()

        if not response.ok:
            self._logger.error(
                f"Power BI admin API error: status={response.status_code}, body={response.text[:500]}, url={url}"
            )
            response.raise_for_status()

        return response.json()


def _activity_event_pages(
    client: PowerBiAdminClient,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PowerBiAdminResumeConfig],
    start_day: date,
    end_day: date,
    resume_token: Optional[str],
) -> Iterator[list[dict[str, Any]]]:
    day = start_day
    continuation_token = resume_token

    while day <= end_day:
        pages = 0
        seen_tokens: set[str] = set()

        while True:
            if continuation_token:
                params = {"continuationToken": f"'{continuation_token}'"}
            else:
                # The API requires both bounds inside one UTC day, single-quoted.
                params = {
                    "startDateTime": f"'{day.isoformat()}T00:00:00'",
                    "endDateTime": f"'{day.isoformat()}T23:59:59'",
                }

            body = client.get("/activityevents", params=params)
            rows = body.get("activityEventEntities") or []
            if rows:
                yield [_normalize_activity_event(row) for row in rows]

            continuation_token = body.get("continuationToken")
            pages += 1

            # A page can come back empty and still carry a token, so termination is
            # "token gone", never "no rows".
            if not continuation_token:
                break

            if continuation_token in seen_tokens:
                logger.warning(f"Power BI admin: repeated continuation token for {day.isoformat()}, stopping the day")
                continuation_token = None
                break
            seen_tokens.add(continuation_token)

            if pages >= MAX_CONTINUATION_PAGES:
                logger.warning(
                    f"Power BI admin: hit the {MAX_CONTINUATION_PAGES}-page cap for {day.isoformat()}, "
                    "the rest of the day is skipped"
                )
                continuation_token = None
                break

            # Save mid-day so a heartbeat timeout resumes inside the day rather than
            # refetching it. Saved after yielding, so a crash re-yields the last page and
            # merge dedupes on `Id`.
            resumable_source_manager.save_state(
                PowerBiAdminResumeConfig(next_day=day.isoformat(), continuation_token=continuation_token)
            )

        day += timedelta(days=1)
        resumable_source_manager.save_state(PowerBiAdminResumeConfig(next_day=day.isoformat()))


def _odata_pages(
    client: PowerBiAdminClient,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PowerBiAdminResumeConfig],
    endpoint: str,
    start_skip: int,
) -> Iterator[list[dict[str, Any]]]:
    config = POWER_BI_ADMIN_ENDPOINTS[endpoint]
    skip = start_skip

    for page in range(MAX_ODATA_PAGES):
        params = {"$top": str(ODATA_PAGE_SIZE), "$skip": str(skip)}
        body = client.get(config.path, params=params)
        rows = body.get(config.data_key) or []
        if rows:
            yield rows

        if len(rows) < ODATA_PAGE_SIZE:
            return

        skip += len(rows)
        resumable_source_manager.save_state(PowerBiAdminResumeConfig(skip=skip))

        if page == MAX_ODATA_PAGES - 1:
            logger.warning(f"Power BI admin: hit the {MAX_ODATA_PAGES}-page cap for {endpoint}, later rows are skipped")


def _single_page(client: PowerBiAdminClient, endpoint: str) -> Iterator[list[dict[str, Any]]]:
    config = POWER_BI_ADMIN_ENDPOINTS[endpoint]
    body = client.get(config.path)
    rows = body.get(config.data_key) or []
    if rows:
        yield rows


@dataclasses.dataclass(frozen=True)
class _ActivityEventWindow:
    """Result of resolving the activity-events sync window: which UTC days to
    walk and, if resuming mid-day, the continuation token to restart from."""

    start_day: date
    end_day: date
    resume_token: Optional[str]


def _activity_event_window(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    resume: Optional[PowerBiAdminResumeConfig],
    logger: FilteringBoundLogger,
) -> _ActivityEventWindow:
    today = datetime.now(UTC).date()
    earliest = today - timedelta(days=ACTIVITY_EVENTS_RETENTION_DAYS - 1)
    start = earliest

    if should_use_incremental_field:
        last_value = _coerce_date(db_incremental_field_last_value)
        if last_value is not None:
            # Restart at the watermark's own day, not the day after: a day is only fully
            # fetched once we move past it, and merge dedupes on `Id`. This also means the
            # order of events inside a day never matters.
            start = max(start, last_value)

    resume_token: Optional[str] = None
    if resume is not None:
        resumed = _coerce_date(resume.next_day)
        if resumed is not None:
            start = max(resumed, earliest)
            # A mid-day token is only valid for the day it was issued against.
            if resumed >= earliest:
                resume_token = resume.continuation_token
            logger.debug(f"Power BI admin: resuming activity events from {start.isoformat()}")

    return _ActivityEventWindow(start_day=start, end_day=today, resume_token=resume_token)


def _get_rows(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PowerBiAdminResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    config = POWER_BI_ADMIN_ENDPOINTS[endpoint]
    client = PowerBiAdminClient(tenant_id, client_id, client_secret, logger)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if endpoint == ACTIVITY_EVENTS_ENDPOINT:
        window = _activity_event_window(should_use_incremental_field, db_incremental_field_last_value, resume, logger)
        yield from _activity_event_pages(
            client, logger, resumable_source_manager, window.start_day, window.end_day, window.resume_token
        )
        return

    if not config.supports_odata_paging:
        yield from _single_page(client, endpoint)
        return

    start_skip = resume.skip if resume is not None and resume.skip is not None else 0
    yield from _odata_pages(client, logger, resumable_source_manager, endpoint, start_skip)


def power_bi_admin_source(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PowerBiAdminResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = POWER_BI_ADMIN_ENDPOINTS[endpoint]
    has_datetime_partition = config.partition_key is not None

    return SourceResponse(
        name=endpoint,
        items=lambda: _get_rows(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if has_datetime_partition else None,
        partition_format="month" if has_datetime_partition else None,
        partition_keys=[config.partition_key] if config.partition_key is not None else None,
        # Days are walked oldest-first, and each day is refetched from its start, so the
        # watermark only ever moves forward.
        sort_mode="asc",
    )


def validate_credentials(
    tenant_id: str,
    client_id: str,
    client_secret: str,
) -> tuple[bool, Optional[str]]:
    if not tenant_id.strip():
        return False, "Enter the directory (tenant) ID of your Entra ID tenant."

    client = PowerBiAdminClient(tenant_id, client_id, client_secret, _module_logger)

    try:
        client.mint_token()
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status in (400, 401):
            return (
                False,
                "Entra ID rejected the service principal. Check the tenant ID, application (client) ID, "
                "and client secret.",
            )
        return False, f"Could not get a token from Entra ID (status {status})."
    except Exception as e:
        return False, f"Could not reach Entra ID ({e}). Please retry."

    try:
        client.get("/groups", params={"$top": "1"}, timeout=VALIDATE_TIMEOUT_SECONDS)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        # Every table here needs the same tenant-wide admin grant, so a denial is a blocking
        # misconfiguration rather than one missing per-table scope.
        if status in (401, 403):
            return False, ADMIN_API_DENIED_ERROR
        return False, f"The Power BI admin API returned an unexpected status ({status})."
    except Exception as e:
        return False, f"Could not reach the Power BI admin API ({e}). Please retry."

    return True, None
