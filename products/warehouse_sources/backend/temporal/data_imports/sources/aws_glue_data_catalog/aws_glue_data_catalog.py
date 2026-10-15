from __future__ import annotations

import re
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_glue_data_catalog.settings import (
    BODY_RETRY_CODES,
    CONTENT_TYPE,
    ENDPOINTS,
    ERROR_MESSAGES,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_PREFIXES,
    GlueEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsgluedatacatalog import (
        AwsGlueDataCatalogSourceConfig,
    )


TRANSPORT_RETRY = BoundedRetry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"POST"}),
    raise_on_status=False,
)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_REGION_PATTERN = re.compile(r"(?:us-gov|[a-z]{2})-[a-z]+-\d+")


@frozen
class AwsGlueDataCatalogResumeConfig:
    next_token: str | None = None
    completed: bool = False


@frozen
class GluePage:
    items: list[dict[str, Any]]
    next_token: str | None


class AwsGlueError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"AWS Glue request failed: {code} - {message}")


class AwsGlueRetryableError(AwsGlueError):
    pass


def error_for_response(response: requests.Response) -> AwsGlueError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw_code = response.headers.get("x-amzn-ErrorType") or body.get("__type") or body.get("code")
    code = str(raw_code or f"HTTP {response.status_code}").split(":", 1)[0].rsplit("#", 1)[-1]
    message = str(body.get("Message") or body.get("message") or response.text)[:500]
    # The transport handles HTTP retries. Only body-coded HTTP 400 failures need a separate retry.
    error_class = AwsGlueRetryableError if response.status_code == 400 and code in BODY_RETRY_CODES else AwsGlueError
    return error_class(code, message)


