from __future__ import annotations

import re
import datetime as dt
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from botocore.serialize import create_serializer
from botocore.session import Session

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_security_hub.settings import (
    ACCESS_DENIED_CODES,
    ENDPOINTS,
    ERROR_MESSAGES,
    SECURITY_HUB_API_VERSION,
    SUBSCRIPTION_MESSAGE,
    SecurityHubEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssecurityhub import (
        AwsSecurityHubSourceConfig,
    )

TRANSPORT_RETRY = BoundedRetry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET", "POST"}),
    raise_on_status=False,
)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


@frozen
class AwsSecurityHubResumeConfig:
    next_token: str | None = None
    updated_after: str | None = None
    finished: bool = False
    parent_id: str | None = None


class AwsSecurityHubError(Exception):
    def __init__(self, code: str, message: str, operation: str = "") -> None:
        self.code = code
        self.message = message
        self.operation = operation
        super().__init__(f"AWS Security Hub request failed: {code} - {message}")

    def user_message(self) -> str:
        if "not subscribed" in self.message.lower() or self.code == "SubscriptionRequiredException":
            return SUBSCRIPTION_MESSAGE
        if self.code in ACCESS_DENIED_CODES:
            return (
                f"Grant securityhub:{self.operation} to this IAM user or role. Check that Security Hub CSPM is enabled."
            )
        return ERROR_MESSAGES.get(self.code, "AWS Security Hub rejected the request. Check the connection settings.")


class AwsSecurityHubClient:
    def __init__(self, config: AwsSecurityHubSourceConfig, api_version: str) -> None:
        if api_version != SECURITY_HUB_API_VERSION:
            raise ValueError(f"Unsupported AWS Security Hub API version: {api_version}")
        if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", config.region):
            raise ValueError("Enter a valid AWS region, such as us-east-1.")
        suffix = "amazonaws.com.cn" if config.region.startswith("cn-") else "amazonaws.com"
        self.base_url = f"https://securityhub.{config.region}.{suffix}"
        # REST-JSON has no version path. The pinned model defines the request paths and fields.
        self.model = Session().get_service_model("securityhub", api_version=api_version)
        self.serializer = create_serializer(self.model.metadata["protocol"])
        self.signer = SigV4Auth(
            Credentials(config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token or None),
            "securityhub",
            config.region,
        )
        self.session = make_tracked_session(
            retry=TRANSPORT_RETRY,
            redact_values=tuple(
                value
                for value in (config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token)
                if value
            ),
        )

    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        serialized = self.serializer.serialize_to_request(payload, self.model.operation_model(operation))
        url = self.base_url + serialized["url_path"]
        if serialized["query_string"]:
            url += "?" + urlencode(serialized["query_string"], doseq=True)
        body = serialized["body"]
        request = AWSRequest(method=serialized["method"], url=url, data=body, headers=serialized["headers"])
        self.signer.add_auth(request)
        response = self.session.request(
            serialized["method"], url, data=body, headers=dict(request.headers), timeout=60, allow_redirects=False
        )
        if response.status_code >= 400:
            try:
                error = response.json()
            except ValueError:
                error = {}
            if not isinstance(error, dict):
                error = {}
            raw_code = response.headers.get("x-amzn-ErrorType") or error.get("__type") or error.get("code")
            code = str(raw_code or f"HTTP {response.status_code}").split(":")[0].rsplit("#", 1)[-1]
            message = str(error.get("message") or error.get("Message") or response.reason)[:500]
            if "not subscribed" in message.lower():
                code = "SubscriptionRequiredException"
            raise AwsSecurityHubError(code, message, operation)
        response.raise_for_status()
        return response.json()


def normalize_row(item: dict[str, Any]) -> dict[str, Any]:
    row = {_CAMEL_BOUNDARY.sub("_", key).lower(): value for key, value in item.items()}
    for key in (
        "created_at",
        "updated_at",
        "first_observed_at",
        "last_observed_at",
        "processed_at",
        "invited_at",
        "control_status_updated_at",
    ):
        if isinstance(row.get(key), str):
            timestamp = dt.datetime.fromisoformat(row[key].replace("Z", "+00:00"))
            row[key] = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=dt.UTC)
    return row


