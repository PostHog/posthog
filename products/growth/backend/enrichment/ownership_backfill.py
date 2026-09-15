"""Backfill ownership_status/parent_company/parent_company_domain for orgs enriched before
Harmonic ownership lookup shipped.

Targets OrganizationEnrichment rows with no "ownership_status" key in `data`, restricted to
orgs the live pipeline actually fetched from a provider (an OrganizationEnrichmentFetch row
exists) and not explicitly flagged personal-domain (data__work_email is not False) — this
excludes personal-domain signups, which never got a provider lookup and would otherwise have
a vendor's own ownership data written onto them. Known gap, accepted: archive_provider_fetch
never raises, so an org whose fetch succeeded but whose archive write failed silently has no
fetch row and is skipped here — rare, and skipping is the safe direction. The missing
"ownership_status" key is otherwise absent both for pre-feature orgs and for orgs where
Harmonic has no ownership opinion, so a re-run is a no-op for the latter rather than a retry;
see the write skip below. Re-fetches each org fresh from Harmonic (paced by the sleep) rather
than replaying the archived payload, since the field didn't exist in the response schema this
repo requested at the time of the original fetch. The fresh fetch is archived the same way the
live path archives one (including a not-found), so the refreshed payload is available to the
labels pipeline and any later offline re-analysis; only the OrganizationEnrichment.data/group-
property write is scoped to the three ownership fields.
"""

import time
import asyncio
from collections.abc import Iterator
from typing import Optional

from django.db.models import Exists, OuterRef, Q, QuerySet

from posthoganalytics.client import Client

from posthog.exceptions_capture import capture_exception
from posthog.ph_client import get_client

from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.labels import signup_domain_for_organization
from products.growth.backend.enrichment.providers import HarmonicEnrichmentProvider
from products.growth.backend.enrichment.writer import archive_provider_fetch, write_organization_enrichment
from products.growth.backend.facade.contracts import OwnershipBackfill, OwnershipBackfillItem, OwnershipOutcome
from products.growth.backend.models import OrganizationEnrichment, OrganizationEnrichmentFetch

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


def backfill_harmonic_ownership(
    *, after_id: str | None, limit: int, dry_run: bool, sleep_seconds: float
) -> OwnershipBackfill:
    qs = _unbackfilled_qs()
    if after_id:
        qs = qs.filter(id__gt=after_id)
    records = list(qs[:limit])

    provider = HarmonicEnrichmentProvider()
    # Never constructed in a dry run: nothing is written, so nothing should touch the network.
    pha_client: Optional[Client] = None if dry_run else get_client()
    return OwnershipBackfill(
        total=len(records),
        items=_iter_records(records, provider, pha_client, dry_run, sleep_seconds),
    )


def _iter_records(
    records: list[OrganizationEnrichment],
    provider: HarmonicEnrichmentProvider,
    pha_client: Optional[Client],
    dry_run: bool,
    sleep_seconds: float,
) -> Iterator[OwnershipBackfillItem]:
    try:
        for record in records:
            yield _process_one(record, provider, pha_client, dry_run, sleep_seconds)
    finally:
        if pha_client is not None:
            pha_client.shutdown()


def _process_one(
    record: OrganizationEnrichment,
    provider: HarmonicEnrichmentProvider,
    pha_client: Optional[Client],
    dry_run: bool,
    sleep_seconds: float,
) -> OwnershipBackfillItem:
    record_id = str(record.id)
    organization_id = str(record.organization_id)
    outcome: OwnershipOutcome | None = None
    acquired_or_merged = False
    with_parent = False
    try:
        domain = signup_domain_for_organization(record.organization)
        if domain is None:
            return OwnershipBackfillItem(record_id=record_id, organization_id=organization_id, outcome="no_domain")

        try:
            lookup = asyncio.run(provider.enrich_by_domain(domain))
        except Exception as e:
            capture_exception(e, {"organization_id": organization_id, "domain": domain})
            return OwnershipBackfillItem(record_id=record_id, organization_id=organization_id, outcome="fetch_failure")
        finally:
            time.sleep(sleep_seconds)

        # Every successful fetch is archived verbatim, including a not-found, same as the live
        # path (core.py) — the refreshed payload now carries ownershipStatus/relatedCompanies for
        # the labels pipeline and any future offline re-analysis to read.
        if not dry_run:
            base_payload = lookup.raw_payload if lookup.raw_payload is not None else _MISS_PAYLOAD
            archive_provider_fetch(
                organization_id=organization_id,
                provider=provider.name,
                payload={**base_payload, "enrichmentUrn": lookup.enrichment_urn},
                is_recheck=True,
            )

        if lookup.fields is None:
            return OwnershipBackfillItem(record_id=record_id, organization_id=organization_id, outcome="not_found")

        ownership_status = lookup.fields.ownership_status
        if ownership_status is None:
            return OwnershipBackfillItem(
                record_id=record_id, organization_id=organization_id, outcome="found_no_ownership_status"
            )

        outcome = "classified"
        if ownership_status == _ACQUIRED_OR_MERGED:
            acquired_or_merged = True
            with_parent = bool(lookup.fields.parent_company)

        if not dry_run and pha_client is not None:
            # Scoped to just the three ownership keys: to_dict()/to_group_properties() only emit
            # set fields, so leaving every other EnrichmentFields attribute unset keeps this write
            # from touching icp_* or any other field a fresh fetch would otherwise churn.
            write_organization_enrichment(
                organization_id=organization_id,
                fields=EnrichmentFields(
                    ownership_status=ownership_status,
                    parent_company=lookup.fields.parent_company,
                    parent_company_domain=lookup.fields.parent_company_domain,
                ),
                pha_client=pha_client,
            )
    except Exception as e:
        capture_exception(e, {"organization_id": organization_id})
        return OwnershipBackfillItem(
            record_id=record_id,
            organization_id=organization_id,
            outcome=outcome,
            acquired_or_merged=acquired_or_merged,
            with_parent=with_parent,
            errored=True,
        )
    return OwnershipBackfillItem(
        record_id=record_id,
        organization_id=organization_id,
        outcome=outcome,
        acquired_or_merged=acquired_or_merged,
        with_parent=with_parent,
    )
