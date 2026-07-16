import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
import structlog
from dateutil import parser as dateutil_parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.automox.settings import (
    AUTOMOX_ENDPOINTS,
    AutomoxEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

AUTOMOX_BASE_URL = "https://console.automox.com/api"
REQUEST_TIMEOUT_SECONDS = 60

# Stable prefixes for the auth-failure messages matched by `get_non_retryable_errors` — retrying
# can never fix a bad key or a misconfigured organization, so syncs stop instead of looping.
ORG_NOT_FOUND_ERROR = "Automox organization not found"
MULTIPLE_ORGS_ERROR = "Automox API key has access to multiple organizations"


class AutomoxRetryableError(Exception):
    pass


class AutomoxOrganizationError(Exception):
    pass


@dataclasses.dataclass
class AutomoxResumeConfig:
    # Zero-indexed page of the next request. Automox paginates with page/limit, so persisting the
    # page number lets a sync pick back up after a heartbeat timeout.
    page: int = 0
    # The server-side time filter value the interrupted run was using. Reused verbatim on resume:
    # recomputing it from the (possibly advanced) watermark would change the filtered result set
    # and make the saved page number point at different rows.
    incremental_param_value: str | None = None


def _make_session(api_key: str) -> requests.Session:
    # `redact_values` masks the bearer token in logged URLs and captured HTTP samples so a failed
    # or sampled request can never persist the raw Automox credential in PostHog's HTTP telemetry.
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        redact_values=(api_key,),
    )


def _build_url(path: str, params: dict[str, Any]) -> str:
    query = {key: value for key, value in params.items() if value is not None and value != ""}
    return f"{AUTOMOX_BASE_URL}{path}?{urlencode(query)}"


@retry(
    retry=retry_if_exception_type((AutomoxRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_json(session: requests.Session, url: str, logger: FilteringBoundLogger) -> Any:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise AutomoxRetryableError(f"Automox API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Don't log the response body: it can echo back request details we'd rather not persist.
        logger.error(f"Automox API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    return response.json()


def _fetch_page(
    session: requests.Session, config: AutomoxEndpointConfig, url: str, logger: FilteringBoundLogger
) -> list[dict[str, Any]]:
    payload = _fetch_json(session, url, logger)

    if config.data_selector is not None:
        if not isinstance(payload, dict):
            raise ValueError(f"Automox API returned a non-object response: url={url}")
        payload = payload.get(config.data_selector) or []

    # A non-list 200 is a permanent API-contract violation (wrapped payload, proxy HTML, …), not a
    # transient failure — raise a plain ValueError so it surfaces immediately instead of burning
    # the retry budget on something retries can't fix.
    if not isinstance(payload, list):
        raise ValueError(f"Automox API returned a non-list response: url={url}")

    return payload


def list_organizations(session: requests.Session, logger: FilteringBoundLogger) -> list[dict[str, Any]]:
    # A single max-size page is plenty: an account with >500 zones is not a realistic case, and
    # `/orgs` is only used to resolve the org the user configured (or the key's only org).
    url = _build_url("/orgs", {"limit": 500, "page": 0})
    payload = _fetch_json(session, url, logger)
    if not isinstance(payload, list):
        raise ValueError("Automox API returned a non-list response for /orgs")
    return payload


def resolve_organization(
    session: requests.Session, organization_id: str | None, logger: FilteringBoundLogger
) -> tuple[int, str | None]:
    """Resolve the numeric organization ID and UUID the sync should run against.

    Automox global API keys can access several organizations, and two endpoint families need the
    org identifier in different shapes: most Console API endpoints take the numeric ID (`o=`),
    while Policy History takes the UUID (`org=`). Both come from one `/orgs` call.
    """
    organizations = list_organizations(session, logger)

    normalized = (organization_id or "").strip()
    if normalized:
        for org in organizations:
            if str(org.get("id")) == normalized:
                return org["id"], org.get("uuid")
        raise AutomoxOrganizationError(
            f"{ORG_NOT_FOUND_ERROR}: no organization with ID {normalized} is accessible with this API key"
        )

    if len(organizations) == 1:
        only = organizations[0]
        return only["id"], only.get("uuid")

    raise AutomoxOrganizationError(
        f"{MULTIPLE_ORGS_ERROR}: set the organization ID on the source to pick which one to sync"
    )


def validate_credentials(api_key: str, organization_id: str | None = None) -> tuple[bool, str | None]:
    logger = structlog.get_logger(__name__)
    session = _make_session(api_key)
    try:
        resolve_organization(session, organization_id, logger)
    except AutomoxOrganizationError as e:
        return False, str(e)
    except Exception:
        return False, "Automox authentication failed. Check that your API key is valid and not expired."
    return True, None


def _coerce_datetime(value: Any) -> datetime | None:
    """Coerce a persisted incremental watermark (datetime, date, ISO string, or epoch) to UTC."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            parsed = dateutil_parser.parse(value)
        except (ValueError, OverflowError):
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _incremental_param_value(config: AutomoxEndpointConfig, last_value: Any) -> str | None:
    """Format the persisted watermark as the endpoint's server-side time filter value."""
    dt = _coerce_datetime(last_value)
    if dt is None:
        return None

    # Cap a future-dated cursor at now so bad upstream data can't wedge the filter.
    now = datetime.now(UTC)
    if dt > now:
        dt = now

    if config.incremental_lookback is not None:
        dt = dt - config.incremental_lookback

    if config.incremental_param_is_date:
        return dt.astimezone(UTC).date().isoformat()
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_rows(
    api_key: str,
    organization_id: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AutomoxResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = AUTOMOX_ENDPOINTS[endpoint]
    # One session reused across every page so urllib3 keeps the connection alive.
    session = _make_session(api_key)

    org_id: int | None = None
    org_uuid: str | None = None
    if config.needs_org_id_param or config.org_uuid_param or "{org_id}" in config.path:
        org_id, org_uuid = resolve_organization(session, organization_id, logger)
        if config.org_uuid_param and not org_uuid:
            raise AutomoxOrganizationError(
                f"{ORG_NOT_FOUND_ERROR}: the organization has no UUID, which the {endpoint} endpoint requires"
            )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume else 0

    incremental_value: str | None = None
    if config.incremental_param and should_use_incremental_field:
        if resume:
            incremental_value = resume.incremental_param_value
        else:
            incremental_value = _incremental_param_value(config, db_incremental_field_last_value)
    if resume:
        logger.debug(f"Automox: resuming {endpoint} from page={page}")

    path = config.path.replace("{org_id}", str(org_id)) if org_id is not None else config.path

    while True:
        params: dict[str, Any] = {
            "page": page,
            "limit": config.page_size,
            **config.extra_params,
        }
        if config.needs_org_id_param and org_id is not None:
            params["o"] = org_id
        if config.org_uuid_param and org_uuid is not None:
            params[config.org_uuid_param] = org_uuid
        if config.incremental_param and incremental_value is not None:
            params[config.incremental_param] = incremental_value

        rows = _fetch_page(session, config, _build_url(path, params), logger)
        if not rows:
            break

        yield rows

        # A short page means we've reached the end of the resource.
        if len(rows) < config.page_size:
            break

        page += 1
        # Save AFTER yielding so a crash re-runs from the last persisted page rather than skipping
        # ahead; the merge dedupes any re-pulled rows on the primary key.
        resumable_source_manager.save_state(AutomoxResumeConfig(page=page, incremental_param_value=incremental_value))


def automox_source(
    api_key: str,
    organization_id: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AutomoxResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = AUTOMOX_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            organization_id=organization_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
    )
