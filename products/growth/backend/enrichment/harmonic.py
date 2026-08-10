"""Harmonic API client, GraphQL query, and generic payload helpers.

Shared by growth's real-time signup-enrichment provider (products/growth/backend/enrichment)
and ee's Salesforce enrichment dag (ee/billing/salesforce_enrichment), which imports these via
products.growth.backend.facade.enrichment.
"""

import typing
import asyncio
from typing import Any, Optional

from django.conf import settings

import aiohttp

from posthog.exceptions_capture import capture_exception

HARMONIC_BASE_URL: str = "https://api.harmonic.ai"
YC_INVESTOR_NAME: str = "y combinator"
HARMONIC_DEFAULT_MAX_CONCURRENT_REQUESTS: int = 5  # rate limit: 10/s
HARMONIC_REQUEST_TIMEOUT_SECONDS: int = 30
HARMONIC_BATCH_SIZE: int = 100
HARMONIC_DOMAIN_VARIATIONS: list[str] = ["", "www."]  # Try exact domain first, then with www prefix

# Harmonic GraphQL query for company enrichment
HARMONIC_COMPANY_ENRICHMENT_QUERY = """
mutation($identifiers: CompanyEnrichmentIdentifiersInput!) {
    enrichCompanyByIdentifiers(identifiers: $identifiers) {
        companyFound
        company {
            name
            companyType
            website {
                url
                domain
            }
            headcount
            description
            location {
                city
                country
                state
            }
            foundingDate {
                date
                granularity
            }
            funding {
                fundingTotal
                numFundingRounds
                lastFundingAt
                lastFundingType
                lastFundingTotal
                fundingStage
                investors {
                    ... on Company {
                        name
                    }
                    ... on Person {
                        fullName
                    }
                }
            }
            tractionMetrics {
                webTraffic {
                    latestMetricValue
                    metrics {
                        timestamp
                        metricValue
                    }
                }
                linkedinFollowerCount {
                    latestMetricValue
                    metrics {
                        timestamp
                        metricValue
                    }
                }
                twitterFollowerCount {
                    latestMetricValue
                    metrics {
                        timestamp
                        metricValue
                    }
                }
                headcount {
                    latestMetricValue
                    metrics {
                        timestamp
                        metricValue
                    }
                }
                headcountEngineering {
                    latestMetricValue
                    metrics {
                        timestamp
                        metricValue
                    }
                }
            }
            tags {
                type
                displayValue
                dateAdded
                isPrimaryTag
            }
            tagsV2 {
                type
                displayValue
                dateAdded
            }
        }
    }
}
"""


