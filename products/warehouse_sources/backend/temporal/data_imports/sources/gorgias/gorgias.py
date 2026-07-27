import re
import base64
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
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


@dataclasses.dataclass
class GorgiasResumeConfig:
    # Opaque, short-lived cursor token returned in `meta.next_cursor`. We only persist
    # it for the duration of a single sync (Redis TTL is 24h) — never longer-term.
    cursor: str


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
    url = f"{get_base_url(domain)}{config.path}"
    session = make_tracked_session(headers=get_headers(email, api_key), redact_values=(api_key,))

    # Gorgias has no server-side time filter. For incremental we sort the chosen field
    # newest-first and stop paginating once a whole page predates the watermark, so a
    # steady-state sync only pulls the changed prefix instead of every page.
    sort_field = _incremental_sort_field(config, should_use_incremental_field, incremental_field)
    order_by = f"{sort_field}:desc" if sort_field else config.order_by
    watermark = _coerce_to_utc(db_incremental_field_last_value) if sort_field else None

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume_config.cursor if resume_config else None
    if cursor:
        logger.debug(f"Gorgias: resuming {endpoint} from saved cursor")

    @retry(
        retry=retry_if_exception_type(
            (GorgiasRetryableError, requests.ReadTimeout, requests.ConnectionError),
        ),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(request_cursor: str | None) -> dict[str, Any]:
        # `cursor` is documented as "position in the list of resources" — the list is
        # defined by `order_by`/`limit`, so we re-send them on every page to keep the
        # sort stable. The docs list `cursor` and `order_by` as coexisting params (no
        # mutual exclusion); dropping order_by on follow-up pages could reset to the
        # endpoint default and corrupt the newest-first order incremental relies on.
        params: dict[str, Any] = {"limit": PAGE_SIZE, "order_by": order_by}
        if request_cursor:
            params["cursor"] = request_cursor

        # The tracked adapter already retries 429/5xx while honoring the Retry-After
        # header; this guard re-raises anything that slips through so tenacity can back off.
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code == 429 or response.status_code >= 500:
            raise GorgiasRetryableError(
                f"Gorgias API error (retryable): status={response.status_code}, endpoint={endpoint}"
            )
        if not response.ok:
            logger.error(f"Gorgias API error: status={response.status_code}, body={response.text}, endpoint={endpoint}")
            response.raise_for_status()
        return response.json()

    while True:
        data = fetch_page(cursor)

        items = data.get("data", [])
        if items:
            yield items

        # Rows arrive newest-first under incremental sort; once an entire page predates the
        # watermark, everything further back is already synced, so stop.
        if watermark is not None and sort_field is not None and items:
            page_newest = _page_newest(items, sort_field)
            if page_newest is not None and page_newest < watermark:
                break

        next_cursor = (data.get("meta") or {}).get("next_cursor")
        if not next_cursor:
            break

        cursor = next_cursor
        # Save AFTER yielding so a crash re-yields the last batch (merge dedupes on the
        # primary key) instead of skipping it.
        resumable_source_manager.save_state(GorgiasResumeConfig(cursor=cursor))


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
    incremental = _incremental_sort_field(config, should_use_incremental_field, incremental_field) is not None

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
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        # Incremental sort returns newest-first; full refresh stays ascending on the
        # stable creation field. sort_mode must match the order rows actually arrive in.
        sort_mode="desc" if incremental else "asc",
    )
