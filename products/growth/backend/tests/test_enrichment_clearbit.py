from parameterized import parameterized

from products.growth.backend.enrichment.clearbit import ClearbitInputs, clearbit_inputs_from_person_properties
from products.growth.backend.enrichment.score import IcpScoreInputs, compute_icp_score


def _properties(band=None):
    company = {"metrics": {"estimatedAnnualRevenue": band}} if band is not None else {}
    return {"clearbit": {"company": company}}


@parameterized.expand(
    [
        ("under_1m", "$0-$1M", 0),
        ("1m_to_10m", "$1M-$10M", 6),
        ("10m_to_50m", "$10M-$50M", 6),
        ("50m_to_100m", "$50M-$100M", 3),
        ("100m_to_250m", "$100M-$250M", 0),
        ("250m_to_500m", "$250M-$500M", 0),
        ("500m_to_1b", "$500M-$1B", 0),
        ("1b_to_10b", "$1B-$10B", 0),
        ("10b_plus", "$10B+", 0),
        ("unknown_band", "$1M-$2M", 0),
        ("missing_band", None, 0),
    ]
)
def test_revenue_band_midpoint_scores_the_formula_band_it_belongs_to(_name, band, expected_score):
    inputs = clearbit_inputs_from_person_properties(_properties(band=band))
    assert compute_icp_score(IcpScoreInputs(est_revenue=inputs.est_revenue, country="US")) == expected_score


@parameterized.expand(
    [
        ("properties_is_none", None, ClearbitInputs()),
        ("properties_not_a_dict", "unexpected", ClearbitInputs()),
        ("missing_clearbit_key", {}, ClearbitInputs()),
        ("clearbit_is_none", {"clearbit": None}, ClearbitInputs()),
        ("clearbit_not_a_dict", {"clearbit": "unexpected"}, ClearbitInputs()),
        ("company_missing", {"clearbit": {}}, ClearbitInputs()),
        ("company_is_none", {"clearbit": {"company": None}}, ClearbitInputs()),
        ("metrics_not_a_dict", {"clearbit": {"company": {"metrics": "unexpected"}}}, ClearbitInputs()),
        (
            "band_not_a_string",
            {"clearbit": {"company": {"metrics": {"estimatedAnnualRevenue": 5_000_000}}}},
            ClearbitInputs(),
        ),
        (
            "band_present",
            {"clearbit": {"company": {"metrics": {"estimatedAnnualRevenue": "$1M-$10M"}}}},
            ClearbitInputs(est_revenue=5_500_000.0),
        ),
    ]
)
def test_extraction_tolerates_missing_or_malformed_shapes(_name, properties, expected):
    assert clearbit_inputs_from_person_properties(properties) == expected
