from typing import Any

from django.db import transaction

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
        self.progress = {
            "status": "initializing",
            "topics_found": 0,
            "categories_created": 0,
            "customers_processed": 0,
            "preferences_updated": 0,
            "current_category": None,
            "current_category_index": 0,
            "total_categories": 0,
            "current_batch": 0,
            "customers_in_current_batch": 0,
            "errors": [],
            "details": "",
        }

    def import_all(self) -> dict[str, Any]:
        try:
            # Try to validate credentials with US region first, then EU
            self.progress["status"] = "validating_credentials"
            
            # Try US region first
            self.client = CustomerIOClient(self.api_key, region="us")
            if self.client.validate_credentials():
                self.progress["status"] = "validated"
            else:
                # Try EU region
                self.client = CustomerIOClient(self.api_key, region="eu")
                if not self.client.validate_credentials():
                    self.progress["status"] = "failed"
                    self.progress["errors"].append("Invalid Customer.io API credentials. Please check: 1) You're using an App API key from Settings > API Credentials > App API Keys, 2) The key has not expired, 3) You've copied the complete key")
                    return self.progress

            # Import subscription topics
            self.progress["status"] = "fetching_topics"
            topics = self.client.get_subscription_centers()  # This actually fetches topics

            if not topics:
                self.progress["errors"].append("No subscription topics found in Customer.io")
                self.progress["status"] = "completed"
                return self.progress

            self.progress["topics_found"] = len(topics)

            # Create message categories from topics
            self.progress["status"] = "creating_categories"
            self._import_topics(topics)

            # Import customer preferences
            self.progress["status"] = "importing_preferences"
            self._import_customer_preferences()

            self.progress["status"] = "completed"

        except Exception as e:
            self.progress["status"] = "failed"
            self.progress["errors"].append(str(e))

        return self.progress

    def _import_topics(self, topics: list[dict[str, Any]]) -> None:
        for topic in topics:
            try:
                # Extract topic data
                topic_id = topic.get("id")
                topic_identifier = topic.get("identifier", f"topic_{topic_id}")  # e.g., "topic_1"
                topic_name = topic.get("name", f"Topic {topic_id}")
                # Use the identifier as the key to maintain consistency with Customer.io
                topic_key = f"customerio_{topic_identifier}"
                description = topic.get("description", "")
                public_description = topic.get("public_description", description)

                # Determine category type based on topic settings
                # Default to marketing unless explicitly marked as transactional
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

                # Store the mapping using both the identifier and numeric ID
                # Customer.io may use either format in preferences
                # Store with topic_ prefix (e.g., "topic_1")
                self.topic_mapping[topic_identifier] = str(category.id)
                # Also store just the numeric ID (e.g., "1")
                self.topic_mapping[str(topic_id)] = str(category.id)

                if created:
                    self.progress["categories_created"] += 1

            except Exception as e:
                self.progress["errors"].append(f"Failed to import topic {topic_id}: {str(e)}")

    def _import_customer_preferences(self) -> None:
        import logging
        logger = logging.getLogger(__name__)
        
        # Get list of topic IDs and their names from our mapping
        topics_to_process = []
        for key in self.topic_mapping.keys():
            # Extract numeric IDs (skip the "topic_N" format duplicates)
            if not key.startswith("topic_"):
                topics_to_process.append({
                    "id": key,
                    "category_id": self.topic_mapping[key],
                    "name": f"Topic {key}"  # We can enhance this later with actual names
                })
        
        self.progress["total_categories"] = len(topics_to_process)
        logger.info(f"Starting customer preference import for {len(topics_to_process)} topics")
        
        # Track unique customers across all topics
        unique_customers = set()
        
        # Process each topic/category one by one
        for idx, topic_info in enumerate(topics_to_process):
            topic_id = topic_info["id"]
            category_id = topic_info["category_id"]
            
            self.progress["current_category_index"] = idx + 1
            self.progress["current_category"] = f"Topic {topic_id}"
            self.progress["status"] = f"processing_category_{idx + 1}_of_{len(topics_to_process)}"
            self.progress["details"] = f"Processing topic {topic_id} ({idx + 1}/{len(topics_to_process)})"
            
            logger.info(f"Processing topic {topic_id} ({idx + 1}/{len(topics_to_process)})")
            
            # Process this topic in batches
            self._import_topic_preferences_in_batches(
                topic_id, 
                category_id, 
                unique_customers,
                batch_size=500  
            )
        
        self.progress["customers_processed"] = len(unique_customers)
        self.progress["status"] = "completed"
        self.progress["details"] = f"Import completed. Processed {len(unique_customers)} unique customers."
        logger.info(f"Completed preference import. Processed {len(unique_customers)} unique customers")
    
    def _import_topic_preferences_in_batches(
        self, 
        topic_id: str, 
        category_id: str, 
        unique_customers: set,
        batch_size: int = 500
    ) -> None:
        """Import preferences for a single topic in batches for better progress tracking"""
        import logging
        logger = logging.getLogger(__name__)
        
        start = None
        batch_num = 0
        topic_total = 0
        
        while True:
            batch_num += 1
            self.progress["current_batch"] = batch_num
            self.progress["details"] = f"Topic {topic_id}: Fetching batch {batch_num}"
            
            try:
                # Fetch a batch of opted-out customers for this topic
                logger.info(f"Topic {topic_id}: Fetching batch {batch_num}")
                response = self.client.search_customers_opted_out_of_topic(
                    topic_id, 
                    limit=batch_size, 
                    start=start
                )
                
                identifiers = response.get("identifiers", [])
                if not identifiers:
                    logger.info(f"Topic {topic_id}: No more customers")
                    break
                
                self.progress["customers_in_current_batch"] = len(identifiers)
                self.progress["details"] = f"Topic {topic_id}: Processing {len(identifiers)} customers in batch {batch_num}"
                
                # Collect batch data for bulk operations
                emails_to_process = []
                for customer_info in identifiers:
                    email = customer_info.get("email")
                    if email:
                        emails_to_process.append(email)
                        unique_customers.add(email)
                
                if emails_to_process:
                    # Bulk fetch/create preferences
                    self._bulk_update_preferences(emails_to_process, category_id)
                    
                    batch_processed = len(emails_to_process)
                    self.progress["preferences_updated"] += batch_processed
                    topic_total += batch_processed
                    
                    logger.info(f"Topic {topic_id}: Batch {batch_num} complete. Processed {batch_processed} customers")
                
                # Check for next page
                next_cursor = response.get("next")
                if not next_cursor or next_cursor == "":
                    break
                start = next_cursor
                
                # Small delay to avoid hitting rate limits
                import time
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error fetching batch {batch_num} for topic {topic_id}: {e}")
                self.progress["errors"].append(f"Batch error: {str(e)[:200]}")
                break
        
        logger.info(f"Topic {topic_id} complete: Processed {topic_total} opt-outs")
        self.progress["details"] = f"Topic {topic_id} complete: {topic_total} opt-outs processed"
    
    def _bulk_update_preferences(self, emails: list[str], category_id: str) -> None:
        """Bulk update preferences for multiple emails"""
        import logging
        from django.db import transaction
        logger = logging.getLogger(__name__)
        
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
                
                # Prepare records to create and update
                to_create = []
                to_update = []
                
                for email in emails:
                    if email in existing_prefs:
                        # Update existing preference
                        pref = existing_prefs[email]
                        pref.preferences[str(category_id)] = PreferenceStatus.OPTED_OUT.value
                        to_update.append(pref)
                    else:
                        # Create new preference
                        to_create.append(
                            MessageRecipientPreference(
                                team_id=self.team.id,
                                identifier=email,
                                preferences={str(category_id): PreferenceStatus.OPTED_OUT.value}
                            )
                        )
                
                # Bulk create new preferences
                if to_create:
                    MessageRecipientPreference.objects.bulk_create(to_create, batch_size=500)
                
                # Bulk update existing preferences
                if to_update:
                    MessageRecipientPreference.objects.bulk_update(
                        to_update, ['preferences', 'updated_at'], batch_size=500
                    )
                
                logger.info(f"Bulk updated {len(emails)} preferences (created: {len(to_create)}, updated: {len(to_update)})")
                
        except Exception as e:
            logger.error(f"Error in bulk update: {str(e)}")
            # Fall back to individual updates
            for email in emails:
                try:
                    recipient_pref = MessageRecipientPreference.get_or_create_for_identifier(
                        team_id=self.team.id, identifier=email
                    )
                    recipient_pref.set_preference(category_id, PreferenceStatus.OPTED_OUT)
                except Exception as individual_error:
                    logger.error(f"Failed to import preference for {email}: {str(individual_error)}")
                    self.progress["errors"].append(f"Failed: {email} - {str(individual_error)[:100]}")

    def get_progress(self) -> dict[str, Any]:
        return self.progress
