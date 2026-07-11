"""Enrichment provider interface and the Harmonic implementation.

The interface keeps the enrichment core provider-agnostic; Harmonic is the first
provider. AsyncHarmonicClient (ee/billing/salesforce_enrichment) is reused as-is —
tach already allows products.growth to import ee.
"""

import abc
from typing import Optional

from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.transform import transform_harmonic_company

from ee.billing.salesforce_enrichment.harmonic_client import AsyncHarmonicClient


class EnrichmentProvider(abc.ABC):
    """Looks up firmographic enrichment for a single company by domain."""

    @abc.abstractmethod
    async def enrich_by_domain(self, domain: str) -> Optional[EnrichmentFields]:
        """Return enrichment for a domain, or None when the company is not found.

        Raises on operational failure (network, provider outage) so the caller can retry
        and alert, rather than conflating an outage with a genuine not-found.
        """


class HarmonicEnrichmentProvider(EnrichmentProvider):
    async def enrich_by_domain(self, domain: str) -> Optional[EnrichmentFields]:
        async with AsyncHarmonicClient() as client:
            company = await client.enrich_company_by_domain_strict(domain)
        return transform_harmonic_company(company)
