from __future__ import annotations

import re
import datetime as dt
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from botocore.loaders import Loader
from botocore.model import ServiceModel
from botocore.serialize import create_serializer

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_macie.settings import (
    ERROR_MESSAGES,
    MACIE_API_VERSION,
    MACIE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsmacie import (
        AwsMacieSourceConfig,
    )


@frozen
class AwsMacieResumeConfig:
    next_token: str | None = None
    since_ms: int | None = None
    completed: bool = False


class AwsMacieError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"AWS Macie request failed: {code} - {message}")


class AwsMacieClient:
    def __init__(self, config: AwsMacieSourceConfig, api_version: str | None = None) -> None:
        version = api_version or MACIE_API_VERSION
        if version != MACIE_API_VERSION:
            raise ValueError(f"Unsupported AWS Macie API version: {version}")
        if not config.aws_access_key_id or not config.aws_secret_access_key:
            raise ValueError("Enter both an AWS access key ID and a secret access key.")
        if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", config.region):
            raise ValueError("Enter an AWS region, such as us-east-1.")
        self.region = config.region
        suffix = "amazonaws.com.cn" if self.region.startswith("cn-") else "amazonaws.com"
        self._url = f"https://macie2.{self.region}.{suffix}"
        self._model = ServiceModel(Loader().load_service_model("macie2", "service-2", api_version=version))
        self._serializer = create_serializer(self._model.protocol)
        self._signer = SigV4Auth(
            Credentials(config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token or None),
            "macie2",
            self.region,
        )
        self._session = make_tracked_session(
            retry=BoundedRetry(
                total=3,
                backoff_factor=1,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET", "POST"}),
                raise_on_status=False,
            ),
            redact_values=tuple(
                value
                for value in (config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token)
                if value
            ),
        )

    def close(self) -> None:
        self._session.close()

    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        serialized = self._serializer.serialize_to_request(payload, self._model.operation_model(operation))
        url = self._url + serialized["url_path"]
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
            try:
                error = response.json()
            except ValueError:
                error = {}
            if not isinstance(error, dict):
                error = {}
            raw_code = response.headers.get("x-amzn-ErrorType") or error.get("__type") or error.get("code")
            code = str(raw_code or f"HTTP {response.status_code}").split(":")[0].split("#")[-1]
            raise AwsMacieError(code, str(error.get("message") or error.get("Message") or "Request failed.")[:500])
        return response.json()


def timestamp(value: dt.datetime | str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return parsed.replace(tzinfo=dt.UTC) if parsed.tzinfo is None else parsed


def normalize_row(endpoint: str, item: dict[str, Any], region: str) -> dict[str, Any]:
    row = {re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key).lower(): value for key, value in item.items()}
    row["region"] = region
    for column in MACIE_ENDPOINTS[endpoint].timestamp_columns:
        if row.get(column) is not None:
            row[column] = timestamp(row[column])
    return row


def list_payload(endpoint: str, since_ms: int | None, page_size: int) -> dict[str, Any]:
    payload: dict[str, Any] = {"maxResults": page_size}
    if endpoint == "members":
        payload["onlyAssociated"] = "false"
    if endpoint == "findings":
        payload["sortCriteria"] = {"attributeName": "updatedAt", "orderBy": "ASC"}
        if since_ms is not None:
            payload["findingCriteria"] = {"criterion": {"updatedAt": {"gte": since_ms}}}
    return payload


def get_rows(
    config: AwsMacieSourceConfig,
    endpoint: str,
    manager: ResumableSourceManager[AwsMacieResumeConfig],
    since: dt.datetime | str | None,
    api_version: str | None,
) -> Iterator[list[dict[str, Any]]]:
    setting = MACIE_ENDPOINTS[endpoint]
    state = manager.load_state()
    if state is None:
        state = AwsMacieResumeConfig(since_ms=int(timestamp(since).timestamp() * 1000) if since is not None else None)
    if state.completed:
        return
    client = AwsMacieClient(config, api_version)
    try:
        while True:
            payload = list_payload(endpoint, state.since_ms, setting.page_size)
            if state.next_token:
                payload["nextToken"] = state.next_token
            page = client.request(setting.operation, payload)
            items = page.get(setting.result_key) or []
            if endpoint == "findings" and items:
                findings: list[dict[str, Any]] = []
                for offset in range(0, len(items), 50):
                    findings.extend(
                        client.request("GetFindings", {"findingIds": items[offset : offset + 50]}).get("findings") or []
                    )
                items = findings
            next_token = page.get("nextToken") or None
            if next_token and next_token == state.next_token:
                raise AwsMacieError("RepeatedPaginationToken", "AWS returned the same page token twice.")
            rows = [normalize_row(endpoint, item, config.region) for item in items]
            state = AwsMacieResumeConfig(next_token=next_token, since_ms=state.since_ms, completed=next_token is None)
            manager.save_state(state)
            if rows:
                yield rows
            manager.safe_point()
            if state.completed:
                return
    finally:
        client.close()


def validate_credentials(
    config: AwsMacieSourceConfig, schema_name: str | None = None, api_version: str | None = None
) -> tuple[bool, str | None]:
    endpoint = schema_name or "findings"
    if endpoint not in MACIE_ENDPOINTS:
        return False, f"Unknown AWS Macie table: {endpoint}"
    try:
        client = AwsMacieClient(config, api_version)
    except ValueError as error:
        return False, str(error)
    try:
        page = client.request(MACIE_ENDPOINTS[endpoint].operation, list_payload(endpoint, None, 1))
        if schema_name == "findings" and page.get("findingIds"):
            client.request("GetFindings", {"findingIds": page["findingIds"][:1]})
    except AwsMacieError as error:
        if schema_name is None and error.code in {"AccessDenied", "AccessDeniedException"}:
            return True, None
        for pattern, message in ERROR_MESSAGES.items():
            if pattern.lower() in str(error).lower():
                return False, message
        raise
    finally:
        client.close()
    return True, None


def aws_macie_source(
    config: AwsMacieSourceConfig,
    endpoint: str,
    manager: ResumableSourceManager[AwsMacieResumeConfig],
    since: dt.datetime | str | None = None,
    api_version: str | None = None,
) -> SourceResponse:
    if endpoint not in MACIE_ENDPOINTS:
        raise ValueError(f"Unknown AWS Macie table: {endpoint}")
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(config, endpoint, manager, since, api_version),
        primary_keys=list(MACIE_ENDPOINTS[endpoint].primary_keys),
        # GetFindings can return details in a different order from ListFindings.
        # "desc" saves the watermark once at job end, so unordered rows cannot strand older ones.
        sort_mode="desc",
        partition_keys=["created_at"] if endpoint == "findings" else None,
        partition_mode="datetime" if endpoint == "findings" else None,
        partition_format="month" if endpoint == "findings" else None,
        on_complete=manager.clear_state,
    )
