import re
import json
import datetime as dt
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

# nosemgrep: python.lang.security.use-defused-xml.use-defused-xml (Element is only the node type for annotations — all parsing goes through defusedxml below)
from xml.etree.ElementTree import Element

import requests
import structlog
import defusedxml.ElementTree as DET
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_budgets.settings import (
    AWS_BUDGETS_ENDPOINTS,
    AWS_JSON_CONTENT_TYPE,
    BUDGETS_ENDPOINT_URL,
    BUDGETS_SIGNING_NAME,
    BUDGETS_SIGNING_REGION,
    BUDGETS_TARGET_PREFIX,
    COST_TYPE_MEMBERS,
    DEFAULT_HISTORY_LOOKBACK_DAYS,
    HISTORY_RESTATEMENT_LOOKBACK_DAYS,
    HISTORY_TIME_UNITS,
    REQUEST_TIMEOUT_SECONDS,
    STS_API_VERSION,
    STS_ENDPOINT_URL,
    STS_SIGNING_NAME,
    STS_SIGNING_REGION,
    AwsBudgetsEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

LOGGER = structlog.get_logger(__name__)

MAX_THROTTLE_ATTEMPTS = 6

# Budgets is a POST-only JSON RPC, and the tracked session's default policy only retries
# idempotent verbs, so POST is opted in explicitly for the transport-level statuses.
TRANSPORT_RETRY = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["POST"]),
    raise_on_status=False,
)

# AWS returns these as HTTP 400 with the code in the body, so the transport can't see them.
THROTTLING_ERROR_CODES = frozenset({"ThrottlingException", "TooManyRequestsException", "RequestLimitExceeded"})

_STALE_TOKEN_CODES = ("InvalidNextTokenException", "ExpiredNextTokenException")

# Failures that belong to one budget rather than to the sync. `NotFoundException` means the budget
# was deleted between listing it and asking for its detail;
# `BillingViewHealthStatusException` is matched defensively, since AWS documents an unhealthy
# billing view on a budget but doesn't list that code among the operation's errors.
_SKIPPABLE_BUDGET_ERROR_CODES = ("NotFoundException", "BillingViewHealthStatusException")

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

_ACCOUNT_ID_PATTERN = re.compile(r"^\d{12}$")

# Codes that mean the key itself is bad, as opposed to a valid key missing an IAM permission.
_CREDENTIAL_ERROR_CODES = (
    "UnrecognizedClientException",
    "InvalidClientTokenId",
    "SignatureDoesNotMatch",
    "InvalidSignatureException",
    "ExpiredTokenException",
    "AccessDenied",
)


class AwsBudgetsError(Exception):
    pass


class AwsBudgetsThrottledError(AwsBudgetsError):
    pass


@dataclasses.dataclass(frozen=True)
class AwsBudgetsResumeConfig:
    """Where a previous attempt stopped: the page token, plus the budget it was fanning out to."""

    next_token: Optional[str] = None
    budget_name: Optional[str] = None


@dataclasses.dataclass(frozen=True)
class BudgetRef:
    """The parts of a listed budget the per-budget operations need."""

    name: str
    time_unit: Optional[str]


@dataclasses.dataclass(frozen=True)
class TimeWindow:
    start: dt.datetime
    end: dt.datetime


