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
from products.growth.backend.enrichment.writer import write_organization_enrichment


async def enrich_organization(
    *,
    organization_id: str,
    domain: str,
    provider: EnrichmentProvider,
    pha_client: Client,
) -> Optional[EnrichmentFields]:
    """Look up enrichment for a domain and persist it to the live stores.

    Returns the enrichment fields, or None when the provider has no match (nothing
    written). The Postgres write runs via sync_to_async to bridge the async provider.
    """
    fields = await provider.enrich_by_domain(domain)
    if fields is None:
        return None

    await sync_to_async(write_organization_enrichment)(
        organization_id=organization_id,
        fields=fields,
        pha_client=pha_client,
    )
    return fields