class AsyncHarmonicClient:
    """Async Harmonic API client with controlled concurrency.

    Enriches company domains using Harmonic's GraphQL API with:
    - 5 concurrent requests (configurable)
    - 30s timeout per request
    - Domain variation fallbacks (www., non-www)
    - Automatic session management via context manager

    Usage:
        async with AsyncHarmonicClient() as client:
            data = await client.enrich_company_by_domain("posthog.com")
    """

    def __init__(self) -> None:
        self.api_key = settings.HARMONIC_API_KEY
        if not self.api_key:
            raise ValueError("Missing Harmonic API key: HARMONIC_API_KEY")

        self.session: Optional[aiohttp.ClientSession] = None
        self._session_cm: Any = None

    async def __aenter__(self) -> typing.Self:
        """Async context manager entry - create session."""
        timeout = aiohttp.ClientTimeout(total=HARMONIC_REQUEST_TIMEOUT_SECONDS)
        self._session_cm = aiohttp.ClientSession(trust_env=True, timeout=timeout)
        self.session = await self._session_cm.__aenter__()
        return self

    async def __aexit__(self, *args) -> None:
        """Async context manager exit - close session."""
        if self._session_cm:
            await self._session_cm.__aexit__(*args)

    def _clean_domain(self, domain: str) -> str:
        """Clean domain name by removing protocols and www prefix."""
        return domain.lower().strip().removeprefix("https://").removeprefix("http://").removeprefix("www.")

    async def enrich_company_by_domain(self, domain: str) -> Optional[dict[str, Any]]:
        """Get company data from Harmonic API for a domain.

        Tries domain variations: example.com → www.example.com if first fails.

        Args:
            domain: Company domain (e.g., "posthog.com")

        Returns:
            Company data dict or None if not found
        """
        # Rate limiting: 5 requests per second
        await asyncio.sleep(0.2)
        domain = self._clean_domain(domain)

        # Try domain variations
        domain_variations = [f"{prefix}{domain}" if prefix else domain for prefix in HARMONIC_DOMAIN_VARIATIONS]

        for domain_variation in domain_variations:
            try:
                variables = {"identifiers": {"websiteUrl": f"https://{domain_variation}"}}

                if self.session is None:
                    raise RuntimeError("HTTP session not initialized. Use async context manager.")
                async with self.session.post(
                    f"{HARMONIC_BASE_URL}/graphql",
                    params={"apikey": self.api_key},
                    json={"query": HARMONIC_COMPANY_ENRICHMENT_QUERY, "variables": variables},
                    headers={"Content-Type": "application/json"},
                ) as response:
                    response.raise_for_status()
                    data = await response.json()

                    if "errors" in data:
                        continue

                    result = data.get("data", {}).get("enrichCompanyByIdentifiers", {})
                    if result.get("companyFound"):
                        company_data = result.get("company")
                        return company_data

            except Exception as e:
                capture_exception(e)
                continue

        return None

    async def enrich_company_by_domain_strict(self, domain: str) -> Optional[dict[str, Any]]:
        """Like enrich_company_by_domain, but distinguishes not-found from operational failure.

        Returns None only for a genuine not-found (every domain variation returned a clean
        GraphQL response with companyFound false). Operational failures (network errors, non-2xx
        status, JSON decode, GraphQL errors) are re-raised so callers can retry and alert instead
        of mistaking an outage for a missing company. Does not capture_exception — the caller owns
        error handling.
        """
        await asyncio.sleep(0.2)
        domain = self._clean_domain(domain)
        domain_variations = [f"{prefix}{domain}" if prefix else domain for prefix in HARMONIC_DOMAIN_VARIATIONS]

        last_error: Optional[Exception] = None
        for domain_variation in domain_variations:
            try:
                variables = {"identifiers": {"websiteUrl": f"https://{domain_variation}"}}

                if self.session is None:
                    raise RuntimeError("HTTP session not initialized. Use async context manager.")
                async with self.session.post(
                    f"{HARMONIC_BASE_URL}/graphql",
                    params={"apikey": self.api_key},
                    json={"query": HARMONIC_COMPANY_ENRICHMENT_QUERY, "variables": variables},
                    headers={"Content-Type": "application/json"},
                ) as response:
                    response.raise_for_status()
                    data = await response.json()

                    if "errors" in data:
                        raise RuntimeError(f"Harmonic GraphQL errors for {domain_variation}: {data['errors']}")

                    result = data.get("data", {}).get("enrichCompanyByIdentifiers", {})
                    if result.get("companyFound"):
                        return result.get("company")
            except Exception as e:
                last_error = e
                continue

        if last_error is not None:
            raise last_error
        return None

    async def enrich_companies_batch(self, domains: list[str]) -> list[dict[str, Any] | None]:
        """Enrich multiple domains concurrently.

        Args:
            domains: List of company domains to enrich

        Returns:
            List of company data dicts (None for failed enrichments)
        """
        if not domains:
            return []

        tasks = [self.enrich_company_by_domain(domain) for domain in domains]

        results: list[dict[str, Any] | BaseException | None] = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, BaseException):
                capture_exception(result)

        return [None if isinstance(result, BaseException) else result for result in results]


def _is_yc_funded(investors: list | None) -> bool:
    """Check if Y Combinator is among the company's investors.

    Args:
        investors: List of investor dicts with 'name' (Company) or 'fullName' (Person)

    Returns:
        True if Y Combinator is found in company investors (not person names)
    """
    if not investors:
        return False

    for investor in investors:
        if isinstance(investor, dict):
            # Only check company names, not person fullNames
            name = investor.get("name", "")
            if name and YC_INVESTOR_NAME in name.lower():
                return True
    return False


def _safe_dict(value: Any) -> dict[str, Any]:
    """Return value if it's a dict, otherwise return an empty dict."""
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    """Return value if it's a list, otherwise return an empty list."""
    return value if isinstance(value, list) else []


def _extract_first_tag(tag_list: list, type_filter: str | None = None) -> str | None:
    """Extract first tag with non-empty displayValue, optionally filtered by type."""
    for tag in tag_list:
        if isinstance(tag, dict) and (not type_filter or tag.get("type") == type_filter):
            if value := tag.get("displayValue"):
                return value
    return None


def _extract_primary_tag(tags: list, tags_v2: list) -> str | None:
    """Extract the primary tag from tags arrays.

    Priority: isPrimaryTag=True in tags, then first valid tag in tags,
    then MARKET_VERTICAL in tagsV2, then first valid tag in tagsV2.
    """
    if tags:
        for tag in tags:
            if isinstance(tag, dict) and tag.get("isPrimaryTag") and (value := tag.get("displayValue")):
                return value
        if first_tag := _extract_first_tag(tags):
            return first_tag

    if tags_v2:
        return _extract_first_tag(tags_v2, "MARKET_VERTICAL") or _extract_first_tag(tags_v2)

    return None
