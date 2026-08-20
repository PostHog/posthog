import re
import datetime as dt
import dataclasses
from collections.abc import Callable, Iterator
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses.settings import (
    AWS_SES_ENDPOINTS,
    REGION_PATTERN,
    REQUEST_TIMEOUT_SECONDS,
    SES_ENDPOINT_TEMPLATE,
    SES_SIGNING_NAME,
    AwsSesEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# SESv2 returns TooManyRequestsException as HTTP 429 and its read APIs throttle at roughly one
# request per second, so 429 gets more headroom than the tracked session's default policy.
TRANSPORT_RETRY = BoundedRetry(
    total=5,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET"]),
    raise_on_status=False,
)

# Rewind applied to the stored watermark before it becomes `StartDate`: the filter's boundary
# semantics are undocumented, and merge on the primary key absorbs the re-read rows.
INCREMENTAL_OVERLAP = dt.timedelta(days=1)

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

_IAM_ACTION_PATTERN = re.compile(r"ses:[A-Za-z0-9]+")

# Codes that mean the key itself is bad, as opposed to a valid key missing an IAM permission.
_CREDENTIAL_ERROR_CODES = (
    "UnrecognizedClientException",
    "InvalidClientTokenId",
    "SignatureDoesNotMatch",
    "InvalidSignatureException",
    "ExpiredTokenException",
)


class AwsSesError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class AwsSesResumeConfig:
    """Pagination token for the next page to request; `None` once a walk completed."""

    next_token: Optional[str] = None


def validate_region(region: str) -> str:
    """Return the region if it is a well-formed AWS region code, else raise.

    The region is interpolated into the request host, so anything outside the region alphabet
    could point the signed request at a host we don't control.
    """
    normalized = (region or "").strip()
    if not REGION_PATTERN.match(normalized):
        raise ValueError(f"Invalid AWS region: {region!r}")
    return normalized


def _snake(name: str) -> str:
    """`IdentityName` -> `identity_name`, `SOARecord` -> `soa_record`."""
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def _parse_timestamp(value: Any) -> Any:
    """SESv2 serializes timestamps as epoch seconds; keep anything unrecognized untouched."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return dt.datetime.fromtimestamp(value, tz=dt.UTC)
    if isinstance(value, str) and value:
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.UTC)
    return value


def coerce_datetime(value: Any) -> Optional[dt.datetime]:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day, tzinfo=dt.UTC)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return dt.datetime.fromtimestamp(value, tz=dt.UTC)
    if isinstance(value, str) and value:
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.UTC)
    return None


def _flatten(prefix: str, obj: dict[str, Any], raw_keys: frozenset[str]) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in obj.items():
        column = f"{prefix}_{_snake(key)}" if prefix else _snake(key)
        if isinstance(value, dict) and key not in raw_keys:
            flattened.update(_flatten(column, value, raw_keys))
        else:
            flattened[column] = value
    return flattened


def normalize_row(endpoint_config: AwsSesEndpointConfig, obj: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested structures into snake_case columns and parse epoch timestamps."""
    row = _flatten("", obj, endpoint_config.raw_keys)
    for column in endpoint_config.timestamp_columns:
        if column in row:
            row[column] = _parse_timestamp(row[column])
    return row


def _error_code(response: requests.Response) -> str:
    header = response.headers.get("x-amzn-ErrorType") or ""
    if header:
        return header.split(":")[0].split("#")[-1]
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    raw = body.get("__type") or body.get("code") or f"HTTP {response.status_code}"
    return str(raw).split("#")[-1]


def _error_message(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:500]
    message = body.get("message") or body.get("Message") or ""
    return str(message)[:500]


def error_for_response(response: requests.Response) -> AwsSesError:
    return AwsSesError(f"Amazon SES request failed: {_error_code(response)} - {_error_message(response)}")


def make_session(secret_access_key: str, session_token: Optional[str]) -> requests.Session:
    redact = tuple(value for value in (secret_access_key, session_token) if value)
    return make_tracked_session(retry=TRANSPORT_RETRY, redact_values=redact)


def send_request(
    session: requests.Session,
    credentials: Credentials,
    region: str,
    path: str,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Sign one SESv2 GET with SigV4 and send it over the tracked session."""
    url = SES_ENDPOINT_TEMPLATE.format(region=region) + path
    if params:
        # Encoded exactly like the SigV4 canonical query string (RFC 3986, sorted keys), so the
        # URL that is signed is byte-identical to the one that is sent.
        url = f"{url}?{urlencode(sorted(params.items()), quote_via=quote, safe='-_.~')}"

    aws_request = AWSRequest(method="GET", url=url)
    SigV4Auth(credentials, SES_SIGNING_NAME, region).add_auth(aws_request)

    response = session.get(url, headers=dict(aws_request.headers.items()), timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code >= 400:
        raise error_for_response(response)
    return response.json()


def resolve_start_date(
    should_use_incremental_field: bool, db_incremental_field_last_value: Any
) -> Optional[dt.datetime]:
    if not should_use_incremental_field:
        return None
    watermark = coerce_datetime(db_incremental_field_last_value)
    if watermark is None:
        return None
    return watermark - INCREMENTAL_OVERLAP


def _fanout_page_rows(
    session: requests.Session,
    credentials: Credentials,
    region: str,
    endpoint_config: AwsSesEndpointConfig,
    body: dict[str, Any],
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    """One full row per listed item, fetched via the endpoint's detail operation."""
    assert endpoint_config.detail_path is not None and endpoint_config.name_column is not None

    rows: list[dict[str, Any]] = []
    for item in body.get(endpoint_config.result_key or "") or []:
        name = item.get(endpoint_config.item_name_key) if isinstance(item, dict) else item
        if not isinstance(name, str) or not name:
            continue

        try:
            detail = send_request(
                session, credentials, region, endpoint_config.detail_path.format(name=quote(name, safe=""))
            )
        except AwsSesError as error:
            if "NotFoundException" in str(error):
                logger.debug(f"Skipping {endpoint_config.name} item deleted mid-sync. name={name}")
                continue
            raise

        row = normalize_row(endpoint_config, item) if isinstance(item, dict) else {}
        row.update(normalize_row(endpoint_config, detail))
        # Detail responses (GetEmailIdentity) do not echo the item name back.
        row[endpoint_config.name_column] = name
        rows.append(row)
    return rows


def _walk_pages(
    session: requests.Session,
    credentials: Credentials,
    region: str,
    endpoint_config: AwsSesEndpointConfig,
    params: dict[str, Any],
    rows_for_body: Callable[[dict[str, Any]], list[dict[str, Any]]],
    resumable_source_manager: ResumableSourceManager[AwsSesResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    next_token = resume.next_token if resume is not None else None
    resumed_token = next_token is not None
    if resumed_token:
        logger.debug(f"Resuming Amazon SES sync from a saved page token. endpoint={endpoint_config.name}")

    while True:
        page_params = dict(params)
        if next_token:
            page_params["NextToken"] = next_token

        try:
            body = send_request(session, credentials, region, endpoint_config.path, page_params)
        except AwsSesError as error:
            # A token saved by a previous attempt can expire; restart the walk instead of
            # failing the job. Merge on the primary key absorbs the re-read rows.
            if resumed_token and "InvalidNextTokenException" in str(error):
                logger.debug(f"Saved page token no longer valid; restarting. endpoint={endpoint_config.name}")
                next_token = None
                resumed_token = False
                resumable_source_manager.clear_state()
                continue
            raise
        resumed_token = False

        rows = rows_for_body(body)
        if rows:
            yield rows

        next_token = body.get("NextToken")
        # Saved after yielding: a crash re-yields the last page, which merges away on the
        # primary key, rather than skipping it.
        resumable_source_manager.save_state(AwsSesResumeConfig(next_token=next_token))
        if not next_token:
            break

    resumable_source_manager.clear_state()


def get_rows(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    aws_region: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[AwsSesResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    endpoint_config = AWS_SES_ENDPOINTS[endpoint]
    region = validate_region(aws_region)
    session = make_session(aws_secret_access_key, aws_session_token)
    credentials = Credentials(aws_access_key_id, aws_secret_access_key, aws_session_token or None)

    if endpoint_config.page_size is None:
        yield [normalize_row(endpoint_config, send_request(session, credentials, region, endpoint_config.path))]
        return

    params: dict[str, Any] = {"PageSize": endpoint_config.page_size}
    if endpoint_config.supports_start_date:
        start_date = resolve_start_date(should_use_incremental_field, db_incremental_field_last_value)
        if start_date is not None:
            params["StartDate"] = start_date.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def rows_for_body(body: dict[str, Any]) -> list[dict[str, Any]]:
        if endpoint_config.detail_path:
            return _fanout_page_rows(session, credentials, region, endpoint_config, body, logger)
        return [normalize_row(endpoint_config, item) for item in body.get(endpoint_config.result_key or "") or []]

    yield from _walk_pages(
        session, credentials, region, endpoint_config, params, rows_for_body, resumable_source_manager, logger
    )


def _permission_reason(error: AwsSesError) -> Optional[str]:
    text = str(error)
    if "AccessDeniedException" in text:
        match = _IAM_ACTION_PATTERN.search(text)
        if match:
            return f"Missing IAM permission {match.group(0)}"
        return "The connected IAM user or role is not allowed to read this table"
    if any(code in text for code in _CREDENTIAL_ERROR_CODES):
        return "AWS rejected the access key. Please check the access key ID and secret access key."
    return None


def endpoint_permission_reason(
    session: requests.Session,
    credentials: Credentials,
    region: str,
    endpoint_config: AwsSesEndpointConfig,
) -> Optional[str]:
    """Probe the calls a sync of this endpoint issues. `None` when reachable.

    Only a real denial counts as unreachable: throttles, 5xx and network errors leave the
    endpoint reported as reachable, so a blip can't hide tables from the schema picker.
    """
    try:
        if endpoint_config.page_size is None:
            send_request(session, credentials, region, endpoint_config.path)
            return None

        body = send_request(session, credentials, region, endpoint_config.path, {"PageSize": 1})
        if endpoint_config.detail_path:
            for item in (body.get(endpoint_config.result_key or "") or [])[:1]:
                name = item.get(endpoint_config.item_name_key) if isinstance(item, dict) else item
                if isinstance(name, str) and name:
                    send_request(
                        session, credentials, region, endpoint_config.detail_path.format(name=quote(name, safe=""))
                    )
    except AwsSesError as error:
        return _permission_reason(error)
    except Exception:
        return None
    return None


def probe_endpoint_permissions(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    aws_region: str,
    endpoints: list[str],
) -> dict[str, str | None]:
    try:
        region = validate_region(aws_region)
    except ValueError:
        return dict.fromkeys(endpoints)

    session = make_session(aws_secret_access_key, aws_session_token)
    credentials = Credentials(aws_access_key_id, aws_secret_access_key, aws_session_token or None)

    reasons: dict[str, str | None] = {}
    for endpoint in endpoints:
        endpoint_config = AWS_SES_ENDPOINTS.get(endpoint)
        reasons[endpoint] = (
            endpoint_permission_reason(session, credentials, region, endpoint_config)
            if endpoint_config is not None
            else None
        )
    return reasons


def validate_credentials(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    aws_region: str,
    schema_name: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    if not aws_access_key_id or not aws_secret_access_key:
        return False, "AWS access key ID and secret access key are required"

    try:
        region = validate_region(aws_region)
    except ValueError:
        return False, f"'{aws_region}' isn't a valid AWS region. Use a region code like us-east-1."

    session = make_session(aws_secret_access_key, aws_session_token)
    credentials = Credentials(aws_access_key_id, aws_secret_access_key, aws_session_token or None)

    if schema_name is not None and schema_name in AWS_SES_ENDPOINTS:
        reason = endpoint_permission_reason(session, credentials, region, AWS_SES_ENDPOINTS[schema_name])
        return reason is None, reason

    try:
        send_request(session, credentials, region, AWS_SES_ENDPOINTS["account"].path)
    except AwsSesError as error:
        # A denied GetAccount still proves the key is genuine; per-table access is reported in
        # the schema picker instead of blocking source creation.
        if "AccessDeniedException" in str(error):
            return True, None
        return False, str(error)
    except Exception:
        return False, "Could not reach the Amazon SES API. Check the AWS region and try again."

    return True, None


def aws_ses_source(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    aws_region: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[AwsSesResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    endpoint_config = AWS_SES_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
            aws_region=aws_region,
            endpoint=endpoint,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            logger=logger,
        ),
        primary_keys=endpoint_config.primary_key,
        # AWS documents no ordering for these list APIs, so the incremental watermark must only
        # commit once a walk completes; "desc" gives exactly that single end-of-run commit.
        sort_mode="desc",
    )
