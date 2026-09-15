from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.growth.backend.facade import api, contracts

_REGION_NOT_ALLOWED = "Signup enrichment is US-only; refusing to backfill in this region"


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
        try:
            api.ensure_fields_backfill_allowed()
        except contracts.RegionNotAllowed:
            raise CommandError(_REGION_NOT_ALLOWED)

        limit: int | None = options["limit"]
        delay: float = options["delay"]
        dry_run: bool = options["dry_run"]
        if limit is not None and limit < 1:
            raise CommandError("--limit must be a positive integer")
        if delay < 0:
            raise CommandError("--delay must be >= 0")

        try:
            items = api.backfill_enrichment_fields(limit=limit, delay=delay, dry_run=dry_run)
        except contracts.RegionNotAllowed:
            raise CommandError(_REGION_NOT_ALLOWED)

        verb = "would write" if dry_run else "wrote"
        strip_verb = "would strip" if dry_run else "stripped"
        considered = written = skipped_no_match = skipped_empty = stripped_stale = 0
        for item in items:
            considered += 1
            if item.outcome == "skipped_no_match":
                skipped_no_match += 1
                continue
            if item.outcome == "skipped_empty":
                skipped_empty += 1
                continue
            written += 1
            if item.stripped:
                stripped_stale += 1
            suffix = f", {strip_verb} {list(item.stripped)}" if item.stripped else ""
            self.stdout.write(f"{verb} {item.organization_id}: {list(item.fields)}{suffix}")

        summary = (
            f"considered {considered}, {verb} {written}, "
            f"skipped_no_match {skipped_no_match}, skipped_empty {skipped_empty}, "
            f"stripped_stale {stripped_stale}"
        )
        self.stdout.write(self.style.SUCCESS(summary))
