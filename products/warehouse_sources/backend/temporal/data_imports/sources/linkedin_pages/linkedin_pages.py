import re
import datetime as dt
import dataclasses
from collections.abc import Iterator, Mapping
from typing import Any, Optional
from urllib.parse import quote, urlencode

import pyarrow as pa
import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_pages.settings import (
    LINKEDIN_PAGES_ENDPOINTS,
    ORGANIZATION_FIELD,
    POSTS_CREATED_AT_FIELD,
    STATS_DATE_FIELD,
    EndpointKind,
    LinkedinPagesEndpointConfig,
)

LINKEDIN_API_BASE_URL = "https://api.linkedin.com/rest"
# LinkedIn's Marketing/Community Management APIs are versioned by month (YYYYMM) via a required
# header, and each version sunsets about a year after release.
LINKEDIN_API_VERSION = "202606"
RESTLI_PROTOCOL_VERSION = "2.0.0"

ORGANIZATION_ACLS_PATH = "/organizationAcls"
ORGANIZATIONS_LOOKUP_PATH = "/organizationsLookup"
# `organizationsLookup` is a Rest.li batch get, so the id list has to stay inside the URL length limit.
ORGANIZATION_LOOKUP_BATCH_SIZE = 50

PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Every configured organization costs a fan-out of statistics calls per window against a daily,
# app-wide LinkedIn call budget, so the configured list is capped. It's far above any real
# customer's page count — LinkedIn itself caps a member at 100+ administered pages in practice —
# and only exists to stop a hand-edited config from spending the shared quota.
MAX_CONFIGURED_ORGANIZATIONS = 100
# Statistics finders return one element per organization per day, so a window is bounded by its
# length rather than by pagination — these finders don't paginate at all. 90 days keeps a single
# response small while keeping the per-sync call count low (LinkedIn budgets calls per day, not
# per second).
STATS_WINDOW_DAYS = 90
# LinkedIn retains roughly 12 months of page analytics, so a first sync can't usefully reach back
# further than that.
INITIAL_LOOKBACK_DAYS = 365
# `timeRange.start` boundary semantics differ per statistics resource, so an incremental run
# re-requests the watermark day itself. Merging on (organization, date) dedupes the overlap.
INCREMENTAL_OVERLAP_DAYS = 1

# LinkedIn 429 bodies name the throttle window that was exceeded (SECOND / MINUTE / DAY). The DAY
# window is the per-app/member daily call budget and only resets at midnight UTC.
_DAY_THROTTLE_PATTERN = re.compile(r"\bDAY\b")

# Configured organization IDs become URN path segments (see `get_organization`), so they must be
# genuine numeric organization/organizationBrand URNs — never anything that could inject path
# segments like `../me` and retarget the authenticated request.
_ORGANIZATION_URN_PATTERN = re.compile(r"urn:li:(?:organization|organizationBrand):[0-9]+")


class LinkedinPagesRetryableError(Exception):
    """Transient LinkedIn response (5xx, short-window 429, malformed body) — worth another attempt."""


class LinkedinPagesDailyRateLimitError(Exception):
    """The per-app/member daily call budget is spent; it only resets at midnight UTC."""


class LinkedinPagesApiError(Exception):
    """A LinkedIn response that retrying can never turn into data.

    Deliberately not named `status_code`: drf-exceptions-hog reads that attribute off any escaping
    exception and would render LinkedIn's status as PostHog's own HTTP response status.
    """

    def __init__(self, message: str, api_status_code: int) -> None:
        super().__init__(message)
        self.api_status_code = api_status_code


@dataclasses.dataclass(frozen=True)
class AdministeredOrganization:
    """One LinkedIn page the authorized member administers, as offered in the source form."""

    urn: str
    name: str


@dataclasses.dataclass(frozen=False)
class LinkedinPagesResumeConfig:
    """Where a previous attempt stopped.

    `org_index` indexes the sorted organization list, so the ordering that produces it has to be
    deterministic. The remaining fields describe how far into that organization we got: a window
    start for the statistics finders, an offset/pageToken for the paginated ones.
    """

    org_index: int = 0
    next_window_start: str = ""
    next_offset: int = 0
    next_page_token: str = ""


@dataclasses.dataclass(frozen=True)
class PageCursor:
    """Next page of a Rest.li finder. Older finders page by `start`/`count`, newer ones hand back
    a `pageToken`; the two are mutually exclusive within a single walk."""

    offset: int = 0
    token: str = ""


