import re
import json
import datetime as dt
from collections.abc import Callable, Iterator
from typing import Any

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_inspector.settings import (
    AWS_INSPECTOR_ENDPOINTS,
    CIS_SCAN_TARGETS_ENDPOINT,
    CIS_SCANS_ENDPOINT,
    ERROR_MESSAGES,
    INCREMENTAL_FIELDS,
    INSPECTOR_API_VERSION,
    AwsInspectorEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import probe_status_message
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsinspector import (
    AwsInspectorSourceConfig,
)

TRANSPORT_RETRY = BoundedRetry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["POST"]),
    raise_on_status=False,
)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
ECR_IMAGE_COVERAGE_FILTER = {
    "resourceType": [{"comparison": "EQUALS", "value": "AWS_ECR_CONTAINER_IMAGE"}],
    "scanType": [{"comparison": "EQUALS", "value": "PACKAGE"}],
}


@frozen
class AwsInspectorResumeConfig:
    next_token: str | None = None
    updated_after: float | None = None
    completed: bool = False
    scan_arn: str | None = None
    parent_token: str | None = None
    parent_key: str | None = None


@frozen
class FanOutPosition:
    parent_token: str | None = None
    parent_key: str | None = None
    next_token: str | None = None


class AwsInspectorError(Exception):
    def __init__(self, code: str, message: str, status_code: int | None = None) -> None:
        super().__init__(f"AWS Inspector request failed: {code} - {message}")
        self.code = code
        self.message = message
        self.status_code = status_code


def error_for_response(response: requests.Response) -> AwsInspectorError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw_code = response.headers.get("x-amzn-ErrorType") or body.get("__type") or body.get("code")
    code = str(raw_code or f"HTTP {response.status_code}").split(":")[0].split("#")[-1]
    message = str(body.get("message") or body.get("Message") or response.reason or "")[:500]
    if response.status_code in (400, 403) and any(
        phrase in message.lower() for phrase in ("not subscribed", "not enabled", "subscription is required")
    ):
        code = "SubscriptionRequiredException"
    return AwsInspectorError(code, message, response.status_code)


def error_message(error: AwsInspectorError) -> str | None:
    return next((message for code, message in ERROR_MESSAGES.items() if error.code.startswith(code)), None)


