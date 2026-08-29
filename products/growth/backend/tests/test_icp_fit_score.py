from typing import Any

from parameterized import parameterized

from products.growth.backend.enrichment.fit_score import (
    SCORE_VERSION,
    STATUS_DISQUALIFIED,
    STATUS_INSUFFICIENT_DATA,
    STATUS_NOT_FOUND,
    STATUS_SCORED,
    is_quality_investor,
    score_company,
)
from products.growth.backend.enrichment.icp_lists import CuratedLists, norm

LISTS = CuratedLists(
    version="test-lists",
    capital_quality=frozenset({"ai grant batch 1"}),
    ai_positive=frozenset({"artificial intelligence", "ai grant batch 1"}),
    software_positive=frozenset({"developer tools"}),
    quality_investors=frozenset({norm("Y Combinator"), norm("Sequoia Capital"), norm("GV")}),
)


def _payload(**overrides):
    """A matched company that scores 0 with full data coverage absent; cases override one branch."""
    payload: dict[str, Any] = {
        "company_type": "STARTUP",
        "headcount": None,
        "description": None,
        "funding": {"funding_total": None, "investors": []},
        "funding_attribute_null_status": None,
        "tags_v2": [{"display_value": "Logistics & Supply Chain", "type": "MARKET"}],
        "traction_metrics": {
            "web_traffic": {"latest_metric_value": None, "90d_ago": {"percent_change": None, "change": None}},
            "headcount": {"latest_metric_value": None, "180d_ago": {"percent_change": None, "change": None}},
            "headcount_engineering": {"latest_metric_value": None},
        },
    }
    for key, value in overrides.items():
        payload[key] = value
    return payload


def _traction(
    web_traffic=None, traffic_growth=None, headcount=None, headcount_growth=None, headcount_adds=None, eng=None
):
    return {
        "web_traffic": {
            "latest_metric_value": web_traffic,
            "90d_ago": {"percent_change": traffic_growth, "change": None},
        },
        "headcount": {
            "latest_metric_value": headcount,
            "180d_ago": {"percent_change": headcount_growth, "change": headcount_adds},
        },
        "headcount_engineering": {"latest_metric_value": eng},
    }


def test_version_is_stamped():
    assert SCORE_VERSION == "v0.5"
    result = score_company(_payload(), lists=LISTS)
    assert result.version == "v0.5"
    assert result.lists_version == "test-lists"


# ---------- statuses ----------


def test_student_role_disqualifies_before_the_payload_is_consulted():
    result = score_company(None, lists=LISTS, role="Student")
    assert (result.status, result.score, result.dq_reason) == (STATUS_DISQUALIFIED, 0, "role=student")


def test_school_company_type_disqualifies():
    result = score_company(_payload(company_type="SCHOOL"), lists=LISTS)
    assert (result.status, result.score, result.dq_reason) == (STATUS_DISQUALIFIED, 0, "company_type=SCHOOL")


def test_school_market_tags_do_not_disqualify_a_startup():
    # Tags describe who a company sells to; only company_type=SCHOOL marks actual institutions.
    result = score_company(_payload(tags_v2=[{"display_value": "Schools", "type": "MARKET"}]), lists=LISTS)
    assert result.status == STATUS_SCORED


def test_missing_payload_is_not_found():
    assert score_company(None, lists=LISTS).status == STATUS_NOT_FOUND


def test_empty_shell_profile_is_insufficient_data_not_a_low_score():
    payload = _payload(tags_v2=[])
    result = score_company(payload, lists=LISTS)
    assert result.status == STATUS_INSUFFICIENT_DATA
    assert result.score is None


@parameterized.expand(
    [
        ("headcount", {"headcount": 4}),
        ("funding", {"funding": {"funding_total": 100_000, "investors": []}}),
        # Investors are a funding signal on their own (handbook + coverage counter):
        # a raise known only through the investor list is not an empty shell.
        ("investors_only", {"funding": {"funding_total": None, "investors": [{"name": "Cousin Capital"}]}}),
        ("tags", {}),  # the base payload's tag row alone
        ("web_traffic", {"traction_metrics": _traction(web_traffic=600)}),
    ]
)
def test_any_single_core_signal_defeats_the_insufficient_data_gate(_name, overrides):
    payload = _payload(tags_v2=[], **overrides) if "tags" not in _name else _payload()
    assert score_company(payload, lists=LISTS).status == STATUS_SCORED