def encode_restli_params(params: Mapping[str, Any]) -> str:
    """Encode Rest.li query params, leaving its tuple/URN punctuation intact.

    Rest.li 2.0 expresses structured values in a literal syntax — `(timeRange:(start:1,end:2))`,
    `urn:li:organization:123` — so the parentheses, colons and commas are grammar, not data.
    Percent-encoding them is accepted by LinkedIn but makes every logged URL unreadable, and
    `requests`' own param encoding would also reorder nothing but escape everything.
    """
    return urlencode(params, safe="():,~", quote_via=quote)


def epoch_ms(day: dt.date) -> int:
    return int(dt.datetime.combine(day, dt.time.min, tzinfo=dt.UTC).timestamp() * 1000)


def time_intervals_param(window_start: dt.date, window_end: dt.date) -> str:
    """Rest.li `timeIntervals` tuple covering `[window_start, window_end]` at DAY granularity.

    LinkedIn's `timeRange` is epoch milliseconds and treats `end` as the exclusive edge of the
    range, so the end boundary is midnight UTC of the day after `window_end`.
    """
    return (
        f"(timeRange:(start:{epoch_ms(window_start)},end:{epoch_ms(window_end + dt.timedelta(days=1))}),"
        "timeGranularityType:DAY)"
    )


def organization_urns_from_config(raw: list[str] | None) -> list[str]:
    """Normalize the selected organizations into URNs.

    The page picker stores URNs, but a bare numeric ID is accepted too so a value typed or migrated
    in by hand still resolves. Anything already written as a URN passes through, since showcase
    pages are `urn:li:organizationBrand:…` rather than `urn:li:organization:…`.

    Duplicates are collapsed and the list is capped: each organization drives its own fan-out of
    statistics requests against a daily, app-wide call budget, so a config that repeats a page (or
    lists thousands of them) would otherwise multiply that cost for no extra data.
    """
    urns: list[str] = []
    seen: set[str] = set()
    for part in raw or []:
        value = part.strip()
        if not value:
            continue
        urn = value if value.startswith("urn:") else f"urn:li:organization:{value}"
        if not _ORGANIZATION_URN_PATTERN.fullmatch(urn):
            raise ValueError(
                f"Invalid organization ID {value!r}: expected a numeric ID or a "
                "urn:li:organization / urn:li:organizationBrand URN"
            )
        if urn in seen:
            continue
        seen.add(urn)
        urns.append(urn)

    if len(urns) > MAX_CONFIGURED_ORGANIZATIONS:
        raise ValueError(
            f"Too many organization IDs: {len(urns)} configured, at most "
            f"{MAX_CONFIGURED_ORGANIZATIONS} are supported. Leave the field blank to sync every "
            "page the authorized member administers."
        )
    return urns


def organization_id_from_urn(urn: str) -> str:
    return urn.rsplit(":", 1)[-1]


def organization_entity_path(urn: str) -> str:
    """Entity collection a URN is addressed through — showcase pages live under a different one."""
    parts = urn.split(":")
    entity = parts[-2] if len(parts) >= 4 else "organization"
    return "/organizationBrands" if entity == "organizationBrand" else "/organizations"


def is_daily_throttle(body: str | None) -> bool:
    return bool(body and _DAY_THROTTLE_PATTERN.search(body))


def next_cursor(body: Mapping[str, Any], current: PageCursor, received: int) -> Optional[PageCursor]:
    """Next page for a Rest.li finder, or None when the walk is done.

    Newer finders return `metadata.nextPageToken`; the rest page by offset and signal the end with
    a short page. Once a walk is token-paginated, a missing token is the end — never fall back to
    offsets, which would restart it from the top.
    """
    metadata = body.get("metadata")
    token = metadata.get("nextPageToken") if isinstance(metadata, dict) else None
    if token:
        return PageCursor(token=str(token))
    if current.token:
        return None
    if received < PAGE_SIZE:
        return None
    return PageCursor(offset=current.offset + received)


def statistics_row(element: Mapping[str, Any], urn: str) -> Optional[dict[str, Any]]:
    """Normalize one statistics element, or None when it isn't a time bucket.

    A response for a lifetime query (no `timeIntervals`) carries no `timeRange`, and such a row
    has neither a cursor nor a primary key — dropping it keeps the table's key unique.
    """
    time_range = element.get("timeRange")
    start_ms = time_range.get("start") if isinstance(time_range, dict) else None
    if not isinstance(start_ms, int):
        return None

    return {
        **element,
        ORGANIZATION_FIELD: urn,
        "organization_id": organization_id_from_urn(urn),
        STATS_DATE_FIELD: dt.datetime.fromtimestamp(start_ms / 1000, tz=dt.UTC).date(),
    }


