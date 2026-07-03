"""Hubspot source helpers"""

import urllib.parse
from collections.abc import Iterator
from http import HTTPStatus
from typing import Any, Optional

import requests
from requests.exceptions import JSONDecodeError as RequestsJSONDecodeError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

from .auth import HubspotRetryableError, hubspot_refresh_access_token
from .settings import OBJECT_TYPE_PLURAL

BASE_URL = "https://api.hubapi.com/"


def _is_retryable_status(status_code: int) -> bool:
    """Transient HubSpot statuses that warrant a backoff-and-retry rather than failing the sync.

    429 and 5xx are the usual transient signals. Unrecognised 4xx codes (e.g. the non-standard 477
    HubSpot's edge has been observed returning during brief incidents) aren't actionable client
    errors, so treat any unknown 4xx as transient too instead of crashing the import on it.
    """
    if status_code == 429 or status_code >= 500:
        return True
    if 400 <= status_code < 500:
        try:
            HTTPStatus(status_code)
        except ValueError:
            return True
    return False


def get_url(endpoint: str) -> str:
    """Get absolute hubspot endpoint URL"""
    return urllib.parse.urljoin(BASE_URL, endpoint)


def _get_headers(api_key: str) -> dict[str, str]:
    """
    Return a dictionary of HTTP headers to use for API requests, including the specified API key.

    Args:
        api_key (str): The API key to use for authentication, as a string.

    Returns:
        dict: A dictionary of HTTP headers to include in API requests, with the `Authorization` header
            set to the specified API key in the format `Bearer {api_key}`.

    """
    # Construct the dictionary of HTTP headers to use for API requests
    return {"authorization": f"Bearer {api_key}"}


def extract_property_history(objects: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for item in objects:
        history = item.get("propertiesWithHistory")
        if not history:
            return
        # Yield a flat list of property history entries
        for key, changes in history.items():
            if not changes:
                continue
            for entry in changes:
                yield {"object_id": item["id"], "property_name": key, **entry}


def fetch_property_history(
    endpoint: str,
    api_key: str,
    props: str,
    params: Optional[dict[str, Any]] = None,
) -> Iterator[list[dict[str, Any]]]:
    """Fetch property history from the given CRM endpoint.

    Args:
        endpoint: The endpoint to fetch data from, as a string.
        api_key: The API key to use for authentication, as a string.
        props: A comma separated list of properties to retrieve the history for
        params: Optional dict of query params to include in the request

    Yields:
         List of property history entries (dicts)
    """
    # Construct the URL and headers for the API request
    url = get_url(endpoint)
    headers = _get_headers(api_key)

    params = dict(params or {})
    params["propertiesWithHistory"] = props
    params["limit"] = 50
    # Make the API request
    r = make_tracked_session().get(url, headers=headers, params=params)
    # Parse the API response and yield the properties of each result

    # Parse the response JSON data
    _data = r.json()
    while _data is not None:
        if "results" in _data:
            yield list(extract_property_history(_data["results"]))

        # Follow pagination links if they exist
        _next = _data.get("paging", {}).get("next", None)
        if _next:
            next_url = _next["link"]
            # Get the next page response
            r = make_tracked_session().get(next_url, headers=headers)
            _data = r.json()
        else:
            _data = None


def fetch_data(
    endpoint: str,
    api_key: str,
    refresh_token: str,
    params: Optional[dict[str, Any]] = None,
    source_id: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    """
    Fetch data from HUBSPOT endpoint using a specified API key and yield the properties of each result.
    For paginated endpoint this function yields item from all pages.

    Args:
        endpoint (str): The endpoint to fetch data from, as a string.
        api_key (str): The API key to use for authentication, as a string.
        params: Optional dict of query params to include in the request

    Yields:
        A List of CRM object dicts

    Raises:
        requests.exceptions.HTTPError: If the API returns an HTTP error status code.

    Notes:
        This function uses the `requests` library to make a GET request to the specified endpoint, with
        the API key included in the headers. A 401 refreshes the access token; transient statuses
        (429, 5xx, and unrecognised non-standard 4xx codes) back off and retry. A permanent client
        error (e.g. 404 Not Found) raises `requests.exceptions.HTTPError`.

        The `endpoint` argument should be a relative URL, which will be appended to the base URL for the
        API. The `params` argument is used to pass additional query parameters to the request.
    """
    # Construct the URL and headers for the API request
    url = get_url(endpoint)
    headers = _get_headers(api_key)

    @retry(
        retry=retry_if_exception_type((HubspotRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def _get(page_url: str, query_params: Optional[dict[str, Any]]) -> dict:
        nonlocal api_key, headers
        r = make_tracked_session().get(page_url, headers=headers, params=query_params)

        if r.status_code == 401:
            api_key = hubspot_refresh_access_token(refresh_token, source_id=source_id)
            headers = _get_headers(api_key)
            raise HubspotRetryableError(f"Hubspot API 401 - refreshed token, retrying: url={page_url}")

        if _is_retryable_status(r.status_code):
            raise HubspotRetryableError(f"Hubspot API error (retryable): status={r.status_code}, url={page_url}")

        r.raise_for_status()

        # See hubspot.fetch_page: a truncated/partial body is transient, so retry rather than crash.
        try:
            return r.json()
        except RequestsJSONDecodeError as e:
            raise HubspotRetryableError(f"Hubspot API malformed JSON response (retryable): url={page_url}") from e

    _data: Optional[dict[str, Any]] = _get(url, params)
    # Yield the properties of each result in the API response
    while _data is not None:
        if "results" in _data:
            _objects: list[dict[str, Any]] = []
            for _result in _data["results"]:
                _obj = _result.get("properties", _result)
                if "id" not in _obj and "id" in _result:
                    # Move id from properties to top level
                    _obj["id"] = _result["id"]
                if "associations" in _result:
                    for association in _result["associations"]:
                        __values = [
                            {
                                "value": _obj["hs_object_id"],
                                f"{association}_id": __r["id"],
                            }
                            for __r in _result["associations"][association]["results"]
                        ]

                        # remove duplicates from list of dicts
                        __values = [dict(t) for t in {tuple(d.items()) for d in __values}]

                        _obj[association] = __values
                _objects.append(_obj)

            yield _objects

        # Follow pagination links if they exist
        _next = _data.get("paging", {}).get("next", None)
        if _next:
            _data = _get(_next["link"], None)
        else:
            _data = None


def _get_property_names(api_key: str, refresh_token: str, object_type: str, source_id: str | None = None) -> list[str]:
    """
    Retrieve property names for a given entity from the HubSpot API.

    Args:
        entity: The entity name for which to retrieve property names.

    Returns:
        A list of property names.

    Raises:
        Exception: If an error occurs during the API request.
    """
    properties = []
    endpoint = f"/crm/v3/properties/{OBJECT_TYPE_PLURAL[object_type]}"

    for page in fetch_data(endpoint, api_key, refresh_token, source_id=source_id):
        properties.extend([prop["name"] for prop in page])

    return properties
