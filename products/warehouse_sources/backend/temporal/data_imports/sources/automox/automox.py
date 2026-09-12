import json
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
import structlog
from dateutil import parser as dateutil_parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.automox.settings import (
    AUTOMOX_ENDPOINTS,
    AutomoxEndpointConfig,
    AutomoxFanOutConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

AUTOMOX_BASE_URL = "https://console.automox.com/api"
REQUEST_TIMEOUT_SECONDS = 60

# Credential-bearing field names stripped from every row before it lands in the warehouse, at any
# depth. `access_key` is the org agent-enrollment secret (embedded on organization records and again
# under each user's `orgs[]` entry) — a teammate with warehouse query access could otherwise read it
# and enroll an attacker-controlled device. `intercom_hmac` is an Intercom identity-verification
# token on user records; paired with the user's ID and email it lets someone impersonate that user
# to Intercom.
CREDENTIAL_FIELD_NAMES = frozenset({"access_key", "intercom_hmac"})

# Stable prefixes for the auth-failure messages matched by `get_non_retryable_errors` — retrying
# can never fix a bad key or a misconfigured organization, so syncs stop instead of looping.
ORG_NOT_FOUND_ERROR = "Automox organization not found"
MULTIPLE_ORGS_ERROR = "Automox API key has access to multiple organizations"

# Reshapes one raw endpoint payload into warehouse rows, for the endpoints that don't already
# answer with a flat row list.
PayloadTransform = Callable[[Any], list[dict[str, Any]]]


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
    # Fan-out endpoints only: the parent-list page the interrupted run was on, and the index within
    # that page of the parent whose children `page` refers to.
    parent_page: int | None = None
    parent_index: int = 0


def _make_session(api_key: str) -> requests.Session:
    # `redact_values` masks the bearer token in logged URLs and captured HTTP samples so a failed
    # or sampled request can never persist the raw Automox credential in PostHog's HTTP telemetry.
    # `capture=False` keeps requests metered and logged but excludes their bodies from HTTP sample
    # capture: `/orgs` and `/users` responses embed org `access_key` enrollment secrets that the
    # name-based sample scrubbers don't recognise, and capture happens before row sanitization.
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        redact_values=(api_key,),
        capture=False,
    )


def _strip_credentials(value: Any) -> Any:
    """Recursively drop credential-bearing keys (see ``CREDENTIAL_FIELD_NAMES``) from a row."""
    if isinstance(value, dict):
        return {k: _strip_credentials(v) for k, v in value.items() if k not in CREDENTIAL_FIELD_NAMES}
    if isinstance(value, list):
        return [_strip_credentials(item) for item in value]
    return value


def _scope_row_to_org(row: dict[str, Any], org_id: int | None, field_map: dict[str, str]) -> dict[str, Any]:
    """Drop nested list entries tagged to organizations other than the resolved one.

    The `o` query param scopes which users are *listed*, but each user row still carries its full
    org memberships and org-tagged roles — metadata for organizations the source owner never
    selected. `field_map` maps a nested list field to the key on each entry carrying the org id.
    """
    if org_id is None or not field_map:
        return row
    scoped = dict(row)
    for field_name, org_key in field_map.items():
        value = scoped.get(field_name)
        if isinstance(value, list):
            scoped[field_name] = [
                item for item in value if isinstance(item, dict) and str(item.get(org_key)) == str(org_id)
            ]
    return scoped


def _inventory_value(value: Any) -> str | None:
    """Render one inventory reading as text.

    Automox types a reading's `value` per attribute — a plain string for most, a list of records
    for `data_records` entries — so storing it as-is would give the column a different type
    depending on which devices synced.
    """
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value)


