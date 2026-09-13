from parameterized import parameterized

from products.growth.backend.enrichment.fit_score import score_company
from products.growth.backend.enrichment.harmonic_adapter import normalize_graphql_company
from products.growth.backend.enrichment.icp_lists import CuratedLists


def _normalized(company):
    result = normalize_graphql_company(company)
    assert result is not None
    return result


LISTS = CuratedLists(version="test-lists")


def _series(*points):
    """(iso_timestamp, value) pairs -> GraphQL metrics list, deliberately unsorted-friendly."""
    return [{"timestamp": ts, "metricValue": value} for ts, value in points]


@parameterized.expand(
    [
        ("none", None),
        ("miss_sentinel", {"companyFound": False}),
        ("empty_dict", {}),
        ("not_a_dict", ["companyFound"]),
    ]
)
def test_unmatched_payloads_normalize_to_none(_name, payload):
    assert normalize_graphql_company(payload) is None


def test_camelcase_projection_to_the_scorer_shape():
    company = {
        "companyType": "STARTUP",
        "headcount": 42,
        "description": "An API platform",
        "fundingAttributeNullStatus": "EXISTS_BUT_UNDISCLOSED",
        "funding": {
            "fundingTotal": 3_500_000,
            # Company entries carry `name`, angel entries carry `fullName`; both fold to `name`.
            "investors": [{"name": "Sequoia Capital"}, {"fullName": "Jane Angel"}, {"logo": "no-name.png"}],
        },
        "tagsV2": [{"displayValue": "Developer Tools", "type": "MARKET", "dateAdded": "2026-01-01"}],
        "tractionMetrics": {
            "webTraffic": {"latestMetricValue": 12_000, "metrics": []},
            "headcount": {"latestMetricValue": 42, "metrics": []},
            "headcountEngineering": {"latestMetricValue": 7, "metrics": []},
        },
    }

    normalized = normalize_graphql_company(company)

    assert normalized == {
        "company_type": "STARTUP",
        "headcount": 42,
        "description": "An API platform",
        "funding": {"funding_total": 3_500_000, "investors": [{"name": "Sequoia Capital"}, {"name": "Jane Angel"}]},
        "funding_attribute_null_status": "EXISTS_BUT_UNDISCLOSED",
        "tags_v2": [{"display_value": "Developer Tools", "type": "MARKET"}],
        "traction_metrics": {
            "web_traffic": {"latest_metric_value": 12_000, "90d_ago": {"percent_change": None, "change": None}},
            "headcount": {"latest_metric_value": 42, "180d_ago": {"percent_change": None, "change": None}},
            "headcount_engineering": {"latest_metric_value": 7},
        },
    }


def test_growth_derived_as_of_the_latest_observation():
    # Latest point 2026-06-01; the 90d-ago anchor (2026-03-03) resolves to the last
    # observation at or before it (2026-02-20, value 8000) — no interpolation, no peeking.
    company = {
        "tractionMetrics": {
            "webTraffic": {
                "latestMetricValue": 12_000,
                "metrics": _series(
                    ("2026-06-01T00:00:00.000Z", 12_000),
                    ("2026-02-20T00:00:00.000Z", 8_000),
                    ("2025-11-01T00:00:00.000Z", 2_000),
                ),
            }
        }
    }
    block = _normalized(company)["traction_metrics"]["web_traffic"]
    assert block["90d_ago"] == {"percent_change": 50.0, "change": 4_000}


def test_headcount_growth_uses_the_180d_window_and_absolute_change():
    company = {
        "tractionMetrics": {
            "headcount": {
                "latestMetricValue": 23,
                "metrics": _series(
                    ("2026-08-01T00:00:00.000Z", 23),
                    ("2026-01-15T00:00:00.000Z", 20),  # last obs at/before 2026-02-02 anchor
                    ("2025-06-01T00:00:00.000Z", 5),
                ),
            }
        }
    }
    block = _normalized(company)["traction_metrics"]["headcount"]
    assert block["180d_ago"] == {"percent_change": 15.0, "change": 3}


@parameterized.expand(
    [
        ("empty_series", []),
        ("single_point_cannot_cover_the_window", _series(("2026-06-01T00:00:00.000Z", 9_000))),
        ("all_points_inside_the_window", _series(("2026-06-01T00:00:00Z", 9_000), ("2026-05-20T00:00:00Z", 7_000))),
        ("zero_baseline", _series(("2026-06-01T00:00:00Z", 9_000), ("2026-01-01T00:00:00Z", 0))),
        (
            "malformed_points",
            [
                {"timestamp": None, "metricValue": 5},
                {"timestamp": "not-a-date", "metricValue": 5},
                {"timestamp": "2026-06-01T00:00:00Z"},
            ],
        ),
    ]
)
def test_uncoverable_windows_yield_unknown_growth_never_zero(_name, metrics):
    company = {"tractionMetrics": {"webTraffic": {"latestMetricValue": 9_000, "metrics": metrics}}}
    block = _normalized(company)["traction_metrics"]["web_traffic"]
    assert block["90d_ago"] == {"percent_change": None, "change": None}


def test_unsorted_series_are_sorted_before_derivation():
    company = {
        "tractionMetrics": {
            "webTraffic": {
                "latestMetricValue": 6_000,
                "metrics": _series(
                    ("2026-01-01T00:00:00Z", 3_000),
                    ("2026-06-01T00:00:00Z", 6_000),
                    ("2026-02-25T00:00:00Z", 4_000),
                ),
            }
        }
    }
    block = _normalized(company)["traction_metrics"]["web_traffic"]
    assert block["90d_ago"]["percent_change"] == 50.0  # 4000 (Feb 25, last <= Mar 3 anchor) -> 6000


def test_normalized_output_scores_end_to_end():
    company = {
        "companyType": "STARTUP",
        "headcount": 12,
        "description": "AI developer platform",
        "funding": {"fundingTotal": 12_000_000, "investors": [{"name": "Y Combinator"}]},
        "tagsV2": [{"displayValue": "S25", "type": "YC_BATCH"}],
        "tractionMetrics": {
            "webTraffic": {
                "latestMetricValue": 120_000,
                "metrics": _series(("2026-08-01T00:00:00Z", 120_000), ("2026-04-01T00:00:00Z", 70_000)),
            },
            "headcount": {
                "latestMetricValue": 12,
                "metrics": _series(("2026-08-01T00:00:00Z", 12), ("2026-01-01T00:00:00Z", 8)),
            },
            "headcountEngineering": {"latestMetricValue": 8, "metrics": []},
        },
    }
    result = score_company(normalize_graphql_company(company), lists=LISTS, domain="acme.ai")
    assert result.status == "scored"
    # traction 15+20 (71% 90d growth) + capital 20+10 capped at 30 ($12M + YC batch) +
    # ai 15 (.ai + description) + headcount growth 10 (50% 180d) + software 10 (eng headcount)
    assert result.score == 100
    assert result.components == {
        "traction": 35,
        "capital": 30,
        "ai_pilled": 15,
        "headcount_growth": 10,
        "software_relevance": 10,
    }
