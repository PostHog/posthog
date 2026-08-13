"""Orchestration-agnostic enrichment core.

Wraps a provider lookup and the live-store write into one coroutine that any
orchestrator can await — the real-time Temporal workflow (fire-and-forget from
signup) today, a batch Dagster asset later. No orchestration concerns leak in here.
"""

import dataclasses
from typing import Optional

from django.conf import settings

from asgiref.sync import sync_to_async
from posthoganalytics.client import Client

from posthog.exceptions_capture import capture_exception
from posthog.models.person.util import get_person_by_distinct_id

from products.growth.backend.enrichment.bridge import ClayBridgeInputs, read_clay_bridge_inputs
from products.growth.backend.enrichment.clearbit import ClearbitInputs, clearbit_inputs_from_person_properties
from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.providers import EnrichmentProvider
from products.growth.backend.enrichment.score import IcpScoreInputs, compute_icp_score
from products.growth.backend.enrichment.writer import archive_provider_fetch, write_organization_enrichment
from products.growth.backend.models import OrganizationEnrichment

# Placeholder archived for a not-found when the provider hands back no response body — records
# the miss as a distinct observation, since absence at fetch time is evidence too.
_MISS_PAYLOAD = {"companyFound": False}


def _persisted_score_exists(organization_id: str) -> bool:
    record = OrganizationEnrichment.objects.filter(organization_id=organization_id).only("data").first()
    return bool(record and record.data.get("icp_score") is not None)


def _reconstruct_fields_from_record(organization_id: str) -> Optional[EnrichmentFields]:
    """Rebuild EnrichmentFields from the last-written record when a provider lookup misses.

    Registry keys are exactly the dataclass field names (see fields.py), so a prior write can be
    replayed back into the same shape. Returns None when there is no prior record, or it carries
    no provider-derived fields — same as a fresh miss. work_email is excluded: it is first-party
    data recorded for every signup, so it neither proves a prior provider match nor belongs in
    the group projection this replay feeds.
    """
    record = OrganizationEnrichment.objects.filter(organization_id=organization_id).first()
    if record is None:
        return None
    fields = EnrichmentFields(
        **{f.name: record.data.get(f.name) for f in dataclasses.fields(EnrichmentFields) if f.name != "work_email"}
    )
    return fields if fields.to_dict() else None


def _fetch_recheck_person_inputs(distinct_id: str) -> tuple[bool, ClearbitInputs]:
    """Fetch the signer's person once for the two recheck-only reads: mirror eligibility and Clearbit's fallback inputs.

    Clay's own writes never stamp icp_score_version; ours always do, so an unversioned icp_score
    on the person is Clay's — never clobber it with a possibly-lower mirror. A lookup failure or
    a malformed person record (unreadable properties) degrades both reads (no mirror, no
    Clearbit fallback) rather than raising out of the scoring path, preferring a missed mirror
    over a possible clobber.
    """
    try:
        person = get_person_by_distinct_id(team_id=settings.GROWTH_ENRICHMENT_INTERNAL_TEAM_ID, distinct_id=distinct_id)
        if person is None:
            return True, ClearbitInputs()

        properties = person.properties or {}
        clay_owned = properties.get("icp_score") is not None and properties.get("icp_score_version") is None
    except Exception as e:
        capture_exception(e)
        return False, ClearbitInputs()

    return not clay_owned, clearbit_inputs_from_person_properties(properties)


def _company_type_from_ownership(ownership_status: Optional[str]) -> Optional[str]:
    """Map Harmonic's ownershipStatus onto the private/public vocabulary the formula matches on.

    Only PRIVATE carries ownership information the formula can score. ACQUIRED_OR_MERGED,
    ACTIVE and OUT_OF_BUSINESS describe a company's state rather than who owns it, so they
    score nothing instead of being folded into either side.
    """
    return "private" if ownership_status == "PRIVATE" else None


