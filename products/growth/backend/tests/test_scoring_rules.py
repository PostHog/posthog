from dataclasses import replace

import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.growth.backend.enrichment.fit_score import score_company
from products.growth.backend.enrichment.icp_lists import CuratedLists
from products.growth.backend.enrichment.scoring_rules import default_scoring_rules, parse_scoring_rules


@parameterized.expand(
    [
        ("unknown_option", {"ai_point": 15}),
        ("no_label", {"ai_labels": []}),
        ("blank_label", {"ai_labels": [""]}),
        ("duplicate_label", {"ai_labels": ["ai_pilled", "ai_pilled"]}),
        ("list_instead_of_object", []),
        ("empty_source", {"source": ""}),
        ("oversized_source", {"source": " " * 30_001}),
        ("syntax_error", {"source": "return {"}),
        ("unknown_function", {"source": "return scoreEverything();"}),
        ("unknown_global", {"source": "return compny.headcount;"}),
        ("blocking_function", {"source": "sleep(10); return null;"}),
        ("query_function", {"source": "return run(sql(select 1));"}),
        ("query_expression", {"source": "return (select 1);"}),
        ("function_alias", {"source": "let wait := sleep; wait(10);"}),
        ("network_function", {"source": "return fetch('https://example.com');"}),
        ("current_date", {"source": "return today();"}),
    ]
)
def test_invalid_policy_is_rejected(_name, value):
    from django.core.exceptions import ValidationError as DjangoValidationError

    from products.growth.backend.enrichment.scoring_rules import validate_scoring_rules

    with pytest.raises(ValueError):
        parse_scoring_rules(value)
    with pytest.raises(DjangoValidationError):
        validate_scoring_rules(value)


def test_default_export_round_trips_without_sharing_mutable_state():
    exported = default_scoring_rules()
    original = parse_scoring_rules(exported)
    exported["ai_labels"].clear()
    assert original == parse_scoring_rules({})
    assert default_scoring_rules()["ai_labels"] == ["ai_pilled"]


@parameterized.expand(
    [
        ("scalar", "return 0;"),
        ("unknown_status", "return {'status': 'unknown'};"),
        ("out_of_range", "return {'status': 'scored', 'score': 101, 'components': {'traffic': 101}};"),
        ("mismatched_total", "return {'status': 'scored', 'score': 15, 'components': {'traffic': 10}};"),
        ("boolean_points", "return {'status': 'scored', 'score': true, 'components': {'traffic': true}};"),
        ("missing_data_with_score", "return {'status': 'insufficient_data', 'score': 0};"),
        ("forged_version", "return {'status': 'not_found', 'lists_version': 'forged'};"),
        ("forged_label", "return {'status': 'not_found', 'ai_pilled_label_result_id': 'forged'};"),
        ("runtime_error", "return {'score': 1 / 0};"),
    ]
)
def test_invalid_formula_result_raises_instead_of_returning_a_score(_name, source):
    lists = CuratedLists(version="example", rules=parse_scoring_rules({"source": source}))
    with pytest.raises((ValueError, ZeroDivisionError)):
        score_company({"headcount": 5}, lists=lists)


def test_infinite_formula_stops_at_the_runtime_budget():
    from common.hogvm.python.utils import HogVMRuntimeExceededException

    lists = CuratedLists(version="example", rules=parse_scoring_rules({"source": "while (true) {}"}))
    with patch("common.hogvm.python.execute.time.time", side_effect=[0, 1]):
        with pytest.raises(HogVMRuntimeExceededException):
            score_company({"headcount": 5}, lists=lists)


def test_formula_does_not_mutate_reused_company_inputs():
    payload = {"headcount": 5}
    lists = CuratedLists(version="example")
    changed = replace(
        lists,
        rules=parse_scoring_rules(
            {"source": "let changed := company; changed.headcount := 0; return {'status': 'not_found'};"}
        ),
    )
    score_company(payload, lists=changed)
    assert payload == {"headcount": 5}
