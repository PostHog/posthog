import re
import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

# nosemgrep: python.lang.security.use-defused-xml.use-defused-xml (Element is only the node type for annotations — all parsing goes through defusedxml below)
from xml.etree.ElementTree import Element
# nosemgrep: python.lang.security.use-defused-xml.use-defused-xml (escape only serializes text — it does no XML parsing, so there is no XXE surface)
from xml.sax.saxutils import escape as xml_escape

import requests
import defusedxml.ElementTree as DET
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce_marketing_cloud.settings import (
    REST_PAGE_SIZE,
    SALESFORCE_MARKETING_CLOUD_ENDPOINTS,
    SalesforceMarketingCloudEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 300
MAX_RETRY_ATTEMPTS = 5

# Marketing Cloud access tokens live ~20 minutes and there is no refresh token — a new one is
# minted with the same client credentials. Re-mint a little early so a long request can't start
# with a token that expires mid-flight, and because the token endpoint itself is rate limited.
TOKEN_EXPIRY_MARGIN_SECONDS = 120

PARTNER_NS = "http://exacttarget.com/wsdl/partnerAPI"
SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

# Retrieve continues while the API reports more batches; anything else is terminal.
STATUS_MORE_DATA = "MoreDataAvailable"
STATUS_OK = "OK"

AUTH_FAILURE_MESSAGE = "Salesforce Marketing Cloud rejected the installed package credentials"

_SUBDOMAIN_PATTERN = re.compile(r"^[a-z0-9-]+$")


class SalesforceMarketingCloudError(Exception):
    pass


class SalesforceMarketingCloudRetryableError(Exception):
    pass


class SalesforceMarketingCloudAuthError(SalesforceMarketingCloudError):
    def __init__(self, status_code: int | None, detail: str = ""):
        self.status_code = status_code
        super().__init__(f"{AUTH_FAILURE_MESSAGE} (status={status_code}). {detail}".strip())


@dataclasses.dataclass
class SalesforceMarketingCloudResumeConfig:
    # SOAP endpoints resume from the `RequestID` continuation token the last batch returned.
    request_id: Optional[str] = None
    # REST endpoints resume from the next 1-based `$page`.
    page: Optional[int] = None


def normalize_subdomain(subdomain: str) -> str:
    """Reduce whatever the user pasted to the bare tenant subdomain.

    Marketing Cloud shows the tenant subdomain embedded in three different host names (auth, rest,
    soap) and users routinely paste a whole URL, so accept those forms rather than failing setup on
    a formatting technicality.
    """
    value = (subdomain or "").strip().lower()
    value = re.sub(r"^https?://", "", value)
    value = value.split("/")[0]
    value = re.sub(r"\.(auth|rest|soap)\.marketingcloudapis\.com$", "", value)

    if not value or not _SUBDOMAIN_PATTERN.match(value):
        raise ValueError(
            "Invalid Marketing Cloud subdomain. Use the tenant subdomain from your installed package, "
            "for example mc563885gzs27c5t9-63k636ttgm."
        )

    return value


def format_soap_datetime(value: Any) -> str | None:
    """Format an incremental watermark for a SOAP `SimpleFilterPart` value.

    The partner API wants a naive `YYYY-MM-DDTHH:MM:SS` local timestamp; it has no timezone
    syntax, so an aware value is converted to UTC first. Marketing Cloud interprets it in the
    account's own timezone, which is why the filter is `greaterThan` on a watermark we then let
    merge dedupe rather than an exact boundary.
    """
    if isinstance(value, datetime):
        as_datetime = value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value
    elif isinstance(value, date):
        as_datetime = datetime(value.year, value.month, value.day)
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        as_datetime = parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed
    else:
        return None

    return as_datetime.strftime("%Y-%m-%dT%H:%M:%S")


def build_retrieve_envelope(
    object_type: str,
    properties: tuple[str, ...],
    access_token: str,
    filter_property: str | None = None,
    filter_value: str | None = None,
    continue_request: str | None = None,
) -> str:
    """Build a partner API `RetrieveRequestMsg` envelope.

    A continuation still repeats ObjectType and Properties — the partner API rejects a
    ContinueRequest that omits them — but must not repeat the filter.
    """
    property_nodes = "".join(f"<Properties>{xml_escape(prop)}</Properties>" for prop in properties)

    if continue_request:
        body = f"<ContinueRequest>{xml_escape(continue_request)}</ContinueRequest>"
    elif filter_property and filter_value:
        body = (
            f'<Filter xsi:type="SimpleFilterPart">'
            f"<Property>{xml_escape(filter_property)}</Property>"
            f"<SimpleOperator>greaterThan</SimpleOperator>"
            f"<Value>{xml_escape(filter_value)}</Value>"
            f"</Filter>"
        )
    else:
        body = ""

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<soapenv:Envelope xmlns:soapenv="{SOAP_ENV_NS}" xmlns:xsi="{XSI_NS}">'
        "<soapenv:Header>"
        f'<fueloauth xmlns="http://exacttarget.com">{xml_escape(access_token)}</fueloauth>'
        "</soapenv:Header>"
        "<soapenv:Body>"
        f'<RetrieveRequestMsg xmlns="{PARTNER_NS}">'
        "<RetrieveRequest>"
        f"<ObjectType>{xml_escape(object_type)}</ObjectType>"
        f"{property_nodes}"
        f"{body}"
        "</RetrieveRequest>"
        "</RetrieveRequestMsg>"
        "</soapenv:Body>"
        "</soapenv:Envelope>"
    )


