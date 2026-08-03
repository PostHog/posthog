import csv
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Optional

from django.db import transaction

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)

logger = logging.getLogger(__name__)

EXPORT_HEADER = ["identifier", "category_key", "updated_at"]

# Accepted spellings for the two columns we read, so a list exported from another
# messaging tool usually imports without being reshaped first.
IDENTIFIER_COLUMNS = ("identifier", "email", "recipient", "email_address")
CATEGORY_COLUMNS = ("category_key", "category")

BATCH_SIZE = 1000
MAX_REPORTED_ERRORS = 10


class UnknownCategoryError(Exception):
    def __init__(self, category_key: str):
        self.category_key = category_key
        super().__init__(f"Message category '{category_key}' not found")


@dataclass(frozen=True, kw_only=True)
class OptOutCsvImportResult:
    total_rows: int
    opted_out: int
    skipped_rows: int
    errors: list[str]


class _Echo:
    """File-like sink so csv.writer can hand rows straight to a streaming response."""

    def write(self, value: str) -> str:
        return value


class OptOutCsvService:
    """Reads and writes opt-out lists as CSV, so recipients can be moved in and out of PostHog."""

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
        """
        category_id = self.resolve_category_id(category_key)
        export_key = category_key or ALL_MESSAGE_PREFERENCE_CATEGORY_ID

        opt_outs = (
            MessageRecipientPreference.objects.filter(
                team_id=self.team_id,
                **{f"preferences__{category_id}": PreferenceStatus.OPTED_OUT.value},
            )
            .order_by("-updated_at")
            .values_list("identifier", "updated_at")
        )

        def rows() -> Iterator[str]:
            writer = csv.writer(_Echo())
            yield writer.writerow(EXPORT_HEADER)
            for identifier, updated_at in opt_outs.iterator(chunk_size=BATCH_SIZE):
                yield writer.writerow([identifier, export_key, updated_at.isoformat()])

        return rows()

    def import_csv(self, csv_file: Any, default_category_key: Optional[str] = None) -> OptOutCsvImportResult:
        """Opt every recipient in the CSV out of the category named on their row, or the default one."""
        default_category_id = self.resolve_category_id(default_category_key)
        key_to_id = self._category_key_to_id()

        reader = csv.reader(_decoded_lines(csv_file))
        try:
            header = next(reader)
        except StopIteration:
            return OptOutCsvImportResult(total_rows=0, opted_out=0, skipped_rows=0, errors=["The file is empty"])

        normalized_header = [column.strip().lower() for column in header]
        identifier_index = _find_column(normalized_header, IDENTIFIER_COLUMNS)
        if identifier_index is None:
            return OptOutCsvImportResult(
                total_rows=0,
                opted_out=0,
                skipped_rows=0,
                errors=[f"No recipient column found. Add a column named one of: {', '.join(IDENTIFIER_COLUMNS)}"],
            )
        category_index = _find_column(normalized_header, CATEGORY_COLUMNS)

        total_rows = 0
        opted_out = 0
        skipped_rows = 0
        errors: list[str] = []
        pending: dict[str, set[str]] = {}

        for row_number, row in enumerate(reader, start=2):
            if not any(cell.strip() for cell in row):
                continue

            total_rows += 1

            identifier = row[identifier_index].strip() if identifier_index < len(row) else ""
            if not identifier:
                skipped_rows += 1
                _record_error(errors, f"Row {row_number}: missing a recipient")
                continue

            category_id = default_category_id
            if category_index is not None and category_index < len(row):
                row_category_key = row[category_index].strip()
                if row_category_key:
                    resolved = key_to_id.get(row_category_key)
                    if resolved is None:
                        skipped_rows += 1
                        _record_error(errors, f"Row {row_number}: no message category with key '{row_category_key}'")
                        continue
                    category_id = resolved

            categories = pending.setdefault(identifier, set())
            if category_id not in categories:
                categories.add(category_id)
                opted_out += 1

            if len(pending) >= BATCH_SIZE:
                self._save_batch(pending)
                pending = {}

        if pending:
            self._save_batch(pending)

        return OptOutCsvImportResult(
            total_rows=total_rows, opted_out=opted_out, skipped_rows=skipped_rows, errors=errors
        )

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


def _decoded_lines(csv_file: Any) -> Iterator[str]:
    """Stream an uploaded file as text lines without holding the whole upload in memory twice."""
    for line in csv_file:
        yield line.decode("utf-8-sig") if isinstance(line, bytes) else line


def _find_column(header: list[str], candidates: tuple[str, ...]) -> Optional[int]:
    for candidate in candidates:
        if candidate in header:
            return header.index(candidate)
    return None


def _record_error(errors: list[str], message: str) -> None:
    if len(errors) < MAX_REPORTED_ERRORS:
        errors.append(message)