def _flatten_device_inventory(payload: Any) -> list[dict[str, Any]]:
    """Flatten a device's nested inventory tree into one row per collected attribute.

    Automox answers with `categories -> <category> -> sub_categories -> <sub category> -> data`,
    where each data entry is a single named reading. A row per reading keeps the table's columns
    stable, which the tree is not: the categories present vary by OS and by the customer's tier.
    """
    documents = payload if isinstance(payload, list) else [payload]
    rows: list[dict[str, Any]] = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        categories = document.get("categories")
        # The reference documents a second `Categories` level under `categories`, while the
        # example responses omit it. Accept either.
        if isinstance(categories, dict) and isinstance(categories.get("Categories"), dict):
            categories = categories["Categories"]
        if not isinstance(categories, dict):
            continue
        for category_name, category in categories.items():
            sub_categories = category.get("sub_categories") if isinstance(category, dict) else None
            if not isinstance(sub_categories, dict):
                continue
            for sub_category_name, sub_category in sub_categories.items():
                entries = sub_category.get("data") if isinstance(sub_category, dict) else None
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict) or entry.get("name") is None:
                        continue
                    rows.append(
                        {
                            "category": category_name,
                            "sub_category": sub_category_name,
                            "name": entry.get("name"),
                            "friendly_name": entry.get("friendly_name"),
                            "description": entry.get("description"),
                            "type": entry.get("type"),
                            "value": _inventory_value(entry.get("value")),
                            "tags": entry.get("tags"),
                            "collected_at": entry.get("collected_at"),
                        }
                    )
    return rows


PAYLOAD_TRANSFORMS: dict[str, PayloadTransform] = {
    "device_inventory": _flatten_device_inventory,
}


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
    session: requests.Session,
    config: AutomoxEndpointConfig,
    url: str,
    logger: FilteringBoundLogger,
    transform: Optional["PayloadTransform"] = None,
) -> list[dict[str, Any]]:
    payload = _fetch_json(session, url, logger)

    if config.data_selector is not None:
        if not isinstance(payload, dict):
            raise ValueError(f"Automox API returned a non-object response: url={url}")
        payload = payload.get(config.data_selector) or []

    if transform is not None:
        return transform(payload)

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


def _fan_out_configs(config: AutomoxEndpointConfig) -> list[AutomoxEndpointConfig]:
    return [config] if config.fan_out is None else [config, config.fan_out.parent]


def _needs_organization(config: AutomoxEndpointConfig) -> bool:
    return any(
        c.needs_org_id_param or c.org_uuid_param or c.restrict_to_org or "{org_id}" in c.path or "{org_uuid}" in c.path
        for c in _fan_out_configs(config)
    )


def _requires_org_uuid(config: AutomoxEndpointConfig) -> bool:
    return any(c.org_uuid_param is not None or "{org_uuid}" in c.path for c in _fan_out_configs(config))


def _resolve_path(path: str, org_id: int | None, org_uuid: str | None) -> str:
    if org_id is not None:
        path = path.replace("{org_id}", str(org_id))
    if org_uuid is not None:
        path = path.replace("{org_uuid}", org_uuid)
    return path


