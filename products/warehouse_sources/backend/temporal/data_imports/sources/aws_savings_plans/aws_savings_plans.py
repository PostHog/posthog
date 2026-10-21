import re
import json
import datetime as dt
import itertools
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_savings_plans.settings import (
    COST_EXPLORER_API_VERSION,
    DEFAULT_LOOKBACK_DAYS,
    ENDPOINTS,
    ERROR_MESSAGES,
    RECOMMENDATION_DECIMAL_FIELDS,
    RECOMMENDATION_OPTIONS,
    RESTATEMENT_DAYS,
    SAVINGS_PLANS_API_VERSION,
    SIGNING_REGION,
    SavingsPlansEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssavingsplans import (
    AwsSavingsPlansSourceConfig,
)

TRANSPORT_RETRY = BoundedRetry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["POST"]),
    raise_on_status=False,
)
THROTTLE_CODES = {"ThrottlingException", "TooManyRequestsException", "LimitExceededException", "RequestLimitExceeded"}
CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


@frozen
class AwsSavingsPlansResumeConfig:
    next_token: str | None = None
    window_start: str | None = None
    window_end: str | None = None
    end_date: str | None = None
    parent_id: str | None = None
    completed: bool = False


class AwsSavingsPlansError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"AWS Savings Plans request failed: {code}")


class AwsSavingsPlansThrottledError(AwsSavingsPlansError):
    pass


