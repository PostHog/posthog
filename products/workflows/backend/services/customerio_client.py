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
        self, filter_conditions: dict[str, Any], limit: int = 50, start: Optional[str] = None
    ) -> dict[str, Any]:
        """
        Search for customers using filter conditions
        NOTE: Customer.io's /customers endpoint requires specific filter syntax.
        
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
        
        logger.info(f"Searching customers with params: {params}, filter: {filter_conditions}")
        result = self._make_request("POST", "/customers", params=params, json_data=json_data)
        logger.info(f"Customer search returned: {result.keys() if result else 'None'}")
        return result
    
    def search_customers_opted_out_of_topic(
        self, topic_id: str, limit: int = 50, start: Optional[str] = None
    ) -> dict[str, Any]:
        """
        Search for customers who have opted out of a specific topic
        
        Args:
            topic_id: The topic ID to search for opt-outs
            limit: Number of results per page (max 100)
            start: Pagination cursor
        Returns:
            Search results with customers who opted out of this topic
        """
        filter_conditions = {
            "or": [
                # Globally unsubscribed
                {"attribute": {"field": "unsubscribed", "operator": "eq", "value": True}},
                # Or specifically opted out of this topic
                {"attribute": {"field": f"topics.{topic_id}.subscribed", "operator": "eq", "value": False}}
            ]
        }
        return self.search_customers(filter_conditions, limit, start)

    def get_opted_out_customers_for_topics(
        self, topic_ids: list[str], batch_size: int = 50
    ) -> dict[str, list[str]]:
        """
        Get all customers who have opted out of each topic
        
        Args:
            topic_ids: List of topic IDs to check
            batch_size: Number of customers to fetch per API call
        Returns:
            Dictionary mapping topic_id -> list of email addresses opted out
        """
        print(f"[DEBUG] get_opted_out_customers_for_topics called with topics: {topic_ids}")
        opt_outs_by_topic = {}
        
        logger.info(f"Starting to fetch opt-outs for {len(topic_ids)} topics: {topic_ids}")
        print(f"[DEBUG] After first log statement")
        
        if not topic_ids:
            logger.warning("No topic IDs provided, returning empty dict")
            return opt_outs_by_topic
        
        for i, topic_id in enumerate(topic_ids):
            print(f"[DEBUG] Starting loop for topic {i+1}/{len(topic_ids)}: {topic_id}")
            logger.info(f"Processing topic {i+1}/{len(topic_ids)}: {topic_id}")
            opted_out_emails = []
            start = None
            page = 0
            
            while True:
                page += 1
                try:
                    print(f"[DEBUG] Topic {topic_id}: About to fetch page {page}")
                    logger.info(f"Topic {topic_id}: Fetching page {page}, start cursor: {start}")
                    
                    # Search for customers opted out of this topic
                    print(f"[DEBUG] Calling search_customers_opted_out_of_topic for topic {topic_id}")
                    response = self.search_customers_opted_out_of_topic(topic_id, limit=batch_size, start=start)
                    print(f"[DEBUG] Response received for topic {topic_id}")
                    
                    logger.info(f"Topic {topic_id}: API response keys: {response.keys() if response else 'None'}")
                    
                    identifiers = response.get("identifiers", [])
                    logger.info(f"Topic {topic_id}: Page {page} returned {len(identifiers)} customers")
                    
                    # Add emails to the list
                    email_count = 0
                    for customer_info in identifiers:
                        email = customer_info.get("email")
                        if email:
                            opted_out_emails.append(email)
                            email_count += 1
                    
                    logger.info(f"Topic {topic_id}: Added {email_count} emails from page {page}")
                    
                    # Check for next page
                    next_cursor = response.get("next")
                    logger.info(f"Topic {topic_id}: Next cursor: {next_cursor}")
                    
                    if not next_cursor or next_cursor == "":
                        logger.info(f"Topic {topic_id}: No more pages, finishing")
                        break
                    start = next_cursor
                    
                    # Rate limiting to avoid hitting API limits
                    time.sleep(0.1)
                    
                except CustomerIOAPIError as e:
                    logger.error(f"Error fetching opt-outs for topic {topic_id} on page {page}: {e}")
                    break
                except Exception as e:
                    logger.exception(f"Unexpected error fetching opt-outs for topic {topic_id} on page {page}: {e}")
                    break
            
            opt_outs_by_topic[str(topic_id)] = opted_out_emails
            logger.info(f"Completed topic {topic_id}: Total {len(opted_out_emails)} customers opted out")
        
        logger.info(f"Finished fetching all opt-outs. Summary: {[(t, len(emails)) for t, emails in opt_outs_by_topic.items()]}")
        return opt_outs_by_topic
    
    def get_all_customers_with_preferences(self, batch_size: int = 50) -> Generator[dict[str, Any], None, None]:
        """
        Fetch all customers and their subscription preferences
        Args:
            batch_size: Number of customers to fetch per API call
        Yields:
            Customer data with email and subscription preferences
        """
        start = None
        # First, get all customers (we'll check their preferences individually)
        logger.info(f"Starting to fetch customers with batch size {batch_size}")
        has_yielded_any = False
        customer_total = 0
        
        while True:
            try:
                # Get a batch of customers
                logger.info(f"Fetching customer batch, start cursor: {start}")
                response = self.search_customers(limit=batch_size, start=start)
                
                # Response has 'identifiers' field with customer data
                if response:
                    logger.info(f"Customer search response keys: {response.keys()}")
                
                identifiers = response.get("identifiers", [])
                logger.info(f"Got {len(identifiers)} unsubscribed customers in this batch")

                if not identifiers:
                    break

                # For each unsubscribed customer, fetch their subscription preferences
                for customer_info in identifiers:
                    email = customer_info.get("email")
                    if not email:
                        continue
                    
                    customer_total += 1
                    logger.info(f"Processing unsubscribed customer #{customer_total}: {email}")
                    
                    try:
                        # Get subscription preferences for this customer
                        pref_response = self.get_customer_subscription_preferences(email, id_type="email")
                        
                        # Extract the customer data and topics
                        customer_data = pref_response.get("customer", {})
                        topics_list = customer_data.get("topics", [])
                        
                        # Convert topics list to dict format for compatibility
                        # Since these are globally unsubscribed customers, we treat them as opted out of ALL topics
                        topics_dict = {}
                        for topic in topics_list:
                            topic_id = topic.get("id")
                            # For globally unsubscribed customers, mark all topics as opted out
                            # Use both numeric ID and topic_N format for compatibility
                            topics_dict[f"topic_{topic_id}"] = False  # Opted out
                            topics_dict[str(topic_id)] = False  # Opted out
                        
                        # Yield the customer data (we know they're globally unsubscribed)
                        logger.info(f"Customer {email} (globally unsubscribed) marked as opted out of all topics: {topics_dict}")
                        has_yielded_any = True
                        yield {
                            "email": email,
                            "id": customer_info.get("id"),
                            "cio_id": customer_info.get("cio_id"),
                            "preferences": {"topics": topics_dict}
                        }
                    except CustomerIOAPIError as e:
                        # Skip customers we can't fetch preferences for
                        logger.warning(f"Could not fetch preferences for {email}: {e}")
                        continue

                # Check for next page
                next_cursor = response.get("next")
                if not next_cursor:
                    break
                    
                start = next_cursor

                # Rate limiting to avoid hitting API limits
                time.sleep(0.1)

            except CustomerIOAPIError as e:
                # Log error and break
                logger.exception(f"Error fetching customers: {e}")
                break
        
        logger.info(f"Finished fetching customers. Total processed: {customer_total}, Yielded any: {has_yielded_any}")

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
            logger.info(f"Credential validation successful")
            return True
        except CustomerIOAPIError as e:
            logger.error(f"Credential validation failed: {e}")
            # Try to provide more helpful error message
            if "401" in str(e):
                logger.error("Authentication failed - please ensure you're using an App API key from Customer.io Settings > API Credentials > App API Keys")
            elif "403" in str(e):
                logger.error("Authorization failed - the API key may not have the required permissions")
            return False