def test_undisclosed_raise_with_a_quality_investor_scores_capital_18():
    # The score owner's ruling (2026-08-19): EXISTS_BUT_UNDISCLOSED + a named quality
    # investor is a scorable profile — base tier 8 plus the quality bonus — not
    # insufficient_data, even when every other core signal is empty.
    payload = _payload(
        tags_v2=[],
        funding={"funding_total": None, "investors": [{"name": "Sequoia Capital"}]},
        funding_attribute_null_status="EXISTS_BUT_UNDISCLOSED",
    )
    result = score_company(payload, lists=LISTS)
    assert result.status == STATUS_SCORED
    assert (result.components or {}).get("capital") == 18
    assert result.quality_investor is True


# ---------- traction (35 = level 15 + growth 20) ----------


@parameterized.expand(
    [
        ("100k_visits", 100_000, 15),
        ("10k_visits", 10_000, 10),
        ("1k_visits", 1_000, 5),
        ("999_visits", 999, 0),
        ("none", None, 0),
    ]
)
def test_traffic_level_tiers(_name, web_traffic, expected):
    result = score_company(_payload(traction_metrics=_traction(web_traffic=web_traffic)), lists=LISTS)
    assert (result.components or {}).get("traction") == expected


@parameterized.expand(
    [
        ("plus_40pct", 10_000, 40.0, 10 + 20),
        ("plus_15pct", 10_000, 15.0, 10 + 12),
        ("barely_positive", 10_000, 0.1, 10 + 5),
        ("flat", 10_000, 0.0, 10 + 0),
        ("shrinking", 10_000, -25.0, 10 + 0),
        ("unknown_growth", 10_000, None, 10 + 0),
        # Growth never counts below a 5k-visit base: small-base percentages invert the signal.
        ("small_base_growth_ignored", 1_000, 300.0, 5 + 0),
    ]
)
def test_traffic_growth_tiers_and_the_5k_base_gate(_name, web_traffic, growth, expected):
    result = score_company(
        _payload(traction_metrics=_traction(web_traffic=web_traffic, traffic_growth=growth)), lists=LISTS
    )
    assert (result.components or {}).get("traction") == expected


# ---------- capital (30 = tier 20 + quality bonus 10, capped) ----------


@parameterized.expand(
    [
        ("10m", 10_000_000, None, 20),
        ("2m", 2_000_000, None, 14),
        ("any_funding", 1, None, 8),
        ("undisclosed_but_exists", 0, "EXISTS_BUT_UNDISCLOSED", 8),
        ("nothing", 0, None, 0),
    ]
)
def test_funding_tiers(_name, funding_total, null_status, expected):
    payload = _payload(
        funding={"funding_total": funding_total, "investors": []}, funding_attribute_null_status=null_status
    )
    assert (score_company(payload, lists=LISTS).components or {}).get("capital") == expected


@parameterized.expand(
    [
        ("named_investor_exact", [{"name": "Sequoia Capital"}], True),
        ("named_investor_substring", [{"name": "Sequoia Capital India"}], True),
        ("short_name_never_substrings", [{"name": "GVK Industries"}], False),
        ("short_name_exact_still_matches", [{"name": "GV"}], True),
        ("unknown_investor", [{"name": "Cousin Capital"}], False),
    ]
)
def test_quality_investor_matching(_name, investors, expect_quality):
    payload = _payload(funding={"funding_total": 12_000_000, "investors": investors})
    result = score_company(payload, lists=LISTS)
    assert result.quality_investor is expect_quality
    assert (result.components or {}).get("capital") == (30 if expect_quality else 20)


def test_yc_batch_tag_type_confers_quality_capital_for_any_batch():
    # Matched on tag TYPE so future batches (W27, ...) qualify without a list update.
    payload = _payload(
        funding={"funding_total": 500_000, "investors": []},
        tags_v2=[{"display_value": "S26", "type": "YC_BATCH"}],
    )
    result = score_company(payload, lists=LISTS)
    assert result.quality_investor is True
    assert (result.components or {}).get("capital") == 8 + 10


def test_capital_is_capped_at_30():
    payload = _payload(funding={"funding_total": 50_000_000, "investors": [{"name": "Y Combinator"}]})
    assert (score_company(payload, lists=LISTS).components or {}).get("capital") == 30


def test_quality_bonus_alone_scores_without_any_recorded_funding():
    payload = _payload(tags_v2=[{"display_value": "AI Grant Batch 1", "type": "ACCELERATOR"}])
    result = score_company(payload, lists=LISTS)
    assert (result.components or {}).get("capital") == 10
    assert result.quality_investor is True


# ---------- AI-pilled (15) ----------


