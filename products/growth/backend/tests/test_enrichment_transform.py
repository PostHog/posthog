from parameterized import parameterized

from products.growth.backend.enrichment.transform import MAX_INVESTORS, transform_harmonic_company


def _company(**overrides):
    company = {
        "companyType": "STARTUP",
        "headcount": 120,
        "location": {"country": "United States"},
        "foundingDate": {"date": "2019-06-01", "granularity": "DAY"},
        "funding": {
            "fundingStage": "SERIES_A",
            "fundingTotal": 12000000,
            "lastFundingTotal": 8000000,
            "lastFundingAt": "2024-02-25T00:00:00Z",
            "investors": [{"name": "Y Combinator"}],
        },
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
        "country": "US",  # ISO alpha-2, matching the icp_country format
        "founded_year": 2019,
        "funding_stage": "SERIES_A",
        "total_raised": 12000000,
        "last_round_size": 8000000,
        "last_round_date": "2024-02-25",  # ISO datetime truncated to the date
        "investors": ["Y Combinator"],
        "is_yc_company": True,
        # is_ai_native stays unset: tagsV2 is empty, which is absence of tag data
    }


def test_investors_capture_company_and_person_names_skipping_malformed_entries():
    investors = [
        {"name": "Formus Capital"},
        {"fullName": "Julia Dewahl"},  # angels come back as Person entries
        {"foo": "bar"},  # neither name nor fullName
        "not-a-dict",
    ]
    fields = transform_harmonic_company(_company(funding={"investors": investors}))
    assert fields is not None
    assert fields.investors == ["Formus Capital", "Julia Dewahl"]


def test_investors_unset_when_funding_has_no_investors():
    fields = transform_harmonic_company(_company(funding={"fundingStage": "SEED"}))
    assert fields is not None
    assert fields.investors is None
    assert "investors" not in fields.to_dict()


def test_investors_capped_to_bound():
    fields = transform_harmonic_company(_company(funding={"investors": [{"name": f"VC {i}"} for i in range(40)]}))
    assert fields is not None
    assert fields.investors is not None
    assert len(fields.investors) == MAX_INVESTORS
    assert fields.investors[0] == "VC 0"


@parameterized.expand(
    [
        ("ai_display_value", [{"type": "TECHNOLOGY_TYPE", "displayValue": "Artificial Intelligence (AI)"}], True),
        ("ml_display_value", [{"type": "MARKET_VERTICAL", "displayValue": "Machine Learning"}], True),
        ("non_ai_tags_present", [{"type": "MARKET_VERTICAL", "displayValue": "Fintech"}], False),
    ]
)
def test_is_ai_native_matches_conservatively(_name, tags_v2, expected):
    fields = transform_harmonic_company(_company(tagsV2=tags_v2))
    assert fields is not None
    assert fields.is_ai_native is expected


def test_is_ai_native_unset_when_tags_v2_absent():
    fields = transform_harmonic_company(_company(tagsV2=[]))
    assert fields is not None
    assert fields.is_ai_native is None
    assert "is_ai_native" not in fields.to_dict()


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


def test_unmapped_country_name_is_dropped_not_written_raw():
    fields = transform_harmonic_company(_company(location={"country": "Kingdom of Freedonia"}))
    assert fields is not None
    assert fields.country is None


def test_none_and_empty_payloads_return_none():
    assert transform_harmonic_company(None) is None
    assert transform_harmonic_company({}) is None


def test_partial_payload_leaves_missing_fields_unset():
    fields = transform_harmonic_company({"companyType": "ENTERPRISE"})
    assert fields is not None
    assert fields.to_dict() == {"company_type": "ENTERPRISE", "is_yc_company": False}
