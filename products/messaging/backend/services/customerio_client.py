import base64
import logging
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


class CustomerIOAPIError(Exception):
    pass


class CustomerIOClient:
    """Client for interacting with Customer.io App API"""

    US_BASE_URL = "https://api.customer.io/v1"
    EU_BASE_URL = "https://beta-api-eu.customer.io/v1"

    def __init__(self, app_api_key: str, region: str = "us", timeout: int = 30):
        self.api_key = app_api_key
        self.timeout = timeout
        self.BASE_URL = self.EU_BASE_URL if region.lower() == "eu" else self.US_BASE_URL
        self.session = requests.Session()
        # Don't store credentials in session headers - add them per request instead
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        json_data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Make an API request to Customer.io"""
        url = f"{self.BASE_URL}{endpoint}"

        try:
            # Add Authorization header per request instead of storing in session
            headers = {"Authorization": f"Bearer {self.api_key}"}
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            if response.status_code == 204:
                return {}
            return response.json()
        except requests.exceptions.HTTPError as e:
            error_msg = f"Customer.io API error: {e}"
            if hasattr(e, "response") and e.response:
                # Do NOT log response text to avoid leaking sensitive information
                status_info = f"Status: {e.response.status_code}"
                logger.exception(f"API request failed. {error_msg}. {status_info}")
            else:
                logger.exception(f"API request failed. {error_msg}")
            raise CustomerIOAPIError(error_msg)
        except requests.exceptions.RequestException as e:
            raise CustomerIOAPIError(f"Request failed: {e}")

    def get_subscription_topics(self) -> list[dict[str, Any]]:
        # Note: Customer.io uses 'subscription_topics' endpoint
        response = self._make_request("GET", "/subscription_topics")
        # The response contains topics in a 'topics' field
        return response.get("topics", [])

    def search_customers(
        self, filter_conditions: dict[str, Any], limit: int = 1000, start: Optional[str] = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": min(limit, 1000)}
        if start:
            params["start"] = start

        json_data = {"filter": filter_conditions}

        result = self._make_request("POST", "/customers", params=params, json_data=json_data)
        return result

    def get_globally_unsubscribed_customers(self, limit: int = 1000, start: Optional[str] = None) -> dict[str, Any]:
        filter_conditions = {"attribute": {"field": "unsubscribed", "operator": "eq", "value": True}}
        return self.search_customers(filter_conditions, limit, start)

    def validate_credentials(self) -> bool:
        try:
            # Try a simple API call to validate credentials
            # Using subscription_topics to check authentication
            self._make_request("GET", "/subscription_topics")
            return True
        except CustomerIOAPIError as e:
            logger.exception(f"Credential validation failed: {e}")
            # Try to provide more helpful error message
            if "401" in str(e):
                logger.exception(
                    "Authentication failed - please ensure you're using an App API key from Customer.io Settings > API Credentials > App API Keys"
                )
            elif "403" in str(e):
                logger.exception("Authorization failed - the API key may not have the required permissions")
            return False


class CustomerIOTrackClient:
    """Client for Customer.io Track API v2 — used to push preference changes back to Customer.io."""

    US_TRACK_URL = "https://track.customer.io"
    EU_TRACK_URL = "https://track-eu.customer.io"

    def __init__(self, site_id: str, api_key: str, region: str = "us", timeout: int = 30):
        self.site_id = site_id
        self.api_key = api_key
        self.timeout = timeout
        base = self.EU_TRACK_URL if region.lower() == "eu" else self.US_TRACK_URL
        self.entity_url = f"{base}/api/v2/entity"
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

    def _auth_header(self) -> dict[str, str]:
        token = base64.b64encode(f"{self.site_id}:{self.api_key}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def _identify(self, email: str, attributes: dict[str, Any]) -> None:
        payload: dict[str, Any] = {
            "type": "person",
            "identifiers": {"email": email},
            "action": "identify",
            "attributes": attributes,
        }
        try:
            resp = self.session.post(
                self.entity_url,
                json=payload,
                headers=self._auth_header(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            status_info = f"Status: {e.response.status_code}" if e.response is not None else ""
            logger.exception(f"Customer.io Track API error: {e}. {status_info}")
            raise CustomerIOAPIError(f"Track API error: {e}")
        except requests.exceptions.RequestException as e:
            raise CustomerIOAPIError(f"Track API request failed: {e}")

    def update_subscription_preferences(self, email: str, topic_prefs: dict[str, bool]) -> None:
        """Update per-topic subscription preferences using dot-notation (preserves other topics)."""
        if not topic_prefs:
            return
        attributes: dict[str, Any] = {
            f"cio_subscription_preferences.topics.{topic_key}": subscribed
            for topic_key, subscribed in topic_prefs.items()
        }
        self._identify(email, attributes)

    def set_global_unsubscribe(self, email: str, unsubscribed: bool) -> None:
        self._identify(email, {"unsubscribed": unsubscribed})
