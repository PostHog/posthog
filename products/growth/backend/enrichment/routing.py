"""Company-type resolution for onboarding routing.

The deterministic classifier runs synchronously at signup and is always present, but it
returns `unknown` for domains it can't place. Enrichment (Harmonic, async) fills in a
company type shortly after — often after onboarding's first read — so it's a best-effort
fallback, not a guarantee. This resolver encodes the precedence and degrades to a safe
`unknown` default when neither signal is set.
"""

from products.growth.backend.enrichment.classifier import CompanyType

DETERMINISTIC_KEY = "company_type_deterministic"
ENRICHED_KEY = "company_type"


def resolve_company_type(enrichment_data: dict) -> str:
    """Return the company type to route on: the deterministic value unless it's unknown or
    missing, then the enrichment record's value, then `unknown`."""
    deterministic = enrichment_data.get(DETERMINISTIC_KEY)
    if deterministic and deterministic != CompanyType.UNKNOWN.value:
        return deterministic

    enriched = enrichment_data.get(ENRICHED_KEY)
    if enriched:
        return enriched

    return CompanyType.UNKNOWN.value
