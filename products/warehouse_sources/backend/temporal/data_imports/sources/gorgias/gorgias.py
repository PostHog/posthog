import re
import json
import base64
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.gorgias.settings import (
    GORGIAS_ENDPOINTS,
    GorgiasEndpointConfig,
)

# Gorgias caps `limit` at 100 on every list endpoint.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5

# A Gorgias subdomain is a single DNS label (1-63 chars, no leading/trailing hyphen).
# Validating against this before building the URL prevents a crafted domain (e.g. one
# containing `#`, `?`, `@`, or `.`) from breaking out of the `.gorgias.com` host and
# redirecting the request — and the Basic-auth header — to an attacker-controlled host.
_VALID_SUBDOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class GorgiasRetryableError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class GorgiasResumeConfig:
    # Opaque, short-lived cursor token returned in `meta.next_cursor`. We only persist
    # it for the duration of a single sync (Redis TTL is 24h) — never longer-term.
    cursor: str | None
    # Index into the endpoint's `param_variants` the cursor belongs to.
    variant: int = 0


def normalize_domain(domain: str) -> str:
    """Reduce whatever the user pasted to the bare Gorgias subdomain.

    Accepts `acme`, `acme.gorgias.com`, or `https://acme.gorgias.com/api/` and
    returns `acme`. The result is not yet validated — `get_base_url` enforces that
    it is a single safe DNS label before it is used to build a request URL.
    """
    value = domain.strip().lower()
    value = value.removeprefix("https://").removeprefix("http://")
    value = value.split("/", 1)[0]
    value = value.removesuffix(".gorgias.com")
    return value.strip("/")


def get_base_url(domain: str) -> str:
    subdomain = normalize_domain(domain)
    if not _VALID_SUBDOMAIN.match(subdomain):
        raise ValueError(
            "Invalid Gorgias domain. Use your account subdomain (letters, digits, and hyphens only), e.g. your-company."
        )
    return f"https://{subdomain}.gorgias.com/api"


