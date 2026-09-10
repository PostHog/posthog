"""Orchestration-agnostic enrichment core.

Wraps a provider lookup and the live-store write into one coroutine that any
orchestrator can await — the real-time Temporal workflow (fire-and-forget from
signup) today, a batch Dagster asset later. No orchestration concerns leak in here.

Two scores ride each enrichment: the legacy clay-parity `icp_score` (score.py), still
written because its live consumers are threshold-tuned to that scale, and the ICP fit
score (fit_score.py) on its own `icp_fit_*` keys. The clay path retires once its
consumers migrate to the fit keys.
"""

import dataclasses
from typing import Any, Optional

from django.conf import settings

from asgiref.sync import sync_to_async
from posthoganalytics.client import Client

from posthog.exceptions_capture import capture_exception
from posthog.models.person.util import get_person_by_distinct_id

from products.growth.backend.enrichment.bridge import (
    ClayBridgeInputs,
    OrganizationBridgeInputs,
    read_organization_bridge_inputs,
)
from products.growth.backend.enrichment.clearbit import ClearbitInputs, clearbit_inputs_from_person_properties
from products.growth.backend.enrichment.context import EnrichmentContext
from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.fit_score import IcpFitResult, score_company
from products.growth.backend.enrichment.harmonic_adapter import normalize_graphql_company
from products.growth.backend.enrichment.icp_lists import load_active_lists
from products.growth.backend.enrichment.providers import EnrichmentProvider, ProviderLookup
from products.growth.backend.enrichment.score import IcpScoreInputs, compute_icp_score
from products.growth.backend.enrichment.writer import archive_provider_fetch, write_organization_enrichment
from products.growth.backend.models import OrganizationEnrichment, OrganizationEnrichmentFetch

# Placeholder archived for a not-found when the provider hands back no response body — records
# the miss as a distinct observation, since absence at fetch time is evidence too.
_MISS_PAYLOAD = {"companyFound": False}

# How many archived fetches to walk back looking for the last matched payload on a miss.
_MATCHED_PAYLOAD_LOOKBACK = 10


@dataclasses.dataclass(frozen=True)
class EnrichmentOutcome:
    """What one enrichment attempt produced.

    provider_fields tracks the provider lookup itself (None on a miss, even when an
    archived-payload fallback still scored the org) — that is what the workflow's
    matched/upgraded reporting reads. fit is the ICP fit evaluation, present whenever fit
    scoring ran (its status distinguishes scored/insufficient_data/not_found/disqualified);
    None only when it degraded (no active curated-lists row, or an unexpected error).
    enrichment_status is the polled status of the org's previously archived tracking URN
    (recheck only; always None on a first attempt), so callers can report it without a
    second read of the archive.
    """

    provider_fields: Optional[EnrichmentFields] = None
    fit: Optional[IcpFitResult] = None
    enrichment_status: Optional[str] = None


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


def _stored_country(organization_id: str) -> Optional[str]:
    record = OrganizationEnrichment.objects.filter(organization_id=organization_id).only("data").first()
    return (record.data or {}).get("country") if record is not None else None


def latest_matched_payload(organization_id: str) -> Optional[dict[str, Any]]:
    """The org's most recent archived payload that was an actual match, or None.

    The fit scorer consumes the raw payload (description, per-tag types, traction series —
    all deliberately absent from EnrichmentFields), so on a provider miss the archive, not
    the field record, is the scoring fallback. Public because the score backfill uses the
    same lookback. Bounded walk: an org has a handful of fetches (signup + recheck +
    occasional backfills), and a sentinel-only history is a real never-matched org.
    """
    payloads = (
        OrganizationEnrichmentFetch.objects.filter(organization_id=organization_id)
        .order_by("-fetched_at", "-id")
        .values_list("payload", flat=True)[:_MATCHED_PAYLOAD_LOOKBACK]
    )
    for payload in payloads:
        if isinstance(payload, dict) and payload and payload.get("companyFound") is not False:
            return payload
    return None


def _latest_archived_urn(organization_id: str) -> Optional[str]:
    """The most recent enrichmentUrn Harmonic has given this org, or None.

    Skips rows whose enrichmentUrn is null or absent: a recheck that lands on an
    already-matched company archives a null urn (no pending refresh), and the latest row
    by fetch time is often exactly that. A naive "latest row" read would then shadow an
    earlier, still-open tracking urn (e.g. the original miss's) with a null one.
    """
    payload = (
        OrganizationEnrichmentFetch.objects.filter(
            organization_id=organization_id, payload__enrichmentUrn__isnull=False
        )
        .exclude(payload__enrichmentUrn=None)
        .order_by("-fetched_at", "-id")
        .values_list("payload", flat=True)
        .first()
    )
    urn = payload.get("enrichmentUrn") if isinstance(payload, dict) else None
    return urn if isinstance(urn, str) else None


