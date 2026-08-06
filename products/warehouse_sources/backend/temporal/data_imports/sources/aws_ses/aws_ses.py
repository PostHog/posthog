import re
import datetime as dt
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses.settings import (
    AWS_SES_ENDPOINTS,
    DEFAULT_PAGE_SIZE,
    SES_DEFAULT_REGION,
    SES_HOST_TEMPLATE,
    SES_SIGNING_NAME,
    SUPPRESSION_RESTATEMENT_LOOKBACK_DAYS,
    SesEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

REQUEST_TIMEOUT_SECONDS = 120

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

# Row fields carrying a SESv2 timestamp, coerced to a datetime so incremental syncs get a real
# cursor value rather than a raw epoch number.
_DATETIME_COLUMNS = frozenset({"last_update_time"})


class AwsSesError(Exception):
    pass


@dataclasses.dataclass
class AwsSesResumeConfig:
    """Where a previous attempt stopped: the page cursor plus, for the windowed suppression
    endpoint, the frozen request window its cursor was minted against."""

    next_token: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


def _snake(name: str) -> str:
    """`IdentityName` -> `identity_name`, `SentLast24Hours` -> `sent_last24_hours`."""
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def _coerce_datetime(value: Any) -> Optional[dt.datetime]:
    """SESv2 serializes body timestamps as epoch seconds; accept ISO strings too."""
    if isinstance(value, dt.datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)
    if isinstance(value, int | float):
        return dt.datetime.fromtimestamp(value, tz=dt.UTC)
    if isinstance(value, str) and value:
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.UTC)
    return None


def _flatten(prefix: str, obj: dict[str, Any]) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in obj.items():
        column = f"{prefix}_{_snake(key)}" if prefix else _snake(key)
        if isinstance(value, dict):
            flattened.update(_flatten(column, value))
        elif column in _DATETIME_COLUMNS:
            flattened[column] = _coerce_datetime(value)
        else:
            flattened[column] = value
    return flattened


def normalize_results(endpoint_config: SesEndpointConfig, body: dict[str, Any]) -> list[dict[str, Any]]:
    # GetAccount returns a single object rather than a list; flatten it into one row.
    if endpoint_config.result_key is None:
        return [_flatten("", body)]

    items = body.get(endpoint_config.result_key) or []

    # ListConfigurationSets returns bare names; wrap each into a one-column row.
    if endpoint_config.string_list_column is not None:
        return [{endpoint_config.string_list_column: item} for item in items]

    return [_flatten("", item) for item in items if isinstance(item, dict)]


def _iso(value: dt.datetime) -> str:
    """The ISO8601 form SESv2 expects for the StartDate/EndDate query params."""
    return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def suppression_window(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    now: dt.datetime,
) -> tuple[Optional[str], str]:
    """The [StartDate, EndDate) the suppression scan asks SES for.

    EndDate is pinned to the present instant, never beyond it: SES filters on LastUpdateTime,
    so requesting a still-open future window would freeze this run's watermark ahead of data
    that has not been written yet. An incremental run rewinds StartDate behind the stored
    watermark because SES bumps LastUpdateTime whenever it re-suppresses an address.
    """
    start: Optional[str] = None
    if should_use_incremental_field:
        watermark = _coerce_datetime(db_incremental_field_last_value)
        if watermark is not None:
            start = _iso(watermark - dt.timedelta(days=SUPPRESSION_RESTATEMENT_LOOKBACK_DAYS))
    return start, _iso(now)


def _error_code(response: requests.Response) -> str:
    header = response.headers.get("x-amzn-ErrorType") or response.headers.get("x-amzn-errortype") or ""
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
    return AwsSesError(f"AWS SES request failed: {_error_code(response)} - {_error_message(response)}")


def make_session(secret_access_key: str, session_token: Optional[str]) -> requests.Session:
    # GET is idempotent, so the tracked session already retries 429 + transient 5xx honoring
    # Retry-After — no second retry layer here.
    redact = tuple(value for value in (secret_access_key, session_token) if value)
    return make_tracked_session(redact_values=redact)