def _flatten_element(element: Element, prefix: str = "") -> dict[str, Any]:
    """Flatten one `<Results>` node into a row.

    Nested partner API complex types (e.g. `DataExtension.CustomerKey`) become underscore-joined
    columns so the warehouse table stays flat.
    """
    row: dict[str, Any] = {}
    for child in element:
        tag = child.tag.split("}")[-1]
        key = f"{prefix}{tag}"
        if len(child):
            row.update(_flatten_element(child, prefix=f"{key}_"))
            continue
        if child.get(f"{{{XSI_NS}}}nil") == "true":
            row[key] = None
            continue
        text = (child.text or "").strip()
        row[key] = text or None
    return row


def parse_retrieve_response(xml_text: str) -> tuple[str, str | None, list[dict[str, Any]]]:
    """Parse a Retrieve response into `(overall_status, request_id, rows)`.

    defusedxml is used because the response body comes from a customer-supplied tenant host.
    """
    root: Element = DET.fromstring(xml_text.strip())

    fault = root.find(f".//{{{SOAP_ENV_NS}}}Fault")
    if fault is not None:
        fault_string = fault.findtext("faultstring") or fault.findtext(f"{{{SOAP_ENV_NS}}}faultstring") or "SOAP fault"
        raise SalesforceMarketingCloudError(f"Marketing Cloud SOAP fault: {fault_string}")

    response = root.find(f".//{{{PARTNER_NS}}}RetrieveResponseMsg")
    if response is None:
        raise SalesforceMarketingCloudError("Marketing Cloud returned an unrecognised SOAP response")

    overall_status = (response.findtext(f"{{{PARTNER_NS}}}OverallStatus") or "").strip()
    request_id = (response.findtext(f"{{{PARTNER_NS}}}RequestID") or "").strip() or None
    results = response.findall(f"{{{PARTNER_NS}}}Results")

    if overall_status not in (STATUS_OK, STATUS_MORE_DATA):
        # The partner API reports permission and bad-property errors in the body with a 200 status.
        detail = response.findtext(f"{{{PARTNER_NS}}}RequestID") or ""
        message = ""
        if results:
            message = results[0].findtext(f"{{{PARTNER_NS}}}StatusMessage") or ""
        raise SalesforceMarketingCloudError(
            f"Marketing Cloud Retrieve failed: status={overall_status or 'unknown'} {message or detail}".strip()
        )

    return overall_status, request_id, [_flatten_element(result) for result in results]