def _snake(name: str) -> str:
    """`IncludeTax` -> `include_tax`, `UseAmortized` -> `use_amortized`."""
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def _parse_timestamp(value: Any) -> Optional[dt.datetime]:
    """Budgets serializes timestamps as epoch seconds under the JSON 1.1 protocol."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return dt.datetime.fromtimestamp(value, tz=dt.UTC)
    return coerce_datetime(value)


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


def cost_type_columns(cost_types: Optional[dict[str, Any]]) -> dict[str, Any]:
    # Driven off the documented member list rather than the response, so a budget type that
    # carries no cost types still lands with the same columns.
    members = cost_types or {}
    return {f"cost_types_{_snake(member)}": members.get(member) for member in COST_TYPE_MEMBERS}


def normalize_budget(budget: dict[str, Any]) -> dict[str, Any]:
    """One row per budget. Monetary amounts stay strings, exactly as AWS returns them."""
    limit = budget.get("BudgetLimit") or {}
    calculated = budget.get("CalculatedSpend") or {}
    actual = calculated.get("ActualSpend") or {}
    forecasted = calculated.get("ForecastedSpend") or {}
    period = budget.get("TimePeriod") or {}
    auto_adjust = budget.get("AutoAdjustData") or {}
    historical = auto_adjust.get("HistoricalOptions") or {}
    health = budget.get("HealthStatus") or {}

    return {
        "budget_name": budget.get("BudgetName"),
        "budget_type": budget.get("BudgetType"),
        "time_unit": budget.get("TimeUnit"),
        "budget_limit_amount": limit.get("Amount"),
        "budget_limit_unit": limit.get("Unit"),
        "actual_spend_amount": actual.get("Amount"),
        "actual_spend_unit": actual.get("Unit"),
        "forecasted_spend_amount": forecasted.get("Amount"),
        "forecasted_spend_unit": forecasted.get("Unit"),
        "time_period_start": _parse_timestamp(period.get("Start")),
        "time_period_end": _parse_timestamp(period.get("End")),
        "last_updated_time": _parse_timestamp(budget.get("LastUpdatedTime")),
        # Caller-defined maps and the recursive filter expression are kept whole: flattening them
        # would mint one column per key the customer happens to filter on.
        "planned_budget_limits": budget.get("PlannedBudgetLimits"),
        "cost_filters": budget.get("CostFilters"),
        "filter_expression": budget.get("FilterExpression"),
        "metrics": budget.get("Metrics"),
        "billing_view_arn": budget.get("BillingViewArn"),
        "auto_adjust_type": auto_adjust.get("AutoAdjustType"),
        "auto_adjust_budget_adjustment_period": historical.get("BudgetAdjustmentPeriod"),
        "auto_adjust_look_back_available_periods": historical.get("LookBackAvailablePeriods"),
        "auto_adjust_last_time": _parse_timestamp(auto_adjust.get("LastAutoAdjustTime")),
        "health_status": health.get("Status"),
        "health_status_reason": health.get("StatusReason"),
        "health_status_last_updated_time": _parse_timestamp(health.get("LastUpdatedTime")),
        **cost_type_columns(budget.get("CostTypes")),
    }


def normalize_history_rows(budget: BudgetRef, body: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per budget period. The response wraps the series in a single history object."""
    history = body.get("BudgetPerformanceHistory") or {}
    base: dict[str, Any] = {
        "budget_name": history.get("BudgetName") or budget.name,
        "budget_type": history.get("BudgetType"),
        "time_unit": history.get("TimeUnit"),
        "billing_view_arn": history.get("BillingViewArn"),
        "cost_filters": history.get("CostFilters"),
        **cost_type_columns(history.get("CostTypes")),
    }

    rows: list[dict[str, Any]] = []
    for amounts in history.get("BudgetedAndActualAmountsList") or []:
        period = amounts.get("TimePeriod") or {}
        budgeted = amounts.get("BudgetedAmount") or {}
        actual = amounts.get("ActualAmount") or {}
        rows.append(
            {
                **base,
                "period_start": _parse_timestamp(period.get("Start")),
                "period_end": _parse_timestamp(period.get("End")),
                "budgeted_amount": budgeted.get("Amount"),
                "budgeted_unit": budgeted.get("Unit"),
                "actual_amount": actual.get("Amount"),
                "actual_unit": actual.get("Unit"),
            }
        )
    return rows


def normalize_notification_rows(budget: BudgetRef, body: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "budget_name": budget.name,
            "notification_type": notification.get("NotificationType"),
            "comparison_operator": notification.get("ComparisonOperator"),
            "threshold": notification.get("Threshold"),
            "threshold_type": notification.get("ThresholdType"),
            "notification_state": notification.get("NotificationState"),
        }
        for notification in body.get("Notifications") or []
    ]


def rows_for_budget(
    endpoint_config: AwsBudgetsEndpointConfig, budget: BudgetRef, body: dict[str, Any]
) -> list[dict[str, Any]]:
    if endpoint_config.name == "budget_performance_history":
        return normalize_history_rows(budget, body)
    return normalize_notification_rows(budget, body)


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


def error_for_response(response: requests.Response) -> AwsBudgetsError:
    code = _error_code(response)
    text = f"AWS Budgets request failed: {code} - {_error_message(response)}"
    # 429 and 5xx are already retried by the tracked transport; only the app-level throttling
    # codes, which arrive as HTTP 400, need a second bounded retry here.
    if code in THROTTLING_ERROR_CODES:
        return AwsBudgetsThrottledError(text)
    return AwsBudgetsError(text)


def make_session(secret_access_key: str, session_token: Optional[str]) -> requests.Session:
    redact = tuple(value for value in (secret_access_key, session_token) if value)
    return make_tracked_session(retry=TRANSPORT_RETRY, redact_values=redact)