def get_rows(
    config: AwsSecurityHubSourceConfig,
    endpoint: str,
    api_version: str,
    manager: ResumableSourceManager[AwsSecurityHubResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: object,
) -> Iterator[list[dict[str, Any]]]:
    endpoint_config = ENDPOINTS[endpoint]
    state = manager.load_state() if manager.can_resume() else None
    if state and state.finished:
        return
    updated_after = None
    if endpoint == "findings" and should_use_incremental_field and db_incremental_field_last_value is not None:
        value = db_incremental_field_last_value
        timestamp = (
            value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
        updated_after = (timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=dt.UTC)).isoformat()
    if state:
        updated_after = state.updated_after
    client = AwsSecurityHubClient(config, api_version)
    try:
        filters: dict[str, Any] = {}
        if endpoint == "findings":
            filters["SortCriteria"] = [{"Field": "UpdatedAt", "SortOrder": "asc"}]
            if updated_after:
                filters["Filters"] = {"UpdatedAt": [{"Start": updated_after}]}
        parent_ids: list[str | None] = [None]
        parent_field = None
        if endpoint_config.parent:
            parent_name, parent_field = endpoint_config.parent
            found: set[str] = set()
            for items, _ in _pages(client, ENDPOINTS[parent_name], None, {}):
                found.update(item[parent_field] for item in items if item.get(parent_field))
                manager.safe_point()
            resume_from = state.parent_id if state and state.parent_id else ""
            # Sorted so a resumed run can skip the parents an earlier attempt finished.
            parent_ids = [parent_id for parent_id in sorted(found) if parent_id >= resume_from]
        start_token = state.next_token if state and parent_ids and parent_ids[0] == state.parent_id else None
        for index, parent_id in enumerate(parent_ids):
            path_params = {parent_field: parent_id} if parent_field else {}
            next_parent = parent_ids[index + 1] if index + 1 < len(parent_ids) else None
            pages = _pages(client, endpoint_config, start_token, {**filters, **path_params})
            start_token = None
            for items, token in pages:
                rows = [normalize_row({**path_params, **item}) for item in items]
                manager.save_state(
                    AwsSecurityHubResumeConfig(
                        next_token=token,
                        updated_after=updated_after,
                        finished=token is None and next_parent is None,
                        parent_id=parent_id if token else next_parent,
                    )
                )
                if rows:
                    yield rows
                manager.safe_point()
    finally:
        client.session.close()


def _pages(
    client: AwsSecurityHubClient, endpoint: SecurityHubEndpoint, token: str | None, extra: dict[str, Any]
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    while True:
        payload: dict[str, Any] = {"MaxResults": endpoint.page_size, **dict(endpoint.params), **extra}
        if token:
            payload["NextToken"] = token
        result = client.request(endpoint.operation, payload)
        token = result.get("NextToken") or None
        yield result.get(endpoint.result_key) or [], token
        if token is None:
            return


def _probe(client: AwsSecurityHubClient, endpoint: SecurityHubEndpoint) -> None:
    path_params: dict[str, Any] = {}
    if endpoint.parent:
        parent_name, parent_field = endpoint.parent
        parent = ENDPOINTS[parent_name]
        items = client.request(parent.operation, {"MaxResults": 1}).get(parent.result_key) or []
        if not items:
            return
        path_params[parent_field] = items[0][parent_field]
    client.request(endpoint.operation, {"MaxResults": 1, **path_params})


def validate_credentials(
    config: AwsSecurityHubSourceConfig, api_version: str, schema_name: str | None = None
) -> tuple[bool, str | None]:
    if not config.aws_access_key_id or not config.aws_secret_access_key:
        return False, "Enter both an AWS access key ID and a secret access key."
    endpoint = ENDPOINTS.get(schema_name or "findings")
    if endpoint is None:
        return False, f"Unknown AWS Security Hub table: {schema_name}"
    try:
        client = AwsSecurityHubClient(config, api_version)
        try:
            _probe(client, endpoint)
        finally:
            client.session.close()
    except AwsSecurityHubError as error:
        if schema_name is None and error.code in ACCESS_DENIED_CODES and "not subscribed" not in error.message.lower():
            return True, None
        return False, error.user_message()
    except ValueError as error:
        return False, str(error)
    except requests.RequestException:
        return False, "Could not reach AWS Security Hub. Try again."
    return True, None


def probe_endpoint_permissions(
    config: AwsSecurityHubSourceConfig, api_version: str, endpoints: list[str]
) -> dict[str, str | None]:
    client = AwsSecurityHubClient(config, api_version)
    permissions: dict[str, str | None] = dict.fromkeys(endpoints)
    try:
        for name in endpoints:
            endpoint = ENDPOINTS.get(name)
            if endpoint is None:
                continue
            try:
                _probe(client, endpoint)
            except AwsSecurityHubError as error:
                if error.code in ERROR_MESSAGES:
                    permissions[name] = error.user_message()
            except requests.RequestException:
                continue
    finally:
        client.session.close()
    return permissions


def aws_security_hub_source(
    config: AwsSecurityHubSourceConfig,
    endpoint: str,
    api_version: str,
    manager: ResumableSourceManager[AwsSecurityHubResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: object,
) -> SourceResponse:
    endpoint_config = ENDPOINTS[endpoint]
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            config, endpoint, api_version, manager, should_use_incremental_field, db_incremental_field_last_value
        ),
        primary_keys=list(endpoint_config.primary_keys),
        sort_mode="asc" if endpoint == "findings" else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        on_complete=manager.clear_state,
    )