def _build_url(region: str, endpoint_config: SesEndpointConfig, params: dict[str, Any]) -> str:
    host = SES_HOST_TEMPLATE.format(region=region)
    url = f"https://{host}{endpoint_config.path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    return url


def send_request(
    session: requests.Session,
    credentials: Credentials,
    region: str,
    endpoint_config: SesEndpointConfig,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Sign one SESv2 GET with SigV4 and send it over the tracked session."""
    url = _build_url(region, endpoint_config, params)
    aws_request = AWSRequest(method="GET", url=url)
    SigV4Auth(credentials, SES_SIGNING_NAME, region).add_auth(aws_request)

    response = session.get(url, headers=dict(aws_request.headers.items()), timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code >= 400:
        raise error_for_response(response)

    return response.json()


def build_params(
    endpoint_config: SesEndpointConfig,
    next_token: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if endpoint_config.paginated:
        params["PageSize"] = DEFAULT_PAGE_SIZE
    if start_date is not None:
        params["StartDate"] = start_date
    if end_date is not None:
        params["EndDate"] = end_date
    if next_token:
        params["NextToken"] = next_token
    return params


def validate_credentials(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    region: str,
) -> tuple[bool, Optional[str]]:
    """One cheap GetAccount probe — the exact permission every table's list call needs."""
    if not aws_access_key_id or not aws_secret_access_key:
        return False, "AWS access key ID and secret access key are required"
    if not region:
        return False, "An AWS region is required"

    try:
        send_request(
            make_session(aws_secret_access_key, aws_session_token),
            Credentials(aws_access_key_id, aws_secret_access_key, aws_session_token or None),
            region,
            AWS_SES_ENDPOINTS["account"],
            {},
        )
    except AwsSesError as error:
        return False, str(error)
    except Exception:
        return False, "Could not reach the AWS SES API"

    return True, None


def get_rows(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    region: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[AwsSesResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    endpoint_config = AWS_SES_ENDPOINTS[endpoint]

    session = make_session(aws_secret_access_key, aws_session_token)
    credentials = Credentials(aws_access_key_id, aws_secret_access_key, aws_session_token or None)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    next_token = resume.next_token if resume else None

    start_date: Optional[str] = None
    end_date: Optional[str] = None
    if endpoint_config.incremental:
        # Reuse the resumed window so a resumed NextToken is paired with the same request it
        # was minted against; otherwise freeze a fresh window for this run.
        if resume is not None and resume.end_date is not None:
            start_date, end_date = resume.start_date, resume.end_date
        else:
            start_date, end_date = suppression_window(
                should_use_incremental_field, db_incremental_field_last_value, dt.datetime.now(dt.UTC)
            )
    if resume is not None:
        logger.debug(f"Resuming AWS SES sync. endpoint={endpoint}")

    while True:
        body = send_request(
            session,
            credentials,
            region,
            endpoint_config,
            build_params(endpoint_config, next_token, start_date, end_date),
        )
        rows = normalize_results(endpoint_config, body)
        if rows:
            yield rows

        next_token = body.get("NextToken") if endpoint_config.paginated else None
        # Saved after yielding: a crash re-yields the last batch, which merges away on the
        # primary key, rather than skipping it.
        resumable_source_manager.save_state(
            AwsSesResumeConfig(next_token=next_token, start_date=start_date, end_date=end_date)
        )

        if not next_token:
            break

    resumable_source_manager.clear_state()


def aws_ses_source(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    region: Optional[str],
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[AwsSesResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    endpoint_config = AWS_SES_ENDPOINTS[endpoint]
    resolved_region = region or SES_DEFAULT_REGION

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
            region=resolved_region,
            endpoint=endpoint,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            logger=logger,
        ),
        primary_keys=endpoint_config.primary_key,
        sort_mode="asc",
    )
