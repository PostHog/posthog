from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.adroll.settings import ADROLL_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

ADROLL_BASE_URL = "https://services.adroll.com"
REQUEST_TIMEOUT_SECONDS = 60
# Quota is requests/day (default 100), so retry sparingly.
MAX_RETRY_ATTEMPTS = 3


class AdRollRetryableError(Exception):
    pass


def _get_session(personal_access_token: str) -> requests.Session:
    return make_tracked_session(
        headers={"Authorization": f"Token {personal_access_token}"},
        redact_values=(personal_access_token,),
    )


def validate_credentials(client_id: str, personal_access_token: str) -> bool:
    """Confirm the PAT + apikey pair is valid with a cheap organization probe."""
    try:
        response = _get_session(personal_access_token).get(
            f"{ADROLL_BASE_URL}/api/v1/organization/get?{urlencode({'apikey': client_id})}",
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    client_id: str,
    personal_access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = ADROLL_ENDPOINTS[endpoint]
    session = _get_session(personal_access_token)

    @retry(
        retry=retry_if_exception_type((AdRollRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=5, max=120),
        reraise=True,
    )
    def fetch(path: str, params: dict[str, Any]) -> dict[str, Any]:
        # Every request needs the app's Client ID as the apikey param, even
        # with PAT auth.
        url = f"{ADROLL_BASE_URL}{path}?{urlencode({**params, 'apikey': client_id})}"
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise AdRollRetryableError(f"AdRoll API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"AdRoll API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    def advertisable_eids() -> list[str]:
        data = fetch(ADROLL_ENDPOINTS["advertisables"].path, {})
        results = data.get("results", []) or []
        return [item["eid"] for item in results if item.get("eid")]

    if not config.advertisable_scoped:
        data = fetch(config.path, {})
        items = data.get("results", []) or []
        if items:
            yield items
        return

    # advertisable_scoped endpoints always define a parent_key (enforced in
    # AdRollEndpointConfig.__post_init__); narrow the Optional for the row build.
    parent_key = config.parent_key
    assert parent_key is not None
    for eid in advertisable_eids():
        data = fetch(config.path, {"advertisable": eid})
        items = [{**item, parent_key: eid} for item in (data.get("results", []) or [])]
        if items:
            yield items


def adroll_source(
    client_id: str,
    personal_access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = ADROLL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            client_id=client_id,
            personal_access_token=personal_access_token,
            endpoint=endpoint,
            logger=logger,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
