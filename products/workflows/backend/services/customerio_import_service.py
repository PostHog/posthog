import io
import csv
import json
import logging
from typing import Any, Optional

from django.db import transaction

from posthog.models import MessageCategory, MessageRecipientPreference, Team
from posthog.models.message_category import MessageCategoryType
from posthog.models.message_preferences import PreferenceStatus

from .customerio_client import CustomerIOClient

logger = logging.getLogger(__name__)


class CustomerIOImportService:
    def __init__(self, team: Team, api_key: Optional[str], user):
        self.team = team
        self.user = user
        self.client: Optional[CustomerIOClient] = None
        self.api_key = api_key
        self.topic_mapping: dict[str, str] = {}  # Maps Customer.io topic IDs to PostHog MessageCategory IDs
        self.topic_names: dict[str, str] = {}  # Maps topic IDs to their display names
        self.all_processed_users: set[str] = set()  # Track ALL unique users across API and CSV
        self.progress: dict[str, Any] = {
            "status": "initializing",
            "topics_found": 0,
            "categories_created": 0,
            "customers_processed": 0,
            "preferences_updated": 0,
            "globally_unsubscribed_count": 0,
            "errors": [],
            "details": "",
        }

    def import_api_data(self) -> dict[str, Any]:
        """Import categories and globally unsubscribed users via API"""
        if not self.api_key:
            self.progress["status"] = "failed"
            self.progress["errors"].append("API key is required for Customer.io API import")
            return self.progress

        try:
            # Step 1: Validate credentials
            # Try US region first
            self.client = CustomerIOClient(self.api_key, region="us")
            if not self.client.validate_credentials():
                # Try EU region
                self.client = CustomerIOClient(self.api_key, region="eu")
                if not self.client.validate_credentials():
                    self.progress["status"] = "failed"
                    self.progress["errors"].append(
                        "Invalid Customer.io API credentials. Please check: 1) You're using an App API key from Settings > API Credentials > App API Keys, 2) The key has not expired, 3) You've copied the complete key"
                    )
                    return self.progress

            # Step 2: Import subscription topics as categories
            assert self.client is not None  # We validated credentials above
            topics = self.client.get_subscription_topics()

            if not topics:
                self.progress["errors"].append("No subscription topics found in Customer.io")
                self.progress["status"] = "completed"
                return self.progress

            self.progress["topics_found"] = len(topics)
            self._import_categories(topics)

            # Step 3: Process globally unsubscribed users
            self._process_globally_unsubscribed_users()

            self.progress["status"] = "completed"

        except Exception as e:
            self.progress["status"] = "failed"
            self.progress["errors"].append(str(e))
            logger.exception("Import failed with error")

        return self.progress

    def process_preferences_csv(self, csv_file) -> dict[str, Any]:
        """Process CSV file with customer preferences"""
        # Reset progress for CSV processing
        csv_progress: dict[str, Any] = {
            "status": "processing_csv",
            "total_rows": 0,
            "rows_processed": 0,
            "users_with_optouts": 0,
            "users_skipped": 0,
            "parse_errors": 0,
            "preferences_updated": 0,
            "current_batch": 0,
            "details": "Starting CSV processing...",
            "failed_imports": [],  # List of failed imports with email and error
        }

        try:
            # Load topic mapping from existing categories
            self._load_topic_mapping()

            if not self.topic_mapping:
                csv_progress["status"] = "failed"
                csv_progress["details"] = "No categories found. Please run API import first."
                return csv_progress

            # Read CSV content
            if hasattr(csv_file, "read"):
                content = csv_file.read()
                if isinstance(content, bytes):
                    content = content.decode("utf-8")
            else:
                content = csv_file

            # Parse CSV
            csv_reader = csv.DictReader(io.StringIO(content))

            # Process in batches
            batch_size = 1000
            current_batch = []

            for row_num, row in enumerate(csv_reader, 1):
                csv_progress["total_rows"] = row_num
                csv_progress["rows_processed"] = row_num

                # Process row
                result = self._process_csv_row(row)

                # Track unique users (only for successful rows with valid emails)
                if result["status"] == "success" and result.get("email"):
                    # Add to our global set of processed users (combines with API users)
                    self.all_processed_users.add(result["email"])

                if result["status"] == "success" and result["opted_out_categories"]:
                    current_batch.append((result["email"], result["opted_out_categories"]))
                    csv_progress["users_with_optouts"] += 1
                elif result["status"] == "success":
                    csv_progress["users_skipped"] += 1
                elif result["status"] == "error":
                    csv_progress["parse_errors"] += 1
                    csv_progress["failed_imports"].append(
                        {"email": result.get("email", "unknown"), "error": result["error"]}
                    )

                # Process batch when it reaches batch_size
                if len(current_batch) >= batch_size:
                    prefs_count = self._save_csv_batch(current_batch)
                    csv_progress["preferences_updated"] += prefs_count
                    current_batch = []

            # Process remaining batch
            if current_batch:
                prefs_count = self._save_csv_batch(current_batch)
                csv_progress["preferences_updated"] += prefs_count

            # Return the total unique users across API and CSV
            csv_progress["total_unique_users"] = len(self.all_processed_users)

            csv_progress["status"] = "completed"
            csv_progress["details"] = (
                f"CSV processing completed. Total unique users imported: {csv_progress['total_unique_users']}."
            )

        except Exception as e:
            csv_progress["status"] = "failed"
            csv_progress["details"] = f"CSV processing failed: {str(e)}"
            logger.exception("CSV processing failed")

        return csv_progress

    def _process_csv_row(self, row: dict) -> dict:
        """Process a single CSV row and return the result"""
        email = row.get("email", "").strip()
        cio_id = row.get("id", "").strip()  # Get Customer.io ID
        preferences_json = row.get("cio_subscription_preferences", "").strip()

        if not email:
            # Use Customer.io ID if email is missing
            identifier = f"Customer.io ID: {cio_id}" if cio_id else "unknown"
            return {"status": "error", "email": identifier, "error": "Missing email"}

        if not preferences_json:
            return {"status": "success", "email": email, "opted_out_categories": []}

        try:
            # Parse JSON preferences
            prefs = json.loads(preferences_json)
            topics = prefs.get("topics", {})

            # Collect opted-out categories (where value is false)
            opted_out_categories = []

            for topic_key, is_subscribed in topics.items():
                if is_subscribed is False:  # Only process opt-outs
                    # Extract topic ID (handle both "topic_1" and "1" formats)
                    topic_id = topic_key.replace("topic_", "")

                    # Map to PostHog category ID
                    category_id = self.topic_mapping.get(topic_id) or self.topic_mapping.get(f"topic_{topic_id}")

                    if category_id:
                        opted_out_categories.append(category_id)
                    else:
                        # Unknown topic, but don't fail the whole row
                        logger.warning(f"Unknown topic ID '{topic_key}' for {email}")

            return {"status": "success", "email": email, "opted_out_categories": opted_out_categories}

        except json.JSONDecodeError as e:
            return {"status": "error", "email": email, "error": f"Invalid JSON: {str(e)[:100]}"}
        except Exception as e:
            return {"status": "error", "email": email, "error": f"Processing error: {str(e)[:100]}"}

    def _save_csv_batch(self, batch: list[tuple[str, list[str]]]) -> int:
        """Save a batch of CSV preferences to database"""
        preferences_count = 0

        try:
            with transaction.atomic():
                # Group by email for efficient processing
                email_to_categories: dict[str, list[str]] = {}
                for email, categories in batch:
                    if email not in email_to_categories:
                        email_to_categories[email] = []
                    email_to_categories[email].extend(categories)

                # Fetch existing preferences
                emails = list(email_to_categories.keys())
                existing_prefs = {
                    pref.identifier: pref
                    for pref in MessageRecipientPreference.objects.filter(team_id=self.team.id, identifier__in=emails)
                }

                to_create = []
                to_update = []

                for email, category_ids in email_to_categories.items():
                    # Remove duplicates
                    unique_categories = list(set(category_ids))

                    if email in existing_prefs:
                        # Update existing preference
                        pref = existing_prefs[email]
                        for category_id in unique_categories:
                            pref.preferences[str(category_id)] = PreferenceStatus.OPTED_OUT.value
                        to_update.append(pref)
                    else:
                        # Create new preference
                        preferences_dict = {
                            str(category_id): PreferenceStatus.OPTED_OUT.value for category_id in unique_categories
                        }
                        to_create.append(
                            MessageRecipientPreference(
                                team_id=self.team.id,
                                identifier=email,
                                preferences=preferences_dict,
                            )
                        )

                    preferences_count += len(unique_categories)

                # Bulk operations
                if to_create:
                    MessageRecipientPreference.objects.bulk_create(to_create, batch_size=500)

                if to_update:
                    MessageRecipientPreference.objects.bulk_update(
                        to_update, ["preferences", "updated_at"], batch_size=500
                    )

        except Exception as e:
            logger.exception(f"Error saving CSV batch: {e}")
            # Could track individual failures here if needed

        return preferences_count

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
                    category, _ = MessageCategory.objects.update_or_create(
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
        if not self.topic_mapping or not self.client:
            return

        start = None
        batch_num = 0
        total_processed = 0
        all_category_ids = list(set(self.topic_mapping.values()))

        while True:
            batch_num += 1
            self.progress["current_batch"] = batch_num

            try:
                # Fetch batch of globally unsubscribed customers
                response = self.client.get_globally_unsubscribed_customers(limit=1000, start=start)
                identifiers = response.get("identifiers", [])

                if not identifiers:
                    break

                self.progress["customers_in_current_batch"] = len(identifiers)
                self.progress["details"] = (
                    f"Processing batch {batch_num} of globally unsubscribed users ({len(identifiers)} users)..."
                )

                # Collect emails for this batch
                emails_to_process = []
                for customer_info in identifiers:
                    email = customer_info.get("email")
                    if email:
                        emails_to_process.append(email)
                        # Add to our global set of processed users
                        self.all_processed_users.add(email)

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
                if not next_cursor or next_cursor == "":
                    break
                start = next_cursor

            except Exception as e:
                self.progress["errors"].append(
                    f"Error processing globally unsubscribed batch {batch_num}: {str(e)[:200]}"
                )
                break

        self.progress["details"] = f"Processed {total_processed} globally unsubscribed users"

    def _bulk_update_all_preferences(self, emails: list[str], category_ids: list[str]) -> None:
        """Bulk update preferences to opt out users from ALL categories"""
        try:
            with transaction.atomic():
                # Fetch existing preferences
                existing_prefs = {
                    pref.identifier: pref
                    for pref in MessageRecipientPreference.objects.filter(team_id=self.team.id, identifier__in=emails)
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
                            str(category_id): PreferenceStatus.OPTED_OUT.value for category_id in category_ids
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
            logger.exception(f"Error bulk updating all preferences: {e}")
            # Don't fall back to individual updates - it would make performance worse
            # Instead, record the batch failure and continue
            self.progress["errors"].append(f"Failed to update batch of {len(emails)} users: {str(e)[:200]}")

    def _load_topic_mapping(self) -> None:
        """Load topic mapping from existing categories"""
        categories = MessageCategory.objects.filter(team=self.team, key__startswith="customerio_", deleted=False)

        for category in categories:
            # Extract topic identifier from key (e.g., "customerio_topic_1" -> "topic_1")
            topic_identifier = category.key.replace("customerio_", "")
            # Also extract numeric ID (e.g., "topic_1" -> "1")
            topic_id = topic_identifier.replace("topic_", "")

            # Store both mappings
            self.topic_mapping[topic_identifier] = str(category.id)
            self.topic_mapping[topic_id] = str(category.id)
            self.topic_names[topic_id] = category.name

    def get_progress(self) -> dict[str, Any]:
        return self.progress
