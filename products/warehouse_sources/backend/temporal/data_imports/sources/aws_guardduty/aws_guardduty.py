import re
import datetime as dt
from collections.abc import Iterator
from dataclasses import field, replace
from typing import Any
from urllib.parse import urlencode

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from botocore.serialize import create_serializer
from botocore.session import get_session
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_guardduty.settings import (
    ENDPOINTS,
    ERROR_MESSAGES,
    GUARDDUTY_API_VERSION,
    MAX_RESULTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsguardduty import (
    AwsGuarddutySourceConfig,
)

TRANSPORT_RETRY = BoundedRetry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET", "POST"}),
    raise_on_status=False,
)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_REGION = re.compile(r"(?:us|eu|ap|sa|ca|me|af|il|mx|cn)-(?:gov-)?[a-z]+-\d+")
_SORT_CRITERIA = {"AttributeName": "updatedAt", "OrderBy": "ASC"}


@frozen
class AwsGuarddutyResumeConfig:
    detector_ids: list[str] = field(default_factory=list)
    next_token: str | None = None
    updated_since_ms: int | None = None


class AwsGuarddutyError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"AWS GuardDuty request failed: {code} - {message}")


class AwsGuarddutyThrottledError(AwsGuarddutyError):
    pass


def error_for_response(response: requests.Response) -> AwsGuarddutyError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw_code = response.headers.get("x-amzn-ErrorType") or body.get("__type") or body.get("code")
    code = str(raw_code or ("AccessDenied" if response.status_code == 403 else f"HTTP {response.status_code}"))
    code = code.split(":")[0].split("#")[-1]
    message = str(body.get("message") or body.get("Message") or response.reason or "AWS request failed")[:500]
    lower_message = message.lower()
    if "not subscribed" in lower_message or (
        "subscription" in lower_message and any(word in lower_message for word in ("required", "subscribe", "not"))
    ):
        code = "SubscriptionRequiredException"
    # HTTP status retries belong to the tracked session; only body-level throttles need this retry.
    error_class = (
        AwsGuarddutyThrottledError
        if response.status_code == 400 and code in {"ThrottlingException", "TooManyRequestsException"}
        else AwsGuarddutyError
    )
    return error_class(code, message)


