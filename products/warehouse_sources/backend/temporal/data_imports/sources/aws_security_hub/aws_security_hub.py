from __future__ import annotations

import re
import json
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
    INCREMENTAL_FIELDS,
    SECURITY_HUB_API_VERSION,
    SUBSCRIPTION_MESSAGE,
    UNMODELED_OPERATION_PATHS,
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
_UNORDERED_INCREMENTAL = frozenset({"finding_history", "findings_v2"})
# CreatedAt never changes, so a finding keeps its position while the walk pages through findings.
_FINDING_HISTORY_PARENT_SORT = [{"Field": "CreatedAt", "SortOrder": "asc"}]


@frozen
class AwsSecurityHubResumeConfig:
    next_token: str | None = None
    updated_after: str | None = None
    finished: bool = False
    parent_id: str | None = None
    parent_token: str | None = None
    cutoff: str | None = None


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

    def serialize(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if operation in self.model.operation_names:
            return self.serializer.serialize_to_request(payload, self.model.operation_model(operation))
        return {
            "method": "POST",
            "url_path": UNMODELED_OPERATION_PATHS[operation],
            "query_string": {},
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload).encode(),
        }

    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        serialized = self.serialize(operation, payload)
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
        "update_time",
        "created_time",
        "modified_time",
        "resource_creation_time_dt",
        "resource_detail_capture_time_dt",
    ):
        if isinstance(row.get(key), str):
            timestamp = dt.datetime.fromisoformat(row[key].replace("Z", "+00:00"))
            row[key] = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=dt.UTC)
    return row


def _prepare(endpoint: str, item: dict[str, Any]) -> dict[str, Any]:
    if endpoint == "finding_history":
        record = dict(item)
        identifier = record.pop("FindingIdentifier", None) or {}
        return {"ProductArn": identifier.get("ProductArn"), "FindingId": identifier.get("Id"), **record}
    if endpoint == "findings_v2":
        # OCSF findings nest their identity and timestamps, so copy them to top-level columns for keys and syncs.
        info = item.get("finding_info") or {}
        product = (item.get("metadata") or {}).get("product") or {}
        return {
            **item,
            "product_uid": product.get("uid"),
            "finding_uid": info.get("uid"),
            "created_time": info.get("created_time_dt"),
            "modified_time": info.get("modified_time_dt"),
        }
    return item


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
    if endpoint in INCREMENTAL_FIELDS and should_use_incremental_field and db_incremental_field_last_value is not None:
        value = db_incremental_field_last_value
        timestamp = (
            value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
        updated_after = (timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=dt.UTC)).isoformat()
    cutoff = None
    if endpoint in _UNORDERED_INCREMENTAL and should_use_incremental_field:
        # A row that changes mid-run sits below the run's highest value, so the next run would skip it.
        # An upper bound keeps every change after the cutoff for the next run.
        cutoff = dt.datetime.now(dt.UTC).isoformat()
    if state:
        updated_after = state.updated_after
        cutoff = state.cutoff
    client = AwsSecurityHubClient(config, api_version)
    try:
        if endpoint == "finding_history":
            yield from _finding_history_rows(client, manager, state, updated_after, cutoff)
            return
        filters: dict[str, Any] = {}
        if endpoint == "findings":
            filters["SortCriteria"] = [{"Field": "UpdatedAt", "SortOrder": "asc"}]
            if updated_after:
                filters["Filters"] = {"UpdatedAt": [{"Start": updated_after}]}
        if endpoint == "findings_v2" and cutoff:
            window = {"End": cutoff, **({"Start": updated_after} if updated_after else {})}
            date_filter = {"FieldName": "finding_info.modified_time_dt", "Filter": window}
            filters["Filters"] = {"CompositeFilters": [{"DateFilters": [date_filter]}]}
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
                rows = [normalize_row(_prepare(endpoint, {**path_params, **item})) for item in items]
                manager.save_state(
                    AwsSecurityHubResumeConfig(
                        next_token=token,
                        updated_after=updated_after,
                        cutoff=cutoff,
                        finished=token is None and next_parent is None,
                        parent_id=parent_id if token else next_parent,
                    )
                )
                if rows:
                    yield rows
                manager.safe_point()
    finally:
        client.session.close()