class SalesforceMarketingCloudClient:
    """Minted-token client for the tenant's auth, REST and SOAP hosts."""

    def __init__(
        self,
        subdomain: str,
        client_id: str,
        client_secret: str,
        account_id: str | None = None,
        logger: FilteringBoundLogger | None = None,
    ) -> None:
        self._subdomain = normalize_subdomain(subdomain)
        self._client_id = client_id
        self._client_secret = client_secret
        self._account_id = (account_id or "").strip() or None
        self._logger = logger
        # tenacity owns retries so each attempt re-mints an expired token; a urllib3-level retry
        # would replay the same request with a dead bearer token.
        #
        # capture=False because the minted bearer token can't be scrubbed by name: it rides in the
        # SOAP `<fueloauth>` request body and the token-mint response body, neither of which the
        # sample scrubbers recognise. Requests are still metered and logged, just not sampled.
        self._session = make_tracked_session(
            retry=Retry(total=0),
            redact_values=(client_id, client_secret),
            capture=False,
        )
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._rest_base_url = f"https://{self._subdomain}.rest.marketingcloudapis.com"
        self._soap_url = f"https://{self._subdomain}.soap.marketingcloudapis.com/Service.asmx"

    @property
    def auth_url(self) -> str:
        return f"https://{self._subdomain}.auth.marketingcloudapis.com/v2/token"

    @property
    def rest_base_url(self) -> str:
        return self._rest_base_url

    @property
    def soap_url(self) -> str:
        return self._soap_url

    def mint_token(self) -> str:
        payload: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        if self._account_id:
            payload["account_id"] = self._account_id

        response = self._session.post(self.auth_url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code in (400, 401, 403):
            raise SalesforceMarketingCloudAuthError(response.status_code, response.text[:500])
        if response.status_code == 429 or response.status_code >= 500:
            raise SalesforceMarketingCloudRetryableError(
                f"Marketing Cloud token endpoint error (retryable): status={response.status_code}"
            )
        response.raise_for_status()

        body = response.json()
        token = body.get("access_token")
        if not token:
            raise SalesforceMarketingCloudAuthError(response.status_code, "token response had no access_token")

        expires_in = int(body.get("expires_in") or 1200)
        self._access_token = token
        self._token_expires_at = time.monotonic() + max(expires_in - TOKEN_EXPIRY_MARGIN_SECONDS, expires_in // 2)

        # The token response carries the tenant's real endpoints; prefer them over the ones derived
        # from the subdomain so a relocated tenant keeps working.
        rest_instance_url = body.get("rest_instance_url")
        if isinstance(rest_instance_url, str) and rest_instance_url:
            self._rest_base_url = rest_instance_url.rstrip("/")
        soap_instance_url = body.get("soap_instance_url")
        if isinstance(soap_instance_url, str) and soap_instance_url:
            self._soap_url = f"{soap_instance_url.rstrip('/')}/Service.asmx"

        return token

    def access_token(self, force_refresh: bool = False) -> str:
        if force_refresh or self._access_token is None or time.monotonic() >= self._token_expires_at:
            return self.mint_token()
        return self._access_token

    def _check_response(self, response: requests.Response, url: str) -> None:
        if response.status_code in (401, 403):
            raise SalesforceMarketingCloudAuthError(response.status_code, response.text[:500])
        if response.status_code == 429 or response.status_code >= 500:
            raise SalesforceMarketingCloudRetryableError(
                f"Marketing Cloud API error (retryable): status={response.status_code}, url={url}"
            )
        if not response.ok:
            if self._logger is not None:
                self._logger.error(
                    f"Marketing Cloud API error: status={response.status_code}, body={response.text[:500]}, url={url}"
                )
            response.raise_for_status()

    @retry(
        retry=retry_if_exception_type(
            (
                SalesforceMarketingCloudRetryableError,
                requests.ReadTimeout,
                requests.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            )
        ),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=60),
        reraise=True,
    )
    def rest_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        token = self.access_token()
        url = f"{self.rest_base_url}{path}?{urlencode(params)}"
        response = self._session.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        # A token can expire mid-sync; re-mint once before treating a 401 as bad credentials.
        if response.status_code == 401:
            token = self.access_token(force_refresh=True)
            url = f"{self.rest_base_url}{path}?{urlencode(params)}"
            response = self._session.get(
                url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

        self._check_response(response, url)
        body = response.json()
        return body if isinstance(body, dict) else {}

    @retry(
        retry=retry_if_exception_type(
            (
                SalesforceMarketingCloudRetryableError,
                requests.ReadTimeout,
                requests.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            )
        ),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=60),
        reraise=True,
    )
    def soap_retrieve(
        self,
        object_type: str,
        properties: tuple[str, ...],
        filter_property: str | None = None,
        filter_value: str | None = None,
        continue_request: str | None = None,
    ) -> tuple[str, str | None, list[dict[str, Any]]]:
        def _post(token: str) -> requests.Response:
            envelope = build_retrieve_envelope(
                object_type=object_type,
                properties=properties,
                access_token=token,
                filter_property=filter_property,
                filter_value=filter_value,
                continue_request=continue_request,
            )
            return self._session.post(
                self.soap_url,
                data=envelope.encode("utf-8"),
                headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": "Retrieve"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

        response = _post(self.access_token())
        if response.status_code == 401:
            response = _post(self.access_token(force_refresh=True))

        self._check_response(response, self.soap_url)
        return parse_retrieve_response(response.text)


def validate_credentials(
    subdomain: str, client_id: str, client_secret: str, account_id: str | None
) -> tuple[bool, str | None]:
    """Probe the installed package credentials by minting one token."""
    try:
        client = SalesforceMarketingCloudClient(subdomain, client_id, client_secret, account_id)
    except ValueError as exc:
        return False, str(exc)

    try:
        client.mint_token()
    except SalesforceMarketingCloudAuthError:
        return False, (
            "Marketing Cloud rejected these credentials. Check the client ID, client secret and "
            "business unit MID on your installed package, and that it uses Server-to-Server integration."
        )
    except Exception:
        return False, "Could not reach Salesforce Marketing Cloud with the details provided."

    return True, None


def _resolve_incremental_property(
    config: SalesforceMarketingCloudEndpointConfig, incremental_field: str | None
) -> str | None:
    """Pick the SOAP property to filter on, honoring the user's chosen incremental field."""
    if incremental_field and incremental_field in config.incremental_field_names:
        return incremental_field
    return config.soap_incremental_property


def _iter_soap_rows(
    client: SalesforceMarketingCloudClient,
    config: SalesforceMarketingCloudEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SalesforceMarketingCloudResumeConfig],
    incremental_field: str | None,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    assert config.object_type is not None

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    continue_request = resume.request_id if resume is not None else None

    filter_property: str | None = None
    filter_value: str | None = None
    if continue_request is None and db_incremental_field_last_value is not None:
        candidate = _resolve_incremental_property(config, incremental_field)
        if candidate is not None:
            formatted = format_soap_datetime(db_incremental_field_last_value)
            if formatted is not None:
                filter_property, filter_value = candidate, formatted

    while True:
        status, request_id, rows = client.soap_retrieve(
            object_type=config.object_type,
            properties=config.properties,
            filter_property=filter_property,
            filter_value=filter_value,
            continue_request=continue_request,
        )

        has_more = status == STATUS_MORE_DATA and bool(request_id)

        if rows:
            yield rows
            # Save after yielding so a crash re-yields the last batch instead of skipping it;
            # merge dedupes on the primary key.
            if has_more and request_id is not None:
                resumable_source_manager.save_state(SalesforceMarketingCloudResumeConfig(request_id=request_id))

        if not has_more:
            break

        logger.debug(f"Marketing Cloud: continuing {config.name} retrieve with request_id={request_id}")
        continue_request = request_id
        # A continuation carries the original filter server-side; re-sending it is rejected.
        filter_property = filter_value = None

    resumable_source_manager.clear_state()


def _iter_rest_rows(
    client: SalesforceMarketingCloudClient,
    config: SalesforceMarketingCloudEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SalesforceMarketingCloudResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    assert config.path is not None

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None and resume.page else 1

    while True:
        data = client.rest_get(config.path, {"$page": page, "$pageSize": REST_PAGE_SIZE})
        rows = data.get(config.data_key) or []
        if not isinstance(rows, list):
            rows = []

        total = data.get("count")
        seen = (page - 1) * REST_PAGE_SIZE + len(rows)
        has_more = bool(rows) and len(rows) == REST_PAGE_SIZE and (not isinstance(total, int) or seen < total)

        if rows:
            yield rows
            if has_more:
                resumable_source_manager.save_state(SalesforceMarketingCloudResumeConfig(page=page + 1))

        if not has_more:
            break

        page += 1

    logger.debug(f"Marketing Cloud: finished paging {config.name} after {page} page(s)")
    resumable_source_manager.clear_state()


def get_rows(
    subdomain: str,
    client_id: str,
    client_secret: str,
    account_id: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SalesforceMarketingCloudResumeConfig],
    incremental_field: str | None = None,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SALESFORCE_MARKETING_CLOUD_ENDPOINTS[endpoint]
    client = SalesforceMarketingCloudClient(subdomain, client_id, client_secret, account_id, logger)

    if config.transport == "soap":
        yield from _iter_soap_rows(
            client,
            config,
            logger,
            resumable_source_manager,
            incremental_field,
            db_incremental_field_last_value,
        )
        return

    yield from _iter_rest_rows(client, config, logger, resumable_source_manager)


def salesforce_marketing_cloud_source(
    subdomain: str,
    client_id: str,
    client_secret: str,
    account_id: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SalesforceMarketingCloudResumeConfig],
    incremental_field: str | None = None,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = SALESFORCE_MARKETING_CLOUD_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            subdomain=subdomain,
            client_id=client_id,
            client_secret=client_secret,
            account_id=account_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            incremental_field=incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # SOAP Retrieve gives no ordering guarantee — batches come back in whatever order the
        # partner API decides. "desc" is the mode that defers the watermark to the max value seen
        # once the run completes, instead of checkpointing per batch, which is the only safe
        # semantics for unordered results.
        sort_mode="desc" if config.transport == "soap" else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
