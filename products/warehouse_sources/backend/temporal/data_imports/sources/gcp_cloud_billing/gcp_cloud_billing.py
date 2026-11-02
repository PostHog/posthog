from collections.abc import Mapping
from typing import Any

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport import Response as GoogleResponse
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account
from requests import PreparedRequest

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_billing.settings import (
    CLOUD_BILLING_URL,
    ENDPOINTS,
    SCOPES,
    TOKEN_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gcpcloudbilling import (
    GcpCloudBillingKeyFileConfig,
)


class GcpCloudBillingCredentialsError(ValueError):
    pass


class BillingTokenRequest(GoogleRequest):
    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 30,
        **kwargs: Any,
    ) -> GoogleResponse:
        response = super().__call__(url, method=method, body=body, headers=headers, timeout=30, allow_redirects=False)
        # The tracked transport already retries these statuses. Stop google-auth from retrying them again.
        if response.status == 429 or response.status >= 500:
            raise TransportError(f"Google token exchange failed with HTTP {response.status}")
        if 300 <= response.status < 400:
            raise GcpCloudBillingCredentialsError(
                "Google token exchange refused a redirect. Replace the service account key."
            )
        return response


class BillingServiceAccountAuth(AuthConfigBase):
    def __init__(self, key_file: GcpCloudBillingKeyFileConfig) -> None:
        try:
            if not key_file.client_email or not key_file.private_key:
                raise ValueError("Expected a service account email and private key")
            # Pin the token host because uploaded keys can contain a customer-controlled token_uri.
            key = {
                "client_email": key_file.client_email,
                "private_key": key_file.private_key,
                "private_key_id": key_file.private_key_id,
                "token_uri": TOKEN_URL,
            }
            self.credentials = service_account.Credentials.from_service_account_info(key, scopes=SCOPES)
        except (ValueError, TypeError, KeyError) as error:
            raise GcpCloudBillingCredentialsError(
                "Invalid GCP service account key. Upload a valid JSON key file."
            ) from error
        self._private_key = key_file.private_key
        self._request = BillingTokenRequest(session=make_tracked_session(capture=False))

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        try:
            self.credentials.before_request(self._request, request.method, request.url, request.headers)
        except RefreshError as error:
            if error.retryable:
                raise
            raise GcpCloudBillingCredentialsError(
                "Google rejected the service account key. Replace the key and reconnect."
            ) from error
        return request

    def secret_values(self) -> tuple[str, ...]:
        return tuple(value for value in (self._private_key, self.credentials.token) if value)


@frozen
class GcpCloudBillingResumeConfig:
    paginator_state: dict[str, Any] | None = None


def probe_credentials(key_file: GcpCloudBillingKeyFileConfig, schema_name: str | None) -> None:
    endpoint = schema_for_resource(ENDPOINTS, schema_name or "billing_accounts")
    auth = BillingServiceAccountAuth(key_file)
    with make_tracked_session(redact_values=auth.secret_values()) as session:
        path = endpoint.path
        if endpoint.fanout:
            parent = ENDPOINTS[endpoint.fanout.parent_name]
            response = session.get(
                f"{CLOUD_BILLING_URL}{parent.path}",
                params={"pageSize": 1},
                auth=auth,
                timeout=(10, 30),
                allow_redirects=False,
            )
            response.raise_for_status()
            parents = response.json().get(parent.data_selector, [])
            if not parents:
                return
            path = path.format(parent=parents[0]["name"])
        url = path if path.startswith("https://") else f"{CLOUD_BILLING_URL}{path}"
        response = session.get(url, params={"pageSize": 1}, auth=auth, timeout=(10, 30), allow_redirects=False)
        response.raise_for_status()


def gcp_cloud_billing_source(
    key_file: GcpCloudBillingKeyFileConfig,
    endpoint_name: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[GcpCloudBillingResumeConfig],
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, endpoint_name)
    if api_version != "v1":
        raise ValueError(f"Unsupported Cloud Billing API version: {api_version}")
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_state(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(GcpCloudBillingResumeConfig(paginator_state=state))

    client: ClientConfig = {
        "base_url": CLOUD_BILLING_URL,
        "auth": BillingServiceAccountAuth(key_file),
        "paginator": {
            "type": "cursor",
            "cursor_path": "nextPageToken",
            "cursor_param": "pageToken",
            "raise_on_repeated_cursor": True,
        },
        "allowed_hosts": ["cloudbilling.googleapis.com", "billingbudgets.googleapis.com"],
        "allow_redirects": False,
        "request_timeout": (10, 30),
    }
    initial_state = resume.paginator_state if resume else None
    if endpoint.fanout:
        parent = ENDPOINTS[endpoint.fanout.parent_name]
        resource = build_dependent_resource(
            endpoint_configs=ENDPOINTS,
            child_endpoint=endpoint_name,
            fanout=endpoint.fanout,
            client_config=client,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            page_size_param="pageSize",
            parent_endpoint_extra={"data_selector": parent.data_selector},
            child_endpoint_extra={"data_selector": endpoint.data_selector},
            resume_hook=save_state,
            initial_paginator_state=initial_state,
        )
    else:
        config: RESTAPIConfig = {
            "client": client,
            "resources": [
                {
                    "name": endpoint_name,
                    "table_name": endpoint_name,
                    "write_disposition": "replace",
                    "table_format": "delta",
                    "endpoint": {
                        "path": endpoint.path,
                        "data_selector": endpoint.data_selector,
                        "params": {"pageSize": endpoint.page_size},
                    },
                }
            ],
        }
        resource = rest_api_resource(
            config,
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            resume_hook=save_state,
            initial_paginator_state=initial_state,
        )
    return SourceResponse(
        name=endpoint_name,
        items=lambda: resource,
        primary_keys=list(endpoint.primary_keys),
        partition_keys=list(endpoint.partition_keys),
        partition_mode=endpoint.partition_mode,
        partition_count=endpoint.partition_count,
        sort_mode=None,
    )
