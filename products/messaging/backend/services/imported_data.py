"""Writes data imported from another messaging tool. Re-importing never undoes a change made in PostHog.

Every writer here adds what is missing and leaves existing rows alone, deleted ones included: someone may have removed
that address from the list, opted that person back in, or deleted that category on purpose.
"""

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime

from django.db import models, transaction
from django.db.models import F, Value
from django.db.models.expressions import CombinedExpression
from django.db.models.functions import Coalesce
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

from products.messaging.backend.models.message_category import MessageCategory, MessageCategoryType
from products.messaging.backend.models.message_preferences import MessageRecipientPreference, PreferenceStatus
from products.messaging.backend.models.message_suppression import MessageSuppression, SuppressionSource


@frozen
class ImportedSuppression:
    identifier: str
    source: SuppressionSource
    reason: str
    # When the other tool suppressed the address, or None when it doesn't say.
    suppressed_at: datetime | None = None
    diagnostic: str | None = None


@frozen
class SuppressionImportResult:
    added: Mapping[SuppressionSource, int]
    already_present: int

    @property
    def total_added(self) -> int:
        return sum(self.added.values())


@frozen
class ImportedCategory:
    key: str
    name: str
    description: str = ""


@frozen
class CategoryImportResult:
    # The category id for every key, new or not. A category someone deleted is left out, so nothing opts out of it.
    ids_by_key: Mapping[str, str]
    created: int
    already_present: int


def import_suppressions(
    team_id: int, imported: Iterable[ImportedSuppression], created_by_id: int | None
) -> SuppressionImportResult:
    """Suppress the addresses that have no row yet.

    A bounce blocks every email, because the other tool lists one only for an address that can't receive mail. Nothing
    here writes to the global hard-bounce list: one team's list must not block addresses for every other team. The one
    change to an existing row is filling in the date and diagnostic of a row an earlier import of the same list wrote
    without them.
    """
    # bulk_create skips the save() that moves a child environment's rows to its parent project.
    effective_team_id = resolve_effective_team_id(team_id)
    by_identifier = {record.identifier: record for record in imported}
    suppressions = MessageSuppression.objects.for_team(effective_team_id, canonical=True)
    existing = {row.identifier: row for row in suppressions.filter(identifier__in=list(by_identifier))}
    now = timezone.now()
    new_rows = [
        MessageSuppression(
            team_id=effective_team_id,
            identifier=identifier,
            source=record.source,
            reason=record.reason,
            suppressed=True,
            suppressed_at=record.suppressed_at or now,
            last_bounce_at=record.suppressed_at if record.source == SuppressionSource.BOUNCE else None,
            last_bounce_diagnostic=record.diagnostic,
            hard_bounced_at=(record.suppressed_at or now) if record.source == SuppressionSource.BOUNCE else None,
            created_by_id=created_by_id,
        )
        # Sorted so concurrent imports take the unique-index locks in the same order and can't deadlock.
        for identifier, record in sorted(by_identifier.items())
        if identifier not in existing
    ]
    # ignore_conflicts covers an address the bounce feedback inserts between the read above and this write.
    suppressions.bulk_create(new_rows, batch_size=500, ignore_conflicts=True)
    inserted = set(suppressions.filter(pk__in=[row.pk for row in new_rows]).values_list("identifier", flat=True))

    backfilled = []
    for identifier, row in existing.items():
        record = by_identifier[identifier]
        if row.reason != record.reason or row.deleted or row.last_bounce_diagnostic or not record.suppressed_at:
            continue
        row.suppressed_at = record.suppressed_at
        if record.source == SuppressionSource.BOUNCE:
            row.last_bounce_at = record.suppressed_at
        row.last_bounce_diagnostic = record.diagnostic
        backfilled.append(row)
    suppressions.bulk_update(backfilled, ["suppressed_at", "last_bounce_at", "last_bounce_diagnostic"], batch_size=500)

    added = Counter(by_identifier[identifier].source for identifier in inserted)
    return SuppressionImportResult(added=added, already_present=len(by_identifier) - len(inserted))


def import_opt_outs(team_id: int, opt_outs: Mapping[str, Iterable[str]], created_by_id: int | None) -> int:
    """Opt each address out of its categories, and return how many addresses gained an opt-out.

    A choice already stored for a category stays, so a person opted back in here isn't opted out again.
    """
    patches = {
        identifier: {str(category_id): PreferenceStatus.OPTED_OUT.value for category_id in category_ids}
        for identifier, category_ids in opt_outs.items()
    }
    patches = {identifier: patch for identifier, patch in patches.items() if patch}
    if not patches:
        return 0
    preferences = MessageRecipientPreference.objects.filter(team_id=team_id)
    with transaction.atomic():
        existing = {row.identifier: row for row in preferences.filter(identifier__in=list(patches))}
        new_rows = [
            MessageRecipientPreference(
                team_id=team_id, identifier=identifier, preferences=patch, created_by_id=created_by_id
            )
            for identifier, patch in sorted(patches.items())
            if identifier not in existing
        ]
        MessageRecipientPreference.objects.bulk_create(new_rows, batch_size=500, ignore_conflicts=True)
        changed = len(new_rows)
        for identifier, row in existing.items():
            patch = patches[identifier]
            stored = row.preferences or {}
            if row.deleted or all(key in stored for key in patch):
                continue
            # The stored side of the merge wins. A choice made after the read above is kept too.
            preferences.filter(pk=row.pk).update(
                preferences=CombinedExpression(
                    Value(patch, output_field=models.JSONField()),
                    "||",
                    Coalesce(F("preferences"), Value({}, output_field=models.JSONField())),
                ),
                updated_at=timezone.now(),
            )
            changed += 1
    return changed


def import_categories(
    team_id: int, categories: Iterable[ImportedCategory], created_by_id: int | None
) -> CategoryImportResult:
    """Create the marketing categories that don't exist yet. An existing one keeps any edit made to it."""
    by_key = {category.key: category for category in categories}
    existing = {row.key: row for row in MessageCategory.objects.filter(team_id=team_id, key__in=list(by_key))}
    MessageCategory.objects.bulk_create(
        [
            MessageCategory(
                team_id=team_id,
                key=category.key,
                name=category.name,
                description=category.description,
                public_description=category.description,
                category_type=MessageCategoryType.MARKETING,
                created_by_id=created_by_id,
            )
            for key, category in sorted(by_key.items())
            if key not in existing
        ],
        ignore_conflicts=True,
    )
    live = MessageCategory.objects.filter(team_id=team_id, key__in=list(by_key), deleted=False)
    created = sum(1 for key in by_key if key not in existing)
    return CategoryImportResult(
        ids_by_key={key: str(category_id) for key, category_id in live.values_list("key", "id")},
        created=created,
        already_present=len(by_key) - created,
    )
