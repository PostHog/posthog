"""Transform a Harmonic company response into the enrichment field registry.

Prior art (and the source of the tag/YC/founding-date heuristics): the Salesforce
enrichment transforms in ee/billing/salesforce_enrichment/enrichment.py.
"""

from typing import Any, Optional

from products.growth.backend.enrichment.countries import country_name_to_iso_code
from products.growth.backend.enrichment.fields import EnrichmentFields

from ee.billing.salesforce_enrichment.constants import YC_INVESTOR_NAME


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_tag(tags: list[Any], type_filter: Optional[str] = None) -> Optional[str]:
    for tag in tags:
        if isinstance(tag, dict) and (not type_filter or tag.get("type") == type_filter):
            if value := tag.get("displayValue"):
                return value
    return None


def _primary_industry(tags: list[Any], tags_v2: list[Any]) -> Optional[str]:
    """Priority: isPrimaryTag in tags, then first tag, then MARKET_VERTICAL in tagsV2, then first tagsV2."""
    for tag in tags:
        if isinstance(tag, dict) and tag.get("isPrimaryTag") and (value := tag.get("displayValue")):
            return value
    if first := _first_tag(tags):
        return first
    return _first_tag(tags_v2, "MARKET_VERTICAL") or _first_tag(tags_v2)


def _is_yc_company(investors: Any) -> bool:
    for investor in _safe_list(investors):
        if isinstance(investor, dict):
            name = investor.get("name")
            if name and YC_INVESTOR_NAME in name.lower():
                return True
    return False


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
        industry=_primary_industry(_safe_list(company.get("tags")), _safe_list(company.get("tagsV2"))),
        # ISO alpha-2 to match the format the icp_country group property already holds.
        country=country_name_to_iso_code(location.get("country")),
        founded_year=_founded_year(founding),
        funding_stage=funding.get("fundingStage"),
        is_yc_company=_is_yc_company(funding.get("investors")),
    )