def post_row(element: Mapping[str, Any], urn: str) -> dict[str, Any]:
    created_at_ms = element.get("createdAt")
    created_at = dt.datetime.fromtimestamp(created_at_ms / 1000, tz=dt.UTC) if isinstance(created_at_ms, int) else None
    return {
        **element,
        ORGANIZATION_FIELD: urn,
        "organization_id": organization_id_from_urn(urn),
        POSTS_CREATED_AT_FIELD: created_at,
    }


def window_start_from_watermark(last_value: Any, today: dt.date) -> dt.date:
    """First day to request, given the incremental watermark the pipeline recorded."""
    default_start = today - dt.timedelta(days=INITIAL_LOOKBACK_DAYS)

    parsed: Optional[dt.date] = None
    if isinstance(last_value, dt.datetime):
        parsed = last_value.date()
    elif isinstance(last_value, dt.date):
        parsed = last_value
    elif isinstance(last_value, str) and last_value.strip():
        try:
            parsed = dt.date.fromisoformat(last_value.strip()[:10])
        except ValueError:
            parsed = None

    if parsed is None:
        return default_start
    return parsed - dt.timedelta(days=INCREMENTAL_OVERLAP_DAYS)


class LinkedinPagesClient:
    """Rest.li client for LinkedIn's Community Management (organization page) APIs."""

    def __init__(self, access_token: str, api_version: str = LINKEDIN_API_VERSION) -> None:
        self._access_token = access_token
        self._api_version = api_version
        # capture=False: pulled bodies carry free-form customer content (post commentary,
        # organization details, demographic analytics) that the name-based sample scrubbers
        # can't recognise. redact_values still masks the token in logged URLs and headers.
        self._session = make_tracked_session(redact_values=(access_token,), capture=False)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "LinkedIn-Version": self._api_version,
            "X-Restli-Protocol-Version": RESTLI_PROTOCOL_VERSION,
            "Accept": "application/json",
        }

    def _send(self, path: str, params: Mapping[str, Any]) -> requests.Response:
        url = f"{LINKEDIN_API_BASE_URL}{path}"
        if params:
            url = f"{url}?{encode_restli_params(params)}"
        return self._session.get(url, headers=self._headers(), timeout=REQUEST_TIMEOUT_SECONDS)

    def request(self, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        """GET a Rest.li resource and classify the response.

        The tracked session already retries 429s and transient 5xxs (honoring Retry-After), so
        anything that reaches here has already been given those attempts.
        """
        response = self._send(path, params)

        if response.status_code == 429:
            if is_daily_throttle(response.text):
                raise LinkedinPagesDailyRateLimitError(f"LinkedIn daily rate limit reached: {response.text}")
            raise LinkedinPagesRetryableError(f"LinkedIn API error (retryable, 429): {response.text}")

        if response.status_code >= 500:
            raise LinkedinPagesRetryableError(
                f"LinkedIn API error (retryable, {response.status_code}): {response.text}"
            )

        if response.status_code != 200:
            raise LinkedinPagesApiError(
                f"LinkedIn API error ({response.status_code}): {response.text}", response.status_code
            )

        try:
            body = response.json()
        except ValueError as e:
            raise LinkedinPagesRetryableError("LinkedIn returned a malformed (non-JSON) response") from e

        return body if isinstance(body, dict) else {}

    def iter_finder_pages(
        self, path: str, params: Mapping[str, Any], cursor: Optional[PageCursor] = None
    ) -> Iterator[tuple[list[dict[str, Any]], Optional[PageCursor]]]:
        """Walk a paginated finder, yielding each page with the cursor that follows it."""
        current = cursor or PageCursor()

        while True:
            page_params: dict[str, Any] = {**params, "count": PAGE_SIZE}
            if current.token:
                page_params["pageToken"] = current.token
            else:
                page_params["start"] = current.offset

            body = self.request(path, page_params)
            elements = body.get("elements")
            elements = elements if isinstance(elements, list) else []

            following = next_cursor(body, current, len(elements))
            yield elements, following

            if following is None:
                return
            current = following

    def list_organization_urns(self) -> list[str]:
        """Every organization the authorized member administers.

        Sorted so the resume state's organization index means the same thing across attempts.
        """
        urns: set[str] = set()
        params = {"q": "roleAssignee", "role": "ADMINISTRATOR", "state": "APPROVED"}
        for elements, _ in self.iter_finder_pages(ORGANIZATION_ACLS_PATH, params):
            for element in elements:
                organization = element.get("organization")
                if isinstance(organization, str) and organization.startswith("urn:"):
                    urns.add(organization)
        return sorted(urns)

    def lookup_organization_names(self, urns: list[str]) -> dict[str, str]:
        """Display names for the given organizations, keyed by URN.

        `organizationsLookup` is a batch get that doesn't need administrator access, so one call
        covers every page. Any organization it omits is simply left out.
        """
        names: dict[str, str] = {}
        by_id = {organization_id_from_urn(urn): urn for urn in urns}
        ids = list(by_id)

        for start in range(0, len(ids), ORGANIZATION_LOOKUP_BATCH_SIZE):
            batch = ids[start : start + ORGANIZATION_LOOKUP_BATCH_SIZE]
            body = self.request(ORGANIZATIONS_LOOKUP_PATH, {"ids": f"List({','.join(batch)})"})
            results = body.get("results")
            if not isinstance(results, dict):
                continue
            for organization_id, organization in results.items():
                name = organization.get("localizedName") if isinstance(organization, dict) else None
                urn = by_id.get(str(organization_id))
                if urn and name:
                    names[urn] = str(name)
        return names

    def list_administered_organizations(self) -> list[AdministeredOrganization]:
        urns = self.list_organization_urns()
        try:
            names = self.lookup_organization_names(urns)
        except LinkedinPagesApiError:
            # The picker is more useful listing bare page IDs than failing outright, and the URNs
            # are already in hand at this point.
            names = {}
        return [
            AdministeredOrganization(urn=urn, name=names.get(urn) or f"Page {organization_id_from_urn(urn)}")
            for urn in urns
        ]

    def get_organization(self, urn: str) -> dict[str, Any]:
        organization_id = organization_id_from_urn(urn)
        body = self.request(f"{organization_entity_path(urn)}/{organization_id}", {})
        return {**body, "id": body.get("id", organization_id), "urn": urn}

    def get_statistics(
        self, config: LinkedinPagesEndpointConfig, urn: str, window_start: dt.date, window_end: dt.date
    ) -> list[dict[str, Any]]:
        params = {**config.urn_query(urn), "timeIntervals": time_intervals_param(window_start, window_end)}
        body = self.request(config.path, params)
        elements = body.get("elements")
        return elements if isinstance(elements, list) else []

    def probe(self) -> None:
        """Cheapest call that proves the credentials mint a token LinkedIn accepts."""
        self.request(ORGANIZATION_ACLS_PATH, {"q": "roleAssignee", "role": "ADMINISTRATOR", "count": 1})


def probe_credentials(
    access_token: str,
    api_version: str = LINKEDIN_API_VERSION,
) -> tuple[bool, Optional[int]]:
    """Report `(is_valid, http status)`. Never raises — an unreachable API just isn't validated."""
    try:
        LinkedinPagesClient(access_token, api_version=api_version).probe()
    except LinkedinPagesApiError as e:
        return False, e.api_status_code
    except Exception:  # noqa: BLE001 — a credential probe must never fail source creation
        return False, None
    return True, 200


def resolve_organization_urns(client: LinkedinPagesClient, configured: list[str] | None) -> list[str]:
    """Organizations to sync: the configured ones, else everything the member administers."""
    urns = organization_urns_from_config(configured)
    return sorted(urns) if urns else client.list_organization_urns()


def _resume_window_start(resume: Optional[LinkedinPagesResumeConfig]) -> Optional[dt.date]:
    if resume is None or not resume.next_window_start:
        return None
    try:
        return dt.date.fromisoformat(resume.next_window_start)
    except ValueError:
        return None


def _resume_cursor(resume: Optional[LinkedinPagesResumeConfig]) -> Optional[PageCursor]:
    if resume is None:
        return None
    if resume.next_page_token:
        return PageCursor(token=resume.next_page_token)
    if resume.next_offset:
        return PageCursor(offset=resume.next_offset)
    return None


def iter_pages(
    client: LinkedinPagesClient,
    config: LinkedinPagesEndpointConfig,
    urns: list[str],
    resume: Optional[LinkedinPagesResumeConfig],
    start_date: dt.date,
    end_date: dt.date,
) -> Iterator[tuple[list[dict[str, Any]], LinkedinPagesResumeConfig]]:
    """Yield `(rows, state to resume from once those rows are durable)` across every organization."""
    start_index = resume.org_index if resume is not None else 0

    for index in range(start_index, len(urns)):
        urn = urns[index]
        # Only the organization the last attempt stopped inside carries partial progress.
        org_resume = resume if index == start_index else None
        next_org = LinkedinPagesResumeConfig(org_index=index + 1)

        if config.kind is EndpointKind.ORGANIZATION:
            yield [client.get_organization(urn)], next_org

        elif config.kind is EndpointKind.TIME_SERIES:
            window_start = _resume_window_start(org_resume) or start_date
            while window_start <= end_date:
                window_end = min(window_start + dt.timedelta(days=STATS_WINDOW_DAYS - 1), end_date)
                rows = [
                    row
                    for element in client.get_statistics(config, urn, window_start, window_end)
                    if (row := statistics_row(element, urn)) is not None
                ]
                window_start = window_end + dt.timedelta(days=1)
                yield (
                    rows,
                    LinkedinPagesResumeConfig(org_index=index, next_window_start=window_start.isoformat())
                    if window_start <= end_date
                    else next_org,
                )

        else:
            params = {**config.urn_query(urn), "sortBy": "LAST_MODIFIED"}
            for elements, cursor in client.iter_finder_pages(config.path, params, _resume_cursor(org_resume)):
                yield (
                    [post_row(element, urn) for element in elements],
                    LinkedinPagesResumeConfig(org_index=index, next_offset=cursor.offset, next_page_token=cursor.token)
                    if cursor is not None
                    else next_org,
                )


def linkedin_pages_source(
    access_token: str,
    organization_ids: list[str] | None,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[LinkedinPagesResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    api_version: str = LINKEDIN_API_VERSION,
) -> SourceResponse:
    config = LINKEDIN_PAGES_ENDPOINTS[endpoint]

    def get_rows() -> Iterator[pa.Table]:
        client = LinkedinPagesClient(access_token, api_version=api_version)
        urns = resolve_organization_urns(client, organization_ids)
        if not urns:
            logger.warning("linkedin_pages: the authorized member administers no organization pages")
            return

        today = dt.datetime.now(tz=dt.UTC).date()
        start_date = (
            window_start_from_watermark(db_incremental_field_last_value, today)
            if should_use_incremental_field
            else today - dt.timedelta(days=INITIAL_LOOKBACK_DAYS)
        )

        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

        # Yield `pa.Table`s rather than row lists so each yield is written before the generator is
        # asked for more. The pipeline buffers raw list/dict yields, so checkpointing right after
        # one could advance past rows still sitting in that buffer — a crash would then skip them
        # permanently. The pending state is only persisted once a table has actually been yielded.
        batcher = Batcher(logger=logger)
        pending: Optional[LinkedinPagesResumeConfig] = None

        try:
            for rows, state in iter_pages(client, config, urns, resume, start_date, today):
                for row in rows:
                    batcher.batch(row)
                    # Drain rather than pop once: an oversized chunk is split into several tables
                    # and the batcher refuses more rows while any of them are still queued.
                    while batcher.should_yield():
                        yield batcher.get_table()
                        if pending is not None:
                            resumable_source_manager.save_state(pending)
                            pending = None
                pending = state
        except LinkedinPagesDailyRateLimitError:
            # The daily budget only resets at midnight UTC, so there is nothing left to fetch
            # today. Everything yielded so far is durable and the next scheduled sync picks up
            # from the incremental watermark, so stop cleanly instead of failing the job.
            logger.info(f"linkedin_pages: daily rate limit reached, stopping {endpoint} early for this run")

        while batcher.should_yield(include_incomplete_chunk=True):
            yield batcher.get_table()
        if pending is not None:
            resumable_source_manager.save_state(pending)

    return SourceResponse(
        name=endpoint,
        items=get_rows,
        primary_keys=config.primary_key,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Statistics windows walk forward in time; the posts finder is newest-first because
        # `sortBy=LAST_MODIFIED` is descending.
        sort_mode="desc" if config.kind is EndpointKind.FINDER else "asc",
    )
