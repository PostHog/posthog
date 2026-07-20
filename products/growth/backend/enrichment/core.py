"""Orchestration-agnostic enrichment core.

Wraps a provider lookup and the live-store write into one coroutine that any
orchestrator can await — the real-time Temporal workflow (fire-and-forget from
signup) today, a batch Dagster asset later. No orchestration concerns leak in here.
"""

from typing import Optional

from asgiref.sync import sync_to_async
from posthoganalytics.client import Client

from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.providers import EnrichmentProvider
from products.growth.backend.enrichment.writer import archive_provider_fetch, write_organization_enrichment

# Placeholder archived for a not-found when the provider hands back no response body — records
# the miss as a distinct observation, since absence at fetch time is evidence too.
_MISS_PAYLOAD = {"companyFound": False}


async def enrich_organization(
    *,
    organization_id: str,
    domain: str,
    provider: EnrichmentProvider,
    pha_client: Client,
    is_recheck: bool = False,
) -> Optional[EnrichmentFields]:
    """Look up enrichment for a domain, archive the raw response, and persist the live stores.

    Every fetch is archived verbatim — including a not-found — before the live-store write.
    Returns the enrichment fields, or None when the provider has no match (nothing written to
    the live stores). The Postgres writes run via sync_to_async to bridge the async provider.
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

    await sync_to_async(write_organization_enrichment)(
        organization_id=organization_id,
        fields=lookup.fields,
        pha_client=pha_client,
    )
    return lookup.fields
