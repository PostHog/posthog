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

from products.growth.backend.enrichment.bridge import read_clay_bridge_inputs
from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.providers import EnrichmentProvider
from products.growth.backend.enrichment.score import IcpScoreInputs, compute_icp_score
from products.growth.backend.enrichment.writer import archive_provider_fetch, write_organization_enrichment
from products.growth.backend.models import OrganizationEnrichment

# Placeholder archived for a not-found when the provider hands back no response body — records
# the miss as a distinct observation, since absence at fetch time is evidence too.
_MISS_PAYLOAD = {"companyFound": False}


def _reconstruct_fields_from_record(organization_id: str) -> Optional[EnrichmentFields]:
    """Rebuild EnrichmentFields from the last-written record for a recheck whose provider lookup missed.

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


def _person_score_is_ours_to_write(distinct_id: str) -> bool:
    """False when the signer's person profile already carries a Clay-written score.

    Clay's own writes never stamp icp_score_version; ours always do, so an unversioned icp_score
    on the person is Clay's — never clobber it with a possibly-lower mirror. A person lookup
    failure also says no, preferring a missed mirror over a possible clobber.
    """
    try:
        person = get_person_by_distinct_id(team_id=settings.GROWTH_ENRICHMENT_INTERNAL_TEAM_ID, distinct_id=distinct_id)
    except Exception as e:
        capture_exception(e)
        return False

    if person is None:
        return True

    properties = person.properties or {}
    clay_owned = properties.get("icp_score") is not None and properties.get("icp_score_version") is None
    return not clay_owned


def _score_and_mirror(
    *,
    organization_id: str,
    fields: EnrichmentFields,
    role: Optional[str],
    is_recheck: bool,
    distinct_id: Optional[str],
) -> tuple[Optional[int], Optional[str]]:
    """Score one org and decide whether to mirror the score onto the signer's person profile.

    A first attempt only scores once Clay's own bridge columns have landed (`clay_processed`) —
    Clay's write lands after ours far more often than not, so scoring earlier would frequently
    undercount. The recheck, four hours later, scores unconditionally: by then Clay's inputs have
    either landed or never will, so scoring on whatever the bridge holds is no worse than what
    Clay would have provided. The person mirror is recheck-only for the same reason, and skipped
    entirely when the person already carries a Clay-written score.

    Wrapped so a bridge-read or score failure degrades to no score rather than taking down the
    firmographic write below — see enrich_organization's docstring.
    """
    try:
        clay = read_clay_bridge_inputs(organization_id=organization_id)
    except Exception as e:
        capture_exception(e)
        return None, None

    if not is_recheck and not clay.clay_processed:
        return None, None

    icp_score = compute_icp_score(
        IcpScoreInputs(
            employees=fields.headcount,
            est_revenue=clay.est_revenue,
            role=role,
            # Clay never projects its GitHub column into PostHog, so this input is always
            # absent here — product-role orgs score 3, not 6, until v-next substitutes the
            # signup's own GitHub auth. Kept on IcpScoreInputs for formula fidelity.
            github_profile_url=None,
            # Clay's own vocabulary ("private"/"public"), which our Harmonic `company_type`
            # (raw enum, e.g. "STARTUP") does not share — so this stays a bridge read for now.
            company_type=clay.company_type,
            founded_year=fields.founded_year,
            country=fields.country,
        )
    )

    mirror_distinct_id = None
    if is_recheck and distinct_id and _person_score_is_ours_to_write(distinct_id):
        mirror_distinct_id = distinct_id

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

    A matched org is also ICP-scored, from these fields plus the signer's role and Clay's
    remaining columns — see `_score_and_mirror` for the first-attempt-vs-recheck scoring and
    person-mirror policy. A bridge-read or score failure degrades to writing firmographics with
    no score, rather than a silently-too-low one; the delayed recheck gets a second chance, and
    the fetch archive backstops a later batch recompute.

    On a recheck whose provider lookup misses, a prior `OrganizationEnrichment` record (if any)
    is reconstructed into fields and scored anyway — so an org matched at first attempt can't end
    up permanently score-less because of one flaky recheck lookup. The return value keeps
    tracking the provider lookup itself (None on a miss, even when the fallback wrote a score),
    since that is what the workflow's matched/upgraded reporting reads.
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
        if not is_recheck:
            return None
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
