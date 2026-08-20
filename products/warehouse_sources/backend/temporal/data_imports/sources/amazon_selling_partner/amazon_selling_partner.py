import re
import gzip
import json
import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import parse_qsl, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util import Retry

from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.oauth import (
    AccessTokenProvider,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.settings import (
    AMAZON_SELLING_PARTNER_ENDPOINTS,
    SpApiEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.url_utils import redact_literal_values
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

SP_API_HOSTS = {
    "na": "https://sellingpartnerapi-na.amazon.com",
    "eu": "https://sellingpartnerapi-eu.amazon.com",
    "fe": "https://sellingpartnerapi-fe.amazon.com",
}
REPORTS_PATH = "/reports/2021-06-30/reports"
REPORT_DOCUMENTS_PATH = "/reports/2021-06-30/documents"
SELLERS_PARTICIPATIONS_PATH = "/sellers/v1/marketplaceParticipations"

REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRY_ATTEMPTS = 6
# Access tokens live an hour and the integration row is refreshed once it is past its own half-life,
# so re-reading the row every few minutes keeps a long sync on a fresh token without hammering
# Postgres on every request.
TOKEN_CACHE_SECONDS = 300
DEFAULT_LOOKBACK_DAYS = 365
# Report jobs are billed per request and carry undocumented per-type cooldowns, so
# backfills are sliced into windows rather than one job per day.
REPORT_WINDOW_DAYS = 30
REPORT_POLL_INTERVAL_SECONDS = 30
REPORT_POLL_MAX_ATTEMPTS = 80
REPORT_PENDING_STATUSES = frozenset({"IN_QUEUE", "IN_PROGRESS"})
# Amazon marketplace IDs are short alphanumeric tokens (e.g. ATVPDKIKX0DER) and there are
# roughly twenty of them worldwide; both bounds are sanity limits on operator input.
MAX_MARKETPLACE_IDS = 50
MARKETPLACE_ID_MAX_LENGTH = 32
MARKETPLACE_ID_PATTERN = re.compile(r"[A-Za-z0-9]+")
# The load-bearing secrets in an AWS SigV4 presigned report-document URL. Redacted by value
# (not just by param name) before a download failure is turned into a job error.
PRESIGNED_CREDENTIAL_PARAMS = frozenset({"x-amz-signature", "x-amz-credential", "x-amz-security-token"})


class AmazonSellingPartnerRetryableError(Exception):
    pass


class AmazonSellingPartnerReportError(Exception):
    pass


@dataclasses.dataclass(frozen=False)
class AmazonSellingPartnerResumeConfig:
    # NextToken of the page (or, for the order-items fan-out, of the parent orders page)
    # to pick back up from.
    next_token: Optional[str] = None
    # Marketplace the saved token belongs to, for endpoints walked one marketplace at a
    # time — an SP-API continuation token is only valid for the query that produced it.
    marketplace_id: Optional[str] = None
    # Start of the report window being processed, ISO-8601.
    window_start: Optional[str] = None
    # Report job already created for `window_start`, so a resume doesn't pay the
    # create-and-cooldown cost again.
    report_id: Optional[str] = None


def _base_url(region: str) -> str:
    host = SP_API_HOSTS.get(region)
    if host is None:
        raise ValueError(f"Invalid Amazon Selling Partner region: {region}")
    return host


def parse_marketplace_ids(raw: str) -> list[str]:
    """Split the user's marketplace id list, preserving order and dropping duplicates.

    The field is free text a source editor controls, so the parse is bounded rather than
    trusting: each id is length- and character-checked, duplicates are detected against a
    set (constant time, so a long list stays linear), and the count is capped. Amazon
    operates on the order of twenty marketplaces, so `MAX_MARKETPLACE_IDS` is a guard
    against a pathological config rather than a product limit.
    """
    ordered: list[str] = []
    seen: set[str] = set()
    for chunk in raw.replace("\n", ",").replace(" ", ",").split(","):
        value = chunk.strip()
        if not value or value in seen:
            continue
        if len(value) > MARKETPLACE_ID_MAX_LENGTH or not MARKETPLACE_ID_PATTERN.fullmatch(value):
            raise ValueError(
                f"Invalid Amazon marketplace ID: {value[:MARKETPLACE_ID_MAX_LENGTH]!r}. "
                "Marketplace IDs are alphanumeric, like ATVPDKIKX0DER."
            )
        if len(ordered) >= MAX_MARKETPLACE_IDS:
            raise ValueError(f"At most {MAX_MARKETPLACE_IDS} Amazon marketplace IDs can be synced at once")
        seen.add(value)
        ordered.append(value)
    if not ordered:
        raise ValueError("At least one Amazon marketplace ID is required")
    return ordered


def _format_timestamp(value: Any) -> str:
    """Format an incremental cursor as the ISO-8601 UTC instant SP-API filters expect."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = str(value)
    return text if text.endswith("Z") else f"{text}Z"


def _parse_window_start(value: Any) -> datetime:
    """Coerce an incremental cursor into an aware UTC datetime for report windowing."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _unwrap(body: dict[str, Any]) -> dict[str, Any]:
    """Return the response envelope's contents — v0 operations wrap them in `payload`."""
    payload = body.get("payload")
    return payload if isinstance(payload, dict) else body


def _extract_next_token(body: dict[str, Any], token_param: str) -> Optional[str]:
    """Read the continuation token, which SP-API places in one of three spots."""
    inner = _unwrap(body)
    pagination = body.get("pagination")
    candidates = [
        inner.get(token_param),
        pagination.get("nextToken") if isinstance(pagination, dict) else None,
        body.get(token_param),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


class SellingPartnerClient:
    """Minimal SP-API client: token caching, retries, and JSON requests.

    SP-API dropped AWS SigV4 signing in 2023, so requests are plain HTTPS carrying the
    Login with Amazon access token in `x-amz-access-token`. The token itself comes from the
    OAuth integration row via `access_token_provider` — this client never holds the grant.
    """

    def __init__(
        self,
        region: str,
        access_token_provider: AccessTokenProvider,
        logger: Optional[FilteringBoundLogger] = None,
    ) -> None:
        self.base_url = _base_url(region)
        self._access_token_provider = access_token_provider
        self._logger = logger
        # Retries live in `_request` (tenacity) so POSTs and the report-job polling loop
        # are covered too; a transport-level policy would only cover idempotent verbs and
        # would compound with this one.
        # `capture=False`: every SP-API call carries a freshly minted `x-amz-access-token`
        # bearer, which the name-based scrubbers don't recognise; responses can also hold
        # buyer PII. Keep the session metered and logged, but out of HTTP sample capture.
        self._session = make_tracked_session(retry=Retry(total=0), capture=False)
        self._token: Optional[str] = None
        self._token_cached_until: float = 0.0

    def access_token(self, force_refresh: bool = False) -> str:
        if force_refresh or self._token is None or time.monotonic() >= self._token_cached_until:
            self._token = self._access_token_provider(force_refresh)
            self._token_cached_until = time.monotonic() + TOKEN_CACHE_SECONDS
        return self._token

    def request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        response = self._request(method, path, params=params, json_body=json_body)
        if not response.content:
            return {}
        return response.json()

    @retry(
        retry=retry_if_exception_type(
            (AmazonSellingPartnerRetryableError, requests.ReadTimeout, requests.ConnectionError)
        ),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=5, max=300),
        reraise=True,
    )
    def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> requests.Response:
        url = f"{self.base_url}{path}"

        def send(token: str) -> requests.Response:
            return self._session.request(
                method,
                url,
                params=params,
                json=json_body,
                headers={"x-amz-access-token": token},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

        response = send(self.access_token())
        if response.status_code == 401:
            # A sync can outlive an access token; mint a fresh one and try once more
            # before treating the 401 as a real credential failure.
            response = send(self.access_token(force_refresh=True))

        if response.status_code == 429 or response.status_code >= 500:
            raise AmazonSellingPartnerRetryableError(
                f"Amazon Selling Partner API error (retryable): status={response.status_code}, url={url}"
            )

        if not response.ok:
            if self._logger is not None:
                self._logger.error(
                    f"Amazon Selling Partner API error: status={response.status_code}, body={response.text}, url={url}"
                )
            response.raise_for_status()

        return response


def validate_credentials(
    region: str,
    access_token_provider: AccessTokenProvider,
) -> tuple[bool, Optional[str]]:
    """Read the connection's access token and probe the sellers API to confirm it is authorized."""
    try:
        client = SellingPartnerClient(region, access_token_provider)
    except ValueError as e:
        return False, str(e)

    try:
        client.access_token()
    except Exception:
        return False, "Could not get an Amazon access token. Reconnect your Amazon seller account."

    try:
        client.request("GET", SELLERS_PARTICIPATIONS_PATH)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status == 403:
            # A valid token whose app lacks the Selling Partner Insights role still syncs
            # the endpoints it is approved for, so this must not block source creation.
            return True, None
        return (
            False,
            "Amazon rejected the Selling Partner API request. Reauthorize PostHog in Seller Central and reconnect.",
        )
    except Exception:
        return False, "Could not reach the Amazon Selling Partner API."

    return True, None


def _endpoint_params(
    config: SpApiEndpointConfig,
    marketplace_ids: list[str],
    since: Optional[str],
) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.extra_params)
    if config.page_size_param and config.page_size:
        params[config.page_size_param] = config.page_size
    if config.marketplace_param:
        params[config.marketplace_param] = ",".join(marketplace_ids)
    if config.since_param and since:
        params[config.since_param] = since
    return params


def _paginate(
    client: SellingPartnerClient,
    config: SpApiEndpointConfig,
    path: str,
    params: dict[str, Any],
    start_token: Optional[str] = None,
) -> Iterator[tuple[list[dict[str, Any]], Optional[str]]]:
    """Walk a NextToken-paginated SP-API list operation.

    Amazon rejects the filter params once a continuation token is supplied, so pages
    after the first send the token alone.
    """
    next_token = start_token
    seen_tokens: set[str] = set()
    while True:
        page_params = {config.token_param: next_token} if next_token else params
        body = client.request("GET", path, params=page_params)
        rows = _unwrap(body).get(config.data_key) or []
        next_token = _extract_next_token(body, config.token_param)

        yield list(rows), next_token

        # A token the API has already handed us means it is not advancing; stop rather
        # than loop on the same page forever.
        if not next_token or next_token in seen_tokens:
            return
        seen_tokens.add(next_token)


def _list_rows(
    client: SellingPartnerClient,
    config: SpApiEndpointConfig,
    marketplace_ids: list[str],
    since: Optional[str],
    resumable_source_manager: ResumableSourceManager[AmazonSellingPartnerResumeConfig],
    resume: Optional[AmazonSellingPartnerResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    # `per_marketplace` endpoints are scoped to one marketplace at a time; the rest take
    # the whole list in one request.
    scopes: list[Optional[str]] = list(marketplace_ids) if config.per_marketplace else [None]

    # A continuation token is only valid for the marketplace whose walk produced it, so
    # resuming skips the marketplaces already finished before that token was saved.
    resume_token = resume.next_token if resume is not None else None
    if resume_token and config.per_marketplace:
        resume_scope = resume.marketplace_id if resume is not None else None
        if resume_scope in scopes:
            scopes = scopes[scopes.index(resume_scope) :]
        else:
            resume_token = None

    for index, scope in enumerate(scopes):
        scoped_ids = [scope] if scope is not None else marketplace_ids
        params = _endpoint_params(config, scoped_ids, since)
        if scope is not None:
            params["granularityId"] = scope

        start_token = resume_token if index == 0 else None

        for rows, next_token in _paginate(client, config, config.path, params, start_token=start_token):
            if scope is not None:
                rows = [{**row, "_marketplace_id": scope} for row in rows]

            if rows:
                yield rows

            # Saved after the yield so a crash re-emits the last page (merge dedupes on
            # the primary key) rather than skipping it.
            if next_token:
                resumable_source_manager.save_state(
                    AmazonSellingPartnerResumeConfig(next_token=next_token, marketplace_id=scope)
                )


def _order_items_rows(
    client: SellingPartnerClient,
    config: SpApiEndpointConfig,
    marketplace_ids: list[str],
    since: Optional[str],
    resumable_source_manager: ResumableSourceManager[AmazonSellingPartnerResumeConfig],
    resume: Optional[AmazonSellingPartnerResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Fan out from the orders list to each order's items."""
    orders_config = AMAZON_SELLING_PARTNER_ENDPOINTS["orders"]
    orders_params = _endpoint_params(orders_config, marketplace_ids, since)
    start_token = resume.next_token if resume is not None else None

    for orders, next_token in _paginate(
        client, orders_config, orders_config.path, orders_params, start_token=start_token
    ):
        for order in orders:
            order_id = order.get("AmazonOrderId")
            if not order_id:
                continue

            path = config.path.format(order_id=order_id)
            for items, _ in _paginate(client, config, path, {}):
                rows = [
                    {
                        **item,
                        "AmazonOrderId": order_id,
                        "_order_last_update_date": order.get("LastUpdateDate"),
                        "_order_purchase_date": order.get("PurchaseDate"),
                    }
                    for item in items
                ]
                if rows:
                    yield rows

        if next_token:
            resumable_source_manager.save_state(AmazonSellingPartnerResumeConfig(next_token=next_token))


def _create_report(
    client: SellingPartnerClient,
    config: SpApiEndpointConfig,
    marketplace_ids: list[str],
    window_start: datetime,
    window_end: datetime,
) -> str:
    body: dict[str, Any] = {
        "reportType": config.report_type,
        "marketplaceIds": marketplace_ids,
        "dataStartTime": _format_timestamp(window_start),
        "dataEndTime": _format_timestamp(window_end),
    }
    if config.report_options:
        body["reportOptions"] = dict(config.report_options)

    response = client.request("POST", REPORTS_PATH, json_body=body)
    report_id = _unwrap(response).get("reportId")
    if not report_id:
        raise AmazonSellingPartnerReportError(f"Amazon did not return a report ID for {config.report_type}")
    return str(report_id)


def _poll_report_document_id(
    client: SellingPartnerClient,
    report_id: str,
    logger: FilteringBoundLogger,
) -> Optional[str]:
    """Poll a report job to completion. Returns None when Amazon cancels it (no data)."""
    for _ in range(REPORT_POLL_MAX_ATTEMPTS):
        body = _unwrap(client.request("GET", f"{REPORTS_PATH}/{report_id}"))
        status = body.get("processingStatus")

        if status == "DONE":
            document_id = body.get("reportDocumentId")
            if not document_id:
                raise AmazonSellingPartnerReportError(f"Report {report_id} finished without a document")
            return str(document_id)

        if status == "CANCELLED":
            # Amazon cancels a report when the window holds no data.
            logger.debug(f"Amazon Selling Partner report {report_id} was cancelled — no data for the window")
            return None

        if status not in REPORT_PENDING_STATUSES:
            raise AmazonSellingPartnerReportError(f"Report {report_id} failed with status {status}")

        time.sleep(REPORT_POLL_INTERVAL_SECONDS)

    raise AmazonSellingPartnerRetryableError(
        f"Amazon Selling Partner API error (retryable): report {report_id} did not finish in time"
    )


def _scrub_presigned(text: str, url: str) -> str:
    """Redact a presigned S3 URL, and its signing params on their own, out of `text`."""
    secrets = [url]
    try:
        for name, value in parse_qsl(urlsplit(url).query, keep_blank_values=True):
            if name.lower() in PRESIGNED_CREDENTIAL_PARAMS and value:
                secrets.append(value)
    except Exception:
        pass
    return redact_literal_values(text, secrets)


def _download_report_document(client: SellingPartnerClient, document_id: str) -> dict[str, Any]:
    """Fetch a report document's presigned URL and return its parsed JSON body."""
    document = _unwrap(client.request("GET", f"{REPORT_DOCUMENTS_PATH}/{document_id}"))
    url = document.get("url")
    if not url:
        raise AmazonSellingPartnerReportError(f"Report document {document_id} has no download URL")

    # The URL is presigned S3: sending our own Authorization/token headers alongside the
    # query-string credentials makes S3 reject the request, so it gets a bare session.
    # `capture=False`: the response body is the seller's report (buyer PII) and the URL
    # carries AWS `X-Amz-*` signing credentials, so keep it out of HTTP sample capture.
    download_session = make_tracked_session(capture=False)
    try:
        response = download_session.get(str(url), timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as err:
        # `requests` puts the request URL in the exception message, and this one is a presigned
        # S3 link whose query string *is* the credential. Job errors are persisted and rendered
        # in the UI, so re-raise with the signing params redacted and suppress the original
        # exception — its message and traceback would carry the raw URL straight back in.
        raise AmazonSellingPartnerReportError(
            f"Failed to download report document {document_id}: {type(err).__name__}: "
            f"{_scrub_presigned(str(err), str(url))}"
        ) from None

    content = response.content
    if document.get("compressionAlgorithm") == "GZIP":
        content = gzip.decompress(content)

    parsed = json.loads(content)
    return parsed if isinstance(parsed, dict) else {}


def _report_rows(
    client: SellingPartnerClient,
    config: SpApiEndpointConfig,
    marketplace_ids: list[str],
    since: Optional[Any],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AmazonSellingPartnerResumeConfig],
    resume: Optional[AmazonSellingPartnerResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    now = datetime.now(UTC)
    window_start = _parse_window_start(since) if since is not None else now - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    existing_report_id: Optional[str] = None

    if resume is not None and resume.window_start:
        window_start = _parse_window_start(resume.window_start)
        existing_report_id = resume.report_id
        logger.debug(f"Amazon Selling Partner: resuming {config.name} report window at {resume.window_start}")

    while window_start < now:
        window_end = min(window_start + timedelta(days=REPORT_WINDOW_DAYS), now)

        report_id = existing_report_id or _create_report(client, config, marketplace_ids, window_start, window_end)
        existing_report_id = None
        resumable_source_manager.save_state(
            AmazonSellingPartnerResumeConfig(window_start=_format_timestamp(window_start), report_id=report_id)
        )

        document_id = _poll_report_document_id(client, report_id, logger)
        if document_id is not None:
            document = _download_report_document(client, document_id)
            rows = document.get(config.report_rows_key or "") or []
            if rows:
                yield list(rows)

        window_start = window_end
        resumable_source_manager.save_state(
            AmazonSellingPartnerResumeConfig(window_start=_format_timestamp(window_start))
        )


def get_rows(
    region: str,
    access_token_provider: AccessTokenProvider,
    marketplace_ids: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AmazonSellingPartnerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = AMAZON_SELLING_PARTNER_ENDPOINTS[endpoint]
    parsed_marketplace_ids = parse_marketplace_ids(marketplace_ids)
    client = SellingPartnerClient(region, access_token_provider, logger=logger)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    watermark = db_incremental_field_last_value if should_use_incremental_field else None

    if config.kind == "report":
        yield from _report_rows(
            client, config, parsed_marketplace_ids, watermark, logger, resumable_source_manager, resume
        )
        return

    since = _format_timestamp(watermark) if watermark is not None else None

    if config.kind == "fanout":
        yield from _order_items_rows(client, config, parsed_marketplace_ids, since, resumable_source_manager, resume)
        return

    yield from _list_rows(client, config, parsed_marketplace_ids, since, resumable_source_manager, resume)


def amazon_selling_partner_source(
    region: str,
    access_token_provider: AccessTokenProvider,
    marketplace_ids: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AmazonSellingPartnerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = AMAZON_SELLING_PARTNER_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            region=region,
            access_token_provider=access_token_provider,
            marketplace_ids=marketplace_ids,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=list(config.primary_key),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
    )
