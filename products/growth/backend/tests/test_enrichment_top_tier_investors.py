from parameterized import parameterized

from products.growth.backend.enrichment.top_tier_investors import (
    _ALIASES,
    TOP_TIER_VCS,
    _normalize,
    is_top_tier_investor,
)


@parameterized.expand(
    [
        ("canonical_exact", "Sequoia Capital", True),
        ("canonical_case_insensitive", "sequoia capital", True),
        ("canonical_trailing_punctuation", "General Catalyst.", True),
        ("alias_a16z", "a16z", True),
        ("alias_a16z_uppercase", "A16Z", True),
        ("alias_yc", "YC", True),
        ("not_top_tier", "Acme Ventures", False),
        ("unrelated_substring_of_a_top_tier_name", "Capital", False),
        ("empty_string", "", False),
    ]
)
def test_is_top_tier_investor(_name, investor_name, expected):
    assert is_top_tier_investor(investor_name) is expected


def test_is_top_tier_investor_rejects_non_string_input():
    assert is_top_tier_investor(None) is False  # type: ignore[arg-type]


def test_every_alias_resolves_to_a_canonical_name():
    canonical_normalized = {_normalize(name) for name in TOP_TIER_VCS}
    for alias, canonical in _ALIASES.items():
        assert _normalize(canonical) in canonical_normalized, (
            f"alias {alias!r} points at {canonical!r}, not in TOP_TIER_VCS"
        )
