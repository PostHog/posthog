import re
import json
import hashlib
import datetime as dt
import dataclasses
from collections.abc import Iterator, Sequence
from typing import Any

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from botocore.serialize import create_serializer
from botocore.session import get_session
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_systems_manager.settings import (
    API_VERSION,
    ENDPOINTS,
    ERROR_MESSAGES,
    EXCLUDED_INVENTORY_TYPES,
    MISSING_PARENT_ERRORS,
    SESSION_STATES,
    SystemsManagerEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssystemsmanager import (
    AwsSystemsManagerSourceConfig,
)

TRANSPORT_RETRY = BoundedRetry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"POST"}),
    raise_on_status=False,
)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
# Inventory type names and OpsItem data keys are dynamic, so retain them in one JSON column.
_JSON_COLUMNS = frozenset({"Data", "OperationalData"})
# DescribeInstancePatchStates accepts at most this many nodes in one request.
_PATCH_STATE_BATCH_SIZE = 50

_PLACEHOLDER_INSTANCE_ID = "i-00000000000000000"
_PLACEHOLDER_UUID = "00000000-0000-0000-0000-000000000000"
# Well-formed identifiers that exist nowhere, so a probe reaches the IAM check and then fails as not found.
PLACEHOLDER_PARENTS: dict[str, dict[str, Any]] = {
    "resource_compliance_summaries": {
        "ResourceId": _PLACEHOLDER_INSTANCE_ID,
        "ResourceType": "ManagedInstance",
        "ComplianceType": "Patch",
    },
    "inventory": {"Id": _PLACEHOLDER_INSTANCE_ID},
    "managed_instances": {"InstanceId": _PLACEHOLDER_INSTANCE_ID},
    "associations": {"AssociationId": _PLACEHOLDER_UUID},
    "association_executions": {"AssociationId": _PLACEHOLDER_UUID, "ExecutionId": _PLACEHOLDER_UUID},
}


@frozen
class SystemsManagerResumeConfig:
    next_token: str | None = None
    completed: bool = False
    # (page token, child key) of the parent row being expanded at each fan-out level, outermost first.
    parents: tuple[tuple[str | None, str], ...] = ()

    def __post_init__(self) -> None:
        # Saved state comes back from JSON with lists in place of tuples.
        object.__setattr__(self, "parents", tuple((token, key) for token, key in self.parents))


class SystemsManagerError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"AWS Systems Manager request failed: {code} - {message}")


class SystemsManagerThrottledError(SystemsManagerError):
    pass


def error_for_response(response: requests.Response) -> SystemsManagerError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw_code = response.headers.get("x-amzn-ErrorType") or body.get("__type") or body.get("code")
    code = str(raw_code or f"HTTP {response.status_code}").split(":")[0].rsplit("#", 1)[-1]
    message = str(body.get("Message") or body.get("message") or response.text)[:500]
    # The HTTP transport cannot detect throttling encoded in a 400 response.
    if response.status_code == 400 and code in {"Throttling", "ThrottlingException", "TooManyRequestsException"}:
        return SystemsManagerThrottledError(code, message)
    return SystemsManagerError(code, message)


