import io
import csv
import json
import time
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Optional

from django.db import transaction
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

from products.messaging.backend.models.message_category import MessageCategory, MessageCategoryType
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)
from products.messaging.backend.models.message_suppression import MessageSuppression, SuppressionSource

from .customerio_client import CustomerIOAPIError, CustomerIOClient

logger = logging.getLogger(__name__)

# Customer.io suppression lists to import, with the suppression source and reason each one maps to. A bounced or
# invalid address can't receive mail, so it blocks every email. A spam report blocks marketing email only. Blocks
# are not imported, because a provider block is often temporary.
CUSTOMERIO_SUPPRESSION_TYPES: dict[str, tuple[SuppressionSource, str]] = {
    "bounces": (SuppressionSource.BOUNCE, "Imported from Customer.io (bounced)"),
    "invalid_emails": (SuppressionSource.BOUNCE, "Imported from Customer.io (invalid address)"),
    "spam_reports": (SuppressionSource.COMPLAINT, "Imported from Customer.io (spam report)"),
}
SUPPRESSION_PAGE_SIZE = 1000
# Customer.io allows 10 App API requests per second.
SUPPRESSION_PAGE_DELAY_SECONDS = 0.2


@frozen
class _ImportedSuppression:
    # When Customer.io suppressed the address, or None when the entry has no time.
    suppressed_at: datetime | None
    # The bounce status code and Mailgun's reason, for example "550 Mailbox full". None for spam reports.
    diagnostic: str | None


@frozen
class SuppressionPage:
    suppression_type: str
    # How many entries Customer.io returned, including any without a usable address.
    entries: int
    addresses: dict[str, _ImportedSuppression]
    # The offset of the next page in the same suppression list.
    next_offset: int
    is_last: bool


@frozen
class GlobalUnsubscribePage:
    # How many customers Customer.io returned, including any without an email address.
    customers: int
    emails: tuple[str, ...]
    # The cursor of the next page, or None on the last page.
    next_start: str | None


