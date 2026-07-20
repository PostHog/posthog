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


def _funding_amount(value: Any) -> Optional[int]:
    # Harmonic reports funding as whole USD; store as int to keep it off floats.
    return int(value) if isinstance(value, (int, float)) else None


def _funding_date(value: Any) -> Optional[str]:
    # Harmonic returns an ISO datetime (e.g. "2025-02-25T00:00:00Z"); keep the date.
    if isinstance(value, str) and value:
        return value.split("T", 1)[0]
    return None


# Bound the passthrough so the group property can't grow unboundedly for a heavily-funded company.
MAX_INVESTORS = 25


def _investor_names(investors: Any) -> Optional[list[str]]:
    # Company entries carry `name`, Person (angel) entries carry `fullName`; keep both.
    if not isinstance(investors, list):
        return None
    names = [
        name
        for investor in investors
        if isinstance(investor, dict) and isinstance(name := investor.get("name") or investor.get("fullName"), str)
    ]
    return names[:MAX_INVESTORS] or None


# Harmonic's own tagsV2 taxonomy spells these out; match conservatively on the phrases
# rather than bare "AI"/"ML" tokens that collide with unrelated words.
AI_NATIVE_TAG_MARKERS = ("artificial intelligence", "machine learning")


def _is_ai_native(tags_v2: list[Any]) -> Optional[bool]:
    # Empty tagsV2 is absence of tag data, not evidence the company isn't AI-native.
    if not tags_v2:
        return None
    for tag in tags_v2:
        display = _safe_dict(tag).get("displayValue")
        if isinstance(display, str) and any(marker in display.lower() for marker in AI_NATIVE_TAG_MARKERS):
            return True
    return False


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

    tags_v2 = _safe_list(company.get("tagsV2"))

    return EnrichmentFields(
        company_type=company.get("companyType"),
        headcount=headcount,
        headcount_engineering=_latest_metric(traction, "headcountEngineering"),
        industry=_extract_primary_tag(_safe_list(company.get("tags")), tags_v2),
        # ISO alpha-2 to match the format the icp_country group property already holds.
        country=country_name_to_iso_code(location.get("country")),
        founded_year=_founded_year(founding),
        funding_stage=funding.get("fundingStage"),
        total_raised=_funding_amount(funding.get("fundingTotal")),
        last_round_size=_funding_amount(funding.get("lastFundingTotal")),
        last_round_date=_funding_date(funding.get("lastFundingAt")),
        investors=_investor_names(funding.get("investors")),
        is_yc_company=_is_yc_funded(funding.get("investors")),
        is_ai_native=_is_ai_native(tags_v2),
    )