@parameterized.expand(
    [
        ("ai_tag", [{"display_value": "Artificial Intelligence", "type": "MARKET"}], None, "acme.com", 15),
        ("ai_description", None, "We build ML pipelines for robots", "acme.com", 15),
        ("dot_ai_domain", None, None, "acme.ai", 15),
        ("none_of_the_three", None, "We sell shoes", "acme.com", 0),
        # \b word boundaries: "aid" or "mail" must not match the AI regex.
        ("no_substring_false_positives", None, "First aid mail retail", "acme.com", 0),
    ]
)
def test_ai_pilled_signals(_name, tags, description, domain, expected):
    payload = _payload(description=description)
    if tags:
        payload["tags_v2"] = tags
    result = score_company(payload, lists=LISTS, domain=domain)
    assert (result.components or {}).get("ai_pilled") == expected


# ---------- headcount growth (10) ----------


@parameterized.expand(
    [
        ("fast_growth", 15.0, None, 10),
        ("moderate_growth", 5.0, None, 6),
        ("three_net_hires_alternative", 2.0, 3, 6),
        ("barely_growing", 1.0, None, 3),
        ("three_hires_with_zero_pct", 0.0, 3, 6),
        ("flat", 0.0, None, 0),
        ("shrinking", -10.0, None, 0),
        ("unknown", None, None, 0),
    ]
)
def test_headcount_growth_tiers(_name, growth, adds, expected):
    payload = _payload(traction_metrics=_traction(headcount=20, headcount_growth=growth, headcount_adds=adds))
    assert (score_company(payload, lists=LISTS).components or {}).get("headcount_growth") == expected


# ---------- software relevance (10) ----------


@parameterized.expand(
    [
        ("eng_headcount", _traction(eng=3), None, None, 10),
        ("software_tag_only", _traction(), [{"display_value": "Developer Tools", "type": "MARKET"}], None, 7),
        ("software_description_only", _traction(), None, "An API platform for teams", 7),
        ("neither", _traction(), None, "We run a bakery", 0),
    ]
)
def test_software_relevance_tiers(_name, traction, tags, description, expected):
    payload = _payload(traction_metrics=traction, description=description)
    if tags:
        payload["tags_v2"] = tags
    assert (score_company(payload, lists=LISTS).components or {}).get("software_relevance") == expected


# ---------- flags & coverage ----------


def test_agency_and_nonprofit_are_flags_not_penalties():
    payload = _payload(
        tags_v2=[
            {"display_value": "Consulting", "type": "MARKET"},
            {"display_value": "Non-Profit & Community Organizations", "type": "MARKET"},
        ],
        headcount=40,
    )
    result = score_company(payload, lists=LISTS)
    assert result.status == STATUS_SCORED
    assert result.agency_flag is True
    assert result.nonprofit_flag is True


def test_low_confidence_flags_thin_coverage():
    result = score_company(_payload(), lists=LISTS)  # tags only: 1 of 4 core signals
    assert result.data_coverage == 1
    assert result.low_confidence is True

    rich = _payload(headcount=50, funding={"funding_total": 5_000_000, "investors": []})
    rich["traction_metrics"] = _traction(web_traffic=20_000)
    result = score_company(rich, lists=LISTS)
    assert result.data_coverage == 4
    assert result.low_confidence is False


def test_archetype_scores_high_across_all_components():
    payload = _payload(
        headcount=12,
        description="AI developer platform",
        funding={"funding_total": 12_000_000, "investors": [{"name": "Y Combinator"}]},
        tags_v2=[
            {"display_value": "Artificial Intelligence", "type": "MARKET"},
            {"display_value": "S25", "type": "YC_BATCH"},
        ],
        traction_metrics=_traction(
            web_traffic=120_000, traffic_growth=55.0, headcount=12, headcount_growth=30.0, eng=8
        ),
    )
    result = score_company(payload, lists=LISTS, domain="acme.ai")
    assert result.status == STATUS_SCORED
    assert result.score == 100
    assert result.components == {
        "traction": 35,
        "capital": 30,
        "ai_pilled": 15,
        "headcount_growth": 10,
        "software_relevance": 10,
    }


# ---------- helpers ----------


@parameterized.expand(
    [
        ("case_folds", "Y COMBINATOR", True),
        ("and_normalizes", "management and strategy consulting", False),  # not an investor list entry
        ("whitespace", "  y combinator  ", True),
    ]
)
def test_norm_based_matching(_name, observed, expected):
    assert is_quality_investor(observed, LISTS.quality_investors) is expected


def test_norm_folds_and_to_ampersand():
    assert norm("Management and Strategy Consulting") == "management & strategy consulting"
