from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.growth.backend.facade import api

_PROGRESS_INTERVAL = 100


class Command(BaseCommand):
    help = (
        "Backfill ownership_status, parent_company, and parent_company_domain onto already-"
        "enriched work-domain organizations (personal-domain signups are excluded), and print "
        "ACQUIRED_OR_MERGED / parent-resolution base rates. An org whose fresh fetch has no "
        "ownership_status is counted as processed but left unwritten and un-flagged for retry "
        "— re-running this command will fetch it again every time until Harmonic starts "
        "returning a value for it."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--after-id", default=None, help="Resume after this OrganizationEnrichment id")
        parser.add_argument("--limit", type=int, default=500, help="Process at most this many orgs")
        parser.add_argument("--dry-run", action="store_true", help="Fetch and count without writing anything")
        parser.add_argument("--sleep", type=float, default=0.2, help="Seconds to sleep between Harmonic fetches")

    def handle(self, *args: Any, **options: Any) -> None:
        after_id: str | None = options["after_id"]
        limit: int = options["limit"]
        dry_run: bool = options["dry_run"]
        sleep_seconds: float = options["sleep"]
        if limit < 1:
            raise CommandError("--limit must be at least 1")
        if sleep_seconds < 0:
            raise CommandError("--sleep must be at least 0")

        run = api.backfill_harmonic_ownership(
            after_id=after_id, limit=limit, dry_run=dry_run, sleep_seconds=sleep_seconds
        )

        counts = {
            "processed": 0,
            "no_domain": 0,
            "fetch_failure": 0,
            "not_found": 0,
            "found_no_ownership_status": 0,
            "errors": 0,
            "classified": 0,
            "acquired_or_merged": 0,
            "acquired_or_merged_with_parent": 0,
        }
        last_id: str | None = after_id

        for item in run.items:
            last_id = item.record_id
            if item.outcome is not None:
                counts[item.outcome] += 1
            if item.acquired_or_merged:
                counts["acquired_or_merged"] += 1
            if item.with_parent:
                counts["acquired_or_merged_with_parent"] += 1
            if item.errored:
                counts["errors"] += 1
            counts["processed"] += 1
            if counts["processed"] % _PROGRESS_INTERVAL == 0:
                self.stdout.write(f"processed {counts['processed']}/{run.total}, last_id={last_id}")

        self.stdout.write(self._summary(counts, last_id))

    def _summary(self, counts: dict[str, int], last_id: str | None) -> str:
        processed = counts["processed"]
        # Only orgs Harmonic returned an ownership_status for can carry a base rate. A no-domain,
        # failed, not-found, or ownership-silent org is unknown rather than "not acquired" — the
        # ownership fields are beta and silent on acquisitions we know happened, so counting those
        # as negatives would understate the rate this backfill exists to measure.
        classified = counts["classified"]
        classified_pct = (classified / processed * 100) if processed else 0.0
        acquired = counts["acquired_or_merged"]
        acquired_pct = (acquired / classified * 100) if classified else 0.0
        with_parent = counts["acquired_or_merged_with_parent"]
        with_parent_pct = (with_parent / acquired * 100) if acquired else 0.0
        return (
            f"processed {processed}, fetch_failures {counts['fetch_failure']}, "
            f"not_found {counts['not_found']}, no_domain {counts['no_domain']}, "
            f"found_no_ownership_status {counts['found_no_ownership_status']}, errors {counts['errors']}, "
            f"classified {classified} ({classified_pct:.1f}% of processed), "
            f"acquired_or_merged {acquired} ({acquired_pct:.1f}% of classified), "
            f"acquired_or_merged_with_parent {with_parent} ({with_parent_pct:.1f}% of acquired_or_merged), "
            f"last_id={last_id}"
        )
