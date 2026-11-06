"""Re-derive enrichment fields from each org's latest archived Harmonic payload and rewrite them.

Generic by design: this re-runs the CURRENT transform_harmonic_company against the stored raw
payload, so it always picks up every field the transform produces at run time -- not just the
fields present when this command was written. A later addition to EnrichmentFields therefore
backfills through this same command with no changes here; only the field registry needs to grow.

Safe to re-run: group_identify overwrites the same keys, and a payload that yields no fields is
skipped rather than clearing anything already written.

Also deletes stale suppressed-placeholder values (see SUPPRESSED_PLACEHOLDERS) from the Postgres
record when the current transform no longer derives the key from the same payload. Deletion is
Postgres-only: group properties cannot be deleted, so ClickHouse keeps any historical placeholder
-- measure field completeness on this table's warehouse copy, not on group properties.
"""

import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from posthog.ph_client import get_client
from posthog.utils import get_instance_region

from products.growth.backend.enrichment.labels import recent_latest_fetches_qs
from products.growth.backend.enrichment.transform import transform_harmonic_company
from products.growth.backend.enrichment.writer import write_organization_enrichment
from products.growth.backend.models import OrganizationEnrichment

# Values older transform versions wrote for a key that the current transform deliberately
# suppresses when the payload can't substantiate them. Only these exact values are ever deleted,
# so a genuine historical value can't be swept up by an over-eager cleanup.
SUPPRESSED_PLACEHOLDERS: dict[str, frozenset[str]] = {"funding_stage": frozenset({"VENTURE_UNKNOWN"})}


def stale_placeholder_keys(data: dict[str, Any], derived: dict[str, Any]) -> list[str]:
    return [
        key
        for key, placeholders in SUPPRESSED_PLACEHOLDERS.items()
        if key not in derived and data.get(key) in placeholders
    ]


def _strip_stale_placeholders(organization_id: str, derived: dict[str, Any]) -> list[str]:
    # Same row lock as the writer's merge, for the same reason: a concurrent live write must not
    # be clobbered by this read-modify-save.
    with transaction.atomic():
        record = OrganizationEnrichment.objects.select_for_update().filter(organization_id=organization_id).first()
        if record is None:
            return []
        stale = stale_placeholder_keys(record.data, derived)
        if stale:
            record.data = {key: value for key, value in record.data.items() if key not in stale}
            record.save(update_fields=["data", "updated_at"])
        return stale


class Command(BaseCommand):
    help = (
        "Re-derive enrichment fields from each organization's latest archived provider fetch and "
        "rewrite the OrganizationEnrichment record and organization group properties. Generic: "
        "re-runs the current transform against the stored payload, so a future field added to "
        "EnrichmentFields backfills through this same command without any changes here. Never "
        "computes or touches icp_score."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--limit", type=int, default=None, help="Backfill at most this many organizations")
        parser.add_argument("--delay", type=float, default=0.1, help="Seconds to sleep between writes")
        parser.add_argument("--dry-run", action="store_true", help="Report what would be written without writing")

    def handle(self, *args: Any, **options: Any) -> None:
        # Enrichment is US-only for v0 (mirrors the signup-path region gate).
        if get_instance_region() != "US":
            raise CommandError("Signup enrichment is US-only; refusing to backfill in this region")

        limit: int | None = options["limit"]
        delay: float = options["delay"]
        dry_run: bool = options["dry_run"]
        if limit is not None and limit < 1:
            raise CommandError("--limit must be a positive integer")
        if delay < 0:
            raise CommandError("--delay must be >= 0")
        pha_client = get_client()

        fetches = recent_latest_fetches_qs()
        if limit is not None:
            fetches = fetches[:limit]

        considered = written = skipped_no_match = skipped_empty = stripped_stale = 0
        for fetch in fetches.iterator():
            considered += 1
            payload = fetch.payload
            # `{"companyFound": False}` is core.py's archived placeholder for a genuine provider
            # miss -- a truthy dict that would otherwise sail through the isinstance check below
            # and get scored as a real (if empty) company by transform_harmonic_company.
            if not isinstance(payload, dict) or payload.get("companyFound") is False:
                skipped_no_match += 1
                continue

            fields = transform_harmonic_company(payload)
            if fields is None:
                skipped_no_match += 1
                continue

            values = fields.to_dict()
            if not values:
                skipped_empty += 1
                continue

            written += 1
            if dry_run:
                record = OrganizationEnrichment.objects.filter(organization_id=fetch.organization_id).first()
                stale = stale_placeholder_keys(record.data, values) if record else []
                if stale:
                    stripped_stale += 1
                suffix = f", would strip {stale}" if stale else ""
                self.stdout.write(f"would write {fetch.organization_id}: {sorted(values)}{suffix}")
                continue

            write_organization_enrichment(
                organization_id=str(fetch.organization_id), fields=fields, pha_client=pha_client
            )
            stale = _strip_stale_placeholders(str(fetch.organization_id), values)
            if stale:
                stripped_stale += 1
            suffix = f", stripped {stale}" if stale else ""
            self.stdout.write(f"wrote {fetch.organization_id}: {sorted(values)}{suffix}")
            if delay:
                time.sleep(delay)

        verb = "would write" if dry_run else "wrote"
        summary = (
            f"considered {considered}, {verb} {written}, "
            f"skipped_no_match {skipped_no_match}, skipped_empty {skipped_empty}, "
            f"stripped_stale {stripped_stale}"
        )
        self.stdout.write(self.style.SUCCESS(summary))
