from products.growth.backend.enrichment.transform import transform_harmonic_company


def _company(**overrides):
    company = {
        "companyType": "STARTUP",
        "headcount": 120,
        "location": {"country": "United States"},
        "foundingDate": {"date": "2019-06-01", "granularity": "DAY"},
        "funding": {"fundingStage": "SERIES_A", "investors": [{"name": "Y Combinator"}]},
        "tractionMetrics": {
            "headcount": {"latestMetricValue": 130},
            "headcountEngineering": {"latestMetricValue": 45},
        },
        "tags": [{"type": "INDUSTRY", "displayValue": "Developer Tools", "isPrimaryTag": True}],
        "tagsV2": [],
    }
    company.update(overrides)
    return company


def test_transform_maps_all_registry_fields():
    fields = transform_harmonic_company(_company())
    assert fields is not None
    assert fields.to_dict() == {
        "company_type": "STARTUP",
        "headcount": 130,  # tractionMetrics wins over the top-level headcount
        "headcount_engineering": 45,
        "industry": "Developer Tools",
        "country": "United States",
        "founded_year": 2019,
        "funding_stage": "SERIES_A",
        "is_yc_company": True,
    }


def test_headcount_falls_back_to_top_level_when_no_traction_metric():
    fields = transform_harmonic_company(_company(tractionMetrics={}))
    assert fields is not None
    assert fields.headcount == 120


def test_industry_falls_back_to_market_vertical_tag_v2():
    fields = transform_harmonic_company(_company(tags=[], tagsV2=[{"type": "MARKET_VERTICAL", "displayValue": "SaaS"}]))
    assert fields is not None
    assert fields.industry == "SaaS"


def test_non_yc_investors():
    fields = transform_harmonic_company(_company(funding={"fundingStage": "SEED", "investors": [{"name": "Acme VC"}]}))
    assert fields is not None
    assert fields.is_yc_company is False


def test_none_and_empty_payloads_return_none():
    assert transform_harmonic_company(None) is None
    assert transform_harmonic_company({}) is None


def test_partial_payload_leaves_missing_fields_unset():
    fields = transform_harmonic_company({"companyType": "ENTERPRISE"})
    assert fields is not None
    assert fields.to_dict() == {"company_type": "ENTERPRISE", "is_yc_company": False}
