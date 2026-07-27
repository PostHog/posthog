from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Optional

import requests
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_billing.settings import (
    CLOUD_BILLING_HOST,
    GCP_CLOUD_BILLING_ENDPOINTS,
)

# The Budgets API only accepts `cloud-platform` and the read/write `cloud-billing` scope, so the
# narrower `cloud-billing.readonly` scope can't cover both APIs with a single token. What the
# service account may actually read is still bound by its IAM roles (Billing Account Viewer).
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

# The token endpoint is pinned rather than read from the uploaded key file: a real service-account
# key always exchanges JWTs at Google's endpoint, and trusting the file's `token_uri` would let an
# uploader point the signed-assertion POST at an arbitrary host (blind SSRF).
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"

REQUEST_TIMEOUT_SECONDS = 120
# Google truncates long error bodies badly in logs; enough to carry the actionable detail
# ("Cloud Billing API has not been used in project ... before or it is disabled").
MAX_ERROR_BODY_CHARS = 1000


@dataclass(frozen=True)
class ServiceAccountKey:
    """The subset of a GCP service-account JSON key file needed to mint an access token."""

    project_id: str
    private_key: str
    private_key_id: str
    client_email: str


def _api_session(key: ServiceAccountKey) -> requests.Session:
    return make_tracked_session(redact_values=(key.private_key, key.private_key_id))


def _token_session(key: ServiceAccountKey) -> requests.Session:
    # The token exchange response body is a bare access token under a generic `access_token`
    # key, so keep it out of HTTP sample capture entirely.
    return make_tracked_session(redact_values=(key.private_key, key.private_key_id), capture=False)


def _mint_token(key: ServiceAccountKey) -> str:
    """Sign a JWT with the service-account key and exchange it for a ~1h OAuth2 access token."""
    credentials = service_account.Credentials.from_service_account_info(
        {
            "project_id": key.project_id,
            "private_key": key.private_key,
            "private_key_id": key.private_key_id,
            "client_email": key.client_email,
            "token_uri": GOOGLE_TOKEN_URI,
        },
        scopes=SCOPES,
    )
    credentials.refresh(GoogleAuthRequest(session=_token_session(key)))
    token = credentials.token
    if not token:
        raise ValueError("Google did not return an access token for the service account key")
    return str(token)


def billing_account_resource_name(billing_account_id: str) -> str:
    """Normalize a user-entered billing account to its `billingAccounts/<id>` resource name."""
    account_id = billing_account_id.strip().removeprefix("billingAccounts/")
    return f"billingAccounts/{account_id}"


def _raise_for_status(response: requests.Response) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        # GCP puts the actionable detail (disabled API, missing IAM permission) in the response
        # body rather than the status line, and non-retryable error matching reads `str(error)`.
        raise requests.HTTPError(f"{error} - {response.text[:MAX_ERROR_BODY_CHARS]}", response=response) from error


class _BillingApiClient:
    """Bearer-token client for the Cloud Billing and Cloud Billing Budgets REST APIs.

    Access tokens are short lived (~1h), so a sync that outlives one re-mints on the first 401
    rather than failing. Retries for 429/5xx are handled by the tracked session's transport.
    """

    def __init__(self, key: ServiceAccountKey) -> None:
        self._key = key
        self._session = _api_session(key)
        self._token = _mint_token(key)

    def get(self, url: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        def _do() -> requests.Response:
            return self._session.get(
                url,
                params=params or {},
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

        response = _do()
        if response.status_code == 401:
            self._token = _mint_token(self._key)
            response = _do()

        _raise_for_status(response)
        body = response.json()
        return body if isinstance(body, dict) else {}

    def paginate(
        self, host: str, path: str, data_key: str, page_size: int, logger: FilteringBoundLogger
    ) -> Iterator[list[dict[str, Any]]]:
        url = f"{host}{path}"
        page_token: Optional[str] = None
        seen_tokens: set[str] = set()

        while True:
            params: dict[str, Any] = {"pageSize": page_size}
            if page_token:
                params["pageToken"] = page_token

            body = self.get(url, params)
            items = body.get(data_key) or []
            if items:
                yield items

            next_token = body.get("nextPageToken")
            if not next_token:
                return
            if next_token in seen_tokens:
                logger.warning(f"GCP Cloud Billing returned a repeated page token, stopping. url={url}")
                return

            seen_tokens.add(next_token)
            page_token = next_token


def validate_credentials(key: ServiceAccountKey, billing_account_id: Optional[str]) -> tuple[bool, Optional[str]]:
    """Mint a token and read one billing resource to confirm the key and its IAM grants work."""
    try:
        client = _BillingApiClient(key)
    except Exception:
        return False, "Could not authenticate with Google. Please check the service account key file you uploaded."

    try:
        if billing_account_id:
            client.get(f"{CLOUD_BILLING_HOST}/v1/{billing_account_resource_name(billing_account_id)}")
        else:
            client.get(f"{CLOUD_BILLING_HOST}/v1/billingAccounts", {"pageSize": 1})
    except requests.HTTPError as error:
        response = error.response
        if response is not None and response.status_code in (401, 403):
            return (
                False,
                "Google denied access to your billing data. Please enable the Cloud Billing API and grant the "
                "service account the Billing Account Viewer role.",
            )
        return False, "Could not reach the Google Cloud Billing API. Please try again."
    except Exception:
        return False, "Could not reach the Google Cloud Billing API. Please try again."

    return True, None


def _billing_account_names(
    client: _BillingApiClient,
    billing_account_id: Optional[str],
    logger: FilteringBoundLogger,
) -> list[str]:
    if billing_account_id:
        return [billing_account_resource_name(billing_account_id)]

    config = GCP_CLOUD_BILLING_ENDPOINTS["billing_accounts"]
    return [
        account["name"]
        for page in client.paginate(config.host, config.path, config.data_key, config.page_size, logger)
        for account in page
        if account.get("name")
    ]


def _service_names(client: _BillingApiClient, logger: FilteringBoundLogger) -> list[str]:
    config = GCP_CLOUD_BILLING_ENDPOINTS["services"]
    return [
        service["name"]
        for page in client.paginate(config.host, config.path, config.data_key, config.page_size, logger)
        for service in page
        if service.get("name")
    ]


def get_rows(
    key: ServiceAccountKey,
    billing_account_id: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = GCP_CLOUD_BILLING_ENDPOINTS[endpoint]
    client = _BillingApiClient(key)

    if config.fan_out is None:
        # A pinned billing account can be read directly; listing would return every account the
        # service account can see, which is not what the user asked for.
        if endpoint == "billing_accounts" and billing_account_id:
            yield [client.get(f"{config.host}/v1/{billing_account_resource_name(billing_account_id)}")]
            return

        yield from client.paginate(config.host, config.path, config.data_key, config.page_size, logger)
        return

    if config.fan_out == "billing_account":
        parents = _billing_account_names(client, billing_account_id, logger)
    else:
        parents = _service_names(client, logger)

    parent_field = config.parent_field or "_parent_name"
    for parent in parents:
        path = config.path.format(parent=parent)
        for page in client.paginate(config.host, path, config.data_key, config.page_size, logger):
            yield [{**item, parent_field: parent} for item in page]


def gcp_cloud_billing_source(
    key: ServiceAccountKey,
    billing_account_id: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = GCP_CLOUD_BILLING_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            key=key,
            billing_account_id=billing_account_id,
            endpoint=endpoint,
            logger=logger,
        ),
        primary_keys=list(config.primary_key),
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