def _score_and_mirror(
    *,
    organization_id: str,
    fields: EnrichmentFields,
    role: Optional[str],
    is_recheck: bool,
    distinct_id: Optional[str],
) -> tuple[Optional[int], Optional[str]]:
    """Score one org; on the recheck, also mirror the score onto the signer's person profile.

    Clay's bridge columns are read as an optional input on every attempt — used when present,
    never waited for. Clay's own write lands after ours far more often than not, so most orgs
    score on our fields alone at signup; the +4h recheck re-reads the bridge and can upgrade the
    score if Clay's columns landed since. The recheck adds one person lookup that serves two
    things: the mirror-ownership check and the Clearbit fallback for est_revenue (Clay wins when
    both exist). company_type comes from Harmonic's own ownershipStatus, fetched server-side in
    the same lookup as the other firmographics.

    Wrapped so a bridge-read or score failure degrades to no score rather than taking down the
    firmographic write below — see enrich_organization's docstring.
    """
    try:
        clay = read_clay_bridge_inputs(organization_id=organization_id)
    except Exception as e:
        # A failed bridge READ is not absent bridge data: the bridge is optional input, so a
        # read failure (unresolvable internal team, transient store error) degrades to scoring
        # without it rather than costing the score entirely. Degraded-mode scores only fill a
        # gap, though — a persisted score may have been computed WITH bridge data, and a
        # bridge-less recompute would silently downgrade it.
        capture_exception(e)
        if _persisted_score_exists(organization_id):
            return None, None
        clay = ClayBridgeInputs()

    mirror_ok = False
    clearbit = ClearbitInputs()
    if is_recheck and distinct_id:
        mirror_ok, clearbit = _fetch_recheck_person_inputs(distinct_id)

    icp_score = compute_icp_score(
        IcpScoreInputs(
            employees=fields.headcount,
            # A Clay-written 0 is not information the formula can use either (_in_band is false
            # at 0 same as at None), so it must not shadow a real Clearbit band.
            est_revenue=clay.est_revenue or clearbit.est_revenue,
            role=role,
            # Clay never projects its GitHub column into PostHog, so this input is always
            # absent here — product-role orgs score 3, not 6, until v-next substitutes the
            # signup's own GitHub auth. Kept on IcpScoreInputs for formula fidelity.
            github_profile_url=None,
            company_type=_company_type_from_ownership(fields.ownership_status),
            founded_year=fields.founded_year,
            country=fields.country,
        )
    )

    mirror_distinct_id = distinct_id if mirror_ok else None

    return icp_score, mirror_distinct_id


async def enrich_organization(
    *,
    organization_id: str,
    domain: str,
    provider: EnrichmentProvider,
    pha_client: Client,
    is_recheck: bool = False,
    role_at_organization: Optional[str] = None,
    geoip_country_code: Optional[str] = None,
    distinct_id: Optional[str] = None,
) -> Optional[EnrichmentFields]:
    """Look up enrichment for a domain, archive the raw response, and persist the live stores.

    Every fetch is archived verbatim — including a not-found — before the live-store write.
    Returns the enrichment fields, or None when the provider has no match. The Postgres writes
    run via sync_to_async to bridge the async provider.

    A matched org is also ICP-scored, from these fields plus the signer's role and Clay's bridge
    columns when present — see `_score_and_mirror` for the scoring and person-mirror policy. A
    bridge-read or score failure degrades to writing firmographics with no score, rather than a
    silently-too-low one; the delayed recheck gets a second chance, and the fetch archive
    backstops a later batch recompute.

    On a miss, a prior `OrganizationEnrichment` record (if any) is reconstructed into fields and
    scored anyway — first attempt or recheck alike — so an org can't end up permanently
    score-less because of one flaky lookup. The return value keeps tracking the provider lookup
    itself (None on a miss, even when the fallback wrote a score), since that is what the
    workflow's matched/upgraded reporting reads.
    """
    lookup = await provider.enrich_by_domain(domain)

    await sync_to_async(archive_provider_fetch)(
        organization_id=organization_id,
        provider=provider.name,
        payload=lookup.raw_payload if lookup.raw_payload is not None else _MISS_PAYLOAD,
        is_recheck=is_recheck,
    )

    fields = lookup.fields
    if fields is None:
        fields = await sync_to_async(_reconstruct_fields_from_record)(organization_id)
        if fields is None:
            return None

    if fields.country is None and geoip_country_code:
        # The incumbent icp_country was a merge — provider country first, signup GeoIP as
        # fallback — so the score and all three stores see the merged value here. replace()
        # keeps the returned lookup.fields provider-verbatim for the at-signup snapshot.
        fields = dataclasses.replace(fields, country=geoip_country_code)

    icp_score, mirror_distinct_id = await sync_to_async(_score_and_mirror)(
        organization_id=organization_id,
        fields=fields,
        role=role_at_organization,
        is_recheck=is_recheck,
        distinct_id=distinct_id,
    )

    await sync_to_async(write_organization_enrichment)(
        organization_id=organization_id,
        fields=fields,
        pha_client=pha_client,
        icp_score=icp_score,
        mirror_distinct_id=mirror_distinct_id,
    )
    return lookup.fields
