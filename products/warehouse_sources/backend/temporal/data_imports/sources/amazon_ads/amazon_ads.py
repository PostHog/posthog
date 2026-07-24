from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_ads.settings import AMAZON_ADS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

AMAZON_ADS_HOSTS = {
    "na": "https://advertising-api.amazon.com",
    "eu": "https://advertising-api-eu.amazon.com",
    "fe": "https://advertising-api-fe.amazon.com",
}
# Login with Amazon token endpoint is global.
LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
PAGE_SIZE = 500
REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRY_ATTEMPTS = 5


class AmazonAdsRetryableError(Exception):
    pass


def _get_session(client_secret: str, refresh_token: str, client_id: str) -> requests.Session:
    return make_tracked_session(
        headers={"Amazon-Advertising-API-ClientId": client_id},
        redact_values=(client_secret, refresh_token),
    )


def _base_url(region: str) -> str:
    host = AMAZON_ADS_HOSTS.get(region)
    if host is None:
        raise ValueError(f"Invalid Amazon Ads region: {region}")
    return host


def _mint_token(session: requests.Session, client_id: str, client_secret: str, refresh_token: str) -> str:
    """Exchange the LWA refresh token for a ~1h access token."""
    response = session.post(
        LWA_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def validate_credentials(region: str, client_id: str, client_secret: str, refresh_token: str) -> bool:
    """Confirm the LWA credentials are valid by minting a token and listing profiles."""
    try:
        _base_url(region)
        session = _get_session(client_secret, refresh_token, client_id)
        token = _mint_token(session, client_id, client_secret, refresh_token)
        response = session.get(
            f"{_base_url(region)}/v2/profiles",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    region: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = AMAZON_ADS_ENDPOINTS[endpoint]
    session = _get_session(client_secret, refresh_token, client_id)
    base_url = _base_url(region)
    token = _mint_token(session, client_id, client_secret, refresh_token)

    @retry(
        retry=retry_if_exception_type((AmazonAdsRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=120),
        reraise=True,
    )
    def request(
        method: str, path: str, profile_id: Optional[str] = None, body: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        nonlocal token
        url = f"{base_url}{path}"

        def _do() -> requests.Response:
            headers: dict[str, str] = {"Authorization": f"Bearer {token}"}
            if profile_id is not None:
                headers["Amazon-Advertising-API-Scope"] = profile_id
            if config.media_type is not None and method == "POST":
                headers["Content-Type"] = config.media_type
                headers["Accept"] = config.media_type
            if method == "POST":
                return session.post(url, json=body or {}, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
            return session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        response = _do()
        # Access tokens last ~1h; re-mint once if the sync outlives one.
        if response.status_code == 401:
            token = _mint_token(session, client_id, client_secret, refresh_token)
            response = _do()

        if response.status_code == 429 or response.status_code >= 500:
            raise AmazonAdsRetryableError(f"Amazon Ads API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Amazon Ads API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response

    def list_profiles() -> list[dict[str, Any]]:
        body = request("GET", "/v2/profiles").json()
        return body if isinstance(body, list) else []

    if endpoint == "profiles":
        profiles = list_profiles()
        if profiles:
            yield profiles
        return

    # Sponsored Products v3 list endpoints, fanned out per profile.
    profile_ids = [str(profile["profileId"]) for profile in list_profiles()]

    for profile_id in profile_ids:
        next_token: Optional[str] = None
        while True:
            body: dict[str, Any] = {"maxResults": PAGE_SIZE}
            if next_token:
                body["nextToken"] = next_token
            data = request("POST", config.path, profile_id=profile_id, body=body).json()
            items = [{**item, "_profile_id": profile_id} for item in (data.get(config.data_key, []) or [])]

            if items:
                yield items

            next_token = data.get("nextToken")
            if not next_token or not items:
                break


def amazon_ads_source(
    region: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = AMAZON_ADS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            region=region,
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            endpoint=endpoint,
            logger=logger,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
