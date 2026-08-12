"""Backfill ownership_status/parent_company/parent_company_domain for orgs enriched before
Harmonic ownership lookup shipped.

Targets OrganizationEnrichment rows with no "ownership_status" key in `data`, restricted to
orgs the live pipeline actually fetched from a provider (an OrganizationEnrichmentFetch row
exists) and not explicitly flagged personal-domain (data__work_email is not False) — this
excludes personal-domain signups, which never got a provider lookup and would otherwise have
a vendor's own ownership data written onto them. Known gap, accepted: archive_provider_fetch
never raises, so an org whose fetch succeeded but whose archive write failed silently has no
fetch row and is skipped here — rare, and skipping is the safe direction for this command. The missing "ownership_status" key is
otherwise absent both for pre-feature orgs and for orgs where Harmonic has no ownership
opinion, so a re-run is a no-op for the latter rather than a retry; see the write skip below.
Re-fetches each org fresh from Harmonic (paced by --sleep) rather than replaying the archived
payload, since the field didn't exist in the response schema this repo requested at the time of
the original fetch. The fresh fetch is archived the same way the live path archives one
(including a not-found), so the refreshed payload is available to the labels pipeline and any
later offline re-analysis; only the OrganizationEnrichment.data/group-property write is scoped
to the three ownership fields. Prints base-rate stats at the end for the vendor decision this
backfill exists to inform.
"""

import time
import asyncio
from typing import Any, Optional

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Exists, OuterRef, Q, QuerySet

from posthoganalytics.client import Client

from posthog.exceptions_capture import capture_exception
from posthog.ph_client import get_client

from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.labels import signup_domain_for_organization
from products.growth.backend.enrichment.providers import HarmonicEnrichmentProvider
from products.growth.backend.enrichment.writer import archive_provider_fetch, write_organization_enrichment
from products.growth.backend.models import OrganizationEnrichment, OrganizationEnrichmentFetch

_PROGRESS_INTERVAL = 100
_ACQUIRED_OR_MERGED = "ACQUIRED_OR_MERGED"
# Matches core.py's not-found placeholder verbatim (companyFound is part of Harmonic's own
# response shape) rather than importing that module-private constant across files.
_MISS_PAYLOAD = {"companyFound": False}


def _unbackfilled_qs() -> QuerySet[OrganizationEnrichment]:
    # Eligibility is "the live pipeline actually fetched this org from a provider", not
    # "has a work_email flag" — personal-domain signups get a work_email=False record but
    # never a provider fetch, so requiring a fetch row keeps them out without depending on
    # work_email having been recorded (it postdates some existing rows).
    has_fetch = OrganizationEnrichmentFetch.objects.filter(organization_id=OuterRef("organization_id"))
    return (
        OrganizationEnrichment.objects.exclude(data__has_key="ownership_status")
        # Q(has_key) & Q(==False), not a bare exclude(data__work_email=False): JSONField key
        # lookups return SQL NULL for a missing key, and exclude() on a bare comparison would
        # drop those NULL rows too (Django's documented JSONField exclude() gotcha).
        .exclude(Q(data__has_key="work_email") & Q(data__work_email=False))
        .filter(Exists(has_fetch))
        .select_related("organization")
        .order_by("id")
    )


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

        qs = _unbackfilled_qs()
        if after_id:
            qs = qs.filter(id__gt=after_id)
        records = list(qs[:limit])

        provider = HarmonicEnrichmentProvider()
        # Never constructed in --dry-run: nothing is written, so nothing should touch the network.
        pha_client: Optional[Client] = None if dry_run else get_client()

        counts = {
            "processed": 0,
            "no_domain": 0,
            "fetch_failures": 0,
            "not_found": 0,
            "found_no_ownership_status": 0,
            "errors": 0,
            "classified": 0,
            "acquired_or_merged": 0,
            "acquired_or_merged_with_parent": 0,
        }
        last_id: str | None = after_id

        try:
            for record in records:
                last_id = str(record.id)
                try:
                    self._process_one(record, provider, pha_client, dry_run, sleep_seconds, counts)
                except Exception as e:
                    capture_exception(e, {"organization_id": str(record.organization_id)})
                    counts["errors"] += 1
                counts["processed"] += 1
                if counts["processed"] % _PROGRESS_INTERVAL == 0:
                    self.stdout.write(f"processed {counts['processed']}/{len(records)}, last_id={last_id}")
        finally:
            if pha_client is not None:
                pha_client.shutdown()

        self.stdout.write(self._summary(counts, last_id))

    def _process_one(
        self,
        record: OrganizationEnrichment,
        provider: HarmonicEnrichmentProvider,
        pha_client: Optional[Client],
        dry_run: bool,
        sleep_seconds: float,
        counts: dict[str, int],
    ) -> None:
        domain = signup_domain_for_organization(record.organization)
        if domain is None:
            counts["no_domain"] += 1
            return

        try:
            lookup = asyncio.run(provider.enrich_by_domain(domain))
        except Exception as e:
            capture_exception(e, {"organization_id": str(record.organization_id), "domain": domain})
            counts["fetch_failures"] += 1
            return
        finally:
            time.sleep(sleep_seconds)

        # Every successful fetch is archived verbatim, including a not-found, same as the live
        # path (core.py) — the refreshed payload now carries ownershipStatus/relatedCompanies for
        # the labels pipeline and any future offline re-analysis to read.
        if not dry_run:
            archive_provider_fetch(
                organization_id=str(record.organization_id),
                provider=provider.name,
                payload=lookup.raw_payload if lookup.raw_payload is not None else _MISS_PAYLOAD,
                is_recheck=True,
            )

        if lookup.fields is None:
            counts["not_found"] += 1
            return

        ownership_status = lookup.fields.ownership_status
        if ownership_status is None:
            counts["found_no_ownership_status"] += 1
            return

        counts["classified"] += 1
        if ownership_status == _ACQUIRED_OR_MERGED:
            counts["acquired_or_merged"] += 1
            if lookup.fields.parent_company:
                counts["acquired_or_merged_with_parent"] += 1

        if dry_run or pha_client is None:
            return

        # Scoped to just the three ownership keys: to_dict()/to_group_properties() only emit set
        # fields, so leaving every other EnrichmentFields attribute unset keeps this write from
        # touching icp_* or any other field a fresh fetch would otherwise churn.
        write_organization_enrichment(
            organization_id=str(record.organization_id),
            fields=EnrichmentFields(
                ownership_status=ownership_status,
                parent_company=lookup.fields.parent_company,
                parent_company_domain=lookup.fields.parent_company_domain,
            ),
            pha_client=pha_client,
        )

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
            f"processed {processed}, fetch_failures {counts['fetch_failures']}, "
            f"not_found {counts['not_found']}, no_domain {counts['no_domain']}, "
            f"found_no_ownership_status {counts['found_no_ownership_status']}, errors {counts['errors']}, "
            f"classified {classified} ({classified_pct:.1f}% of processed), "
            f"acquired_or_merged {acquired} ({acquired_pct:.1f}% of classified), "
            f"acquired_or_merged_with_parent {with_parent} ({with_parent_pct:.1f}% of acquired_or_merged), "
            f"last_id={last_id}"
        )
