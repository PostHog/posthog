import time
import socket
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

from requests import Response
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    JSONDecodeError,
    Timeout as RequestsTimeout,
)

from posthog.psycopg_helpers import is_temporary_resolution_failure

from products.warehouse_sources.backend.temporal.data_imports.sources.common import integration_secrets
from products.warehouse_sources.backend.temporal.data_imports.sources.common.deadline import (
    DeadlineExceededError,
    run_with_deadline,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth


class SalesforceAuth(BearerTokenAuth):
    def __init__(
        self,
        refresh_token: Optional[str] = None,
        access_token: Optional[str] = None,
        instance_url: Optional[str] = None,
    ):
        super().__init__(token=access_token)
        self.refresh_token = refresh_token
        self.instance_url = instance_url
        self.token_expiry: Optional[datetime] = datetime.now(UTC)

    def __call__(self, request: Any) -> Any:
        if self.token is None or self.is_token_expired():
            self.obtain_token()
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request

    def is_token_expired(self) -> bool:
        if self.token_expiry is None:
            return True
        return datetime.now(UTC) >= self.token_expiry

    def obtain_token(self) -> None:
        if self.refresh_token is None or self.instance_url is None:
            raise ValueError("refresh_token and instance_url are required to obtain a new token")
        new_token = salesforce_refresh_access_token(self.refresh_token, self.instance_url)
        self.token = new_token
        self.token_expiry = datetime.now(UTC) + timedelta(hours=1)


class SalesforceAuthRequestError(Exception):
    """Exception to capture errors when an auth request fails."""

    def __init__(self, error_message: str, response: Response):
        self.response = response
        super().__init__(error_message)

    @classmethod
    def raise_from_response(cls, response: Response) -> None:
        """Raise a `SalesforceAuthRequestError` from a failed response.

        If the response did not fail, nothing is raised or returned.
        """
        if 400 <= response.status_code < 500:
            error_message = f"{response.status_code} Client Error: {response.reason}: "

        elif 500 <= response.status_code < 600:
            error_message = f"{response.status_code} Server Error: {response.reason}: "
        else:
            return

        try:
            error_description = response.json()["error_description"]
        except JSONDecodeError:
            if response.text:
                error_message += response.text
            else:
                error_message += "No additional error details"
        else:
            error_message += error_description

        raise cls(error_message, response=response)


# Matched by `SalesforceSource.get_non_retryable_errors`. It carries no host, so it is safe to store.
INSTANCE_HOST_NOT_FOUND_ERROR = "Salesforce instance host does not resolve"
_INSTANCE_HOST_LOOKUP_TIMEOUT_SECONDS = 10


class SalesforceInstanceNotFoundError(Exception):
    """The org's instance host has no DNS record, so no attempt can reach the token endpoint."""


def _instance_host_missing(instance_url: str) -> bool:
    """Whether DNS answers that the instance host does not exist.

    The egress proxy reports a host it cannot resolve as a 502 on CONNECT, the same as a real proxy
    blip. A lookup of our own tells the two apart. A resolver that fails or times out is no answer,
    so it counts as not missing and the error stays retryable.
    """
    host = urlparse(instance_url).hostname
    if not host:
        return False
    try:
        run_with_deadline(
            lambda: socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP),
            timeout_seconds=_INSTANCE_HOST_LOOKUP_TIMEOUT_SECONDS,
            thread_name="salesforce-instance-resolve",
        )
    except socket.gaierror as e:
        return not is_temporary_resolution_failure(e)
    except (DeadlineExceededError, UnicodeError):
        return False
    return False


# Salesforce serializes OAuth token requests per connected app: when a refresh for the same app
# arrives while another is still in flight (parallel schema syncs sharing one connection commonly
# do this), it rejects the duplicate with a 400 "token request is already being processed". The
# lock clears in moments, so a short in-process backoff recovers without failing the whole import
# activity — which would otherwise restart pagination and surface captured error-tracking noise.
_TRANSIENT_TOKEN_REQUEST_ERROR = "token request is already being processed"
_MAX_TOKEN_REFRESH_ATTEMPTS = 4


def _salesforce_app_credentials() -> dict[str, str]:
    """PostHog's own Salesforce connected-app key and secret, named as the token endpoint wants."""
    resolved = integration_secrets.get_secrets(["SALESFORCE_CONSUMER_KEY", "SALESFORCE_CONSUMER_SECRET"])
    return {
        "client_id": resolved["SALESFORCE_CONSUMER_KEY"],
        "client_secret": resolved["SALESFORCE_CONSUMER_SECRET"],
    }


def salesforce_refresh_access_token(refresh_token: str, instance_url: str, *, capture: bool = True) -> str:
    # capture=False lets a caller keep this exchange out of HTTP sample capture: the request body
    # carries the refresh token and the shared client secret, and the response carries a freshly
    # minted access token, none of which the name-based scrubbers reliably redact.
    session = make_tracked_session(redact_values=(refresh_token,), capture=capture)
    # Resolved once, outside the loop: a retry is for a transient token-endpoint failure, and
    # re-reading the same credential on each attempt would add a hop per attempt for nothing.
    app_credentials = _salesforce_app_credentials()
    attempt = 0
    while True:
        try:
            res = session.post(
                f"{instance_url}/services/oauth2/token",
                data={
                    "grant_type": "refresh_token",
                    **app_credentials,
                    "refresh_token": refresh_token,
                },
            )
        except (RequestsConnectionError, RequestsTimeout):
            # A failed connection or timeout reaching the token endpoint — most often PostHog's
            # egress proxy returning a transient 502 on CONNECT — never minted a token, so it's safe
            # to reissue. Without this in-process retry a single proxy blip fails the whole import
            # activity before it reads a row, and the sync restarts from scratch.
            attempt += 1
            if attempt >= _MAX_TOKEN_REFRESH_ATTEMPTS:
                # A deleted org, or one whose My Domain was renamed, leaves an instance host with no
                # DNS record. That fails the same way on every run, so it must not stay retryable.
                if _instance_host_missing(instance_url):
                    raise SalesforceInstanceNotFoundError(INSTANCE_HOST_NOT_FOUND_ERROR) from None
                raise
            time.sleep(min(0.5 * attempt, 5))
            continue

        try:
            SalesforceAuthRequestError.raise_from_response(res)
        except SalesforceAuthRequestError as err:
            attempt += 1
            # A 5xx from the token endpoint (Salesforce's own maintenance page, an outage) never
            # minted a token either, so it's as safe to reissue as the connection failures above.
            transient = _TRANSIENT_TOKEN_REQUEST_ERROR in str(err) or err.response.status_code >= 500
            if attempt >= _MAX_TOKEN_REFRESH_ATTEMPTS or not transient:
                raise
            time.sleep(min(0.5 * attempt, 5))
            continue

        return res.json()["access_token"]


def get_salesforce_access_token_from_code(code: str, redirect_uri: str, instance_url: str) -> tuple[str, str]:
    res = make_tracked_session().post(
        f"{instance_url}/services/oauth2/token",
        data={
            "grant_type": "authorization_code",
            **_salesforce_app_credentials(),
            "redirect_uri": redirect_uri,
            "code": code,
        },
    )

    SalesforceAuthRequestError.raise_from_response(res)

    payload = res.json()

    return payload["access_token"], payload["refresh_token"]
