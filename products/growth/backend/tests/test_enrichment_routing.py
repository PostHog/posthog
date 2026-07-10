from products.growth.backend.enrichment.classifier import CompanyType
from products.growth.backend.enrichment.routing import resolve_company_type


def test_prefers_known_deterministic_value():
    assert resolve_company_type({"company_type_deterministic": "yc", "company_type": "STARTUP"}) == "yc"


def test_falls_back_to_enrichment_when_deterministic_unknown():
    data = {"company_type_deterministic": CompanyType.UNKNOWN.value, "company_type": "STARTUP"}
    assert resolve_company_type(data) == "STARTUP"


def test_falls_back_to_enrichment_when_deterministic_missing():
    assert resolve_company_type({"company_type": "STARTUP"}) == "STARTUP"


def test_safe_default_when_nothing_set():
    assert resolve_company_type({}) == CompanyType.UNKNOWN.value


def test_safe_default_when_unknown_and_no_enrichment_yet():
    # Enrichment hasn't landed by onboarding's first read: degrade to unknown, don't raise.
    assert resolve_company_type({"company_type_deterministic": "unknown"}) == CompanyType.UNKNOWN.value
