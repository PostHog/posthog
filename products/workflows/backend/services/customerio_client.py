import time
import logging
from collections.abc import Generator
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


class CustomerIOAPIError(Exception):
    """Customer.io API related errors"""

    pass


class CustomerIOClient:
    """Client for interacting with Customer.io App API"""

    BASE_URL = "https://api.customer.io/v1"

    def __init__(self, app_api_key: str, timeout: int = 30):
        """
        Initialize Customer.io client with App API key
        Args:
            app_api_key: Bearer token from Customer.io App API
            timeout: Request timeout in seconds
        """
        self.api_key = app_api_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {"Authorization": f"Bearer {app_api_key}", "Accept": "application/json", "Content-Type": "application/json"}
        )

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
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                timeout=self.timeout,
            )
            response.raise_for_status()
            if response.status_code == 204:
                return {}
            return response.json()
        except requests.exceptions.HTTPError as e:
            error_msg = f"Customer.io API error: {e}"
            if hasattr(e.response, "text"):
                error_msg = f"{error_msg}. Response: {e.response.text}"
            raise CustomerIOAPIError(error_msg)
        except requests.exceptions.RequestException as e:
            raise CustomerIOAPIError(f"Request failed: {e}")

    def get_subscription_centers(self) -> list[dict[str, Any]]:
        """
        Fetch all subscription centers from Customer.io
        Returns:
            List of subscription center configurations
        """
        response = self._make_request("GET", "/subscription_centers")
        return response.get("subscription_centers", [])

    def get_subscription_center_topics(self, subscription_center_id: str) -> list[dict[str, Any]]:
        """
        Fetch topics for a specific subscription center
        Args:
            subscription_center_id: ID of the subscription center
        Returns:
            List of topics with their configuration
        """
        response = self._make_request("GET", f"/subscription_centers/{subscription_center_id}")
        return response.get("subscription_center", {}).get("topics", [])

    def get_customer_subscription_preferences(self, identifier: str, id_type: str = "email") -> dict[str, Any]:
        """
        Get subscription preferences for a specific customer
        Args:
            identifier: Customer identifier (email, id, or cio_id)
            id_type: Type of identifier ("email", "id", or "cio_id")
        Returns:
            Dictionary containing subscription preferences
        """
        params = {"id_type": id_type} if id_type != "cio_id" else {}
        response = self._make_request("GET", f"/customers/{identifier}/subscription_preferences", params=params)
        return response

    def search_customers(
        self, filter_conditions: dict[str, Any], limit: int = 50, start: Optional[str] = None
    ) -> dict[str, Any]:
        """
        Search for customers using filter conditions
        Args:
            filter_conditions: Filter conditions for the search
            limit: Number of results per page (max 100)
            start: Pagination cursor
        Returns:
            Search results with customers and pagination info
        """
        params = {"limit": min(limit, 100)}
        if start:
            params["start"] = start
        json_data = {"filter": filter_conditions}
        return self._make_request("POST", "/customers", params=params, json_data=json_data)

    def get_all_customers_with_preferences(self, batch_size: int = 50) -> Generator[dict[str, Any], None, None]:
        """
        Fetch all customers who have opted out of any topics
        Args:
            batch_size: Number of customers to fetch per API call
        Yields:
            Customer data with email and subscription preferences
        """
        start = None
        # Search for customers who have any subscription preferences set
        filter_conditions = {"and": [{"attribute": {"field": "cio_subscription_preferences", "operator": "exists"}}]}
        while True:
            try:
                response = self.search_customers(filter_conditions, limit=batch_size, start=start)
                customers = response.get("customers", [])

                if not customers:
                    break

                for customer in customers:
                    # Extract relevant data
                    email = customer.get("email")
                    if email:
                        preferences = customer.get("attributes", {}).get("cio_subscription_preferences", {})
                        yield {
                            "email": email,
                            "id": customer.get("id"),
                            "cio_id": customer.get("cio_id"),
                            "preferences": preferences,
                        }

                # Check for next page
                next_cursor = response.get("next")
                if not next_cursor:
                    break

                # Extract start parameter from next URL
                if "start=" in next_cursor:
                    start = next_cursor.split("start=")[-1].split("&")[0]
                else:
                    break

                # Rate limiting
                time.sleep(0.1)

            except CustomerIOAPIError as e:
                # Log error and break
                logger.exception(f"Error fetching customers: {e}")
                break

    def validate_credentials(self) -> bool:
        """
        Validate if the provided credentials are valid
        Returns:
            True if credentials are valid, False otherwise
        """
        try:
            # Try to fetch subscription centers as a validation check
            self._make_request("GET", "/subscription_centers")
            return True
        except CustomerIOAPIError:
            return False