class AwsInspectorClient:
    def __init__(self, config: AwsInspectorSourceConfig, api_version: str = INSPECTOR_API_VERSION) -> None:
        if api_version != INSPECTOR_API_VERSION:
            raise ValueError(f"Unsupported AWS Inspector API version: {api_version}")
        if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", config.region):
            raise ValueError("Enter an AWS region code, such as us-east-1.")
        if not config.aws_access_key_id or not config.aws_secret_access_key:
            raise ValueError("Enter both an AWS access key ID and a secret access key.")
        suffix = "amazonaws.com.cn" if config.region.startswith("cn-") else "amazonaws.com"
        self._base_url = f"https://inspector2.{config.region}.{suffix}"
        self._signer = SigV4Auth(
            Credentials(config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token or None),
            "inspector2",
            config.region,
        )
        self._session = make_tracked_session(
            retry=TRANSPORT_RETRY,
            redact_values=tuple(
                value
                for value in (config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token)
                if value
            ),
        )

    def close(self) -> None:
        self._session.close()

    def request(self, endpoint: AwsInspectorEndpoint, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        url = self._base_url + endpoint.path
        request = AWSRequest(method="POST", url=url, data=body, headers={"Content-Type": "application/json"})
        self._signer.add_auth(request)
        response = self._session.post(url, data=body, headers=dict(request.headers), timeout=60, allow_redirects=False)
        if response.status_code != 200:
            raise error_for_response(response)
        parsed = response.json()
        if not isinstance(parsed, dict):
            raise ValueError("AWS Inspector returned an invalid response.")
        return parsed


def timestamp(value: dt.datetime | str | int | float) -> float:
    if isinstance(value, int | float):
        return float(value)
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.timestamp()


def request_payload(endpoint: AwsInspectorEndpoint, updated_after: float | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if endpoint.page_size is not None:
        payload["maxResults"] = endpoint.page_size
    if endpoint.operation == "ListCoverageStatistics":
        payload["groupBy"] = "RESOURCE_TYPE"
    if endpoint.operation == "ListFindings" and updated_after is not None:
        payload["filterCriteria"] = {"updatedAt": [{"startInclusive": updated_after}]}
    if endpoint.operation == "ListMembers":
        payload["onlyAssociated"] = False
    if endpoint.operation == "ListCisScans":
        payload["sortBy"] = "SCAN_START_DATE"
        payload["sortOrder"] = "ASC"
        if updated_after is not None:
            payload["filterCriteria"] = {"scanAtFilters": [{"earliestScanStartTime": updated_after}]}
    if endpoint.operation == "ListCisScanResultsAggregatedByTargetResource":
        payload["sortBy"] = "RESOURCE_ID"
        payload["sortOrder"] = "ASC"
    if endpoint.operation == "GetCisScanResultDetails":
        payload["sortBy"] = "CHECK_ID"
        payload["sortOrder"] = "ASC"
    return payload


def next_page_token(body: dict[str, Any], current: str | None) -> str | None:
    token = body.get("nextToken") or None
    if token is not None and (not isinstance(token, str) or token == current):
        raise ValueError("AWS Inspector returned an invalid pagination token.")
    return token


def fetch_page(
    client: AwsInspectorClient, endpoint: AwsInspectorEndpoint, payload: dict[str, Any], token: str | None
) -> tuple[list[dict[str, Any]], str | None]:
    body = client.request(endpoint, {**payload, "nextToken": token} if token else payload)
    return list(body.get(endpoint.result_key) or []), next_page_token(body, token)


def normalize_row(endpoint: AwsInspectorEndpoint, item: dict[str, Any], region: str) -> dict[str, Any]:
    row = {_CAMEL_BOUNDARY.sub("_", key).lower(): value for key, value in item.items()}
    for column in endpoint.timestamp_columns:
        if row.get(column) is not None:
            row[column] = dt.datetime.fromtimestamp(timestamp(row[column]), tz=dt.UTC)
    row["region"] = region
    return row


def get_rows(
    config: AwsInspectorSourceConfig,
    endpoint: AwsInspectorEndpoint,
    manager: ResumableSourceManager[AwsInspectorResumeConfig],
    updated_after: float | None,
    api_version: str,
) -> Iterator[list[dict[str, Any]]]:
    state = manager.load_state() if manager.can_resume() else None
    if state is not None and state.completed:
        return
    next_token = state.next_token if state else None
    payload = request_payload(endpoint, state.updated_after if state else updated_after)
    client = AwsInspectorClient(config, api_version)
    try:
        while True:
            request_body = dict(payload)
            if next_token:
                request_body["nextToken"] = next_token
            body = client.request(endpoint, request_body)
            rows = [normalize_row(endpoint, item, config.region) for item in body.get(endpoint.result_key, [])]
            token = next_page_token(body, next_token)
            manager.save_state(
                AwsInspectorResumeConfig(
                    next_token=token,
                    updated_after=state.updated_after if state else updated_after,
                    completed=token is None,
                )
            )
            if rows:
                yield rows
            manager.safe_point()
            if token is None:
                break
            next_token = token
    finally:
        client.close()


def fan_out(
    client: AwsInspectorClient,
    endpoint: AwsInspectorEndpoint,
    parent_payload: dict[str, Any],
    key_of: Callable[[dict[str, Any]], str],
    child_payload: Callable[[dict[str, Any]], dict[str, Any]],
    parent_fields: Callable[[dict[str, Any]], dict[str, Any]],
    region: str,
    position: FanOutPosition,
    stage: Callable[[FanOutPosition | None], None],
    manager: ResumableSourceManager[AwsInspectorResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Walk the parent listing and call `endpoint` once for each parent, from `position` on.

    `stage` receives the position after each child page, or `None` once the walk is complete.
    """
    if endpoint.parent is None:
        raise ValueError(f"AWS Inspector table has no parent listing: {endpoint.operation}")
    parent_token, resume_key, resume_token = position.parent_token, position.parent_key, position.next_token
    while True:
        parents, next_parent_token = fetch_page(client, endpoint.parent, parent_payload, parent_token)
        manager.safe_point()
        keys = [key_of(parent) for parent in parents]
        start = keys.index(resume_key) if resume_key in keys else 0
        if resume_key not in keys:
            resume_token = None
        resume_key = None
        for index in range(start, len(parents)):
            token, resume_token = resume_token, None
            payload = {**request_payload(endpoint), **child_payload(parents[index])}
            while True:
                items, next_token = fetch_page(client, endpoint, payload, token)
                if next_token is not None:
                    stage(FanOutPosition(parent_token=parent_token, parent_key=keys[index], next_token=next_token))
                elif index + 1 < len(parents):
                    stage(FanOutPosition(parent_token=parent_token, parent_key=keys[index + 1]))
                elif next_parent_token is not None:
                    stage(FanOutPosition(parent_token=next_parent_token))
                else:
                    stage(None)
                fields = parent_fields(parents[index])
                rows = [normalize_row(endpoint, {**item, **fields}, region) for item in items]
                if rows:
                    yield rows
                manager.safe_point()
                if next_token is None:
                    break
                token = next_token
        if next_parent_token is None:
            return
        parent_token = next_parent_token


def list_cis_scans(
    client: AwsInspectorClient,
    manager: ResumableSourceManager[AwsInspectorResumeConfig],
    scans_after: float | None,
    incremental: bool,
) -> list[dict[str, Any]]:
    payload = request_payload(CIS_SCANS_ENDPOINT, scans_after)
    scans: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        items, token = fetch_page(client, CIS_SCANS_ENDPOINT, payload, token)
        scans.extend(item for item in items if item.get("scanArn") and item.get("scanDate") is not None)
        manager.safe_point()
        if token is None:
            break
    if incremental:
        # The watermark is the latest scan date synced, so an unfinished scan would be skipped for good
        # once a later scan finishes. Stop before the earliest unfinished scan until it finishes.
        unfinished = [timestamp(scan["scanDate"]) for scan in scans if scan.get("status") == "IN_PROGRESS"]
        if unfinished:
            scans = [scan for scan in scans if timestamp(scan["scanDate"]) < min(unfinished)]
    return sorted(scans, key=lambda scan: (timestamp(scan["scanDate"]), scan["scanArn"]))


def get_cis_scan_result_details(
    config: AwsInspectorSourceConfig,
    endpoint: AwsInspectorEndpoint,
    manager: ResumableSourceManager[AwsInspectorResumeConfig],
    scans_after: float | None,
    incremental: bool,
    api_version: str,
) -> Iterator[list[dict[str, Any]]]:
    state = manager.load_state() if manager.can_resume() else None
    if state is not None and state.completed:
        return
    scans_after = state.updated_after if state else scans_after
    client = AwsInspectorClient(config, api_version)
    try:
        scans = list_cis_scans(client, manager, scans_after, incremental)
        arns = [scan["scanArn"] for scan in scans]
        resumed = state is not None and state.scan_arn in arns
        start = arns.index(state.scan_arn) if state is not None and resumed else 0
        for index in range(start, len(scans)):
            scan = scans[index]
            position = (
                FanOutPosition(
                    parent_token=state.parent_token, parent_key=state.parent_key, next_token=state.next_token
                )
                if state is not None and resumed and index == start
                else FanOutPosition()
            )

            def stage(next_position: FanOutPosition | None, index: int = index) -> None:
                if next_position is not None:
                    resume = AwsInspectorResumeConfig(
                        updated_after=scans_after,
                        scan_arn=arns[index],
                        parent_token=next_position.parent_token,
                        parent_key=next_position.parent_key,
                        next_token=next_position.next_token,
                    )
                elif index + 1 < len(arns):
                    resume = AwsInspectorResumeConfig(updated_after=scans_after, scan_arn=arns[index + 1])
                else:
                    resume = AwsInspectorResumeConfig(updated_after=scans_after, completed=True)
                manager.save_state(resume)

            def child_payload(target: dict[str, Any], scan_arn: str = arns[index]) -> dict[str, Any]:
                return {
                    "scanArn": scan_arn,
                    "targetResourceId": target.get("targetResourceId"),
                    "accountId": target.get("accountId"),
                }

            def parent_fields(target: dict[str, Any], scan: dict[str, Any] = scan) -> dict[str, Any]:
                return {
                    "scanArn": scan["scanArn"],
                    "scanDate": scan["scanDate"],
                    "accountId": target.get("accountId"),
                    "targetResourceId": target.get("targetResourceId"),
                }

            yield from fan_out(
                client,
                endpoint,
                {**request_payload(CIS_SCAN_TARGETS_ENDPOINT), "scanArn": scan["scanArn"]},
                key_of=lambda target: f"{target.get('accountId')}/{target.get('targetResourceId')}",
                child_payload=child_payload,
                parent_fields=parent_fields,
                region=config.region,
                position=position,
                stage=stage,
                manager=manager,
            )
    finally:
        client.close()


def get_clusters_for_image(
    config: AwsInspectorSourceConfig,
    endpoint: AwsInspectorEndpoint,
    manager: ResumableSourceManager[AwsInspectorResumeConfig],
    api_version: str,
) -> Iterator[list[dict[str, Any]]]:
    state = manager.load_state() if manager.can_resume() else None
    if state is not None and state.completed:
        return
    position = (
        FanOutPosition(parent_token=state.parent_token, parent_key=state.parent_key, next_token=state.next_token)
        if state is not None
        else FanOutPosition()
    )

    def stage(next_position: FanOutPosition | None) -> None:
        manager.save_state(
            AwsInspectorResumeConfig(
                parent_token=next_position.parent_token,
                parent_key=next_position.parent_key,
                next_token=next_position.next_token,
            )
            if next_position is not None
            else AwsInspectorResumeConfig(completed=True)
        )

    assert endpoint.parent is not None
    client = AwsInspectorClient(config, api_version)
    try:
        yield from fan_out(
            client,
            endpoint,
            {**request_payload(endpoint.parent), "filterCriteria": ECR_IMAGE_COVERAGE_FILTER},
            key_of=lambda image: str(image.get("resourceId")),
            child_payload=lambda image: {"filter": {"resourceId": image.get("resourceId")}},
            parent_fields=lambda image: {"resourceId": image.get("resourceId")},
            region=config.region,
            position=position,
            stage=stage,
            manager=manager,
        )
    finally:
        client.close()


def validate_credentials(
    config: AwsInspectorSourceConfig,
    schema_name: str | None = None,
    api_version: str = INSPECTOR_API_VERSION,
) -> tuple[bool, str | None]:
    endpoint = AWS_INSPECTOR_ENDPOINTS.get(schema_name or "findings")
    if endpoint is None:
        return False, f"Unknown AWS Inspector table: {schema_name}"
    probe = endpoint
    while probe.parent is not None:
        probe = probe.parent
    try:
        client = AwsInspectorClient(config, api_version)
    except ValueError as error:
        return False, str(error)
    payload = request_payload(probe)
    if probe.page_size is not None:
        payload["maxResults"] = 1
    try:
        client.request(probe, payload)
    except AwsInspectorError as error:
        if error.code.startswith("AccessDenied") or error.code == "HTTP 403":
            if schema_name is None:
                return True, None
            return False, f"Grant {', '.join(endpoint.iam_actions)} to read this table."
        message = error_message(error) or probe_status_message("AWS Inspector", error.status_code)
        if message:
            return False, message
        raise
    finally:
        client.close()
    return True, None


def aws_inspector_source(
    config: AwsInspectorSourceConfig,
    endpoint: str,
    manager: ResumableSourceManager[AwsInspectorResumeConfig],
    should_use_incremental_field: bool,
    last_value: dt.datetime | str | int | float | None,
    api_version: str = INSPECTOR_API_VERSION,
) -> SourceResponse:
    endpoint_config = AWS_INSPECTOR_ENDPOINTS.get(endpoint)
    if endpoint_config is None:
        raise ValueError(f"Unknown AWS Inspector table: {endpoint}")
    updated_after = (
        timestamp(last_value)
        if endpoint in INCREMENTAL_FIELDS and should_use_incremental_field and last_value is not None
        else None
    )
    items: Callable[[], Iterator[list[dict[str, Any]]]]
    if endpoint_config.operation == "GetCisScanResultDetails":
        items = lambda: get_cis_scan_result_details(
            config, endpoint_config, manager, updated_after, should_use_incremental_field, api_version
        )
    elif endpoint_config.operation == "GetClustersForImage":
        items = lambda: get_clusters_for_image(config, endpoint_config, manager, api_version)
    else:
        items = lambda: get_rows(config, endpoint_config, manager, updated_after, api_version)
    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=list(endpoint_config.primary_keys),
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        # Inspector filters by updatedAt but cannot sort by it.
        # "desc" saves the watermark once at job end, so unordered rows cannot strand older ones.
        sort_mode="desc",
        on_complete=manager.clear_state,
    )
