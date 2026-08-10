"""Enrichment provider interface and the Harmonic implementation.

The interface keeps the enrichment core provider-agnostic; Harmonic is the first provider.
AsyncHarmonicClient also backs ee's Salesforce enrichment dag, which imports it via the growth
facade rather than growth importing it from ee.
"""

import abc
import dataclasses
from typing import Any, Optional

from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.harmonic import AsyncHarmonicClient
from products.growth.backend.enrichment.transform import transform_harmonic_company


@dataclasses.dataclass
class ProviderLookup:
    """One provider lookup: the transformed fields plus the raw response kept for the archive.

    `fields` is None on a not-found. `raw_payload` is the provider's verbatim response for the
    company, or None when the provider returns nothing at all for a miss.
    """

    fields: Optional[EnrichmentFields]
    raw_payload: Optional[dict[str, Any]]


class EnrichmentProvider(abc.ABC):
    """Looks up firmographic enrichment for a single company by domain."""

    name: str

    @abc.abstractmethod
    async def enrich_by_domain(self, domain: str) -> ProviderLookup:
        """Return the fields and raw payload for a domain; fields is None when not found.

        Raises on operational failure (network, provider outage) so the caller can retry
        and alert, rather than conflating an outage with a genuine not-found.
        """


class HarmonicEnrichmentProvider(EnrichmentProvider):
    name = "harmonic"

    async def enrich_by_domain(self, domain: str) -> ProviderLookup:
        async with AsyncHarmonicClient() as client:
            company = await client.enrich_company_by_domain_strict(domain)
        return ProviderLookup(fields=transform_harmonic_company(company), raw_payload=company)
