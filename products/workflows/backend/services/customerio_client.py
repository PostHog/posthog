import logging
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


class CustomerIOAPIError(Exception):
    """Customer.io API related errors"""

    pass


class CustomerIOClient:
    """Client for interacting with Customer.io App API"""

    US_BASE_URL = "https://api.customer.io/v1"
    EU_BASE_URL = "https://beta-api-eu.customer.io/v1"

    def __init__(self, app_api_key: str, region: str = "us", timeout: int = 30):
        """
        Initialize Customer.io client with App API key
        Args:
            app_api_key: App API key from Customer.io
            region: Region for the API endpoint ("us" or "eu")
            timeout: Request timeout in seconds
        """
        self.api_key = app_api_key
        self.timeout = timeout
        self.BASE_URL = self.EU_BASE_URL if region.lower() == "eu" else self.US_BASE_URL
        self.session = requests.Session()
        # Customer.io App API uses the key directly as Bearer token
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
            if hasattr(e, "response") and e.response:
                error_msg = f"{error_msg}. Status: {e.response.status_code}. Response: {e.response.text}"
            logger.error(f"API request failed: {error_msg}")
            raise CustomerIOAPIError(error_msg)
        except requests.exceptions.RequestException as e:
            raise CustomerIOAPIError(f"Request failed: {e}")

    def get_subscription_centers(self) -> list[dict[str, Any]]:
        """
        Fetch all subscription topics from Customer.io
        Returns:
            List of subscription topics
        """
        # Note: Customer.io uses 'subscription_topics' endpoint
        response = self._make_request("GET", "/subscription_topics")
        # The response contains topics in a 'topics' field
        return response.get("topics", [])

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
        self, filter_conditions: dict[str, Any], limit: int = 1000, start: Optional[str] = None
    ) -> dict[str, Any]:
        """
        Search for customers using filter conditions
        NOTE: Customer.io's /customers endpoint requires specific filter syntax.
        
        Args:
            filter_conditions: Filter conditions for the search
            limit: Number of results per page (max 1000)
            start: Pagination cursor
        Returns:
            Search results with customers and pagination info
        """
        params = {"limit": min(limit, 1000)}
        if start:
            params["start"] = start
        
        json_data = {"filter": filter_conditions}
        
        result = self._make_request("POST", "/customers", params=params, json_data=json_data)
        return result
    
    def get_globally_unsubscribed_customers(
        self, limit: int = 1000, start: Optional[str] = None
    ) -> dict[str, Any]:
        """
        Fetch customers who are globally unsubscribed (unsubscribed=true)
        These customers are opted out of ALL topics/categories
        
        Args:
            limit: Number of results per page (max 1000)
            start: Pagination cursor
        Returns:
            Search results with globally unsubscribed customers
        """
        filter_conditions = {
            "attribute": {"field": "unsubscribed", "operator": "eq", "value": True}
        }
        return self.search_customers(filter_conditions, limit, start)
    
    def get_customers_with_preferences(
        self, limit: int = 1000, start: Optional[str] = None
    ) -> dict[str, Any]:
        """
        Fetch customers who have subscription preference attributes set
        These contain JSON with topic-specific opt-out settings
        
        Args:
            limit: Number of results per page (max 1000)
            start: Pagination cursor
        Returns:
            Search results with customers who have preference attributes
        """
        filter_conditions = {
            "or": [
                {"attribute": {"field": "cio_subscription_preferences", "operator": "exists", "value": True}},
                {"attribute": {"field": "_cio_subscription_preferences_computed", "operator": "exists", "value": True}}
            ]
        }
        return self.search_customers(filter_conditions, limit, start)
    
    def search_for_specific_customer(self, email: str) -> dict[str, Any]:
        """
        Search for a specific customer by email to debug
        
        Args:
            email: Email address to search for
        Returns:
            Search results for that specific customer
        """
        filter_conditions = {
            "and": [
                {"attribute": {"field": "email", "operator": "eq", "value": email}},
                {
                    "or": [
                        {"attribute": {"field": "cio_subscription_preferences", "operator": "exists", "value": True}},
                        {"attribute": {"field": "_cio_subscription_preferences_computed", "operator": "exists", "value": True}}
                    ]
                }
            ]
        }
        return self.search_customers(filter_conditions, limit=1)
    
    def get_customer_attributes(self, identifier: str, id_type: str = "cio_id") -> dict[str, Any]:
        """
        Get all attributes for a specific customer
        Used to fetch the full attribute set including JSON preference data
    
        Args:
            identifier: Customer identifier (email, id, or cio_id)
            id_type: Type of identifier ("email", "id", or "cio_id")
        Returns:
            Dictionary containing all customer attributes
        """
        params = {"id_type": id_type} if id_type != "cio_id" else {}
        response = self._make_request("GET", f"/customers/{identifier}/attributes", params=params)
        return response


    def validate_credentials(self) -> bool:
        """
        Validate if the provided credentials are valid
        Returns:
            True if credentials are valid, False otherwise
        """
        try:
            # Try a simple API call to validate credentials
            # Using subscription_topics to check authentication
            response = self._make_request("GET", "/subscription_topics")
            return True
        except CustomerIOAPIError as e:
            logger.error(f"Credential validation failed: {e}")
            # Try to provide more helpful error message
            if "401" in str(e):
                logger.error("Authentication failed - please ensure you're using an App API key from Customer.io Settings > API Credentials > App API Keys")
            elif "403" in str(e):
                logger.error("Authorization failed - the API key may not have the required permissions")
            return False