class CustomerIOImportService:
    def __init__(self, team_id: int, api_key: Optional[str], created_by_id: Optional[int]):
        self.team_id = team_id
        self.created_by_id = created_by_id
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
            "suppressions_imported": 0,
            "errors": [],
            "details": "",
        }

    def connect(self, timeout: int = 30) -> bool:
        """Find the region the App API key belongs to and keep a client for it.

        Returns False when every region rejects the key. Raises CustomerIOAPIError when a region fails in another
        way, for example a timeout or a server error, because the key can still be valid there.
        """
        if not self.api_key:
            return False
        unavailable: CustomerIOAPIError | None = None
        for region in ("us", "eu"):
            client = CustomerIOClient(self.api_key, region=region, timeout=timeout)
            try:
                client.get_subscription_topics()
            except CustomerIOAPIError as e:
                if e.status_code not in (401, 403):
                    unavailable = e
                continue
            self.client = client
            return True
        self.client = None
        if unavailable is not None:
            raise unavailable
        return False

    def import_api_data(self) -> dict[str, Any]:
        """Import categories, globally unsubscribed users and suppressed addresses via API"""
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

            self.progress["topics_found"] = len(topics)
            self.import_categories(topics)

            # Step 3: Import addresses Customer.io's email provider suppressed. They go before the global
            # unsubscribes because those can run to hundreds of pages, past the request timeout, and each page
            # saves on its own, so the shorter suppression lists finish first.
            self._import_suppressions()

            # Step 4: Process globally unsubscribed users
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

            # Read CSV content
            if hasattr(csv_file, "read"):
                content = csv_file.read()
                if isinstance(content, bytes):
                    content = content.decode("utf-8")
            else:
                content = csv_file

            # Parse CSV
            csv_reader = csv.DictReader(io.StringIO(content))

            if not self.topic_mapping and "unsubscribed" not in (csv_reader.fieldnames or []):
                csv_progress["status"] = "failed"
                csv_progress["details"] = "No categories found. Please run API import first."
                return csv_progress

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
                if result.get("error"):
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
        email = (row.get("email") or "").strip()
        cio_id = (row.get("id") or "").strip()  # Get Customer.io ID
        preferences_json = (row.get("cio_subscription_preferences") or "").strip()

        if not email:
            # Use Customer.io ID if email is missing
            identifier = f"Customer.io ID: {cio_id}" if cio_id else "unknown"
            return {"status": "error", "email": identifier, "error": "Missing email"}

        globally_unsubscribed = (row.get("unsubscribed") or "").strip().lower() in {"true", "1"}
        opted_out_categories = [ALL_MESSAGE_PREFERENCE_CATEGORY_ID] if globally_unsubscribed else []

        if not preferences_json:
            return {"status": "success", "email": email, "opted_out_categories": opted_out_categories}

        error = ""
        try:
            # Parse JSON preferences
            prefs = json.loads(preferences_json)
            topics = prefs.get("topics", {})

            # Collect opted-out categories (where value is false)
            for topic_key, is_subscribed in topics.items():
                if is_subscribed is False:  # Only process opt-outs
                    if not self.topic_mapping and not globally_unsubscribed:
                        return {
                            "status": "error",
                            "email": email,
                            "error": "No categories found. Please run API import first.",
                        }

                    # Extract topic ID (handle both "topic_1" and "1" formats)
                    topic_id = topic_key.replace("topic_", "")

                    # Map to PostHog category ID
                    category_id = self.topic_mapping.get(topic_id) or self.topic_mapping.get(f"topic_{topic_id}")

                    if category_id:
                        opted_out_categories.append(category_id)
                    else:
                        # Unknown topic, but don't fail the whole row
                        logger.warning(f"Unknown topic ID '{topic_key}' for {email}")

        except json.JSONDecodeError as e:
            error = f"Invalid JSON: {str(e)[:100]}"
        except Exception as e:
            error = f"Processing error: {str(e)[:100]}"

        if error:
            return {
                "status": "success" if globally_unsubscribed else "error",
                "email": email,
                "opted_out_categories": opted_out_categories,
                "error": f"Global opt-out imported; topic preferences not imported: {error}. Fix the topic preferences and upload the CSV again."
                if globally_unsubscribed
                else error,
            }

        return {"status": "success", "email": email, "opted_out_categories": opted_out_categories}

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
                    for pref in MessageRecipientPreference.objects.filter(team_id=self.team_id, identifier__in=emails)
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
                                team_id=self.team_id,
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

    def import_categories(self, topics: list[dict[str, Any]]) -> None:
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
                        team_id=self.team_id,
                        key=topic_key,
                        defaults={
                            "name": topic_name,
                            "description": description,
                            "public_description": public_description,
                            "category_type": category_type,
                            "created_by_id": self.created_by_id,
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
        """Record Customer.io global unsubscribes as an opt-out of all marketing, keeping each topic choice"""
        if not self.client:
            return

        batch_num = 0
        total_processed = 0
        pages = self.fetch_global_unsubscribe_pages(start=None)

        while True:
            batch_num += 1
            self.progress["current_batch"] = batch_num

            try:
                page = next(pages, None)
                if page is None:
                    break

                self.progress["customers_in_current_batch"] = page.customers
                self.progress["details"] = (
                    f"Processing batch {batch_num} of globally unsubscribed users ({page.customers} users)..."
                )
                # Add to our global set of processed users
                self.all_processed_users.update(page.emails)

                if page.emails:
                    # Bulk update: opt out these users from all marketing
                    self._bulk_update_all_preferences(list(page.emails), [ALL_MESSAGE_PREFERENCE_CATEGORY_ID])

                    batch_processed = len(page.emails)
                    total_processed += batch_processed
                    self.progress["globally_unsubscribed_count"] += batch_processed
                    self.progress["customers_processed"] += batch_processed
                    self.progress["preferences_updated"] += batch_processed

            except Exception as e:
                self.progress["errors"].append(
                    f"Error processing globally unsubscribed batch {batch_num}: {str(e)[:200]}"
                )
                break

        self.progress["details"] = f"Processed {total_processed} globally unsubscribed users"

    def fetch_global_unsubscribe_pages(self, start: str | None) -> Iterator[GlobalUnsubscribePage]:
        """Page through Customer.io's globally unsubscribed customers, starting at the `start` cursor.

        The caller writes each page, so it decides what a failed write does to the rest of the import.
        """
        assert self.client is not None
        while True:
            response = self.client.get_globally_unsubscribed_customers(limit=1000, start=start)
            identifiers = response.get("identifiers", [])
            if not identifiers:
                return

            next_cursor = response.get("next") or None
            yield GlobalUnsubscribePage(
                customers=len(identifiers),
                emails=tuple(email for customer in identifiers if (email := customer.get("email"))),
                next_start=next_cursor,
            )
            if not next_cursor:
                return
            start = next_cursor

    def _import_suppressions(self) -> None:
        """Add Customer.io's bounced, invalid and spam-reported addresses to the suppression list.

        Without them, the first send to each of these addresses after moving to Workflows bounces again, and the
        bounces count against the shared sender reputation.
        """
        if not self.client:
            return

        for suppression_type in CUSTOMERIO_SUPPRESSION_TYPES:
            pages = self.fetch_suppression_pages(suppression_type, offset=0)
            while True:
                try:
                    page = next(pages, None)
                except Exception as e:
                    self.progress["errors"].append(f"Error importing Customer.io {suppression_type}: {str(e)[:200]}")
                    break
                if page is None:
                    break
                self.progress["suppressions_imported"] += self.save_suppression_page(page)

    def fetch_suppression_pages(self, suppression_type: str, offset: int) -> Iterator[SuppressionPage]:
        """Page through one Customer.io suppression list, starting at `offset`.

        The caller saves each page with `save_suppression_page`, so it decides what a failed request does to the
        rest of the import.
        """
        assert self.client is not None
        while True:
            entries = self.client.get_suppressions(suppression_type, limit=SUPPRESSION_PAGE_SIZE, offset=offset)
            offset += len(entries)
            yield SuppressionPage(
                suppression_type=suppression_type,
                entries=len(entries),
                addresses={
                    email.strip().lower(): _imported_suppression(entry)
                    for entry in entries
                    if isinstance(entry, dict) and isinstance(email := entry.get("email"), str) and "@" in email
                },
                next_offset=offset,
                is_last=len(entries) < SUPPRESSION_PAGE_SIZE,
            )
            if len(entries) < SUPPRESSION_PAGE_SIZE:
                return
            time.sleep(SUPPRESSION_PAGE_DELAY_SECONDS)

    def save_suppression_page(self, page: SuppressionPage) -> int:
        """Suppress the page's addresses and return how many new rows it added."""
        if not page.addresses:
            return 0
        source, reason = CUSTOMERIO_SUPPRESSION_TYPES[page.suppression_type]
        # bulk_create skips the save() that moves a child environment's rows to its parent project.
        return self._add_suppressions(resolve_effective_team_id(self.team_id), page.addresses, source, reason)

    def _add_suppressions(
        self, team_id: int, imported: dict[str, _ImportedSuppression], source: SuppressionSource, reason: str
    ) -> int:
        """Suppress the addresses that have no suppression row yet, and return how many it added.

        An existing row is left alone. It can be a manual entry, an address someone removed from the list on
        purpose, or a row the bounce feedback already manages. The one exception is a row an earlier import of
        this list created without Customer.io's date and diagnostic, which gets them filled in.
        """
        suppressions = MessageSuppression.objects.for_team(team_id, canonical=True)
        existing = {row.identifier: row for row in suppressions.filter(identifier__in=list(imported))}
        now = timezone.now()
        is_bounce = source == SuppressionSource.BOUNCE
        new_rows = [
            MessageSuppression(
                team_id=team_id,
                identifier=email,
                source=source,
                reason=reason,
                suppressed=True,
                suppressed_at=details.suppressed_at or now,
                last_bounce_at=details.suppressed_at if is_bounce else None,
                last_bounce_diagnostic=details.diagnostic,
                # Customer.io lists an address under bounces or invalid emails only when it can't receive
                # mail, so these block transactional email the way our own hard bounces do.
                hard_bounced_at=(details.suppressed_at or now) if is_bounce else None,
                created_by_id=self.created_by_id,
            )
            for email, details in sorted(imported.items())
            if email not in existing
        ]
        # ignore_conflicts covers an address the bounce feedback inserts between the read above and this write.
        suppressions.bulk_create(new_rows, batch_size=500, ignore_conflicts=True)

        backfilled = []
        for email, row in existing.items():
            details = imported[email]
            if row.reason != reason or row.deleted or row.last_bounce_diagnostic or not details.suppressed_at:
                continue
            row.suppressed_at = details.suppressed_at
            row.last_bounce_at = details.suppressed_at if is_bounce else row.last_bounce_at
            row.last_bounce_diagnostic = details.diagnostic
            backfilled.append(row)
        suppressions.bulk_update(
            backfilled, ["suppressed_at", "last_bounce_at", "last_bounce_diagnostic"], batch_size=500
        )
        return len(new_rows)

    def _bulk_update_all_preferences(self, emails: list[str], category_ids: list[str]) -> None:
        """Bulk update preferences to opt out users from ALL categories"""
        try:
            self.save_opt_outs(emails, category_ids)
        except Exception as e:
            logger.exception(f"Error bulk updating all preferences: {e}")
            # Don't fall back to individual updates - it would make performance worse
            # Instead, record the batch failure and continue
            self.progress["errors"].append(f"Failed to update batch of {len(emails)} users: {str(e)[:200]}")

    def save_opt_outs(self, emails: list[str], category_ids: list[str]) -> int:
        """Opt the recipients out of the categories, keeping their other preferences.

        Returns how many recipients were not already opted out of every category.
        """
        # Customer.io can return several profiles with one email. A repeated address would add two rows for one
        # recipient and fail the whole batch on the unique (team, identifier) constraint.
        emails = list(dict.fromkeys(emails))
        changed = 0
        with transaction.atomic():
            # Fetch existing preferences
            existing_prefs = {
                pref.identifier: pref
                for pref in MessageRecipientPreference.objects.filter(team_id=self.team_id, identifier__in=emails)
            }

            to_create = []
            to_update = []

            for email in emails:
                if email in existing_prefs:
                    # Update existing preference
                    pref = existing_prefs[email]
                    if any(
                        pref.preferences.get(str(category_id)) != PreferenceStatus.OPTED_OUT.value
                        for category_id in category_ids
                    ):
                        changed += 1
                    for category_id in category_ids:
                        pref.preferences[str(category_id)] = PreferenceStatus.OPTED_OUT.value
                    to_update.append(pref)
                else:
                    # Create new preference with all categories opted out
                    preferences_dict = {
                        str(category_id): PreferenceStatus.OPTED_OUT.value for category_id in category_ids
                    }
                    changed += 1
                    to_create.append(
                        MessageRecipientPreference(
                            team_id=self.team_id,
                            identifier=email,
                            preferences=preferences_dict,
                        )
                    )

            # Bulk operations
            if to_create:
                # No ignore_conflicts: a row inserted between the read and this write must fail the batch, so a retry
                # merges the opt-out into it instead of silently skipping the recipient.
                MessageRecipientPreference.objects.bulk_create(to_create, batch_size=500)

            if to_update:
                MessageRecipientPreference.objects.bulk_update(to_update, ["preferences", "updated_at"], batch_size=500)

        return changed

    def _load_topic_mapping(self) -> None:
        """Load topic mapping from existing categories"""
        categories = MessageCategory.objects.filter(team_id=self.team_id, key__startswith="customerio_", deleted=False)

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


def _imported_suppression(entry: dict[str, Any]) -> _ImportedSuppression:
    """The date and bounce diagnostic Customer.io returns for one suppressed address."""
    created = entry.get("created")
    suppressed_at = (
        datetime.fromtimestamp(created, tz=UTC) if isinstance(created, int | float) and created > 0 else None
    )
    parts = [
        part.strip() for part in (entry.get("status"), entry.get("reason")) if isinstance(part, str) and part.strip()
    ]
    return _ImportedSuppression(suppressed_at=suppressed_at, diagnostic=" ".join(parts)[:1000] or None)