class AwsGuarddutyClient:
    def __init__(self, config: AwsGuarddutySourceConfig, api_version: str) -> None:
        if not config.aws_access_key_id or not config.aws_secret_access_key:
            raise ValueError("Enter both an AWS access key ID and a secret access key.")
        if not _REGION.fullmatch(config.aws_region):
            raise ValueError("Enter a valid AWS region, such as us-east-1.")
        if api_version != GUARDDUTY_API_VERSION:
            raise ValueError(f"Unsupported AWS GuardDuty API version: {api_version}")
        self.region = config.aws_region
        suffix = "amazonaws.com.cn" if self.region.startswith("cn-") else "amazonaws.com"
        self.base_url = f"https://guardduty.{self.region}.{suffix}"
        # Pin the REST serializer to the service model because GuardDuty has no versioned URL or target header.
        self._model = get_session().get_service_model("guardduty", api_version=api_version)
        self._serializer = create_serializer(self._model.metadata["protocol"])
        self._signer = SigV4Auth(
            Credentials(config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token or None),
            "guardduty",
            self.region,
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

    @retry(
        retry=retry_if_exception_type(AwsGuarddutyThrottledError),
        stop=stop_after_attempt(4),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        serialized = self._serializer.serialize_to_request(payload, self._model.operation_model(operation))
        url = self.base_url + serialized["url_path"]
        if serialized["query_string"]:
            url += "?" + urlencode(serialized["query_string"])
        request = AWSRequest(
            method=serialized["method"], url=url, data=serialized["body"], headers=serialized["headers"]
        )
        self._signer.add_auth(request)
        response = self._session.request(
            serialized["method"],
            url,
            data=serialized["body"],
            headers=dict(request.headers),
            timeout=60,
            allow_redirects=False,
        )
        if response.status_code >= 300:
            raise error_for_response(response)
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("AWS GuardDuty returned an invalid response.")
        return body

    def detector_ids(self) -> Iterator[str]:
        token: str | None = None
        seen_tokens: set[str] = set()
        while True:
            payload: dict[str, Any] = {"MaxResults": MAX_RESULTS}
            if token:
                payload["NextToken"] = token
            body = self.request("ListDetectors", payload)
            yield from body.get("detectorIds", [])
            next_token = body.get("nextToken")
            if not next_token:
                return
            if next_token in seen_tokens:
                raise ValueError("AWS GuardDuty repeated a page token.")
            seen_tokens.add(next_token)
            token = next_token


def normalize_row(item: dict[str, Any], detector_id: str, region: str) -> dict[str, Any]:
    row = {_CAMEL_BOUNDARY.sub("_", key).lower(): value for key, value in item.items()}
    row["source_detector_id"] = detector_id
    row["region"] = region
    for column in ("created_at", "updated_at", "invited_at"):
        value = row.get(column)
        if isinstance(value, str) and value:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            row[column] = parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
    return row


def watermark_milliseconds(value: dt.datetime | str | None) -> int | None:
    if value is None:
        return None
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return int(parsed.timestamp() * 1000)


def get_rows(
    config: AwsGuarddutySourceConfig,
    endpoint: str,
    api_version: str,
    manager: ResumableSourceManager[AwsGuarddutyResumeConfig],
    updated_since: dt.datetime | str | None,
) -> Iterator[list[dict[str, Any]]]:
    endpoint_config = schema_for_resource(ENDPOINTS, endpoint)
    client = AwsGuarddutyClient(config, api_version)
    try:
        state = manager.load_state() if manager.can_resume() else None
        if state is None:
            state = AwsGuarddutyResumeConfig(
                detector_ids=list(client.detector_ids()),
                updated_since_ms=watermark_milliseconds(updated_since) if endpoint == "findings" else None,
            )
        seen_tokens = {state.next_token} if state.next_token else set()
        while state.detector_ids:
            detector_id = state.detector_ids[0]
            payload: dict[str, Any] = {"DetectorId": detector_id}
            if endpoint_config.result_key:
                payload["MaxResults"] = MAX_RESULTS
                if state.next_token:
                    payload["NextToken"] = state.next_token
            if endpoint == "findings":
                payload["SortCriteria"] = _SORT_CRITERIA
                if state.updated_since_ms is not None:
                    payload["FindingCriteria"] = {
                        "Criterion": {"updatedAt": {"GreaterThanOrEqual": state.updated_since_ms}}
                    }
            elif endpoint == "members":
                payload["OnlyAssociated"] = "false"
            body = client.request(endpoint_config.operation, payload)
            next_token = body.get("nextToken")
            if next_token and next_token in seen_tokens:
                raise ValueError("AWS GuardDuty repeated a page token.")
            if next_token:
                seen_tokens.add(next_token)
            else:
                seen_tokens.clear()
            if endpoint == "findings":
                finding_ids = body.get("findingIds", [])
                items = []
                if finding_ids:
                    findings = client.request(
                        "GetFindings",
                        {"DetectorId": detector_id, "FindingIds": finding_ids, "SortCriteria": _SORT_CRITERIA},
                    )
                    items = findings.get("findings", [])
            elif endpoint_config.result_key:
                items = body.get(endpoint_config.result_key, [])
            else:
                items = [body]
            rows = [normalize_row(item, detector_id, client.region) for item in items]
            if rows:
                yield rows
            state = replace(
                state,
                detector_ids=state.detector_ids if next_token else state.detector_ids[1:],
                next_token=next_token or None,
            )
            manager.save_state(state)
            manager.safe_point()
    finally:
        client.close()


def permission_message(error: AwsGuarddutyError, schema_name: str | None) -> str | None:
    if error.code in {"AccessDenied", "AccessDeniedException", "ForbiddenException"}:
        actions = ENDPOINTS[schema_name].iam_actions if schema_name else ("guardduty:ListDetectors",)
        return "AWS denied access. Required IAM permissions: " + ", ".join(actions) + "."
    for code, message in ERROR_MESSAGES.items():
        if error.code.startswith(code):
            return message
    return None


def validate_credentials(
    config: AwsGuarddutySourceConfig, api_version: str, schema_name: str | None = None
) -> tuple[bool, str | None]:
    if schema_name is not None and schema_name not in ENDPOINTS:
        return False, f"Unknown GuardDuty table: {schema_name}"
    try:
        client = AwsGuarddutyClient(config, api_version)
    except ValueError as error:
        return False, str(error)
    try:
        body = client.request("ListDetectors", {"MaxResults": 1})
        if schema_name:
            detector_id = next(iter(body.get("detectorIds", [])), None)
            if detector_id is None:
                return False, "Enable GuardDuty in the selected AWS region, then reconnect."
            endpoint = ENDPOINTS[schema_name]
            payload: dict[str, Any] = {"DetectorId": detector_id}
            if endpoint.result_key:
                payload["MaxResults"] = 1
            if schema_name == "members":
                payload["OnlyAssociated"] = "false"
            body = client.request(endpoint.operation, payload)
            if schema_name == "findings" and body.get("findingIds"):
                client.request("GetFindings", {"DetectorId": detector_id, "FindingIds": body["findingIds"]})
        return True, None
    except AwsGuarddutyError as error:
        if schema_name is None and error.code in {"AccessDenied", "AccessDeniedException", "ForbiddenException"}:
            return True, None
        message = permission_message(error, schema_name)
        if message:
            return False, message
        raise
    finally:
        client.close()


def aws_guardduty_source(
    config: AwsGuarddutySourceConfig,
    endpoint: str,
    api_version: str,
    manager: ResumableSourceManager[AwsGuarddutyResumeConfig],
    updated_since: dt.datetime | str | None,
) -> SourceResponse:
    endpoint_config = schema_for_resource(ENDPOINTS, endpoint)
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(config, endpoint, api_version, manager, updated_since),
        primary_keys=list(endpoint_config.primary_keys),
        # Findings can change between listing IDs and retrieving details, so global ordering is not guaranteed.
        # "desc" saves the watermark once at job end, so unordered rows cannot strand older ones.
        sort_mode="desc",
        partition_keys=["created_at"] if endpoint == "findings" else None,
        partition_mode="datetime" if endpoint == "findings" else None,
        partition_format="month" if endpoint == "findings" else None,
        on_complete=manager.clear_state,
    )