def _coerce_to_utc(value: Any) -> datetime | None:
    """Best-effort parse of a Gorgias datetime (ISO string) or a DB watermark (datetime)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _page_newest(items: list[Any], field: str) -> datetime | None:
    """Newest value of `field` across a page; None if nothing parses."""
    parsed = [dt for item in items if isinstance(item, dict) and (dt := _coerce_to_utc(item.get(field))) is not None]
    return max(parsed) if parsed else None


def _incremental_sort_field(
    config: GorgiasEndpointConfig, should_use_incremental_field: bool, incremental_field: Optional[str]
) -> str | None:
    """The field to sort `<field>:desc` for an incremental sync, or None for full refresh.

    Guards against sending a sort the endpoint does not accept: an `order_by` Gorgias
    rejects (or silently ignores) would break the newest-first ordering the watermark
    stop condition relies on, so anything not in `sortable_datetime_fields` falls back
    to full refresh.
    """
    if should_use_incremental_field and incremental_field in config.sortable_datetime_fields:
        return incremental_field
    return None


def _uses_server_filter(config: GorgiasEndpointConfig, sort_field: str | None) -> bool:
    return sort_field is not None and sort_field in config.filterable_datetime_fields


def _field_value_as_text(value: Any) -> Any:
    # Values are text, number, or boolean depending on the field, so keep the column one type
    # rather than mixing them across rows.
    return value if value is None or isinstance(value, str) else json.dumps(value)


def _flatten_ticket_child(tickets: list[Any], child: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ticket in tickets:
        if not isinstance(ticket, dict):
            continue
        parent = {"ticket_id": ticket.get("id"), "ticket_created_datetime": ticket.get("created_datetime")}
        if child == "tags":
            for tag in ticket.get("tags") or []:
                if isinstance(tag, dict) and tag.get("id") is not None:
                    rows.append({**tag, **parent})
        elif child == "custom_fields":
            # Keyed by custom field id: {"<field_id>": {"id", "field", "value", "prediction"}}.
            for field_id, field_value in (ticket.get("custom_fields") or {}).items():
                if not isinstance(field_value, dict):
                    continue
                rows.append(
                    {
                        **field_value,
                        **parent,
                        "field_id": int(field_id) if str(field_id).isdigit() else field_id,
                        "value": _field_value_as_text(field_value.get("value")),
                    }
                )
        else:
            raise ValueError(f"Unknown Gorgias ticket child collection: {child}")
    return rows


def _flatten_customer_field_values(customer: dict[str, Any], items: list[Any]) -> list[dict[str, Any]]:
    parent = {"customer_id": customer.get("id"), "customer_created_datetime": customer.get("created_datetime")}
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        field = item.get("field")
        field_id = field.get("id") if isinstance(field, dict) else None
        if field_id is None:
            continue
        rows.append({**item, **parent, "field_id": field_id, "value": _field_value_as_text(item.get("value"))})
    return rows


def _get_auth_header(email: str, api_key: str) -> str:
    token = base64.b64encode(f"{email}:{api_key}".encode()).decode()
    return f"Basic {token}"


def get_headers(email: str, api_key: str) -> dict[str, str]:
    return {
        "Authorization": _get_auth_header(email, api_key),
        "Accept": "application/json",
    }


def validate_credentials(domain: str, email: str, api_key: str) -> tuple[bool, str | None]:
    """Cheap probe to confirm the credentials are genuine.

    `/account` is the canonical "who am I" endpoint and the lightest call available.
    A 200 means the basic-auth pair is valid; 401/403 means it is not.
    """
    try:
        url = f"{get_base_url(domain)}/account"
    except ValueError as e:
        return False, str(e)

    try:
        session = make_tracked_session(headers=get_headers(email, api_key), redact_values=(api_key,))
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception as e:
        return False, f"Could not connect to Gorgias: {e}"

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Gorgias credentials. Check your domain, email, and API key."
    return False, f"Gorgias API returned an unexpected status: {response.status_code}"


def get_rows(
    domain: str,
    email: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GorgiasResumeConfig],
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[Any]:
    config = GORGIAS_ENDPOINTS[endpoint]
    base_url = get_base_url(domain)
    url = f"{base_url}{config.path}"
    session = make_tracked_session(headers=get_headers(email, api_key), redact_values=(api_key,))

    # Most endpoints have no server-side time filter. For incremental we sort the chosen field
    # newest-first and stop paginating once a whole page predates the watermark, so a
    # steady-state sync only pulls the changed prefix instead of every page. Endpoints that do
    # filter server-side sort ascending and request only rows from the watermark onwards.
    sort_field = _incremental_sort_field(config, should_use_incremental_field, incremental_field)
    server_filtered = _uses_server_filter(config, sort_field)
    watermark = _coerce_to_utc(db_incremental_field_last_value) if sort_field else None
    filter_params: dict[str, str] = {}
    stop_watermark: datetime | None = None
    if server_filtered:
        order_by: str | None = f"{sort_field}:asc"
        if watermark is not None:
            filter_params[f"{sort_field}[gte]"] = watermark.isoformat()
    elif sort_field:
        order_by = f"{sort_field}:desc"
        stop_watermark = watermark
    else:
        order_by = config.order_by

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume_config.cursor if resume_config else None
    start_variant = resume_config.variant if resume_config else 0
    if resume_config:
        logger.debug(f"Gorgias: resuming {endpoint} from saved cursor")

    @retry(
        retry=retry_if_exception_type(
            (GorgiasRetryableError, requests.ReadTimeout, requests.ConnectionError),
        ),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch(request_url: str, params: dict[str, Any]) -> requests.Response:
        # The tracked adapter already retries 429/5xx while honoring the Retry-After
        # header; this guard re-raises anything that slips through so tenacity can back off.
        response = session.get(request_url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code == 429 or response.status_code >= 500:
            raise GorgiasRetryableError(
                f"Gorgias API error (retryable): status={response.status_code}, endpoint={endpoint}"
            )
        return response

    def raise_for_error(response: requests.Response) -> None:
        if not response.ok:
            logger.error(f"Gorgias API error: status={response.status_code}, body={response.text}, endpoint={endpoint}")
            response.raise_for_status()

    def fetch_page(request_cursor: str | None, variant_params: dict[str, str]) -> Any:
        # `cursor` is documented as "position in the list of resources" — the list is
        # defined by `order_by`/`limit`, so we re-send them on every page to keep the
        # sort stable. The docs list `cursor` and `order_by` as coexisting params (no
        # mutual exclusion); dropping order_by on follow-up pages could reset to the
        # endpoint default and corrupt the newest-first order incremental relies on.
        params: dict[str, Any] = {"limit": PAGE_SIZE, **variant_params, **filter_params}
        if order_by:
            params["order_by"] = order_by
        if request_cursor:
            params["cursor"] = request_cursor

        response = fetch(url, params)
        raise_for_error(response)
        return response.json()

    def fetch_child_rows(child_path: str, parents: list[Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for parent in parents:
            if not isinstance(parent, dict) or not isinstance(parent.get("id"), int):
                continue
            response = fetch(f"{base_url}{child_path.format(id=parent['id'])}", {})
            # The parent can be deleted between listing it and fetching its children.
            if response.status_code == 404:
                continue
            raise_for_error(response)
            data = response.json()
            items = data.get("data", []) if isinstance(data, dict) else data
            rows.extend(_flatten_customer_field_values(parent, items or []))
        return rows

    def page_rows(items: list[Any]) -> list[Any]:
        if config.child_path:
            return fetch_child_rows(config.child_path, items)
        if config.ticket_child:
            return _flatten_ticket_child(items, config.ticket_child)
        return items

    for variant_index in range(start_variant, len(config.param_variants)):
        variant_params = config.param_variants[variant_index]
        while True:
            data = fetch_page(cursor, variant_params)

            items = data.get("data", [])
            next_cursor = (data.get("meta") or {}).get("next_cursor")

            # Rows arrive newest-first under incremental sort; once an entire page predates the
            # watermark, everything further back is already synced, so stop.
            reached_watermark = False
            if stop_watermark is not None and sort_field is not None and items:
                page_newest = _page_newest(items, sort_field)
                reached_watermark = page_newest is not None and page_newest < stop_watermark

            rows = page_rows(items) if items else []

            # Stage the position after this page before yielding it. A resumed full refresh
            # appends, so a cursor that lags one page behind would write that page twice. The
            # final page stages a variant past the end, so a resume after it reads nothing.
            if next_cursor and not reached_watermark:
                resumable_source_manager.save_state(GorgiasResumeConfig(cursor=next_cursor, variant=variant_index))
            else:
                resumable_source_manager.save_state(GorgiasResumeConfig(cursor=None, variant=variant_index + 1))

            if rows:
                yield rows
            else:
                # A fan-out page whose parents have no children yields nothing, and many in a row
                # would otherwise hold off a worker shutdown.
                resumable_source_manager.safe_point()

            if not next_cursor or reached_watermark:
                break
            cursor = next_cursor

        cursor = None


def gorgias_source(
    domain: str,
    email: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GorgiasResumeConfig],
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = GORGIAS_ENDPOINTS[endpoint]
    sort_field = _incremental_sort_field(config, should_use_incremental_field, incremental_field)
    newest_first = sort_field is not None and not _uses_server_filter(config, sort_field)

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            domain=domain,
            email=email,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        # Incremental without a server-side filter returns newest-first; everything else is
        # ascending. sort_mode must match the order rows actually arrive in.
        sort_mode="desc" if newest_first else "asc",
    )
