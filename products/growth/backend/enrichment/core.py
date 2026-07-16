"""Orchestration-agnostic enrichment core.

Wraps a provider lookup and the live-store write into one coroutine that any
orchestrator can await — the real-time Temporal workflow (fire-and-forget from
signup) today, a batch Dagster asset later. No orchestration concerns leak in here.
"""

from typing import Optional

from asgiref.sync import sync_to_async
from posthoganalytics.client import Client

from products.growth.backend.enrichment.bridge import read_clay_bridge_inputs
from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.providers import EnrichmentProvider
from products.growth.backend.enrichment.score import IcpScoreInputs, compute_icp_score
from products.growth.backend.enrichment.writer import archive_provider_fetch, write_organization_enrichment

# Placeholder archived for a not-found when the provider hands back no response body — records
# the miss as a distinct observation, since absence at fetch time is evidence too.
_MISS_PAYLOAD = {"companyFound": False}


def _icp_score(*, organization_id: str, fields: EnrichmentFields, role: Optional[str]) -> int:
    """Assemble the score inputs from our fields, the signup's role, and Clay's remaining columns."""
    clay = read_clay_bridge_inputs(organization_id=organization_id)
    return compute_icp_score(
        IcpScoreInputs(
            employees=fields.headcount,
            est_revenue=clay.est_revenue,
            role=role,
            github_profile_url=clay.github_profile_url,
            # Clay's own vocabulary ("private"/"public"), which our Harmonic `company_type`
            # (raw enum, e.g. "STARTUP") does not share — so this stays a bridge read for now.
            company_type=clay.company_type,
            founded_year=fields.founded_year,
            country=fields.country,
        )
    )


async def enrich_organization(
    *,
    organization_id: str,
    domain: str,
    provider: EnrichmentProvider,
    pha_client: Client,
    is_recheck: bool = False,
    role_at_organization: Optional[str] = None,
) -> Optional[EnrichmentFields]:
    """Look up enrichment for a domain, archive the raw response, and persist the live stores.

    Every fetch is archived verbatim — including a not-found — before the live-store write.
    Returns the enrichment fields, or None when the provider has no match (nothing written to
    the live stores). The Postgres writes run via sync_to_async to bridge the async provider.

    A matched org is also ICP-scored, from these fields plus the signer's role and Clay's
    remaining columns. The score write is deliberately not defended against a bridge-read
    failure: a score computed on inputs we failed to fetch would be silently too low.
    """
    lookup = await provider.enrich_by_domain(domain)

    await sync_to_async(archive_provider_fetch)(
        organization_id=organization_id,
        provider=provider.name,
        payload=lookup.raw_payload if lookup.raw_payload is not None else _MISS_PAYLOAD,
        is_recheck=is_recheck,
    )

    if lookup.fields is None:
        return None

    icp_score = await sync_to_async(_icp_score)(
        organization_id=organization_id,
        fields=lookup.fields,
        role=role_at_organization,
    )

    await sync_to_async(write_organization_enrichment)(
        organization_id=organization_id,
        fields=lookup.fields,
        pha_client=pha_client,
        icp_score=icp_score,
    )
    return lookup.fields