class AwsSavingsPlansClient:
    def __init__(self, config: AwsSavingsPlansSourceConfig, api_version: str) -> None:
        if api_version != SAVINGS_PLANS_API_VERSION:
            raise ValueError(f"Unsupported AWS Savings Plans API version: {api_version}")
        self.credentials = Credentials(config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token)
        self.session = make_tracked_session(
            retry=TRANSPORT_RETRY,
            redact_values=tuple(
                value
                for value in (config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token)
                if value
            ),
        )

    @retry(
        retry=retry_if_exception_type(AwsSavingsPlansThrottledError),
        wait=wait_exponential_jitter(initial=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def request(self, endpoint: SavingsPlansEndpoint, payload: dict[str, Any]) -> dict[str, Any]:
        if endpoint.service == "savingsplans":
            url = f"https://savingsplans.amazonaws.com/{endpoint.operation}"
            headers = {"Content-Type": "application/json", "X-Amz-Api-Version": SAVINGS_PLANS_API_VERSION}
        else:
            url = "https://ce.us-east-1.amazonaws.com/"
            headers = {
                "Content-Type": "application/x-amz-json-1.1",
                "X-Amz-Target": f"AWSInsightsIndexService.{endpoint.operation}",
                "X-Amz-Api-Version": COST_EXPLORER_API_VERSION,
            }
        body = json.dumps(payload).encode()
        request = AWSRequest(method="POST", url=url, data=body, headers=headers)
        SigV4Auth(self.credentials, endpoint.service, SIGNING_REGION).add_auth(request)
        response = self.session.post(url, data=body, headers=dict(request.headers), timeout=60)
        if response.status_code >= 400:
            try:
                error = response.json()
            except ValueError:
                error = {}
            if not isinstance(error, dict):
                error = {}
            raw_code = response.headers.get("x-amzn-ErrorType") or error.get("__type") or error.get("code")
            code = str(raw_code or f"HTTP {response.status_code}").split(":")[0].rsplit("#", 1)[-1]
            if response.status_code == 400 and code in THROTTLE_CODES:
                raise AwsSavingsPlansThrottledError(code)
            raise AwsSavingsPlansError(code)
        return response.json()

    def close(self) -> None:
        self.session.close()


def parse_date(value: Any) -> dt.date | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def build_payload(
    endpoint: SavingsPlansEndpoint, start: dt.date | None = None, end: dt.date | None = None
) -> dict[str, Any]:
    if not endpoint.windowed:
        return {endpoint.page_size_key: endpoint.page_size} if endpoint.page_size_key else {}
    if start is None or end is None:
        raise ValueError("Cost Explorer requires a start date and an end date")
    payload: dict[str, Any] = {"TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()}}
    if endpoint.granularity:
        payload["Granularity"] = endpoint.granularity
    if endpoint.token_key:
        payload["MaxResults"] = 100
    if endpoint.operation == "GetSavingsPlansUtilizationDetails":
        payload["DataType"] = ["ATTRIBUTES", "UTILIZATION", "AMORTIZED_COMMITMENT", "SAVINGS"]
    return payload


def snake_case(item: dict[str, Any]) -> dict[str, Any]:
    return {CAMEL_BOUNDARY.sub("_", key).lower(): value for key, value in item.items()}


def recommendation_details(body: dict[str, Any]) -> list[dict[str, Any]]:
    return (body.get("SavingsPlansPurchaseRecommendation") or {}).get("SavingsPlansPurchaseRecommendationDetails") or []


def normalize_recommendation(row: dict[str, Any]) -> dict[str, Any]:
    row.update(snake_case(row.pop("savings_plans_details", None) or {}))
    for field in RECOMMENDATION_DECIMAL_FIELDS:
        if field in row:
            row[field] = Decimal(row[field]) if row[field] not in (None, "") else None
    for field in ("generation_timestamp", "latest_usage_timestamp"):
        if row.get(field):
            row[field] = dt.datetime.fromisoformat(row[field].replace("Z", "+00:00"))
    return row


def normalize_rows(endpoint: SavingsPlansEndpoint, body: dict[str, Any]) -> list[dict[str, Any]]:
    if endpoint.operation == "GetSavingsPlansPurchaseRecommendation":
        recommendation = body.get(endpoint.result_key) or {}
        shared = {
            key: value
            for key, value in snake_case({**recommendation, **(body.get("Metadata") or {})}).items()
            if not isinstance(value, dict | list)
        }
        return [normalize_recommendation({**shared, **snake_case(item)}) for item in recommendation_details(body)]
    if endpoint.operation == "GetSavingsPlanPurchaseRecommendationDetails":
        detail = body.get(endpoint.result_key)
        if not detail:
            return []
        return [normalize_recommendation(snake_case(detail))]
    rows = []
    for item in body.get(endpoint.result_key, []):
        row = snake_case(item)
        if endpoint.service == "savingsplans":
            for field in ("start", "end", "returnable_until"):
                if row.get(field):
                    row[field] = dt.datetime.fromisoformat(row[field].replace("Z", "+00:00"))
            for field in ("commitment", "recurring_payment_amount", "upfront_payment_amount", "rate"):
                if row.get(field) is not None:
                    row[field] = Decimal(row[field])
        else:
            period = row.pop("time_period", body.get("TimePeriod"))
            if not period:
                raise ValueError("AWS returned metrics without a time period")
            row["period_start"] = dt.datetime.fromisoformat(period["Start"]).replace(tzinfo=dt.UTC)
            row["period_end"] = dt.datetime.fromisoformat(period["End"]).replace(tzinfo=dt.UTC)
            for field in ("utilization", "savings", "amortized_commitment", "coverage"):
                for key, value in row.pop(field, {}).items():
                    row[f"{field}_{CAMEL_BOUNDARY.sub('_', key).lower()}"] = (
                        Decimal(value) if value not in (None, "") else None
                    )
        rows.append(row)
    return rows


def recommendation_options() -> list[tuple[str, dict[str, str]]]:
    combinations = [
        dict(zip(options, values))
        for options in RECOMMENDATION_OPTIONS
        for values in itertools.product(*options.values())
    ]
    return sorted(("|".join(options.values()), options) for options in combinations)


def iter_pages(
    client: AwsSavingsPlansClient,
    endpoint: SavingsPlansEndpoint,
    payload: dict[str, Any],
    manager: ResumableSourceManager[AwsSavingsPlansResumeConfig],
) -> Iterator[dict[str, Any]]:
    token = None
    while True:
        body = client.request(
            endpoint, {**payload, endpoint.token_key: token} if token and endpoint.token_key else payload
        )
        manager.safe_point()
        yield body
        next_token = body.get(endpoint.token_key) if endpoint.token_key else None
        if not next_token:
            return
        if next_token == token:
            raise ValueError("AWS returned a repeated pagination token")
        token = next_token


def list_parents(
    client: AwsSavingsPlansClient,
    endpoint: SavingsPlansEndpoint,
    manager: ResumableSourceManager[AwsSavingsPlansResumeConfig],
) -> list[tuple[str, dict[str, Any]]]:
    if endpoint.fan_out == "savings_plans":
        plans = ENDPOINTS["savings_plans"]
        ids = {
            plan["savingsPlanId"]
            for body in iter_pages(client, plans, build_payload(plans), manager)
            for plan in body.get(plans.result_key, [])
        }
        return [(plan_id, {"savingsPlanId": plan_id}) for plan_id in sorted(ids)]
    if endpoint.fan_out == "recommendation_options":
        return recommendation_options()
    recommendations = ENDPOINTS["purchase_recommendations"]
    detail_ids = {
        detail["RecommendationDetailId"]
        for _, options in recommendation_options()
        for body in iter_pages(client, recommendations, {**build_payload(recommendations), **options}, manager)
        for detail in recommendation_details(body)
    }
    return [(detail_id, {"RecommendationDetailId": detail_id}) for detail_id in sorted(detail_ids)]


def first_parent(client: AwsSavingsPlansClient, endpoint: SavingsPlansEndpoint) -> dict[str, Any] | None:
    if endpoint.fan_out == "savings_plans":
        plans = client.request(ENDPOINTS["savings_plans"], {"maxResults": 1}).get("savingsPlans") or []
        return {"savingsPlanId": plans[0]["savingsPlanId"]} if plans else None
    options = recommendation_options()[0][1]
    if endpoint.fan_out == "recommendation_options":
        return options
    details = recommendation_details(client.request(ENDPOINTS["purchase_recommendations"], {**options, "PageSize": 1}))
    return {"RecommendationDetailId": details[0]["RecommendationDetailId"]} if details else None


def validation_error(code: str, endpoint: SavingsPlansEndpoint) -> str:
    if code.startswith("AccessDenied") or code == "UnauthorizedException":
        return f"AWS denied access. Grant {endpoint.service}:{endpoint.operation} to the IAM user or role."
    for pattern, message in ERROR_MESSAGES.items():
        if pattern in code:
            return message
    return "AWS could not complete the request. Check the credentials and try again."


def validate_credentials(
    config: AwsSavingsPlansSourceConfig,
    schema_name: str | None = None,
    api_version: str = SAVINGS_PLANS_API_VERSION,
) -> tuple[bool, str | None]:
    if not config.aws_access_key_id or not config.aws_secret_access_key:
        return False, "Enter an AWS access key ID and secret access key."
    endpoint = ENDPOINTS.get(schema_name or "savings_plans")
    if endpoint is None:
        return False, "Unknown AWS Savings Plans table."
    try:
        parse_date(config.start_date)
    except ValueError:
        return False, "Enter the start date as YYYY-MM-DD."
    client = AwsSavingsPlansClient(config, api_version)
    try:
        end = dt.datetime.now(dt.UTC).date() - dt.timedelta(days=1)
        payload = build_payload(endpoint, end - dt.timedelta(days=1), end)
        if endpoint.token_key:
            payload[endpoint.page_size_key or "MaxResults"] = 1
        # A fan-out table can only check its own permission once a parent exists.
        parent: dict[str, Any] | None = {}
        if endpoint.fan_out:
            try:
                parent = first_parent(client, endpoint)
            except AwsSavingsPlansError as error:
                return False, validation_error(error.code, ENDPOINTS.get(endpoint.fan_out, endpoint))
        if parent is not None:
            client.request(endpoint, {**payload, **parent})
    except AwsSavingsPlansError as error:
        if schema_name is None and (error.code.startswith("AccessDenied") or error.code == "UnauthorizedException"):
            return True, None
        return False, validation_error(error.code, endpoint)
    except requests.RequestException:
        return False, "Could not reach AWS. Try again later."
    finally:
        client.close()
    return True, None


def get_rows(
    config: AwsSavingsPlansSourceConfig,
    endpoint: SavingsPlansEndpoint,
    manager: ResumableSourceManager[AwsSavingsPlansResumeConfig],
    incremental: bool,
    last_value: Any,
    api_version: str,
) -> Iterator[list[dict[str, Any]]]:
    resume = manager.load_state() if manager.can_resume() else None
    if resume and resume.completed:
        return
    # Freeze request windows across retries because AWS tokens depend on the original parameters.
    end = parse_date(resume.end_date) if resume else None
    end = end or (dt.datetime.now(dt.UTC).date() - dt.timedelta(days=1))
    history_floor = end - dt.timedelta(days=DEFAULT_LOOKBACK_DAYS)
    floor = max(parse_date(config.start_date) or history_floor, history_floor)
    watermark = parse_date(last_value) if incremental and endpoint.windowed else None
    start = max(floor, watermark - dt.timedelta(days=RESTATEMENT_DAYS)) if watermark else floor
    start = (parse_date(resume.window_start) or start) if resume else start
    stop = (parse_date(resume.window_end) if resume else None) or min(
        start + dt.timedelta(days=endpoint.window_days), end
    )
    token = resume.next_token if resume else None
    client = AwsSavingsPlansClient(config, api_version)
    try:
        if endpoint.fan_out:
            yield from get_fan_out_rows(client, endpoint, manager, resume)
            return
        while not endpoint.windowed or start < end:
            payload = build_payload(endpoint, start, stop)
            if token and endpoint.token_key:
                payload[endpoint.token_key] = token
            body = client.request(endpoint, payload)
            rows = normalize_rows(endpoint, body)
            next_token = body.get(endpoint.token_key) if endpoint.token_key else None
            if next_token and next_token == token:
                raise ValueError("AWS returned a repeated pagination token")
            completed = not next_token and (not endpoint.windowed or stop >= end)
            next_start = start if next_token else stop
            next_stop = stop if next_token else min(stop + dt.timedelta(days=endpoint.window_days), end)
            manager.save_state(
                AwsSavingsPlansResumeConfig(
                    next_token=next_token,
                    window_start=next_start.isoformat(),
                    window_end=next_stop.isoformat(),
                    end_date=end.isoformat(),
                    completed=completed,
                )
            )
            if rows:
                yield rows
            manager.safe_point()
            if completed:
                break
            start, stop, token = next_start, next_stop, next_token
    finally:
        client.close()


def get_fan_out_rows(
    client: AwsSavingsPlansClient,
    endpoint: SavingsPlansEndpoint,
    manager: ResumableSourceManager[AwsSavingsPlansResumeConfig],
    resume: AwsSavingsPlansResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    resume_parent = resume.parent_id if resume else None
    resume_token = resume.next_token if resume else None
    # Parents are sorted, so a resumed run skips every parent that an earlier attempt finished.
    parents = [
        (key, params)
        for key, params in list_parents(client, endpoint, manager)
        if resume_parent is None or key > resume_parent or (key == resume_parent and resume_token)
    ]
    for index, (key, params) in enumerate(parents):
        token = resume_token if key == resume_parent else None
        while True:
            payload = {**build_payload(endpoint), **params}
            if token and endpoint.token_key:
                payload[endpoint.token_key] = token
            body = client.request(endpoint, payload)
            rows = normalize_rows(endpoint, body)
            if endpoint.parent_column:
                rows = [{**row, endpoint.parent_column: key} for row in rows]
            next_token = body.get(endpoint.token_key) if endpoint.token_key else None
            if next_token and next_token == token:
                raise ValueError("AWS returned a repeated pagination token")
            manager.save_state(
                AwsSavingsPlansResumeConfig(
                    parent_id=key,
                    next_token=next_token,
                    completed=not next_token and index == len(parents) - 1,
                )
            )
            if rows:
                yield rows
            manager.safe_point()
            if not next_token:
                break
            token = next_token


def aws_savings_plans_source(
    config: AwsSavingsPlansSourceConfig,
    endpoint_name: str,
    manager: ResumableSourceManager[AwsSavingsPlansResumeConfig],
    incremental: bool,
    last_value: Any,
    api_version: str,
) -> SourceResponse:
    endpoint = ENDPOINTS[endpoint_name]
    metrics = endpoint.windowed
    return SourceResponse(
        name=endpoint_name,
        items=lambda: get_rows(config, endpoint, manager, incremental, last_value, api_version),
        primary_keys=list(endpoint.primary_keys),
        partition_keys=["period_start"] if metrics else None,
        partition_mode="datetime" if metrics else None,
        partition_format="month" if metrics else None,
        # "desc" saves the watermark once at job end, so unordered rows cannot strand older ones.
        sort_mode="desc",
        on_complete=manager.clear_state,
    )
