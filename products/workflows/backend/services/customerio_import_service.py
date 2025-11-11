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
        self.client = CustomerIOClient(api_key)
        self.topic_mapping = {}  # Maps Customer.io topic IDs to PostHog MessageCategory IDs
        self.progress = {
            "status": "initializing",
            "topics_found": 0,
            "workflows_created": 0,
            "customers_processed": 0,
            "preferences_updated": 0,
            "errors": [],
        }

    def import_all(self) -> dict[str, Any]:
        try:
            # Validate credentials first
            self.progress["status"] = "validating_credentials"
            if not self.client.validate_credentials():
                self.progress["status"] = "failed"
                self.progress["errors"].append("Invalid Customer.io API credentials")
                return self.progress

            # Import subscription centers and topics
            self.progress["status"] = "fetching_topics"
            subscription_centers = self.client.get_subscription_centers()

            if not subscription_centers:
                self.progress["errors"].append("No subscription centers found in Customer.io")
                self.progress["status"] = "completed"
                return self.progress

            # Process the first subscription center (most accounts have only one)
            center = subscription_centers[0]
            center_id = center.get("id")

            # Get topics from the subscription center
            topics = self.client.get_subscription_center_topics(center_id)
            self.progress["topics_found"] = len(topics)

            # Create workflows from topics
            self.progress["status"] = "creating_workflows"
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
                topic_name = topic.get("name", f"Topic {topic_id}")
                topic_key = f"customerio_topic_{topic_id}"
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

                # Store the mapping for later use
                self.topic_mapping[str(topic_id)] = str(category.id)

                if created:
                    self.progress["workflows_created"] += 1

            except Exception as e:
                self.progress["errors"].append(f"Failed to import topic {topic_id}: {str(e)}")

    def _import_customer_preferences(self) -> None:
        # Fetch customers with preferences
        for customer_data in self.client.get_all_customers_with_preferences():
            try:
                email = customer_data.get("email")
                if not email:
                    continue

                preferences = customer_data.get("preferences", {})
                topics = preferences.get("topics", {})

                if not topics:
                    continue

                # Get or create recipient preference
                recipient_pref = MessageRecipientPreference.get_or_create_for_identifier(
                    team_id=self.team.id, identifier=email
                )

                # Process each topic preference
                preferences_updated = False
                for topic_id, is_subscribed in topics.items():
                    # Extract numeric ID from topic_N format
                    if topic_id.startswith("topic_"):
                        numeric_id = topic_id.replace("topic_", "")
                    else:
                        numeric_id = topic_id

                    # Find the corresponding PostHog category
                    category_id = self.topic_mapping.get(numeric_id)
                    if not category_id:
                        continue

                    # Set preference (False in Customer.io means opted out)
                    status = PreferenceStatus.OPTED_IN if is_subscribed else PreferenceStatus.OPTED_OUT

                    # Only update if it's an opt-out (we care about unsubscribes)
                    if not is_subscribed:
                        recipient_pref.set_preference(category_id, status)
                        preferences_updated = True

                if preferences_updated:
                    self.progress["preferences_updated"] += 1

                self.progress["customers_processed"] += 1

            except Exception as e:
                self.progress["errors"].append(f"Failed to import preferences for {email}: {str(e)}")

    def get_progress(self) -> dict[str, Any]:
        return self.progress