def _request_params(
    config: AutomoxEndpointConfig,
    page: int,
    org_id: int | None,
    org_uuid: str | None,
    incremental_value: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.paginated:
        params["page"] = page
        params["limit"] = config.page_size
    params.update(config.extra_params)
    if config.needs_org_id_param and org_id is not None:
        params["o"] = org_id
    if config.org_uuid_param and org_uuid is not None:
        params[config.org_uuid_param] = org_uuid
    if config.incremental_param and incremental_value is not None:
        params[config.incremental_param] = incremental_value
    return params


def _iter_pages(
    session: requests.Session,
    config: AutomoxEndpointConfig,
    path: str,
    logger: FilteringBoundLogger,
    start_page: int,
    org_id: int | None,
    org_uuid: str | None,
    incremental_value: str | None = None,
    transform: Optional[PayloadTransform] = None,
) -> Iterator[tuple[int, bool, list[dict[str, Any]]]]:
    """Walk one endpoint path, yielding ``(page, is_last_page, rows)`` until it is exhausted."""
    page = start_page
    while True:
        url = _build_url(path, _request_params(config, page, org_id, org_uuid, incremental_value))
        rows = _fetch_page(session, config, url, logger, transform)
        if not rows:
            return

        # Decide on the raw page length: the caller's filtering can shrink a page without meaning
        # the resource is exhausted.
        is_last = not config.paginated or len(rows) < config.page_size
        yield page, is_last, rows
        if is_last:
            return
        page += 1


def _sanitize_rows(
    config: AutomoxEndpointConfig, rows: list[dict[str, Any]], org_id: int | None
) -> list[dict[str, Any]]:
    if config.restrict_to_org:
        rows = [row for row in rows if org_id is not None and str(row.get("id")) == str(org_id)]
    rows = [_strip_credentials(row) for row in rows]
    if config.org_scoped_list_fields:
        rows = [_scope_row_to_org(row, org_id, config.org_scoped_list_fields) for row in rows]
    return rows


def _iter_fan_out_rows(
    session: requests.Session,
    config: AutomoxEndpointConfig,
    fan_out: AutomoxFanOutConfig,
    path: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AutomoxResumeConfig],
    resume: AutomoxResumeConfig | None,
    org_id: int | None,
    org_uuid: str | None,
    transform: Optional[PayloadTransform] = None,
) -> Iterator[list[dict[str, Any]]]:
    """Walk the parent list and call the child endpoint once per parent row."""
    parent_path = _resolve_path(fan_out.parent.path, org_id, org_uuid)
    parent_page, skip_parents, child_page = 0, 0, 0
    if resume is not None and resume.parent_page is not None:
        parent_page, skip_parents, child_page = resume.parent_page, resume.parent_index, resume.page

    for page, _, parents in _iter_pages(session, fan_out.parent, parent_path, logger, parent_page, org_id, org_uuid):
        # Resuming re-reads the parent page and skips the parents already walked. Automox does not
        # promise a stable order across requests, so a parent added mid-sync can shift the page;
        # the merge dedupes whatever is re-read, and the next full sync picks up anything shifted.
        for index in range(skip_parents, len(parents)):
            start_child_page, child_page = child_page, 0
            parent = parents[index]
            parent_value = parent.get(fan_out.parent_field)
            if parent_value is None:
                continue

            child_path = path.replace(fan_out.placeholder, str(parent_value))
            parent_columns = {column: parent.get(field) for field, column in fan_out.include_from_parent.items()}

            for child_page_number, is_last, raw_rows in _iter_pages(
                session, config, child_path, logger, start_child_page, org_id, org_uuid, transform=transform
            ):
                rows = [{**parent_columns, **row} for row in _sanitize_rows(config, raw_rows, org_id)]
                if rows:
                    yield rows
                # Save AFTER yielding so a crash re-runs the last batch rather than skipping it.
                if not is_last:
                    resumable_source_manager.save_state(
                        AutomoxResumeConfig(page=child_page_number + 1, parent_page=page, parent_index=index)
                    )

            resumable_source_manager.save_state(AutomoxResumeConfig(page=0, parent_page=page, parent_index=index + 1))
        skip_parents = 0


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
    if _needs_organization(config):
        org_id, org_uuid = resolve_organization(session, organization_id, logger)
        if _requires_org_uuid(config) and not org_uuid:
            raise AutomoxOrganizationError(
                f"{ORG_NOT_FOUND_ERROR}: the organization has no UUID, which the {endpoint} endpoint requires"
            )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    incremental_value: str | None = None
    if config.incremental_param and should_use_incremental_field:
        if resume:
            incremental_value = resume.incremental_param_value
        else:
            incremental_value = _incremental_param_value(config, db_incremental_field_last_value)
    if resume:
        logger.debug(f"Automox: resuming {endpoint} from page={resume.page}")

    path = _resolve_path(config.path, org_id, org_uuid)
    transform = PAYLOAD_TRANSFORMS.get(endpoint)

    if config.fan_out is not None:
        yield from _iter_fan_out_rows(
            session=session,
            config=config,
            fan_out=config.fan_out,
            path=path,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            resume=resume,
            org_id=org_id,
            org_uuid=org_uuid,
            transform=transform,
        )
        return

    for page, is_last, raw_rows in _iter_pages(
        session,
        config,
        path,
        logger,
        resume.page if resume else 0,
        org_id,
        org_uuid,
        incremental_value,
        transform,
    ):
        rows = _sanitize_rows(config, raw_rows, org_id)
        if rows:
            yield rows

        # Save AFTER yielding so a crash re-runs from the last persisted page rather than skipping
        # ahead; the merge dedupes any re-pulled rows on the primary key.
        if not is_last:
            resumable_source_manager.save_state(
                AutomoxResumeConfig(page=page + 1, incremental_param_value=incremental_value)
            )


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
