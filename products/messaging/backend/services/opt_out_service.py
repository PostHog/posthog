import csv
import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Optional

from django.db import connections, transaction
from django.db.models import Q

from posthog.security.spreadsheet_safety import sanitize_formula_injection

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)

logger = logging.getLogger(__name__)

EXPORT_HEADER = ["identifier", "category_key", "updated_at"]

BATCH_SIZE = 1000
MAX_REPORTED_ERRORS = 10


class UnknownCategoryError(Exception):
    def __init__(self, category_key: str):
        self.category_key = category_key
        super().__init__(f"Message category '{category_key}' not found")


@dataclass(frozen=True, kw_only=True)
class BulkOptOutEntry:
    identifier: str
    category_key: Optional[str] = None


@dataclass(frozen=True, kw_only=True)
class BulkOptOutResult:
    total: int
    opted_out: int
    skipped: int
    errors: list[str]


class _Echo:
    """File-like sink so csv.writer can hand rows straight to a streaming response."""

    def write(self, value: str) -> str:
        return value


class OptOutService:
    """Reads and writes opt-out lists in bulk, so recipients can be moved in and out of PostHog."""

    def __init__(self, team_id: int, user: Optional[Any] = None):
        self.team_id = team_id
        self.user = user

    def _category_key_to_id(self) -> dict[str, str]:
        """Map every usable category key to the ID stored in a recipient's preferences blob."""
        mapping = {
            key: str(category_id)
            for key, category_id in MessageCategory.objects.filter(team_id=self.team_id, deleted=False).values_list(
                "key", "id"
            )
        }
        mapping[ALL_MESSAGE_PREFERENCE_CATEGORY_ID] = ALL_MESSAGE_PREFERENCE_CATEGORY_ID
        return mapping

    def resolve_category_id(self, category_key: Optional[str]) -> str:
        """Turn a category key into its preferences-blob ID, defaulting to the all-marketing opt-out."""
        if not category_key or category_key == ALL_MESSAGE_PREFERENCE_CATEGORY_ID:
            return ALL_MESSAGE_PREFERENCE_CATEGORY_ID

        category_id = self._category_key_to_id().get(category_key)
        if category_id is None:
            raise UnknownCategoryError(category_key)
        return category_id

    def export_rows(self, category_key: Optional[str] = None) -> Iterator[str]:
        """Return the opt-out list for one category as CSV lines, ready to stream.

        The category is resolved eagerly so an unknown key surfaces as a normal
        error rather than half way through a response that already sent a 200.

        Rows are fetched in keyset-paginated batches with the DB connection closed
        after each fetch: streaming_response() releases the request connections
        before the body runs, so anything the generator opens would otherwise stay
        pinned to a pgbouncer slot for as long as the client takes to download.
        """
        category_id = self.resolve_category_id(category_key)
        export_key = category_key or ALL_MESSAGE_PREFERENCE_CATEGORY_ID

        def fetch_batch(after: Optional[tuple[Any, Any]]) -> list[tuple[str, Any, Any]]:
            queryset = MessageRecipientPreference.objects.filter(
                team_id=self.team_id,
                **{f"preferences__{category_id}": PreferenceStatus.OPTED_OUT.value},
            ).order_by("-updated_at", "-id")
            if after is not None:
                queryset = queryset.filter(Q(updated_at__lt=after[0]) | Q(updated_at=after[0], id__lt=after[1]))
            batch = list(queryset.values_list("identifier", "updated_at", "id")[:BATCH_SIZE])
            # Same guard as _release_request_connections: severing an open transaction
            # corrupts it (only tests stream inside one).
            connection = connections[MessageRecipientPreference.objects.db]
            if not connection.in_atomic_block:
                connection.close()
            return batch

        def rows() -> Iterator[str]:
            writer = csv.writer(_Echo())
            yield writer.writerow(EXPORT_HEADER)
            after: Optional[tuple[Any, Any]] = None
            while True:
                batch = fetch_batch(after)
                if not batch:
                    return
                for identifier, updated_at, _ in batch:
                    yield writer.writerow(
                        [
                            sanitize_formula_injection(identifier),
                            sanitize_formula_injection(export_key),
                            updated_at.isoformat(),
                        ]
                    )
                after = (batch[-1][1], batch[-1][2])

        return rows()

    def opt_out_recipients(
        self, entries: Sequence[BulkOptOutEntry], default_category_key: Optional[str] = None
    ) -> BulkOptOutResult:
        """Opt every recipient out of the category named on their entry, or the default one.

        An entry naming a category that doesn't exist is skipped and reported rather
        than failing the request, so one bad entry can't block the rest of the list.
        """
        default_category_id = self.resolve_category_id(default_category_key)
        key_to_id = self._category_key_to_id()

        opted_out = 0
        skipped = 0
        errors: list[str] = []
        pending: dict[str, set[str]] = {}

        for entry_number, entry in enumerate(entries, start=1):
            category_id = default_category_id
            if entry.category_key:
                resolved = key_to_id.get(entry.category_key)
                if resolved is None:
                    skipped += 1
                    _record_error(errors, f"Entry {entry_number}: no message category with key '{entry.category_key}'")
                    continue
                category_id = resolved

            categories = pending.setdefault(entry.identifier, set())
            if category_id not in categories:
                categories.add(category_id)
                opted_out += 1

            if len(pending) >= BATCH_SIZE:
                self._save_batch(pending)
                pending = {}

        if pending:
            self._save_batch(pending)

        return BulkOptOutResult(total=len(entries), opted_out=opted_out, skipped=skipped, errors=errors)

    def _save_batch(self, batch: dict[str, set[str]]) -> None:
        with transaction.atomic():
            existing = {
                preference.identifier: preference
                for preference in MessageRecipientPreference.objects.filter(
                    team_id=self.team_id, identifier__in=list(batch.keys())
                )
            }

            to_create = []
            to_update = []

            for identifier, category_ids in batch.items():
                preference = existing.get(identifier)
                if preference is None:
                    to_create.append(
                        MessageRecipientPreference(
                            team_id=self.team_id,
                            identifier=identifier,
                            created_by=self.user,
                            preferences=dict.fromkeys(category_ids, PreferenceStatus.OPTED_OUT.value),
                        )
                    )
                    continue

                for category_id in category_ids:
                    preference.preferences[category_id] = PreferenceStatus.OPTED_OUT.value
                to_update.append(preference)

            if to_create:
                MessageRecipientPreference.objects.bulk_create(to_create, batch_size=500)
            if to_update:
                MessageRecipientPreference.objects.bulk_update(to_update, ["preferences", "updated_at"], batch_size=500)


def _record_error(errors: list[str], message: str) -> None:
    if len(errors) < MAX_REPORTED_ERRORS:
        errors.append(message)