class AwsGlueClient:
    def __init__(self, config: AwsGlueDataCatalogSourceConfig, api_version: str) -> None:
        if not config.aws_access_key_id or not config.aws_secret_access_key:
            raise ValueError("Enter both an AWS access key ID and a secret access key.")
        if not _REGION_PATTERN.fullmatch(config.aws_region):
            raise ValueError("Enter an AWS region such as us-east-1.")
        if api_version not in TARGET_PREFIXES:
            raise ValueError(f"Unsupported AWS Glue API version: {api_version}")
        self.region = config.aws_region
        suffix = "amazonaws.com.cn" if self.region.startswith("cn-") else "amazonaws.com"
        self.url = f"https://glue.{self.region}.{suffix}/"
        self.target_prefix = TARGET_PREFIXES[api_version]
        self.signer = SigV4Auth(
            Credentials(config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token or None),
            "glue",
            self.region,
        )
        self.session = make_tracked_session(
            retry=TRANSPORT_RETRY,
            redact_values=tuple(value for value in (config.aws_secret_access_key, config.aws_session_token) if value),
        )

    def close(self) -> None:
        self.session.close()

    @retry(
        retry=retry_if_exception_type(AwsGlueRetryableError),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = AWSRequest(
            method="POST",
            url=self.url,
            data=body,
            headers={"Content-Type": CONTENT_TYPE, "X-Amz-Target": f"{self.target_prefix}.{operation}"},
        )
        self.signer.add_auth(request)
        response = self.session.post(
            self.url,
            data=body,
            headers=dict(request.headers),
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
        if response.status_code != 200:
            raise error_for_response(response)
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("AWS Glue returned an invalid response.")
        return result

    def pages(
        self,
        endpoint: GlueEndpoint,
        payload: dict[str, Any],
        start_token: str | None = None,
    ) -> Iterator[GluePage]:
        token = start_token
        while True:
            params = {"MaxResults": endpoint.page_size, **payload}
            if token:
                params["NextToken"] = token
            body = self.request(endpoint.operation, params)
            items = body[endpoint.result_key]
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise ValueError("AWS Glue returned an invalid list response.")
            next_token = body.get("NextToken") or None
            if next_token is not None and not isinstance(next_token, str):
                raise ValueError("AWS Glue returned an invalid pagination token.")
            if next_token and next_token == token:
                raise ValueError("AWS Glue returned a repeated pagination token.")
            yield GluePage(items=items, next_token=next_token)
            if next_token is None:
                return
            token = next_token


def normalize_row(endpoint: str, item: dict[str, Any], region: str, parent_payload: dict[str, Any]) -> dict[str, Any]:
    row = {_CAMEL_BOUNDARY.sub("_", key).lower(): value for key, value in item.items()}
    row["region"] = region
    for column in ENDPOINTS[endpoint].timestamp_columns:
        value = row.get(column)
        if isinstance(value, int | float) and not isinstance(value, bool):
            row[column] = datetime.fromtimestamp(value, tz=UTC)
    for key in ("DatabaseName", "TableName", "JobName", "CatalogId"):
        if key in parent_payload:
            row[_CAMEL_BOUNDARY.sub("_", key).lower()] = parent_payload[key]
    if endpoint == "partitions":
        # JSON preserves value boundaries, so different partition tuples cannot share a key.
        row["partition_values"] = json.dumps(item["Values"], ensure_ascii=False, separators=(",", ":"))
    return row


def parent_payload(endpoint: str, parent: dict[str, Any]) -> dict[str, Any]:
    if endpoint == "job_runs":
        return {"JobName": parent["name"]}
    payload = {"DatabaseName": parent["name"] if endpoint == "tables" else parent["database_name"]}
    if parent.get("catalog_id"):
        payload["CatalogId"] = parent["catalog_id"]
    if endpoint == "partitions":
        payload["TableName"] = parent["name"]
    return payload


def walk_rows(
    client: AwsGlueClient,
    endpoint: str,
    manager: ResumableSourceManager[AwsGlueDataCatalogResumeConfig],
    checkpoint: bool = False,
) -> Iterator[list[dict[str, Any]]]:
    spec = ENDPOINTS[endpoint]
    if spec.parent:
        for parents in walk_rows(client, spec.parent, manager):
            for parent in parents:
                payload = parent_payload(endpoint, parent)
                for page in client.pages(spec, payload):
                    if page.items:
                        yield [normalize_row(endpoint, item, client.region, payload) for item in page.items]
                    manager.safe_point()
        return

    state = manager.load_state() if checkpoint and manager.can_resume() else None
    if state and state.completed:
        return
    for page in client.pages(spec, {}, start_token=state.next_token if state else None):
        rows = [normalize_row(endpoint, item, client.region, {}) for item in page.items]
        if checkpoint:
            manager.save_state(
                AwsGlueDataCatalogResumeConfig(next_token=page.next_token, completed=page.next_token is None)
            )
        if rows:
            yield rows
        manager.safe_point()


def aws_glue_data_catalog_source(
    config: AwsGlueDataCatalogSourceConfig,
    endpoint: str,
    api_version: str,
    manager: ResumableSourceManager[AwsGlueDataCatalogResumeConfig],
) -> SourceResponse:
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Unknown AWS Glue table: {endpoint}")
    spec = ENDPOINTS[endpoint]
    # Parent lists have no stable order. Dependent tables restart discovery after an interrupted sync.
    supports_resume = spec.parent is None

    def get_rows() -> Iterator[list[dict[str, Any]]]:
        client = AwsGlueClient(config, api_version)
        try:
            yield from walk_rows(client, endpoint, manager, checkpoint=supports_resume)
        finally:
            client.close()

    return SourceResponse(
        name=endpoint,
        items=get_rows,
        primary_keys=list(spec.primary_keys),
        sort_mode=None,
        supports_resume=supports_resume,
        on_complete=manager.clear_state if supports_resume else None,
    )


def probe_endpoint(client: AwsGlueClient, endpoint: str) -> dict[str, Any] | None:
    spec = ENDPOINTS[endpoint]
    payload: dict[str, Any] = {}
    if spec.parent:
        parent = probe_endpoint(client, spec.parent)
        if parent is None:
            return None
        payload = parent_payload(endpoint, parent)
    body = client.request(spec.operation, {**payload, "MaxResults": 1})
    items = body.get(spec.result_key) or []
    return normalize_row(endpoint, items[0], client.region, payload) if items else None


def validate_credentials(
    config: AwsGlueDataCatalogSourceConfig, api_version: str, schema_name: str | None = None
) -> tuple[bool, str | None]:
    if schema_name is not None and schema_name not in ENDPOINTS:
        return False, f"Unknown AWS Glue table: {schema_name}"
    try:
        client = AwsGlueClient(config, api_version)
    except ValueError as error:
        return False, str(error)
    try:
        probe_endpoint(client, schema_name or "databases")
        return True, None
    except AwsGlueError as error:
        if schema_name is None and error.code in {"AccessDenied", "AccessDeniedException"}:
            return True, None
        return False, ERROR_MESSAGES.get(
            error.code, "AWS Glue could not verify access. Try again after checking AWS service status."
        )
    except requests.RequestException:
        return False, "Could not connect to AWS Glue. Check the region and try again."
    finally:
        client.close()


def probe_endpoint_permissions(
    config: AwsGlueDataCatalogSourceConfig, api_version: str, endpoints: list[str]
) -> dict[str, str | None]:
    try:
        client = AwsGlueClient(config, api_version)
    except ValueError as error:
        return dict.fromkeys(endpoints, str(error))
    permissions: dict[str, str | None] = {}
    try:
        for endpoint in endpoints:
            if endpoint not in ENDPOINTS:
                continue
            permissions[endpoint] = None
            try:
                probe_endpoint(client, endpoint)
            except AwsGlueError as error:
                permissions[endpoint] = ERROR_MESSAGES.get(error.code)
            except requests.RequestException:
                pass
        return permissions
    finally:
        client.close()