async def _poll_prior_status(ctx: EnrichmentContext, provider: EnrichmentProvider) -> Optional[str]:
    """Never raises: a status-check failure must not block the recheck's own lookup below."""
    if not ctx.is_recheck:
        return None
    urn = await sync_to_async(_latest_archived_urn)(ctx.organization_id)
    if not urn:
        return None
    try:
        return await provider.enrichment_status_for(urn)
    except Exception as e:
        capture_exception(e, {"organization_id": ctx.organization_id, "enrichment_urn": urn})
        return None


async def _archive_lookup(
    ctx: EnrichmentContext, provider: EnrichmentProvider, lookup: ProviderLookup, enrichment_status: Optional[str]
) -> None:
    base_payload = lookup.raw_payload if lookup.raw_payload is not None else _MISS_PAYLOAD
    archived_payload = {**base_payload, "enrichmentUrn": lookup.enrichment_urn}
    if ctx.is_recheck:
        archived_payload["enrichmentStatus"] = enrichment_status
    await sync_to_async(archive_provider_fetch)(
        organization_id=ctx.organization_id,
        provider=provider.name,
        payload=archived_payload,
        is_recheck=ctx.is_recheck,
    )


async def _resolve_fields(ctx: EnrichmentContext, lookup: ProviderLookup) -> Optional[EnrichmentFields]:
    fields = lookup.fields
    if fields is None:
        fields = await sync_to_async(_reconstruct_fields_from_record)(ctx.organization_id)

    if fields is not None and fields.country is None:
        # A re-score with no new provider country would otherwise take the non-scored-country
        # penalty the signup score avoided. replace() keeps provider_fields verbatim for the snapshot.
        fallback_country = ctx.geoip_country_code or await sync_to_async(_stored_country)(ctx.organization_id)
        if fallback_country:
            fields = dataclasses.replace(fields, country=fallback_country)

    return fields


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
    ctx: EnrichmentContext, *, bridge_inputs: Optional[OrganizationBridgeInputs], fields: EnrichmentFields
) -> tuple[Optional[int], Optional[str]]:
    """Score one org under the legacy clay formula; on the recheck, also mirror onto the person.

    Clay's bridge columns are read as an optional input on every attempt — used when present,
    never waited for. Clay's own write lands after ours far more often than not, so most orgs
    score on our fields alone at signup; the +4h recheck re-reads the bridge and can upgrade the
    score if Clay's columns landed since. The recheck adds one person lookup that serves two
    things: the mirror-ownership check and the Clearbit fallback for est_revenue (Clay wins when
    both exist). company_type comes from Harmonic's own ownershipStatus, fetched server-side in
    the same lookup as the other firmographics.
    """
    try:
        if bridge_inputs is None:
            if _persisted_score_exists(ctx.organization_id):
                return None, None
            clay = ClayBridgeInputs()
        else:
            clay = bridge_inputs.clay

        mirror_ok = False
        clearbit = ClearbitInputs()
        if ctx.is_recheck and ctx.distinct_id:
            mirror_ok, clearbit = _fetch_recheck_person_inputs(ctx.distinct_id)

        icp_score = compute_icp_score(
            IcpScoreInputs(
                employees=fields.headcount,
                # A Clay-written 0 is not information the formula can use either (_in_band is false
                # at 0 same as at None), so it must not shadow a real Clearbit band.
                est_revenue=clay.est_revenue or clearbit.est_revenue,
                role=ctx.role_at_organization,
                # Clay never projects its GitHub column into PostHog, so this input is always
                # absent here — product-role orgs score 3, not 6, until v-next substitutes the
                # signup's own GitHub auth. Kept on IcpScoreInputs for formula fidelity.
                github_profile_url=None,
                company_type=_company_type_from_ownership(fields.ownership_status),
                founded_year=fields.founded_year,
                country=fields.country,
            )
        )

        mirror_distinct_id = ctx.distinct_id if mirror_ok else None
        return icp_score, mirror_distinct_id
    except Exception as e:
        capture_exception(e, {"organization_id": ctx.organization_id})
        return None, None


