"""Transform a Harmonic company response into the enrichment field registry.

Tag/YC/safe-cast heuristics are shared with the Salesforce enrichment transforms in
ee/billing/salesforce_enrichment/enrichment.py and imported from there rather than copied.
"""

from typing import Any, Optional

from products.growth.backend.enrichment.countries import country_name_to_iso_code
from products.growth.backend.enrichment.fields import EnrichmentFields

from ee.billing.salesforce_enrichment.enrichment import _extract_primary_tag, _is_yc_funded, _safe_dict, _safe_list


def _latest_metric(traction: dict[str, Any], metric: str) -> Optional[int]:
    value = _safe_dict(traction.get(metric)).get("latestMetricValue")
    return int(value) if isinstance(value, (int, float)) else None


def _founded_year(founding: dict[str, Any]) -> Optional[int]:
    date = founding.get("date")
    if isinstance(date, str) and "-" in date:
        year = date.split("-", 1)[0]
        if year.isdigit():
            return int(year)
    return None


def transform_harmonic_company(company: Optional[dict[str, Any]]) -> Optional[EnrichmentFields]:
    """Map a Harmonic `enrichCompanyByIdentifiers.company` payload to EnrichmentFields.

    Returns None when the payload is missing or not a dict.
    """
    if not company or not isinstance(company, dict):
        return None

    funding = _safe_dict(company.get("funding"))
    traction = _safe_dict(company.get("tractionMetrics"))
    location = _safe_dict(company.get("location"))
    founding = _safe_dict(company.get("foundingDate"))

    headcount = _latest_metric(traction, "headcount")
    if headcount is None and isinstance(company.get("headcount"), (int, float)):
        headcount = int(company["headcount"])

    return EnrichmentFields(
        company_type=company.get("companyType"),
        headcount=headcount,
        headcount_engineering=_latest_metric(traction, "headcountEngineering"),
        industry=_extract_primary_tag(_safe_list(company.get("tags")), _safe_list(company.get("tagsV2"))),
        # ISO alpha-2 to match the format the icp_country group property already holds.
        country=country_name_to_iso_code(location.get("country")),
        founded_year=_founded_year(founding),
        funding_stage=funding.get("fundingStage"),
        is_yc_company=_is_yc_funded(funding.get("investors")),
    )