@retry(
    retry=retry_if_exception_type(AwsBudgetsThrottledError),
    stop=stop_after_attempt(MAX_THROTTLE_ATTEMPTS),
    wait=wait_exponential_jitter(initial=5, max=120),
    reraise=True,
)
def send_operation(
    session: requests.Session,
    credentials: Credentials,
    operation: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Sign one Budgets JSON-RPC call with SigV4 and send it over the tracked session."""
    body = json.dumps(payload).encode()
    aws_request = AWSRequest(
        method="POST",
        url=BUDGETS_ENDPOINT_URL,
        data=body,
        headers={
            "Content-Type": AWS_JSON_CONTENT_TYPE,
            "X-Amz-Target": f"{BUDGETS_TARGET_PREFIX}.{operation}",
        },
    )
    SigV4Auth(credentials, BUDGETS_SIGNING_NAME, BUDGETS_SIGNING_REGION).add_auth(aws_request)

    response = session.post(
        BUDGETS_ENDPOINT_URL,
        data=body,
        headers=dict(aws_request.headers.items()),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise error_for_response(response)

    return response.json()


def _sts_error(response: requests.Response) -> AwsBudgetsError:
    """STS speaks the query protocol, so its errors are XML rather than JSON."""
    code = f"HTTP {response.status_code}"
    message = ""
    try:
        root: Element = DET.fromstring(response.text)
    except Exception:
        return AwsBudgetsError(f"AWS STS request failed: {code} - {response.text[:500]}")

    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "Code" and element.text:
            code = element.text
        elif tag == "Message" and element.text:
            message = element.text[:500]
    return AwsBudgetsError(f"AWS STS request failed: {code} - {message}")


def fetch_account_id(session: requests.Session, credentials: Credentials) -> str:
    """Derive the 12-digit account id the Budgets operations require.

    `sts:GetCallerIdentity` needs no IAM permission, so this doubles as the probe that tells a
    genuine-but-under-permissioned key apart from an invalid one.
    """
    body = urlencode({"Action": "GetCallerIdentity", "Version": STS_API_VERSION}).encode()
    aws_request = AWSRequest(
        method="POST",
        url=STS_ENDPOINT_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
    )
    SigV4Auth(credentials, STS_SIGNING_NAME, STS_SIGNING_REGION).add_auth(aws_request)

    response = session.post(
        STS_ENDPOINT_URL,
        data=body,
        headers=dict(aws_request.headers.items()),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise _sts_error(response)

    try:
        root: Element = DET.fromstring(response.text)
    except Exception as error:
        raise AwsBudgetsError("AWS STS returned a response we could not read") from error

    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "Account" and element.text:
            account_id = element.text.strip()
            if _ACCOUNT_ID_PATTERN.match(account_id):
                return account_id

    raise AwsBudgetsError("AWS STS did not return an account ID for these credentials")


def resolve_history_window(
    should_use_incremental_field: bool, db_incremental_field_last_value: Any, now: dt.datetime
) -> TimeWindow:
    """The period range this run asks AWS for.

    An incremental run rewinds behind the stored watermark because actual spend for recent periods
    keeps being restated until the bill finalizes.
    """
    floor = now - dt.timedelta(days=DEFAULT_HISTORY_LOOKBACK_DAYS)

    start = floor
    if should_use_incremental_field:
        watermark = coerce_datetime(db_incremental_field_last_value)
        if watermark is not None:
            start = max(floor, watermark - dt.timedelta(days=HISTORY_RESTATEMENT_LOOKBACK_DAYS))

    # Reaches past now so the period in progress is included; its actual spend merges again on
    # every later run.
    return TimeWindow(start=start, end=now + dt.timedelta(days=1))


def _has_code(error: AwsBudgetsError, codes: tuple[str, ...]) -> bool:
    text = str(error)
    return any(code in text for code in codes)


def _walk_pages(
    session: requests.Session,
    credentials: Credentials,
    operation: str,
    payload: dict[str, Any],
    start_token: Optional[str],
    logger: FilteringBoundLogger,
) -> Iterator[tuple[dict[str, Any], Optional[str]]]:
    """Yield each response page with the token that follows it."""
    token = start_token
    resumed = start_token is not None

    while True:
        page_payload = dict(payload)
        if token:
            page_payload["NextToken"] = token

        try:
            body = send_operation(session, credentials, operation, page_payload)
        except AwsBudgetsError as error:
            # A token saved by an earlier attempt can expire; restart the walk instead of failing
            # the job. Merge on the primary key absorbs the re-read rows.
            if resumed and _has_code(error, _STALE_TOKEN_CODES):
                logger.debug(f"Saved AWS Budgets page token is no longer valid; restarting. operation={operation}")
                token = None
                resumed = False
                continue
            raise
        resumed = False

        token = body.get("NextToken")
        yield body, token
        if not token:
            return


def list_budgets(
    session: requests.Session,
    credentials: Credentials,
    account_id: str,
    page_size: int,
    logger: FilteringBoundLogger,
) -> list[BudgetRef]:
    """Every budget on the account, in the order AWS lists them.

    The per-budget operations need the whole list up front: resuming a fan-out means finding the
    budget the previous attempt stopped on.
    """
    payload: dict[str, Any] = {"AccountId": account_id, "MaxResults": page_size}
    budgets: list[BudgetRef] = []
    for body, _ in _walk_pages(session, credentials, "DescribeBudgets", payload, None, logger):
        for budget in body.get("Budgets") or []:
            name = budget.get("BudgetName")
            if isinstance(name, str) and name:
                budgets.append(BudgetRef(name=name, time_unit=budget.get("TimeUnit")))
    return budgets


def resume_position(budgets: list[BudgetRef], resume: Optional[AwsBudgetsResumeConfig]) -> tuple[int, Optional[str]]:
    """Where to pick a fan-out up. A budget that no longer exists restarts the run."""
    if resume is None or resume.budget_name is None:
        return 0, None

    for index, budget in enumerate(budgets):
        if budget.name == resume.budget_name:
            return index, resume.next_token

    return 0, None


def _budget_rows(
    session: requests.Session,
    credentials: Credentials,
    account_id: str,
    endpoint_config: AwsBudgetsEndpointConfig,
    resumable_source_manager: ResumableSourceManager[AwsBudgetsResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_token = resume.next_token if resume is not None else None
    if start_token:
        logger.debug("Resuming AWS Budgets sync from a saved page token. endpoint=budgets")

    payload: dict[str, Any] = {
        "AccountId": account_id,
        "MaxResults": endpoint_config.page_size,
        # Budgets created with a filter expression only report it when asked.
        "ShowFilterExpression": True,
    }

    for body, next_token in _walk_pages(session, credentials, endpoint_config.operation, payload, start_token, logger):
        rows = [normalize_budget(budget) for budget in body.get("Budgets") or []]
        if rows:
            yield rows
        # Saved after yielding: a crash re-yields the last page, which merges away on the primary
        # key, rather than skipping it.
        resumable_source_manager.save_state(AwsBudgetsResumeConfig(next_token=next_token))

    resumable_source_manager.clear_state()


def _fanout_rows(
    session: requests.Session,
    credentials: Credentials,
    account_id: str,
    endpoint_config: AwsBudgetsEndpointConfig,
    resumable_source_manager: ResumableSourceManager[AwsBudgetsResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    budgets = list_budgets(session, credentials, account_id, AWS_BUDGETS_ENDPOINTS["budgets"].page_size, logger)
    if endpoint_config.supports_time_period:
        budgets = [budget for budget in budgets if (budget.time_unit or "") in HISTORY_TIME_UNITS]
    if not budgets:
        resumable_source_manager.clear_state()
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    index, token = resume_position(budgets, resume)
    if resume is not None:
        logger.debug(f"Resuming AWS Budgets sync. endpoint={endpoint_config.name}, budget_name={budgets[index].name}")

    payload_extra: dict[str, Any] = {}
    if endpoint_config.supports_time_period:
        window = resolve_history_window(
            should_use_incremental_field, db_incremental_field_last_value, dt.datetime.now(dt.UTC)
        )
        payload_extra["TimePeriod"] = {"Start": int(window.start.timestamp()), "End": int(window.end.timestamp())}

    for budget in budgets[index:]:
        payload: dict[str, Any] = {
            "AccountId": account_id,
            "BudgetName": budget.name,
            "MaxResults": endpoint_config.page_size,
            **payload_extra,
        }

        try:
            for body, next_token in _walk_pages(
                session, credentials, endpoint_config.operation, payload, token, logger
            ):
                rows = rows_for_budget(endpoint_config, budget, body)
                if rows:
                    yield rows
                resumable_source_manager.save_state(
                    AwsBudgetsResumeConfig(next_token=next_token, budget_name=budget.name)
                )
        except AwsBudgetsError as error:
            if not _has_code(error, _SKIPPABLE_BUDGET_ERROR_CODES):
                raise
            logger.debug(f"Skipping a budget AWS could not report on. budget_name={budget.name}, error={error}")

        token = None

    resumable_source_manager.clear_state()


def get_rows(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[AwsBudgetsResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    endpoint_config = AWS_BUDGETS_ENDPOINTS[endpoint]
    session = make_session(aws_secret_access_key, aws_session_token)
    credentials = Credentials(aws_access_key_id, aws_secret_access_key, aws_session_token or None)
    account_id = fetch_account_id(session, credentials)

    if endpoint_config.per_budget:
        yield from _fanout_rows(
            session,
            credentials,
            account_id,
            endpoint_config,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
            logger,
        )
        return

    yield from _budget_rows(session, credentials, account_id, endpoint_config, resumable_source_manager, logger)


def _permission_reason(error: AwsBudgetsError) -> Optional[str]:
    text = str(error)
    if "AccessDeniedException" in text:
        return "The connected IAM user or role is not allowed to read this table"
    if _has_code(error, _CREDENTIAL_ERROR_CODES):
        return "AWS rejected the access key. Please check the access key ID and secret access key."
    return None


def endpoint_permission_reason(
    session: requests.Session,
    credentials: Credentials,
    account_id: str,
    endpoint_config: AwsBudgetsEndpointConfig,
) -> Optional[str]:
    """Probe the calls a sync of this endpoint issues. `None` when reachable.

    Only a real denial counts as unreachable: throttles, 5xx and network errors leave the endpoint
    reported as reachable, so a blip can't hide tables from the schema picker.
    """
    try:
        budgets = list_budgets(session, credentials, account_id, 1, LOGGER)
        if not endpoint_config.per_budget:
            return None

        eligible = [
            budget
            for budget in budgets
            if not endpoint_config.supports_time_period or (budget.time_unit or "") in HISTORY_TIME_UNITS
        ]
        for budget in eligible[:1]:
            payload: dict[str, Any] = {"AccountId": account_id, "BudgetName": budget.name, "MaxResults": 1}
            send_operation(session, credentials, endpoint_config.operation, payload)
    except AwsBudgetsError as error:
        if _has_code(error, _SKIPPABLE_BUDGET_ERROR_CODES):
            return None
        return _permission_reason(error)
    except Exception:
        return None
    return None


def probe_endpoint_permissions(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    endpoints: list[str],
) -> dict[str, str | None]:
    session = make_session(aws_secret_access_key, aws_session_token)
    credentials = Credentials(aws_access_key_id, aws_secret_access_key, aws_session_token or None)

    try:
        account_id = fetch_account_id(session, credentials)
    except Exception:
        return dict.fromkeys(endpoints)

    reasons: dict[str, str | None] = {}
    for endpoint in endpoints:
        endpoint_config = AWS_BUDGETS_ENDPOINTS.get(endpoint)
        reasons[endpoint] = (
            endpoint_permission_reason(session, credentials, account_id, endpoint_config)
            if endpoint_config is not None
            else None
        )
    return reasons


def validate_credentials(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    schema_name: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    if not aws_access_key_id or not aws_secret_access_key:
        return False, "AWS access key ID and secret access key are required"

    session = make_session(aws_secret_access_key, aws_session_token)
    credentials = Credentials(aws_access_key_id, aws_secret_access_key, aws_session_token or None)

    try:
        account_id = fetch_account_id(session, credentials)
    except AwsBudgetsError as error:
        return False, str(error)
    except Exception:
        return False, "Could not reach AWS to check these credentials. Please try again."

    if schema_name is not None and schema_name in AWS_BUDGETS_ENDPOINTS:
        reason = endpoint_permission_reason(session, credentials, account_id, AWS_BUDGETS_ENDPOINTS[schema_name])
        return reason is None, reason

    try:
        send_operation(session, credentials, "DescribeBudgets", {"AccountId": account_id, "MaxResults": 1})
    except AwsBudgetsError as error:
        # STS already proved the key is genuine, so a denial here is a missing IAM permission. It
        # is reported per table in the schema picker rather than blocking source creation.
        if "AccessDeniedException" in str(error):
            return True, None
        return False, str(error)
    except Exception:
        return False, "Could not reach the AWS Budgets API. Please try again."

    return True, None


def aws_budgets_source(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: Optional[str],
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[AwsBudgetsResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    endpoint_config = AWS_BUDGETS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
            endpoint=endpoint,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            logger=logger,
        ),
        primary_keys=endpoint_config.primary_key,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        # AWS documents no ordering for these operations, and the per-budget fan-out restarts each
        # budget's history at its earliest period, so the incremental watermark must only commit
        # once a walk completes. "desc" gives exactly that single end-of-run commit.
        sort_mode="desc",
    )