def _finding_history_rows(
    client: AwsSecurityHubClient,
    manager: ResumableSourceManager[AwsSecurityHubResumeConfig],
    state: AwsSecurityHubResumeConfig | None,
    start_time: str | None,
    cutoff: str | None,
) -> Iterator[list[dict[str, Any]]]:
    history = ENDPOINTS["finding_history"]
    extra = {key: value for key, value in (("StartTime", start_time), ("EndTime", cutoff)) if value}
    parent_token = state.parent_token if state else None
    resume_from = state.parent_id if state else None
    start_token = state.next_token if state else None
    while True:
        payload: dict[str, Any] = {"MaxResults": 100, "SortCriteria": _FINDING_HISTORY_PARENT_SORT}
        if parent_token:
            payload["NextToken"] = parent_token
        result = client.request("GetFindings", payload)
        next_parent_token = result.get("NextToken") or None
        identifiers = [
            {"Id": finding["Id"], "ProductArn": finding["ProductArn"]}
            for finding in result.get("Findings") or []
            if finding.get("Id") and finding.get("ProductArn")
        ]
        keys = [_finding_key(identifier) for identifier in identifiers]
        if resume_from in keys:
            identifiers = identifiers[keys.index(resume_from) :]
            keys = keys[keys.index(resume_from) :]
        else:
            start_token = None
        resume_from = None
        if not identifiers:
            manager.save_state(
                AwsSecurityHubResumeConfig(
                    updated_after=start_time,
                    cutoff=cutoff,
                    parent_token=next_parent_token,
                    finished=next_parent_token is None,
                )
            )
            manager.safe_point()
        for index, identifier in enumerate(identifiers):
            next_key = keys[index + 1] if index + 1 < len(keys) else None
            pages = _pages(client, history, start_token, {"FindingIdentifier": identifier, **extra})
            start_token = None
            for records, token in pages:
                rows = [normalize_row(_prepare("finding_history", record)) for record in records]
                if token or next_key:
                    next_state = AwsSecurityHubResumeConfig(
                        updated_after=start_time,
                        cutoff=cutoff,
                        parent_token=parent_token,
                        parent_id=keys[index] if token else next_key,
                        next_token=token,
                    )
                else:
                    next_state = AwsSecurityHubResumeConfig(
                        updated_after=start_time,
                        cutoff=cutoff,
                        parent_token=next_parent_token,
                        finished=next_parent_token is None,
                    )
                manager.save_state(next_state)
                if rows:
                    yield rows
                manager.safe_point()
        if next_parent_token is None:
            return
        parent_token = next_parent_token


def _finding_key(identifier: dict[str, str]) -> str:
    return f"{identifier['ProductArn']}\n{identifier['Id']}"


def _items(endpoint: SecurityHubEndpoint, result: dict[str, Any]) -> list[dict[str, Any]]:
    items = result.get(endpoint.result_key) or []
    if isinstance(items, dict):
        # GetInsightResults returns one object with the grouped counts nested inside it.
        group_by = items.get("GroupByAttribute")
        return [{"GroupByAttribute": group_by, **value} for value in items.get("ResultValues") or []]
    return items


def _pages(
    client: AwsSecurityHubClient, endpoint: SecurityHubEndpoint, token: str | None, extra: dict[str, Any]
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    while True:
        payload: dict[str, Any] = {**dict(endpoint.params), **extra}
        if endpoint.page_size:
            payload["MaxResults"] = endpoint.page_size
        if token:
            payload["NextToken"] = token
        result = client.request(endpoint.operation, payload)
        token = result.get("NextToken") or None
        yield _items(endpoint, result), token
        if token is None:
            return


def _probe(client: AwsSecurityHubClient, endpoint: SecurityHubEndpoint) -> None:
    path_params: dict[str, Any] = {}
    if endpoint.operation == "GetFindingHistory":
        findings = client.request("GetFindings", {"MaxResults": 1}).get("Findings") or []
        if not findings:
            return
        path_params["FindingIdentifier"] = {"Id": findings[0]["Id"], "ProductArn": findings[0]["ProductArn"]}
    if endpoint.parent:
        parent_name, parent_field = endpoint.parent
        parent = ENDPOINTS[parent_name]
        items = client.request(parent.operation, {"MaxResults": 1}).get(parent.result_key) or []
        if not items:
            return
        path_params[parent_field] = items[0][parent_field]
    client.request(endpoint.operation, {**({"MaxResults": 1} if endpoint.page_size else {}), **path_params})


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
        # Finding history arrives grouped by finding, and GetFindingsV2 is not sorted, so the pipeline
        # takes the highest value of the run as the watermark when the run ends.
        sort_mode="asc" if endpoint == "findings" else "desc" if endpoint in INCREMENTAL_FIELDS else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        on_complete=manager.clear_state,
    )
