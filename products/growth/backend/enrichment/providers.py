"""Enrichment provider interface and the Harmonic implementation.

The interface keeps the enrichment core provider-agnostic; Harmonic is the first
provider. AsyncHarmonicClient (ee/billing/salesforce_enrichment) is reused as-is —
tach already allows products.growth to import ee.
"""

import abc
import dataclasses
from typing import Any, Optional

from posthog.exceptions_capture import capture_exception

from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.transform import transform_harmonic_company

from ee.billing.salesforce_enrichment.harmonic_client import AsyncHarmonicClient


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


def _parent_company_urn(company: dict[str, Any]) -> Optional[str]:
    """Pick the parent-company URN from `relatedCompanies`: subsidiaryOf wins over acquiredBy.

    Both links are beta and sparse (often present with a null companyUrn even when
    ownershipStatus says the company was acquired), so absence here is normal.
    """
    related = company.get("relatedCompanies")
    if not isinstance(related, dict):
        return None
    for key in ("subsidiaryOf", "acquiredBy"):
        link = related.get(key)
        if isinstance(link, dict) and isinstance(urn := link.get("companyUrn"), str) and urn:
            return urn
    return None


class HarmonicEnrichmentProvider(EnrichmentProvider):
    name = "harmonic"

    async def enrich_by_domain(self, domain: str) -> ProviderLookup:
        async with AsyncHarmonicClient() as client:
            company = await client.enrich_company_by_domain_strict(domain)
            fields = transform_harmonic_company(company)
            if fields is not None and company is not None:
                fields = await self._with_parent_company(client, company, fields)
        return ProviderLookup(fields=fields, raw_payload=company)

    async def _with_parent_company(
        self, client: AsyncHarmonicClient, company: dict[str, Any], fields: EnrichmentFields
    ) -> EnrichmentFields:
        """Best-effort parent-company resolution: never fails the lookup, just leaves the fields unset."""
        urn = _parent_company_urn(company)
        if urn is None:
            return fields

        try:
            parent = await client.get_company_by_urn(urn)
        except Exception as e:
            capture_exception(e)
            return fields

        if not isinstance(parent, dict):
            return fields

        website = parent.get("website")
        domain = website.get("domain") if isinstance(website, dict) else None
        return dataclasses.replace(fields, parent_company=parent.get("name"), parent_company_domain=domain)
