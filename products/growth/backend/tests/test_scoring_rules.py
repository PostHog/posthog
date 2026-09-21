from dataclasses import FrozenInstanceError

import pytest

from parameterized import parameterized
from pydantic import ValidationError


@parameterized.expand(
    [
        ("unknown_option", {"ai_point": 15}),
        ("unknown_nested_option", {"traction": {"growth_horizn": "90d_ago"}}),
        ("negative_points", {"ai_points": -1}),
        ("boolean_points", {"ai_points": True}),
        ("unknown_source", {"ai_sources": ["website"]}),
        ("duplicate_source", {"ai_sources": ["wizard", "wizard"]}),
        ("no_label", {"ai_labels": []}),
        ("blank_label", {"ai_labels": [""]}),
        ("duplicate_label", {"ai_labels": ["ai_pilled", "ai_pilled"]}),
        ("unsupported_horizon", {"traction": {"growth_horizon": "7d_ago"}}),
        (
            "unordered_tiers",
            {"traction": {"traffic_levels": [{"minimum": 100, "points": 5}, {"minimum": 10, "points": 10}]}},
        ),
        (
            "decreasing_points",
            {"capital": {"funding_levels": [{"minimum": 1, "points": 10}, {"minimum": 2, "points": 5}]}},
        ),
        ("above_component_cap", {"capital": {"cap": 10}}),
        ("above_total_cap", {"ai_points": 30}),
        ("unknown_schema", {"schema_version": 2}),
        ("boolean_schema", {"schema_version": True}),
        ("list_instead_of_object", []),
    ]
)
def test_invalid_policy_is_rejected(_name, value):
    from django.core.exceptions import ValidationError as DjangoValidationError

    from products.growth.backend.enrichment.scoring_rules import parse_scoring_rules, validate_scoring_rules

    with pytest.raises(ValueError):
        parse_scoring_rules(value)
    with pytest.raises(DjangoValidationError):
        validate_scoring_rules(value)


def test_policy_is_immutable_after_validation():
    from products.growth.backend.enrichment.scoring_rules import parse_scoring_rules

    rules = parse_scoring_rules({"ai_sources": ["wizard"], "ai_labels": ["engineering_ai"]})
    assert rules.ai_sources == ("wizard",)
    assert rules.ai_labels == ("engineering_ai",)
    for model, field, value in ((rules, "ai_points", 99), (rules.capital, "cap", 0)):
        with pytest.raises((ValidationError, FrozenInstanceError)):
            setattr(model, field, value)


def test_default_export_round_trips_without_sharing_mutable_state():
    from products.growth.backend.enrichment.scoring_rules import default_scoring_rules, parse_scoring_rules

    exported = default_scoring_rules()
    original = parse_scoring_rules(exported)
    exported["ai_sources"].clear()
    assert original == parse_scoring_rules({})
    assert default_scoring_rules()["ai_sources"] == ["harmonic", "wizard", "llm"]