def _read_bridge_inputs(
    ctx: EnrichmentContext, fields: Optional[EnrichmentFields]
) -> Optional[OrganizationBridgeInputs]:
    """Empty means the run never asked; None means the read failed, which the scorers treat differently."""
    if fields is None and not ctx.is_recheck:
        return OrganizationBridgeInputs()
    try:
        return read_organization_bridge_inputs(organization_id=ctx.organization_id)
    except Exception as e:
        capture_exception(e, {"organization_id": ctx.organization_id})
        return None


def _persisted_wizard_ai_sdk(*, organization_id: str) -> bool:
    record = OrganizationEnrichment.objects.filter(organization_id=organization_id).only("data").first()
    flags = record.data.get("icp_fit_flags") if record else None
    return isinstance(flags, dict) and flags.get("wizard_ai_sdk") is True


def _score_fit(
    ctx: EnrichmentContext,
    *,
    bridge_inputs: Optional[OrganizationBridgeInputs],
    raw_payload: Optional[dict[str, Any]],
) -> tuple[Optional[IcpFitResult], Optional[str]]:
    """Evaluate one org under the ICP fit score.

    Scores from the raw provider payload — falling back to the org's last matched archived
    payload on a miss, so one flaky lookup can't leave an org permanently score-less. No
    active curated-lists row degrades to no evaluation at all (captured, never raised):
    scoring against empty lists would floor three components and look like a real answer.

    The wizard's AI-SDK stamp affects rechecks only because the wizard usually finishes
    after the first score.

    The fit person mirror needs no ownership guard and no person read: `icp_fit_score` is a
    brand-new person key nothing else writes, so every evaluation mirrors blindly on every
    attempt (unlike the clay mirror, which shares Clay's key and stays recheck-only behind
    the ownership check) — including a score-less one, whose status overwrites a stale
    number left by an earlier scored attempt.
    """
    try:
        wizard_ai_sdk = False
        if ctx.is_recheck:
            if bridge_inputs is None:
                if not _persisted_wizard_ai_sdk(organization_id=ctx.organization_id):
                    return None, None
                wizard_ai_sdk = True
            else:
                wizard_ai_sdk = bridge_inputs.wizard.ai_sdk_detected
        lists = load_active_lists()
        if lists is None:
            capture_exception(RuntimeError("icp_fit_no_active_lists: IcpScoringConfig has no active row"))
            return None, None

        payload = normalize_graphql_company(raw_payload)
        if payload is None:
            payload = normalize_graphql_company(latest_matched_payload(ctx.organization_id))

        result = score_company(
            payload, lists=lists, role=ctx.role_at_organization, domain=ctx.domain, wizard_ai_sdk=wizard_ai_sdk
        )
    except Exception as e:
        capture_exception(e, {"organization_id": ctx.organization_id})
        return None, None

    return result, ctx.distinct_id


async def enrich_organization(
    ctx: EnrichmentContext, *, provider: EnrichmentProvider, pha_client: Client
) -> EnrichmentOutcome:
    """Archiving precedes the live-store write, so a fetch survives a later step failing.

    Either scorer failing degrades to writing what the rest produced rather than a
    silently-wrong value. The returned provider_fields tracks the lookup itself, staying
    None on a miss even when an archived payload still scored, because that is what the
    workflow's matched and upgraded reporting reads.
    """
    enrichment_status = await _poll_prior_status(ctx, provider)

    lookup = await provider.enrich_by_domain(ctx.domain)
    await _archive_lookup(ctx, provider, lookup, enrichment_status)

    fields = await _resolve_fields(ctx, lookup)
    bridge_inputs = await sync_to_async(_read_bridge_inputs)(ctx, fields)

    icp_score: Optional[int] = None
    mirror_distinct_id: Optional[str] = None
    if fields is not None:
        icp_score, mirror_distinct_id = await sync_to_async(_score_and_mirror)(
            ctx, bridge_inputs=bridge_inputs, fields=fields
        )

    fit, fit_mirror_distinct_id = await sync_to_async(_score_fit)(
        ctx, bridge_inputs=bridge_inputs, raw_payload=lookup.raw_payload
    )

    if fields is None and fit is None:
        return EnrichmentOutcome(provider_fields=None, fit=None, enrichment_status=enrichment_status)

    await sync_to_async(write_organization_enrichment)(
        organization_id=ctx.organization_id,
        fields=fields,
        pha_client=pha_client,
        icp_score=icp_score,
        mirror_distinct_id=mirror_distinct_id,
        fit=fit,
        fit_mirror_distinct_id=fit_mirror_distinct_id,
    )
    return EnrichmentOutcome(provider_fields=lookup.fields, fit=fit, enrichment_status=enrichment_status)
