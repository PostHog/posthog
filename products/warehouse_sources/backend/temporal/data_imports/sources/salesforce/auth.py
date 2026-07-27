import time
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from django.conf import settings

from requests import Response
from requests.exceptions import JSONDecodeError

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


# Salesforce serializes OAuth token requests per connected app: when a refresh for the same app
# arrives while another is still in flight (parallel schema syncs sharing one connection commonly
# do this), it rejects the duplicate with a 400 "token request is already being processed". The
# lock clears in moments, so a short in-process backoff recovers without failing the whole import
# activity — which would otherwise restart pagination and surface captured error-tracking noise.
_TRANSIENT_TOKEN_REQUEST_ERROR = "token request is already being processed"
_MAX_TOKEN_REFRESH_ATTEMPTS = 4


def salesforce_refresh_access_token(refresh_token: str, instance_url: str) -> str:
    attempt = 0
    while True:
        res = make_tracked_session().post(
            f"{instance_url}/services/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "client_id": settings.SALESFORCE_CONSUMER_KEY,
                "client_secret": settings.SALESFORCE_CONSUMER_SECRET,
                "refresh_token": refresh_token,
            },
        )

        try:
            SalesforceAuthRequestError.raise_from_response(res)
        except SalesforceAuthRequestError as err:
            attempt += 1
            if attempt >= _MAX_TOKEN_REFRESH_ATTEMPTS or _TRANSIENT_TOKEN_REQUEST_ERROR not in str(err):
                raise
            time.sleep(min(0.5 * attempt, 5))
            continue

        return res.json()["access_token"]


def get_salesforce_access_token_from_code(code: str, redirect_uri: str, instance_url: str) -> tuple[str, str]:
    res = make_tracked_session().post(
        f"{instance_url}/services/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": settings.SALESFORCE_CONSUMER_KEY,
            "client_secret": settings.SALESFORCE_CONSUMER_SECRET,
            "redirect_uri": redirect_uri,
            "code": code,
        },
    )

    SalesforceAuthRequestError.raise_from_response(res)

    payload = res.json()

    return payload["access_token"], payload["refresh_token"]