class SystemsManagerClient:
    def __init__(self, config: AwsSystemsManagerSourceConfig, api_version: str) -> None:
        if api_version != API_VERSION:
            raise ValueError(f"Unsupported AWS Systems Manager API version: {api_version}")
        if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", config.aws_region):
            raise ValueError("Enter a valid AWS region, such as us-east-1.")
        session = get_session()
        self._model = session.get_service_model("ssm", api_version=api_version)
        self._serializer = create_serializer(self._model.metadata["protocol"])
        endpoint = session.get_component("endpoint_resolver").construct_endpoint("ssm", config.aws_region)
        if endpoint is None:
            raise ValueError("AWS Systems Manager is unavailable in this region. Select another region.")
        self.url = f"https://{endpoint['hostname']}/"
        self.region = config.aws_region
        self._signer = SigV4Auth(
            Credentials(config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token or None),
            "ssm",
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
        retry=retry_if_exception_type(SystemsManagerThrottledError),
        stop=stop_after_attempt(6),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        serialized = self._serializer.serialize_to_request(payload, self._model.operation_model(operation))
        request = AWSRequest(method="POST", url=self.url, data=serialized["body"], headers=serialized["headers"])
        self._signer.add_auth(request)
        response = self._session.post(
            self.url, data=serialized["body"], headers=dict(request.headers), timeout=60, allow_redirects=False
        )
        if response.status_code >= 400:
            raise error_for_response(response)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("AWS Systems Manager returned an invalid response.")
        return body


def request_payload(endpoint: SystemsManagerEndpoint, *, probe: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {"MaxResults": endpoint.probe_size if probe else endpoint.page_size}
    if endpoint.operation == "GetInventory":
        payload["ResultAttributes"] = [{"TypeName": "AWS:InstanceInformation"}]
    return payload


def root_payloads(endpoint: SystemsManagerEndpoint, *, probe: bool = False) -> list[dict[str, Any]]:
    payload = request_payload(endpoint, probe=probe)
    if endpoint.operation == "DescribeSessions":
        return [{**payload, "State": state} for state in SESSION_STATES]
    return [payload]


def endpoint_chain(endpoint: SystemsManagerEndpoint) -> list[SystemsManagerEndpoint]:
    chain = [endpoint]
    while chain[0].parent is not None:
        chain.insert(0, ENDPOINTS[chain[0].parent])
    return chain


def _instance_status(item: dict[str, Any]) -> str | None:
    data = item.get("Data")
    info = data.get("AWS:InstanceInformation") if isinstance(data, dict) else None
    content = info.get("Content") if isinstance(info, dict) else None
    if isinstance(content, list) and content and isinstance(content[0], dict):
        return content[0].get("InstanceStatus")
    return None


def child_payloads(
    endpoint: SystemsManagerEndpoint, parent: dict[str, Any], inventory_types: Sequence[str]
) -> list[dict[str, Any]]:
    if endpoint.operation == "ListComplianceItems":
        return [
            {
                "ResourceIds": [parent["ResourceId"]],
                "ResourceTypes": [parent["ResourceType"]],
                "Filters": [{"Key": "ComplianceType", "Values": [parent["ComplianceType"]], "Type": "EQUAL"}],
            }
        ]
    if endpoint.operation == "ListInventoryEntries":
        # ListInventoryEntries rejects terminated nodes, which GetInventory still lists.
        if _instance_status(parent) == "Terminated":
            return []
        return [{"InstanceId": parent["Id"], "TypeName": type_name} for type_name in inventory_types]
    if endpoint.operation == "DescribeAssociationExecutions":
        return [{"AssociationId": parent["AssociationId"]}]
    if endpoint.operation == "DescribeAssociationExecutionTargets":
        return [{"AssociationId": parent["AssociationId"], "ExecutionId": parent["ExecutionId"]}]
    if endpoint.operation == "DescribeInstancePatchStates":
        return [{"InstanceIds": [parent["InstanceId"]]}]
    if endpoint.operation == "DescribeInstancePatches":
        return [{"InstanceId": parent["InstanceId"]}]
    raise ValueError(f"AWS Systems Manager table has no parent mapping: {endpoint.operation}")


def page_child_payloads(
    endpoint: SystemsManagerEndpoint, parents: Sequence[dict[str, Any]], inventory_types: Sequence[str]
) -> list[dict[str, Any]]:
    payloads = [payload for parent in parents for payload in child_payloads(endpoint, parent, inventory_types)]
    if endpoint.operation != "DescribeInstancePatchStates":
        return payloads
    instance_ids = [instance_id for payload in payloads for instance_id in payload["InstanceIds"]]
    return [
        {"InstanceIds": instance_ids[start : start + _PATCH_STATE_BATCH_SIZE]}
        for start in range(0, len(instance_ids), _PATCH_STATE_BATCH_SIZE)
    ]


def _flatten(obj: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    row: dict[str, Any] = {}
    for key, value in obj.items():
        column = prefix + _CAMEL_BOUNDARY.sub("_", key).lower()
        if key in _JSON_COLUMNS and not prefix:
            row[column] = json.dumps(value)
        elif isinstance(value, dict):
            row.update(_flatten(value, column + "_"))
        else:
            row[column] = value
    return row


def normalize_row(item: dict[str, Any], endpoint: SystemsManagerEndpoint, region: str) -> dict[str, Any]:
    row = _flatten(item)
    row["region"] = region
    for name in endpoint.timestamps:
        value = row.get(name)
        if isinstance(value, int | float) and not isinstance(value, bool):
            row[name] = dt.datetime.fromtimestamp(value, tz=dt.UTC)
    return row


def page_rows(
    endpoint: SystemsManagerEndpoint, body: dict[str, Any], payload: dict[str, Any], region: str
) -> list[dict[str, Any]]:
    items = body.get(endpoint.result_key) or []
    if endpoint.operation == "DescribeInstancePatches":
        # Patches do not name the node they belong to.
        return [{**normalize_row(item, endpoint, region), "instance_id": payload["InstanceId"]} for item in items]
    if endpoint.operation != "ListInventoryEntries":
        return [normalize_row(item, endpoint, region) for item in items]
    capture_time = body.get("CaptureTime")
    rows: list[dict[str, Any]] = []
    for item in items:
        # Entry keys depend on the inventory type, and entries carry no identifier of their own.
        entry = json.dumps(item, sort_keys=True)
        rows.append(
            {
                "region": region,
                "instance_id": payload["InstanceId"],
                "type_name": payload["TypeName"],
                "schema_version": body.get("SchemaVersion"),
                "capture_time": dt.datetime.fromisoformat(capture_time) if isinstance(capture_time, str) else None,
                "entry_id": hashlib.sha256(entry.encode()).hexdigest(),
                "entry": entry,
            }
        )
    return rows


def _next_token(body: dict[str, Any], token: str | None) -> str | None:
    next_token = body.get("NextToken") or None
    if next_token is not None and (not isinstance(next_token, str) or next_token == token):
        raise ValueError("AWS Systems Manager returned an invalid or repeated page token.")
    return next_token


class SystemsManagerWalk:
    """Walks an endpoint and its fan-out parents, yielding each page with the state that resumes after it."""

    def __init__(
        self,
        client: SystemsManagerClient,
        chain: list[SystemsManagerEndpoint],
        manager: ResumableSourceManager[SystemsManagerResumeConfig],
    ) -> None:
        self._client = client
        self._chain = chain
        self._manager = manager
        self._inventory_types: tuple[str, ...] = ()

    def pages(
        self, state: SystemsManagerResumeConfig | None
    ) -> Iterator[tuple[list[dict[str, Any]], SystemsManagerResumeConfig]]:
        if any(endpoint.operation == "ListInventoryEntries" for endpoint in self._chain):
            self._inventory_types = self._load_inventory_types()
        payloads = root_payloads(self._chain[0])
        if len(payloads) == 1:
            yield from self._walk(0, payloads[0], (), state)
            return
        # Each root payload is walked like a parent row, so resume state records which one was in progress.
        key = state.parents[0][1] if state and state.parents else ""
        inner = dataclasses.replace(state, parents=state.parents[1:]) if state and state.parents else None
        roots = {json.dumps(payload, sort_keys=True): payload for payload in payloads}
        keys = list(roots)
        start = keys.index(key) if key in roots else 0
        for root_key in keys[start:]:
            yield from self._walk(0, roots[root_key], ((None, root_key),), inner if root_key == key else None)
        yield [], SystemsManagerResumeConfig(completed=True)

    def _load_inventory_types(self) -> tuple[str, ...]:
        names: set[str] = set()
        token: str | None = None
        while True:
            payload: dict[str, Any] = {"MaxResults": 200}
            if token:
                payload["NextToken"] = token
            body = self._client.request("GetInventorySchema", payload)
            names.update(
                schema["TypeName"]
                for schema in body.get("Schemas") or []
                if isinstance(schema, dict) and isinstance(schema.get("TypeName"), str)
            )
            self._manager.safe_point()
            token = _next_token(body, token)
            if token is None:
                return tuple(sorted(names - EXCLUDED_INVENTORY_TYPES))

    def _fetch(
        self,
        endpoint: SystemsManagerEndpoint,
        payload: dict[str, Any],
        token: str | None,
        *,
        resumed: bool,
        child: bool,
    ) -> tuple[dict[str, Any], str | None]:
        while True:
            try:
                return self._client.request(
                    endpoint.operation, {**payload, "NextToken": token} if token else payload
                ), token
            except SystemsManagerError as error:
                if resumed and token and error.code == "InvalidNextToken":
                    token, resumed = None, False
                    continue
                if child and error.code in MISSING_PARENT_ERRORS:
                    return {}, token
                raise

    def _walk(
        self,
        level: int,
        payload: dict[str, Any],
        prefix: tuple[tuple[str | None, str], ...],
        state: SystemsManagerResumeConfig | None,
    ) -> Iterator[tuple[list[dict[str, Any]], SystemsManagerResumeConfig]]:
        if state is not None and state.completed and not state.parents:
            return
        endpoint = self._chain[level]
        if level == len(self._chain) - 1:
            token = state.next_token if state else None
            resumed = token is not None
            while True:
                body, token = self._fetch(endpoint, payload, token, resumed=resumed, child=level > 0)
                resumed = False
                next_token = _next_token(body, token)
                rows = page_rows(endpoint, body, payload, self._client.region)
                yield (
                    rows,
                    SystemsManagerResumeConfig(parents=prefix, next_token=next_token, completed=next_token is None),
                )
                if next_token is None:
                    return
                token = next_token

        token, key = state.parents[0] if state and state.parents else (None, "")
        inner = dataclasses.replace(state, parents=state.parents[1:]) if state and state.parents else None
        resumed = token is not None
        child_endpoint = self._chain[level + 1]
        while True:
            body, used = self._fetch(endpoint, payload, token, resumed=resumed, child=level > 0)
            if used != token:
                key, inner = "", None
            token, resumed = used, False
            next_token = _next_token(body, token)
            children = {
                json.dumps(child, sort_keys=True): child
                for child in page_child_payloads(
                    child_endpoint, body.get(endpoint.result_key) or [], self._inventory_types
                )
            }
            keys = list(children)
            start = keys.index(key) if key in children else 0
            for child_key in keys[start:]:
                yield from self._walk(
                    level + 1,
                    {"MaxResults": child_endpoint.page_size, **children[child_key]},
                    (*prefix, (token, child_key)),
                    inner if child_key == key else None,
                )
            if next_token is None:
                yield [], SystemsManagerResumeConfig(parents=prefix, completed=True)
                return
            token, key, inner = next_token, "", None
            yield [], SystemsManagerResumeConfig(parents=(*prefix, (token, "")))


def get_rows(
    config: AwsSystemsManagerSourceConfig,
    endpoint: SystemsManagerEndpoint,
    api_version: str,
    manager: ResumableSourceManager[SystemsManagerResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    state = manager.load_state() if manager.can_resume() else None
    if state and state.completed and not state.parents:
        return
    client = SystemsManagerClient(config, api_version)
    try:
        for rows, next_state in SystemsManagerWalk(client, endpoint_chain(endpoint), manager).pages(state):
            manager.save_state(next_state)
            if rows:
                yield rows
            manager.safe_point()
    finally:
        client.close()


def probe_payload(child: SystemsManagerEndpoint, parent_body: dict[str, Any]) -> dict[str, Any]:
    # IAM can scope the child operations to specific resources, so probe a real parent row when one exists.
    parent_endpoint = ENDPOINTS[child.parent or ""]
    for item in (parent_body.get(parent_endpoint.result_key) or [])[:1]:
        payloads = child_payloads(child, item, ("AWS:Application",))
        if payloads:
            return {**payloads[0], "MaxResults": child.probe_size}
    payload = child_payloads(child, PLACEHOLDER_PARENTS[child.parent or ""], ("AWS:Application",))[0]
    return {**payload, "MaxResults": child.probe_size}


def validate_credentials(
    config: AwsSystemsManagerSourceConfig, api_version: str, schema_name: str | None = None
) -> tuple[bool, str | None]:
    if not config.aws_access_key_id or not config.aws_secret_access_key:
        return False, "Enter both an AWS access key ID and a secret access key."
    endpoint = ENDPOINTS.get(schema_name or "managed_instances")
    if endpoint is None:
        return False, f"Unknown AWS Systems Manager table: {schema_name}"
    try:
        client = SystemsManagerClient(config, api_version)
    except ValueError as error:
        return False, str(error)
    chain = endpoint_chain(endpoint)
    operation = chain[0].operation
    try:
        body = client.request(operation, root_payloads(chain[0], probe=True)[0])
        if endpoint.operation == "ListInventoryEntries":
            operation = "GetInventorySchema"
            client.request(operation, {"MaxResults": 50})
        for child in chain[1:]:
            operation = child.operation
            try:
                body = client.request(operation, probe_payload(child, body))
            except SystemsManagerError as error:
                if error.code not in MISSING_PARENT_ERRORS:
                    raise
                body = {}
    except SystemsManagerError as error:
        if error.code in {"AccessDenied", "AccessDeniedException"}:
            if schema_name is None:
                return True, None
            return False, f"Grant ssm:{operation} to read this table."
        return False, ERROR_MESSAGES.get(
            error.code, "AWS Systems Manager could not validate the credentials. Try again."
        )
    except requests.RequestException:
        return False, "Could not reach AWS Systems Manager. Check the region and try again."
    finally:
        client.close()
    return True, None


def aws_systems_manager_source(
    config: AwsSystemsManagerSourceConfig,
    schema_name: str,
    api_version: str,
    manager: ResumableSourceManager[SystemsManagerResumeConfig],
) -> SourceResponse:
    endpoint = ENDPOINTS.get(schema_name)
    if endpoint is None:
        raise ValueError(f"Unknown AWS Systems Manager table: {schema_name}")
    return SourceResponse(
        name=schema_name,
        items=lambda: get_rows(config, endpoint, api_version, manager),
        primary_keys=list(endpoint.primary_key),
        sort_mode=None,
        on_complete=manager.clear_state,
    )
