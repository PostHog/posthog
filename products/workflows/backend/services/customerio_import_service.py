import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from django.db import transaction

logger = logging.getLogger(__name__)

from posthog.models import MessageCategory, MessageRecipientPreference, Team
from posthog.models.message_category import MessageCategoryType
from posthog.models.message_preferences import PreferenceStatus

from .customerio_client import CustomerIOClient


class CustomerIOImportService:
    """Service for importing Customer.io topics and preferences into PostHog"""

    def __init__(self, team: Team, api_key: str, user):
        self.team = team
        self.user = user
        self.client = None
        self.api_key = api_key
        self.topic_mapping = {}  # Maps Customer.io topic IDs to PostHog MessageCategory IDs
        self.topic_names = {}  # Maps topic IDs to their display names
        self.progress = {
            "status": "initializing",
            "topics_found": 0,
            "categories_created": 0,
            "customers_processed": 0,
            "preferences_updated": 0,
            "globally_unsubscribed_count": 0,
            "preference_users_count": 0,
            "current_batch": 0,
            "customers_in_current_batch": 0,
            "errors": [],
            "details": "",
        }

    def import_all(self) -> dict[str, Any]:
        try:
            # Step 1: Validate credentials
            self.progress["status"] = "validating_credentials"
            self.progress["details"] = "Validating Customer.io API credentials..."

            # Try US region first
            self.client = CustomerIOClient(self.api_key, region="us")
            if self.client.validate_credentials():
                self.progress["status"] = "validated"
            else:
                # Try EU region
                self.client = CustomerIOClient(self.api_key, region="eu")
                if not self.client.validate_credentials():
                    self.progress["status"] = "failed"
                    self.progress["errors"].append(
                        "Invalid Customer.io API credentials. Please check: 1) You're using an App API key from Settings > API Credentials > App API Keys, 2) The key has not expired, 3) You've copied the complete key"
                    )
                    return self.progress

            # Step 2: Import subscription topics as categories
            self.progress["status"] = "creating_categories"
            self.progress["details"] = "Fetching subscription topics from Customer.io..."
            topics = self.client.get_subscription_centers()

            if not topics:
                self.progress["errors"].append("No subscription topics found in Customer.io")
                self.progress["status"] = "completed"
                return self.progress

            self.progress["topics_found"] = len(topics)
            self.progress["details"] = f"Creating {len(topics)} message categories..."
            self._import_categories(topics)

            # Step 3: Process globally unsubscribed users
            self.progress["status"] = "processing_globally_unsubscribed"
            self.progress["details"] = "Processing globally unsubscribed users..."
            self._process_globally_unsubscribed_users()

            # Step 4: Process users with subscription preferences
            self.progress["status"] = "processing_preference_users"
            self.progress["details"] = "Processing users with subscription preferences..."
            self._process_users_with_preferences()

            self.progress["status"] = "completed"
            self.progress["details"] = "Import completed successfully"

        except Exception as e:
            self.progress["status"] = "failed"
            self.progress["errors"].append(str(e))
            logger.exception("Import failed with error")

        return self.progress

    def _import_categories(self, topics: list[dict[str, Any]]) -> None:
        """Import Customer.io topics as message categories"""
        for topic in topics:
            try:
                topic_id = topic.get("id")
                topic_identifier = topic.get("identifier", f"topic_{topic_id}")
                topic_name = topic.get("name", f"Topic {topic_id}")
                topic_key = f"customerio_{topic_identifier}"
                description = topic.get("description", "")
                public_description = topic.get("public_description", description)

                # Determine category type
                category_type = MessageCategoryType.MARKETING
                if topic.get("transactional", False):
                    category_type = MessageCategoryType.TRANSACTIONAL

                # Create or update the MessageCategory
                with transaction.atomic():
                    category, created = MessageCategory.objects.update_or_create(
                        team=self.team,
                        key=topic_key,
                        defaults={
                            "name": topic_name,
                            "description": description,
                            "public_description": public_description,
                            "category_type": category_type,
                            "created_by": self.user,
                            "deleted": False,
                        },
                    )

                # Store mappings for both identifier and numeric ID
                self.topic_mapping[topic_identifier] = str(category.id)
                self.topic_mapping[str(topic_id)] = str(category.id)
                self.topic_names[str(topic_id)] = topic_name

                self.progress["categories_created"] += 1

            except Exception as e:
                self.progress["errors"].append(f"Failed to import topic {topic_id}: {str(e)}")

    def _process_globally_unsubscribed_users(self) -> None:
        """Process users who are globally unsubscribed (opted out of ALL categories)"""
        if not self.topic_mapping:
            return

        start = None
        batch_num = 0
        total_processed = 0
        all_category_ids = list(set(self.topic_mapping.values()))
        
        print(f"\n=== Starting to process globally unsubscribed users ===")
        print(f"Will opt out from {len(all_category_ids)} categories")

        while True:
            batch_num += 1
            self.progress["current_batch"] = batch_num

            try:
                # Fetch batch of globally unsubscribed customers
                print(f"\nBatch {batch_num}: Fetching globally unsubscribed (start={start})...")
                response = self.client.get_globally_unsubscribed_customers(limit=1000, start=start)
                identifiers = response.get("identifiers", [])

                if not identifiers:
                    print(f"Batch {batch_num}: No more globally unsubscribed users found")
                    break

                print(f"Batch {batch_num}: Found {len(identifiers)} globally unsubscribed users")
                self.progress["customers_in_current_batch"] = len(identifiers)
                self.progress["details"] = f"Processing batch {batch_num} of globally unsubscribed users ({len(identifiers)} users)..."

                # Collect emails for this batch
                emails_to_process = []
                for customer_info in identifiers:
                    email = customer_info.get("email")
                    if email:
                        emails_to_process.append(email)

                if emails_to_process:
                    # Bulk update: opt out these users from ALL categories
                    self._bulk_update_all_preferences(emails_to_process, all_category_ids)
                    
                    batch_processed = len(emails_to_process)
                    total_processed += batch_processed
                    self.progress["globally_unsubscribed_count"] += batch_processed
                    self.progress["customers_processed"] += batch_processed
                    # Each user gets opted out of all categories
                    self.progress["preferences_updated"] += batch_processed * len(all_category_ids)

                # Check for next page
                next_cursor = response.get("next")
                print(f"Batch {batch_num}: Next cursor = '{next_cursor}'")
                if not next_cursor or next_cursor == "":
                    print(f"Batch {batch_num}: No next cursor, stopping")
                    break
                start = next_cursor

            except Exception as e:
                print(f"Error in batch {batch_num}: {e}")
                self.progress["errors"].append(f"Error processing globally unsubscribed batch {batch_num}: {str(e)[:200]}")
                break

        print(f"\n=== Finished processing globally unsubscribed users ===")
        print(f"Total processed: {total_processed}")
        self.progress["details"] = f"Processed {total_processed} globally unsubscribed users"

    def _process_users_with_preferences(self) -> None:
        """Process users who have subscription preference attributes"""
        if not self.topic_mapping:
            return

        start = None
        batch_num = 0
        total_processed = 0
        total_fetched = 0  # Track total customers fetched from API

        print(f"\n=== Starting to process users with preferences ===")
        print(f"Topic mapping: {self.topic_mapping}")
        
        # Debug: Check if specific user can be found
        print("\n=== Checking for david.bai@openrouter.ai ===")
        try:
            test_response = self.client.search_for_specific_customer("david.bai@openrouter.ai")
            if test_response.get("identifiers"):
                print(f"FOUND david.bai@openrouter.ai in search: {test_response['identifiers'][0]}")
            else:
                print("david.bai@openrouter.ai NOT FOUND in preference search")
        except Exception as e:
            print(f"Error searching for david.bai@openrouter.ai: {e}")
        print("=== End specific user check ===\n")

        while True:
            batch_num += 1
            self.progress["current_batch"] = batch_num

            try:
                # Fetch batch of customers with preference attributes
                print(f"\nBatch {batch_num}: Fetching customers with preferences (start={start})...")
                response = self.client.get_customers_with_preferences(limit=1000, start=start)
                identifiers = response.get("identifiers", [])

                if not identifiers:
                    print(f"Batch {batch_num}: No more customers found")
                    break

                total_fetched += len(identifiers)
                print(f"Batch {batch_num}: Found {len(identifiers)} customers (total fetched: {total_fetched})")
                
                # Print first 3 customers for debugging
                if batch_num <= 2:
                    for i, customer in enumerate(identifiers[:3]):
                        print(f"  Customer {i+1}: {customer.get('email')} (cio_id: {customer.get('cio_id')})")

                self.progress["customers_in_current_batch"] = len(identifiers)
                self.progress["details"] = f"Processing batch {batch_num} of users with preferences ({len(identifiers)} users)..."

                # Process customers in parallel to fetch their attributes
                # Reduced workers to avoid rate limiting
                batch_preferences = {}  # Maps email to list of category_ids they're opted out of
                customers_with_no_optouts = 0
                
                with ThreadPoolExecutor(max_workers=10) as executor:
                    future_to_customer = {}
                    
                    for customer_info in identifiers:
                        cio_id = customer_info.get("cio_id")
                        email = customer_info.get("email")
                        if email and cio_id:
                            future = executor.submit(self._fetch_and_parse_preferences, cio_id, email)
                            future_to_customer[future] = email
                    
                    # Collect results
                    for future in as_completed(future_to_customer):
                        email = future_to_customer[future]
                        try:
                            opted_out_categories = future.result()
                            if opted_out_categories:
                                batch_preferences[email] = opted_out_categories
                            else:
                                customers_with_no_optouts += 1
                        except Exception as e:
                            logger.warning(f"Could not process preferences for {email}: {e}")

                print(f"Batch {batch_num}: {len(batch_preferences)} customers have opt-outs, {customers_with_no_optouts} have no opt-outs")

                # Bulk update preferences for this batch
                if batch_preferences:
                    for email, category_ids in batch_preferences.items():
                        if category_ids:
                            self._bulk_update_preferences([email], category_ids)
                            self.progress["preference_users_count"] += 1
                            self.progress["customers_processed"] += 1
                            self.progress["preferences_updated"] += len(category_ids)
                    
                    total_processed += len(batch_preferences)

                # Check for next page
                next_cursor = response.get("next")
                print(f"Batch {batch_num}: Next cursor = '{next_cursor}'")
                
                if not next_cursor or next_cursor == "":
                    print(f"Batch {batch_num}: No next cursor, stopping pagination")
                    print(f"WARNING: Check if we hit API pagination limit. Total fetched: {total_fetched}")
                    if total_fetched >= 30000:
                        print("!!! Possible pagination limit reached around 30k records !!!")
                    break
                start = next_cursor

            except Exception as e:
                print(f"Error in batch {batch_num}: {e}")
                self.progress["errors"].append(f"Error processing preference users batch {batch_num}: {str(e)[:200]}")
                break

        print(f"\n=== Finished processing preference users ===")
        print(f"Total fetched from API: {total_fetched}")
        print(f"Total with opt-outs saved to DB: {total_processed}")
        self.progress["details"] = f"Processed {total_processed} users with subscription preferences"

    def _fetch_and_parse_preferences(self, cio_id: str, email: str) -> list[str]:
        """
        Fetch and parse subscription preferences for a single customer
        Returns list of category IDs the customer is opted out of
        """
        import time
        max_retries = 3
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                # Debug specific user
                if email == "david.bai@openrouter.ai":
                    print(f"\n=== FOUND DAVID.BAI@OPENROUTER.AI ===")
                    print(f"CIO ID: {cio_id}")
                
                # Fetch customer attributes
                attrs_response = self.client.get_customer_attributes(cio_id, id_type="cio_id")
                
                # Handle different response structures
                if "customer" in attrs_response:
                    attributes = attrs_response.get("customer", {}).get("attributes", {})
                else:
                    # Direct attributes response
                    attributes = attrs_response
                
                # Debug specific user
                if email == "david.bai@openrouter.ai":
                    print(f"Attributes keys: {list(attributes.keys())[:20]}")
                    print(f"cio_subscription_preferences: {attributes.get('cio_subscription_preferences', 'NOT FOUND')}")
                    print(f"_cio_subscription_preferences_computed: {attributes.get('_cio_subscription_preferences_computed', 'NOT FOUND')}")
                
                # Parse subscription preferences JSON
                pref_json = attributes.get("cio_subscription_preferences") or attributes.get("_cio_subscription_preferences_computed")
                
                if pref_json:
                    prefs = json.loads(pref_json) if isinstance(pref_json, str) else pref_json
                    topics = prefs.get("topics", {})
                    
                    # Debug specific user
                    if email == "david.bai@openrouter.ai":
                        print(f"Parsed topics: {topics}")
                    
                    # Collect opted-out categories
                    opted_out_categories = []
                    for topic_key, is_subscribed in topics.items():
                        if is_subscribed is False:
                            # Extract topic ID (could be "topic_1" or "1")
                            topic_id = topic_key.replace("topic_", "")
                            
                            # Get the corresponding PostHog category ID
                            category_id = self.topic_mapping.get(topic_id) or self.topic_mapping.get(f"topic_{topic_id}")
                            
                            if category_id:
                                opted_out_categories.append(category_id)
                            elif email == "david.bai@openrouter.ai":
                                print(f"Warning: No mapping for topic {topic_id}")
                    
                    # Debug specific user
                    if email == "david.bai@openrouter.ai":
                        print(f"Opted out categories: {opted_out_categories}")
                        print("=== END DAVID.BAI DEBUG ===\n")
                    
                    return opted_out_categories
                
                # Debug if no preferences found
                if email == "david.bai@openrouter.ai":
                    print(f"No preferences JSON found for david.bai@openrouter.ai")
                    print("=== END DAVID.BAI DEBUG ===\n")
                
                return []
                
            except Exception as e:
                error_str = str(e)
                if "429" in error_str:
                    # Rate limit error - retry with exponential backoff
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)
                        if email == "david.bai@openrouter.ai":
                            print(f"Rate limited, retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.warning(f"Rate limited fetching preferences for {email} after {max_retries} attempts")
                        if email == "david.bai@openrouter.ai":
                            print(f"ERROR: Rate limited after {max_retries} attempts")
                else:
                    logger.warning(f"Could not fetch/parse preferences for {email}: {e}")
                    if email == "david.bai@openrouter.ai":
                        print(f"ERROR processing david.bai@openrouter.ai: {e}")
                break
        
        return []

    def _bulk_update_all_preferences(self, emails: list[str], category_ids: list[str]) -> None:
        """Bulk update preferences to opt out users from ALL categories"""
        try:
            with transaction.atomic():
                # Fetch existing preferences
                existing_prefs = {
                    pref.identifier: pref
                    for pref in MessageRecipientPreference.objects.filter(
                        team_id=self.team.id, 
                        identifier__in=emails
                    )
                }

                to_create = []
                to_update = []

                for email in emails:
                    if email in existing_prefs:
                        # Update existing preference
                        pref = existing_prefs[email]
                        for category_id in category_ids:
                            pref.preferences[str(category_id)] = PreferenceStatus.OPTED_OUT.value
                        to_update.append(pref)
                    else:
                        # Create new preference with all categories opted out
                        preferences_dict = {
                            str(category_id): PreferenceStatus.OPTED_OUT.value 
                            for category_id in category_ids
                        }
                        to_create.append(
                            MessageRecipientPreference(
                                team_id=self.team.id,
                                identifier=email,
                                preferences=preferences_dict,
                            )
                        )

                # Bulk operations
                if to_create:
                    MessageRecipientPreference.objects.bulk_create(to_create, batch_size=500)

                if to_update:
                    MessageRecipientPreference.objects.bulk_update(
                        to_update, ["preferences", "updated_at"], batch_size=500
                    )

        except Exception as e:
            logger.error(f"Error bulk updating all preferences: {e}")
            # Fall back to individual updates
            for email in emails:
                try:
                    recipient_pref = MessageRecipientPreference.get_or_create_for_identifier(
                        team_id=self.team.id, identifier=email
                    )
                    for category_id in category_ids:
                        recipient_pref.set_preference(category_id, PreferenceStatus.OPTED_OUT)
                except Exception as individual_error:
                    self.progress["errors"].append(f"Failed to update {email}: {str(individual_error)[:100]}")

    def _bulk_update_preferences(self, emails: list[str], category_ids: list[str]) -> None:
        """Bulk update preferences for specific categories"""
        try:
            with transaction.atomic():
                # Fetch existing preferences
                existing_prefs = {
                    pref.identifier: pref
                    for pref in MessageRecipientPreference.objects.filter(
                        team_id=self.team.id,
                        identifier__in=emails
                    )
                }

                to_create = []
                to_update = []

                for email in emails:
                    if email in existing_prefs:
                        # Update existing preference
                        pref = existing_prefs[email]
                        for category_id in category_ids:
                            pref.preferences[str(category_id)] = PreferenceStatus.OPTED_OUT.value
                        to_update.append(pref)
                    else:
                        # Create new preference
                        preferences_dict = {
                            str(category_id): PreferenceStatus.OPTED_OUT.value
                            for category_id in category_ids
                        }
                        to_create.append(
                            MessageRecipientPreference(
                                team_id=self.team.id,
                                identifier=email,
                                preferences=preferences_dict,
                            )
                        )

                # Bulk operations
                if to_create:
                    MessageRecipientPreference.objects.bulk_create(to_create, batch_size=500)

                if to_update:
                    MessageRecipientPreference.objects.bulk_update(
                        to_update, ["preferences", "updated_at"], batch_size=500
                    )

        except Exception as e:
            logger.error(f"Error bulk updating preferences: {e}")
            # Fall back to individual updates
            for email in emails:
                try:
                    recipient_pref = MessageRecipientPreference.get_or_create_for_identifier(
                        team_id=self.team.id, identifier=email
                    )
                    for category_id in category_ids:
                        recipient_pref.set_preference(category_id, PreferenceStatus.OPTED_OUT)
                except Exception as individual_error:
                    self.progress["errors"].append(f"Failed to update {email}: {str(individual_error)[:100]}")

    def get_progress(self) -> dict[str, Any]:
        return self.progress