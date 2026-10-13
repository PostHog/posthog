import re
import json
import datetime as dt
from collections.abc import Generator
from dataclasses import field
from typing import Any
from urllib.parse import quote, urlencode

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_iam_access_analyzer.settings import (
    API_VERSION,
    DEFAULT_REGION,
    ENDPOINTS,
    ERROR_MESSAGES,
    PAGE_SIZE,
    PARTITION_KEY,
    TIMESTAMP_COLUMNS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsiamaccessanalyzer import (
    AwsIamAccessAnalyzerSourceConfig,
)

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


@frozen
class AwsIamAccessAnalyzerResumeConfig:
    next_token: str | None = None
    analyzers_next_token: str | None = None
    pending_analyzers: list[dict[str, str]] = field(default_factory=list)
    finished: bool = False


class AwsIamAccessAnalyzerError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"AWS IAM Access Analyzer request failed: {code} - {message}")


class AwsIamAccessAnalyzerClient:
    def __init__(self, config: AwsIamAccessAnalyzerSourceConfig, api_version: str = API_VERSION) -> None:
        if api_version != API_VERSION:
            raise ValueError(f"Unsupported AWS IAM Access Analyzer API version: {api_version}")
        if not config.aws_access_key_id or not config.aws_secret_access_key:
            raise ValueError("Enter both an AWS access key ID and a secret access key.")
        self.region = (config.region or "").strip() or DEFAULT_REGION
        if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", self.region):
            raise ValueError("Enter a valid AWS region, such as us-east-1.")
        suffix = "amazonaws.com.cn" if self.region.startswith("cn-") else "amazonaws.com"
        self.url = f"https://access-analyzer.{self.region}.{suffix}"
        self.signer = SigV4Auth(
            Credentials(config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token or None),
            "access-analyzer",
            self.region,
        )
        self.session = make_tracked_session(
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
        self.session.close()

    def request(
        self,
        endpoint: str,
        *,
        analyzer: dict[str, str] | None = None,
        next_token: str | None = None,
        page_size: int = PAGE_SIZE,
    ) -> dict[str, Any]:
        definition = ENDPOINTS[endpoint]
        payload: dict[str, Any] = {"maxResults": page_size}
        if next_token:
            payload["nextToken"] = next_token
        path = definition.path
        if endpoint != "analyzers":
            if analyzer is None:
                raise ValueError(f"An analyzer is required for {endpoint}.")
            if endpoint == "findings":
                payload["analyzerArn"] = analyzer["arn"]
            else:
                path = path.format(analyzer_name=quote(analyzer["name"], safe=""))
        url = self.url + path
        body = None
        if definition.method == "GET":
            url += "?" + urlencode(payload)
        else:
            body = json.dumps(payload).encode("utf-8")
        request = AWSRequest(method=definition.method, url=url, data=body, headers={"Content-Type": "application/json"})
        self.signer.add_auth(request)
        response = self.session.request(
            definition.method,
            url,
            data=body,
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
            code = str(raw_code or f"HTTP {response.status_code}").split(":")[0].rsplit("#", 1)[-1]
            # AWS error text can include identifiers and credentials. Keep only the error code.
            raise AwsIamAccessAnalyzerError(code, ERROR_MESSAGES.get(code, "AWS could not complete the request."))
        return response.json()


def normalize_row(row: dict[str, Any], region: str, analyzer: dict[str, str] | None = None) -> dict[str, Any]:
    result = {_CAMEL_BOUNDARY.sub("_", key).lower(): value for key, value in row.items()}
    for column in TIMESTAMP_COLUMNS:
        value = result.get(column)
        if isinstance(value, str) and value:
            result[column] = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    result["region"] = region
    if analyzer is not None:
        result["analyzer_arn"] = analyzer["arn"]
    return result


def get_rows(
    config: AwsIamAccessAnalyzerSourceConfig,
    endpoint: str,
    manager: ResumableSourceManager[AwsIamAccessAnalyzerResumeConfig],
    api_version: str,
) -> Generator[list[dict[str, Any]]]:
    state = manager.load_state() if manager.can_resume() else None
    state = state or AwsIamAccessAnalyzerResumeConfig()
    if state.finished:
        return
    client = AwsIamAccessAnalyzerClient(config, api_version)
    try:
        while not state.finished:
            analyzer = None
            if endpoint != "analyzers":
                if not state.pending_analyzers:
                    parent_page = client.request("analyzers", next_token=state.analyzers_next_token)
                    parents = [{"arn": row["arn"], "name": row["name"]} for row in parent_page["analyzers"]]
                    parent_token = parent_page.get("nextToken") or None
                    state = AwsIamAccessAnalyzerResumeConfig(
                        pending_analyzers=parents,
                        analyzers_next_token=parent_token,
                        finished=not parents and parent_token is None,
                    )
                    if not parents:
                        manager.save_state(state)
                        manager.safe_point()
                        continue
                analyzer = state.pending_analyzers[0]
            try:
                page = client.request(endpoint, analyzer=analyzer, next_token=state.next_token)
            except AwsIamAccessAnalyzerError as error:
                if analyzer is None or error.code != "ResourceNotFoundException":
                    raise
                page = {ENDPOINTS[endpoint].result_key: []}
            rows = [normalize_row(row, client.region, analyzer) for row in page[ENDPOINTS[endpoint].result_key]]
            next_token = page.get("nextToken") or None
            if endpoint == "analyzers":
                state = AwsIamAccessAnalyzerResumeConfig(next_token=next_token, finished=next_token is None)
            else:
                pending = state.pending_analyzers if next_token else state.pending_analyzers[1:]
                state = AwsIamAccessAnalyzerResumeConfig(
                    next_token=next_token,
                    pending_analyzers=pending,
                    analyzers_next_token=state.analyzers_next_token,
                    finished=not pending and state.analyzers_next_token is None,
                )
            manager.save_state(state)
            if rows:
                yield rows
            manager.safe_point()
    finally:
        client.close()


def validate_credentials(
    config: AwsIamAccessAnalyzerSourceConfig,
    schema_name: str | None = None,
    api_version: str = API_VERSION,
) -> tuple[bool, str | None]:
    if schema_name is not None and schema_name not in ENDPOINTS:
        return False, f"Unknown AWS IAM Access Analyzer table: {schema_name}"
    try:
        client = AwsIamAccessAnalyzerClient(config, api_version)
        try:
            page = client.request("analyzers", page_size=1)
            if schema_name is not None and schema_name != "analyzers":
                while not page["analyzers"] and page.get("nextToken"):
                    page = client.request("analyzers", page_size=1, next_token=page["nextToken"])
                if page["analyzers"]:
                    client.request(schema_name, analyzer=page["analyzers"][0], page_size=1)
            return True, None
        finally:
            client.close()
    except AwsIamAccessAnalyzerError as error:
        if error.code in {"AccessDenied", "AccessDeniedException"} and schema_name is None:
            return True, None
        return False, ERROR_MESSAGES.get(error.code, "AWS could not validate these credentials. Try again.")
    except ValueError as error:
        return False, str(error)
    except requests.RequestException:
        return False, "Could not connect to AWS IAM Access Analyzer. Check the region and try again."


def aws_iam_access_analyzer_source(
    config: AwsIamAccessAnalyzerSourceConfig,
    endpoint: str,
    manager: ResumableSourceManager[AwsIamAccessAnalyzerResumeConfig],
    api_version: str,
) -> SourceResponse:
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Unknown AWS IAM Access Analyzer table: {endpoint}")
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(config, endpoint, manager, api_version),
        primary_keys=list(ENDPOINTS[endpoint].primary_keys),
        partition_keys=[PARTITION_KEY],
        partition_mode="datetime",
        partition_format="month",
        sort_mode=None,
        on_complete=manager.clear_state,
    )
