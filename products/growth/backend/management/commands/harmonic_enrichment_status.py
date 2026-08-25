"""Read-only poll of Harmonic's /enrichment_status for recently archived enrichment URNs.

Measures how long Harmonic takes to finish enriching a stub company (companyFound: false,
enrichmentUrn set) into a resolvable record. Join the printed status against each row's
fetched_at to see when COMPLETE lands relative to the original lookup. Writes nothing to
the archive or the enrichment record. Needs HARMONIC_API_KEY, so run it from the
signup-enrichment worker shell, not a toolbox pod (the key deliberately never reaches web
pods).
"""

import csv
import asyncio
import datetime as dt
from collections import Counter
from typing import Any, Optional

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

import aiohttp

from products.growth.backend.models import OrganizationEnrichmentFetch

from ee.billing.salesforce_enrichment.constants import HARMONIC_BASE_URL

_BATCH_SIZE = 50
_SLEEP_BETWEEN_CALLS_SECONDS = 0.25
_REQUEST_TIMEOUT_SECONDS = 30
UNQUERIED_STATUS = "NOT_QUERIED"


def _rows_with_urn(since_days: int, limit: int) -> list[OrganizationEnrichmentFetch]:
    cutoff = timezone.now() - dt.timedelta(days=since_days)
    queryset = OrganizationEnrichmentFetch.objects.filter(fetched_at__gte=cutoff).order_by("-fetched_at", "-id")
    rows: list[OrganizationEnrichmentFetch] = []
    for fetch in queryset.iterator():
        payload = fetch.payload
        if isinstance(payload, dict) and payload.get("enrichmentUrn"):
            rows.append(fetch)
        if len(rows) >= limit:
            break
    return rows


async def _fetch_statuses(urns: list[str], api_key: str) -> dict[str, dict[str, Any]]:
    statuses: dict[str, dict[str, Any]] = {}
    timeout = aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(trust_env=True, timeout=timeout) as session:
        for start in range(0, len(urns), _BATCH_SIZE):
            if start > 0:
                await asyncio.sleep(_SLEEP_BETWEEN_CALLS_SECONDS)
            batch = urns[start : start + _BATCH_SIZE]
            async with session.get(
                f"{HARMONIC_BASE_URL}/enrichment_status",
                params=[("urns", urn) for urn in batch],
                headers={"apikey": api_key},
            ) as response:
                response.raise_for_status()
                data = await response.json()
            for entry in data:
                if isinstance(entry, dict) and isinstance(entry.get("entity_urn"), str):
                    statuses[entry["entity_urn"]] = entry
    return statuses


class Command(BaseCommand):
    help = (
        "Read-only poll of Harmonic's /enrichment_status for recently archived enrichment "
        "URNs. Writes nothing to the database."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--since-days", type=int, default=7, help="How many days back to look for archive rows")
        parser.add_argument("--limit", type=int, default=500, help="Max archive rows to poll")
        parser.add_argument("--out", help="Write per-row results to this CSV")

    def handle(self, *args: Any, **options: Any) -> None:
        api_key = getattr(settings, "HARMONIC_API_KEY", None)
        if not api_key:
            raise CommandError("HARMONIC_API_KEY is not set. Run this from a worker shell.")
        since_days: int = options["since_days"]
        limit: int = options["limit"]
        if since_days < 1:
            raise CommandError("--since-days must be a positive integer")
        if limit < 1:
            raise CommandError("--limit must be a positive integer")

        rows = _rows_with_urn(since_days, limit)
        if not rows:
            self.stdout.write(self.style.SUCCESS("no archived rows with an enrichmentUrn in the window"))
            return

        urns = list(dict.fromkeys(row.payload["enrichmentUrn"] for row in rows))
        statuses = asyncio.run(_fetch_statuses(urns, api_key))

        out_rows: list[dict[str, Optional[str]]] = []
        counts: Counter[str] = Counter()
        for row in rows:
            urn = row.payload["enrichmentUrn"]
            entry = statuses.get(urn, {})
            status = entry.get("status", UNQUERIED_STATUS)
            enriched_entity_urn = entry.get("enriched_entity_urn")
            counts[status] += 1
            out_rows.append(
                {
                    "organization_id": str(row.organization_id),
                    "fetched_at": row.fetched_at.isoformat(),
                    "is_recheck": str(row.is_recheck),
                    "urn": urn,
                    "status": status,
                    "enriched_entity_urn": enriched_entity_urn,
                }
            )
            self.stdout.write(
                f"{row.organization_id}\t{row.fetched_at.isoformat()}\t{row.is_recheck}\t{urn}\t"
                f"{status}\t{enriched_entity_urn}"
            )

        if options.get("out"):
            fieldnames = ["organization_id", "fetched_at", "is_recheck", "urn", "status", "enriched_entity_urn"]
            with open(options["out"], "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(out_rows)
            self.stdout.write(f"wrote {options['out']}")

        self.stdout.write(self.style.SUCCESS(f"polled {len(urns)} distinct urns from {len(rows)} rows"))
        for status, count in sorted(counts.items()):
            self.stdout.write(f"  {status}: {count}")
