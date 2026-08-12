from parameterized import parameterized

from products.growth.backend.enrichment.score import SCORE_VERSION, IcpScoreInputs, compute_icp_score


# A country on the allowlist keeps the -5 penalty out of the way, so each case isolates its branch.
def _inputs(**overrides) -> IcpScoreInputs:
    return IcpScoreInputs(country="US", **overrides)


def test_version_is_stamped():
    assert SCORE_VERSION == "clay-parity-1"


def test_all_inputs_missing_scores_only_the_country_penalty():
    assert compute_icp_score(IcpScoreInputs()) == -5


def test_no_signals_but_allowlisted_country_scores_zero():
    assert compute_icp_score(_inputs()) == 0


@parameterized.expand(
    [
        ("below_band", 500, 0),
        ("lower_edge", 501, 3),
        ("upper_edge", 1000, 3),
        ("above_band", 1001, 0),
        ("far_below", 12, 0),
        ("far_above", 50000, 0),
        ("missing", None, 0),
    ]
)
def test_employees_band(_name, employees, expected):
    assert compute_icp_score(_inputs(employees=employees)) == expected


@parameterized.expand(
    [
        ("below_both", 1_000_000, 0),
        ("lower_edge_of_first", 1_000_001, 6),
        ("upper_edge_of_first", 50_000_000, 6),
        ("lower_edge_of_second", 50_000_001, 3),
        ("upper_edge_of_second", 100_000_000, 3),
        ("above_both", 100_000_001, 0),
        ("missing", None, 0),
    ]
)
def test_est_revenue_bands(_name, est_revenue, expected):
    assert compute_icp_score(_inputs(est_revenue=est_revenue)) == expected


def test_est_revenue_bands_are_exclusive_for_whole_dollars():
    # 6 and 3 are never both scored, so 6 is the most revenue alone can contribute.
    scores = {compute_icp_score(_inputs(est_revenue=revenue)) for revenue in range(49_999_998, 50_000_004)}
    assert scores == {6, 3}


@parameterized.expand(
    [
        ("engineering", "engineering", 6),
        ("founder", "founder", 6),
        ("mixed_case", "EnGiNeErInG", 6),
        ("upper_case_founder", "FOUNDER", 6),
        ("product", "product", 3),
        ("marketing", "marketing", 0),
        ("empty", "", 0),
        ("missing", None, 0),
    ]
)
def test_role_branches(_name, role, expected):
    assert compute_icp_score(_inputs(role=role)) == expected


@parameterized.expand(
    [
        ("with_profile", "https://github.com/someone", 6),
        ("mixed_case_role_with_profile", "https://github.com/someone", 6),
        ("without_profile", None, 3),
        ("empty_profile_url", "", 3),
    ]
)
def test_product_role_splits_on_github_profile(_name, github_profile_url, expected):
    assert compute_icp_score(_inputs(role="Product", github_profile_url=github_profile_url)) == expected


def test_github_profile_only_matters_for_the_product_role():
    assert compute_icp_score(_inputs(role="engineering", github_profile_url="https://github.com/someone")) == 6
    assert compute_icp_score(_inputs(role="marketing", github_profile_url="https://github.com/someone")) == 0


@parameterized.expand(
    [
        ("private", "private", 3),
        ("mixed_case", "Private", 3),
        ("public", "public", 0),
        ("personal", "personal", 0),
        # Our own Harmonic-derived company_type is a raw enum in a different vocabulary, so it
        # would never score this branch — hence the value is bridge-read from Clay.
        ("harmonic_raw_enum", "STARTUP", 0),
        ("empty", "", 0),
        ("missing", None, 0),
    ]
)
def test_company_type_branch(_name, company_type, expected):
    assert compute_icp_score(_inputs(company_type=company_type)) == expected


@parameterized.expand(
    [
        ("on_the_edge", 2014, 0),
        ("just_after", 2015, 3),
        ("recent", 2024, 3),
        ("older", 1998, 0),
        ("missing", None, 0),
    ]
)
def test_founded_year_branch(_name, founded_year, expected):
    assert compute_icp_score(_inputs(founded_year=founded_year)) == expected


@parameterized.expand(
    [
        ("united_states", "US", 0),
        ("germany", "DE", 0),
        ("south_korea", "KR", 0),
        ("india_not_allowlisted", "IN", -5),
        ("missing", None, -5),
        ("empty", "", -5),
        # Clay matches the allowlist case-sensitively; our ISO codes are upper-cased upstream.
        ("lower_case_is_not_allowlisted", "us", -5),
    ]
)
def test_country_penalty(_name, country, expected):
    assert compute_icp_score(IcpScoreInputs(country=country)) == expected


def test_maximum_score():
    inputs = IcpScoreInputs(
        employees=750,
        est_revenue=25_000_000,
        role="founder",
        company_type="private",
        founded_year=2021,
        country="US",
    )
    assert compute_icp_score(inputs) == 21


def test_minimum_score():
    inputs = IcpScoreInputs(
        employees=5000,
        est_revenue=500_000_000,
        role="sales",
        company_type="public",
        founded_year=1998,
        country="IN",
    )
    assert compute_icp_score(inputs) == -5


def test_every_branch_scoring_together_with_the_country_penalty():
    inputs = IcpScoreInputs(
        employees=1000,
        est_revenue=1_000_001,
        role="product",
        github_profile_url="https://github.com/someone",
        company_type="private",
        founded_year=2015,
        country=None,
    )
    assert compute_icp_score(inputs) == 16
