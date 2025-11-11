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
            "categories_created": 0,  # Changed from workflows_created for clarity
            "customers_processed": 0,
            "preferences_updated": 0,
            "errors": [],
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
        
        # Get list of topic IDs from our mapping
        topic_ids = []
        for key in self.topic_mapping.keys():
            # Extract numeric IDs (skip the "topic_N" format duplicates)
            if not key.startswith("topic_"):
                topic_ids.append(key)
        
        logger.info(f"Starting customer preference import for topics: {topic_ids}")
        
        # Get all opted-out customers per topic
        logger.info("Calling get_opted_out_customers_for_topics...")
        logger.info(f"Client exists: {self.client is not None}")
        logger.info(f"Client type: {type(self.client)}")
        
        try:
            logger.info("About to call client.get_opted_out_customers_for_topics")
            opt_outs_by_topic = self.client.get_opted_out_customers_for_topics(topic_ids)
            logger.info(f"Call completed. Received opt-outs data: {[(t, len(emails)) for t, emails in opt_outs_by_topic.items()]}")
        except Exception as e:
            logger.error(f"Failed to fetch opt-outs: {e}")
            logger.exception("Full traceback:")
            self.progress["errors"].append(f"Failed to fetch opt-outs: {str(e)}")
            return
        
        # Track unique customers processed
        unique_customers = set()
        
        # Process opt-outs for each topic
        logger.info("Starting to process opt-outs by topic...")
        for topic_id, opted_out_emails in opt_outs_by_topic.items():
            # Get the PostHog category ID for this topic
            category_id = self.topic_mapping.get(str(topic_id))
            if not category_id:
                logger.warning(f"Could not find mapping for topic {topic_id}")
                continue
            
            logger.info(f"Processing {len(opted_out_emails)} opt-outs for topic {topic_id} -> category {category_id}")
            
            # Process each opted-out customer
            processed_in_topic = 0
            for email in opted_out_emails:
                try:
                    # Track unique customers
                    unique_customers.add(email)
                    
                    logger.debug(f"Getting/creating preference for {email}")
                    
                    # Get or create recipient preference
                    recipient_pref = MessageRecipientPreference.get_or_create_for_identifier(
                        team_id=self.team.id, identifier=email
                    )
                    
                    logger.debug(f"Got preference object with ID {recipient_pref.id} for {email}")
                    
                    # Set opt-out preference for this topic
                    logger.info(f"Setting opt-out for {email} on category {category_id} (topic {topic_id})")
                    recipient_pref.set_preference(category_id, PreferenceStatus.OPTED_OUT)
                    
                    logger.debug(f"Successfully set opt-out for {email}")
                    
                    self.progress["preferences_updated"] += 1
                    processed_in_topic += 1
                    
                except Exception as e:
                    logger.error(f"Failed to import preference for {email} on topic {topic_id}: {str(e)}")
                    logger.exception(f"Full error trace:")
                    self.progress["errors"].append(f"Failed to import preference for {email}: {str(e)}")
            
            logger.info(f"Processed {processed_in_topic}/{len(opted_out_emails)} opt-outs for topic {topic_id}")
        
        self.progress["customers_processed"] = len(unique_customers)
        logger.info(f"Completed preference import. Processed {len(unique_customers)} unique customers")

    def get_progress(self) -> dict[str, Any]:
        return self.progress
