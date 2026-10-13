"""Transport for the Similarweb REST API.

Hand-rolled rather than declared through the shared `rest_source` framework: every table fans
out over a list of domains the user types into the source form (Similarweb has no "list my
domains" entity to drive a parent resource from), each response wraps its series under a body
key named after the metric, and the rows need the domain, country and granularity that were
requested stamped onto them because the payload doesn't carry them.
"""

import re
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote

import requests
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.similarweb.settings import (
    API_VERSION_V5,
    BASE_URL,
    CAPABILITIES_PATH,
    CHUNK_ROWS,
    DEFAULT_COUNTRY,
    MAX_DOMAINS,
    PAGE_LIMIT,
    SIMILARWEB_ENDPOINTS,
    TRAFFIC_SOURCES,
    V5_ENGAGEMENT_PATH,
    V5_WORLDWIDE_COUNTRY,
    SimilarwebEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60

NO_DOMAINS_ERROR = "No domains configured for this Similarweb source"

_MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")
_COUNTRY_PATTERN = re.compile(r"^[a-z]{2}$")


@frozen
class SimilarwebResumeConfig:
    # Index into the configured domain list that the next request should start from.
    next_domain_index: int
    # Offset within that domain's result set, for the offset-paginated tables.
    next_offset: int = 0


def parse_domains(raw: Optional[str]) -> list[str]:
    """Split the configured domain list into the bare, lowercase domains the API expects."""
    if not raw:
        return []
    domains: list[str] = []
    seen: set[str] = set()
    for candidate in re.split(r"[,\n]", raw):
        domain = candidate.strip().lower()
        domain = re.sub(r"^https?://", "", domain)
        # Similarweb keys on the bare host: no scheme, no `www.`, no path.
        domain = domain.split("/")[0]
        domain = re.sub(r"^www\.", "", domain)
        if domain and domain not in seen:
            seen.add(domain)
            domains.append(domain)
    return domains


def normalize_country(country: Optional[str]) -> str:
    normalized = (country or "").strip().lower()
    return normalized or DEFAULT_COUNTRY


def is_valid_country(country: Optional[str]) -> bool:
    normalized = normalize_country(country)
    return normalized == DEFAULT_COUNTRY or bool(_COUNTRY_PATTERN.match(normalized))


def coerce_month(value: Any) -> Optional[str]:
    """Coerce a config value or incremental watermark to the `YYYY-MM` the API filters on."""
    if isinstance(value, datetime | date):
        return f"{value.year:04d}-{value.month:02d}"
    if isinstance(value, str):
        stripped = value.strip()
        if _MONTH_PATTERN.match(stripped):
            return stripped
        try:
            return coerce_month(datetime.fromisoformat(stripped))
        except ValueError:
            return None
    return None


def _parse_row_date(value: Any) -> Optional[datetime]:
    """Parse the API's period label into a timestamp.

    Series endpoints return `YYYY-MM-DD` while the rank endpoint returns `YYYY-MM`; both become
    a UTC timestamp at the start of the period so one typed `date` column works across tables.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if _MONTH_PATTERN.match(stripped):
        stripped = f"{stripped}-01"
    try:
        return datetime.fromisoformat(stripped).replace(tzinfo=UTC)
    except ValueError:
        return None


def _uses_v5_engagement(config: SimilarwebEndpointConfig, api_version: str) -> bool:
    """Whether this request goes to the V5 multi-metric engagement endpoint rather than legacy."""
    return api_version == API_VERSION_V5 and config.v5_metric is not None


@frozen
class _PreparedRequest:
    url: str
    params: dict[str, Any]
    headers: dict[str, str]


def _prepare_request(
    api_key: str,
    api_version: str,
    config: SimilarwebEndpointConfig,
    domain: str,
    country: str,
    granularity: str,
    start_month: Optional[str],
    end_month: Optional[str],
    offset: Optional[int] = None,
) -> _PreparedRequest:
    """Build the request for one call, dispatching on the resolved API version.

    V5 serves the engagement metrics from one `/v5/website-analysis` endpoint with `api-key` header
    auth and a `metrics` selector; every other table — and every table under the legacy pin — keeps
    the per-resource path and `api_key` query param it has always used.
    """
    if _uses_v5_engagement(config, api_version):
        params: dict[str, Any] = {"domain": domain, "metrics": config.v5_metric, "format": "json"}
        if config.accepts_country:
            # V5 spells the worldwide breakdown `ww`; the legacy `world` sentinel is rejected there.
            params["country"] = V5_WORLDWIDE_COUNTRY if country == DEFAULT_COUNTRY else country
        if config.accepts_granularity:
            params["granularity"] = granularity
        if start_month and end_month:
            params["start_date"] = start_month
            params["end_date"] = end_month
        return _PreparedRequest(url=f"{BASE_URL}{V5_ENGAGEMENT_PATH}", params=params, headers={"api-key": api_key})

    url = f"{BASE_URL}{config.path.format(domain=quote(domain, safe=''))}"
    legacy_params = _build_params(api_key, config, country, granularity, start_month, end_month, offset=offset)
    return _PreparedRequest(url=url, params=legacy_params, headers={})


def _build_params(
    api_key: str,
    config: SimilarwebEndpointConfig,
    country: str,
    granularity: str,
    start_month: Optional[str],
    end_month: Optional[str],
    offset: Optional[int] = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"api_key": api_key, "format": "json"}
    if config.accepts_country:
        params["country"] = country
    if config.accepts_granularity:
        params["granularity"] = granularity
    # The window params are only meaningful as a pair; with neither, the API returns its
    # default last-28-days window.
    if start_month and end_month:
        params["start_date"] = start_month
        params["end_date"] = end_month
    if config.paginated:
        params["limit"] = PAGE_LIMIT
        params["offset"] = offset or 0
    return params


def _request(
    session: requests.Session,
    prepared: _PreparedRequest,
    config: SimilarwebEndpointConfig,
    domain: str,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    url = prepared.url
    try:
        response = session.get(
            url, params=prepared.params, headers=prepared.headers or None, timeout=REQUEST_TIMEOUT_SECONDS
        )
    except requests.RequestException as exc:
        # Connection/timeout exceptions carry the prepared URL — including the api_key query param —
        # and str(exc) is persisted as the import's error, so re-raise with the param-free url only.
        raise type(exc)(f"Similarweb request failed ({type(exc).__name__}) for {url}") from None

    # Similarweb answers 401 with "data not found" — the documented cause is a domain it has no
    # data for, not a bad key (that is 403). One unknown domain shouldn't fail the other domains'
    # rows, so skip it and carry on.
    if response.status_code in (401, 404):
        logger.warning(f"Similarweb: no {config.name} data for '{domain}' (status {response.status_code})")
        return {}

    if not response.ok:
        logger.error(f"Similarweb API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        # Don't use raise_for_status(): it embeds response.url — which carries the api_key query
        # param — into the exception message, and that propagates to the job's stored error, logs,
        # and analytics. Raise with the param-free url instead.
        raise requests.HTTPError(f"Similarweb API returned status {response.status_code} for {url}", response=response)

    body = response.json()
    return body if isinstance(body, dict) else {}


def _series_rows(
    body: dict[str, Any],
    config: SimilarwebEndpointConfig,
    domain: str,
    country: str,
    granularity: str,
    logger: FilteringBoundLogger,
    api_version: str,
) -> list[dict[str, Any]]:
    # V5 wraps every metric's series under a standardized `data` key; legacy names the key after
    # the metric. Either way each row carries its `date` and the metric value.
    data_key = "data" if _uses_v5_engagement(config, api_version) else config.data_key
    payload = body.get(data_key)
    if not isinstance(payload, list):
        return []

    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        parsed_date = _parse_row_date(item.get("date"))
        if parsed_date is None:
            logger.warning(f"Similarweb: dropping {config.name} row for '{domain}' with unparsable date")
            continue
        row: dict[str, Any] = {"domain": domain, **item, "date": parsed_date}
        if config.accepts_country:
            row["country"] = country
        if config.accepts_granularity:
            row["granularity"] = granularity
        rows.append(row)
    return rows


def _traffic_sources_rows(
    body: dict[str, Any],
    config: SimilarwebEndpointConfig,
    domain: str,
    country: str,
    granularity: str,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    """Flatten `{"visits": {"<domain>": [{"source_type": ..., "visits": [...]}]}}` into rows."""
    payload = body.get(config.data_key)
    if not isinstance(payload, dict):
        return []

    rows: list[dict[str, Any]] = []
    for channels in payload.values():
        if not isinstance(channels, list):
            continue
        for channel in channels:
            if not isinstance(channel, dict):
                continue
            for point in channel.get("visits") or []:
                if not isinstance(point, dict):
                    continue
                parsed_date = _parse_row_date(point.get("date"))
                if parsed_date is None:
                    logger.warning(f"Similarweb: dropping traffic_sources row for '{domain}' with unparsable date")
                    continue
                rows.append(
                    {
                        "domain": domain,
                        "country": country,
                        "granularity": granularity,
                        "source_type": channel.get("source_type"),
                        "date": parsed_date,
                        "organic": point.get("organic"),
                        "paid": point.get("paid"),
                    }
                )
    return rows


def _record_rows(body: dict[str, Any], config: SimilarwebEndpointConfig, domain: str) -> list[dict[str, Any]]:
    payload = body.get(config.data_key)
    if not isinstance(payload, list):
        return []
    return [{"domain": domain, **record} for record in payload if isinstance(record, dict)]


def _resolve_window(
    config: SimilarwebEndpointConfig,
    granularity: str,
    start_date: Optional[str],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> tuple[Optional[str], Optional[str]]:
    """Resolve the `start_date`/`end_date` months to request, or `(None, None)` for the API default."""
    start_month = coerce_month(start_date)

    if should_use_incremental_field:
        watermark = coerce_month(db_incremental_field_last_value)
        if watermark is not None:
            # Re-request the watermark's own month rather than the one after it: the filter is
            # month-granular, and merge dedupes the periods already loaded.
            start_month = max(start_month, watermark) if start_month else watermark

    now = datetime.now(UTC)
    current_month = f"{now.year:04d}-{now.month:02d}"

    if start_month is None:
        # Similarweb's no-date "last 28 days" default is only valid for daily/weekly granularity, so
        # a monthly request must carry an explicit window; fall back to the current month rather than
        # send an invalid monthly/no-date request.
        if config.accepts_granularity and granularity == "monthly":
            return current_month, current_month
        return None, None

    return start_month, current_month


def _paginated_rows(
    session: requests.Session,
    config: SimilarwebEndpointConfig,
    domains: list[str],
    api_key: str,
    country: str,
    granularity: str,
    start_month: Optional[str],
    end_month: Optional[str],
    resumable_source_manager: ResumableSourceManager[SimilarwebResumeConfig],
    logger: FilteringBoundLogger,
    api_version: str,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = resume.next_domain_index if resume is not None else 0
    start_offset = resume.next_offset if resume is not None else 0

    for index in range(start_index, len(domains)):
        domain = domains[index]
        offset = start_offset if index == start_index else 0

        while True:
            prepared = _prepare_request(
                api_key, api_version, config, domain, country, granularity, start_month, end_month, offset=offset
            )
            rows = _record_rows(_request(session, prepared, config, domain, logger), config, domain)
            if rows:
                yield rows
            if len(rows) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT
            # Saved after the yield so a crash re-fetches the last page (merge dedupes it)
            # rather than skipping it.
            resumable_source_manager.save_state(SimilarwebResumeConfig(next_domain_index=index, next_offset=offset))

        resumable_source_manager.save_state(SimilarwebResumeConfig(next_domain_index=index + 1, next_offset=0))

    resumable_source_manager.clear_state()


def _series_chunks(
    session: requests.Session,
    config: SimilarwebEndpointConfig,
    domains: list[str],
    api_key: str,
    country: str,
    granularity: str,
    start_month: Optional[str],
    end_month: Optional[str],
    logger: FilteringBoundLogger,
    api_version: str,
) -> Iterator[list[dict[str, Any]]]:
    """Collect every domain's series, then emit it ordered by period.

    Each domain's request returns the whole requested window in one response, so the per-domain
    streams overlap in time. They have to be merged before yielding: the pipeline checkpoints the
    incremental watermark after every batch it receives, so emitting one domain's full history and
    then the next domain's would strand the second domain's older periods behind a watermark that
    has already advanced. The volume is bounded by the domain cap times the periods in the window,
    which stays small for aggregate traffic data.
    """
    rows: list[dict[str, Any]] = []
    for domain in domains:
        prepared = _prepare_request(api_key, api_version, config, domain, country, granularity, start_month, end_month)
        body = _request(session, prepared, config, domain, logger)
        if config.name == TRAFFIC_SOURCES:
            rows.extend(_traffic_sources_rows(body, config, domain, country, granularity, logger))
        else:
            rows.extend(_series_rows(body, config, domain, country, granularity, logger, api_version))

    rows.sort(key=lambda row: (row["date"], row["domain"]))

    for start in range(0, len(rows), CHUNK_ROWS):
        yield rows[start : start + CHUNK_ROWS]


def _get_rows(
    api_key: str,
    domains_raw: Optional[str],
    country: Optional[str],
    granularity: str,
    start_date: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SimilarwebResumeConfig],
    api_version: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    domains = parse_domains(domains_raw)
    if not domains:
        raise ValueError(NO_DOMAINS_ERROR)

    config = SIMILARWEB_ENDPOINTS[endpoint]
    normalized_country = normalize_country(country)
    start_month, end_month = _resolve_window(
        config, granularity, start_date, should_use_incremental_field, db_incremental_field_last_value
    )

    # The key rides in a query param, so it has to be named explicitly for redaction.
    session = make_tracked_session(redact_values=(api_key,))

    if config.paginated:
        yield from _paginated_rows(
            session,
            config,
            domains[:MAX_DOMAINS],
            api_key,
            normalized_country,
            granularity,
            start_month,
            end_month,
            resumable_source_manager,
            logger,
            api_version,
        )
        return

    yield from _series_chunks(
        session,
        config,
        domains[:MAX_DOMAINS],
        api_key,
        normalized_country,
        granularity,
        start_month,
        end_month,
        logger,
        api_version,
    )


def similarweb_source(
    api_key: str,
    domains: Optional[str],
    country: Optional[str],
    granularity: str,
    start_date: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SimilarwebResumeConfig],
    api_version: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = SIMILARWEB_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: _get_rows(
            api_key=api_key,
            domains_raw=domains,
            country=country,
            granularity=granularity,
            start_date=start_date,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            api_version=api_version,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )


def validate_credentials(api_key: str) -> tuple[bool, Optional[str]]:
    """Probe the free capabilities endpoint, which costs no data credits."""
    session = make_tracked_session(redact_values=(api_key,))
    try:
        response = session.get(
            f"{BASE_URL}{CAPABILITIES_PATH}",
            params={"api_key": api_key},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception:
        # The exception can carry the prepared request URL, including the api_key query param, so
        # keep it out of the returned message rather than interpolating str(e).
        return False, "Could not reach the Similarweb API. Please retry."

    if response.status_code == 200:
        return True, None
    if response.status_code == 403:
        return False, "Similarweb rejected the API key. Check the key is active and the account has data credits."
    return False, f"Unexpected response from the Similarweb API (status {response.status_code})."
