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
        ("removed_label_option", {"ai_labels": ["ai_pilled"]}),
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
    exported["source"] = 'return {"status": "not_found"};'
    assert original == parse_scoring_rules({})
    assert default_scoring_rules()["source"] == original.source


@parameterized.expand(
    [
        ("scalar", "return 0;"),
        ("unknown_status", "return {'status': 'unknown'};"),
        ("out_of_range", "return {'status': 'scored', 'score': 101, 'components': {'traffic': 101}};"),
        ("mismatched_total", "return {'status': 'scored', 'score': 15, 'components': {'traffic': 10}};"),
        ("boolean_points", "return {'status': 'scored', 'score': true, 'components': {'traffic': true}};"),
        ("missing_data_with_score", "return {'status': 'insufficient_data', 'score': 0};"),
        ("forged_version", "return {'status': 'not_found', 'lists_version': 'forged'};"),
        ("forged_input_version", "return {'status': 'not_found', 'input_versions': {'custom': 'forged'}};"),
        ("forged_input_hash", "return {'status': 'not_found', 'input_hash': 'forged'};"),
        ("nested_flag", "return {'status': 'not_found', 'flags': {'custom': {'nested': true}}};"),
        ("oversized_flag", "return {'status': 'not_found', 'flags': {'custom': '" + "x" * 1001 + "'}};"),
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


def test_generic_enrichment_outputs_control_score_and_flags():
    from products.growth.backend.enrichment.fit_score import evaluate_score

    result = evaluate_score(
        """
            let points := if(enrichments.customer_type.category == 'software', 25, 0);
            return {'status': 'scored', 'score': points, 'components': {'customer_type': points},
                    'flags': {'category': enrichments.customer_type.category, 'review': false,
                              'certainty': 0.8, 'missing': null}};
        """,
        {"company": {}, "signup": {}, "enrichments": {"customer_type": {"category": "software"}}, "lists": {}},
    )
    assert result.score == 25
    assert result.components == {"customer_type": 25}
    assert result.flags == {"category": "software", "review": False, "certainty": 0.8, "missing": None}


@parameterized.expand(
    [
        ("missing", {}, 1, None),
        ("unknown", {"custom": {"value": "unknown"}}, 2, "unknown"),
        ("negative", {"custom": {"value": False}}, 3, False),
        ("positive", {"custom": {"value": True}}, 4, True),
    ]
)
def test_formula_selects_each_enrichment_value_without_input_coercion(
    _name, enrichments, expected_score, expected_value
):
    from products.growth.backend.enrichment.fit_score import evaluate_score

    result = evaluate_score(
        """
            let value := enrichments.custom.value;
            let points := if(not has(keys(enrichments), 'custom'), 1,
                if(typeof(value) == 'string', 2, if(value, 4, 3)));
            return {'status': 'scored', 'score': points, 'components': {'custom': points},
                    'flags': {'value': value}};
        """,
        {"company": {}, "signup": {}, "enrichments": enrichments, "lists": {}},
    )
    assert result.score == expected_score
    assert result.flags == {"value": expected_value}


def test_input_hash_tracks_input_changes_and_versions_without_depending_on_mapping_order():
    from products.growth.backend.enrichment.fit_score import build_scoring_inputs, score_context, scoring_input_hash

    lists = CuratedLists(version="example")
    inputs = build_scoring_inputs(
        {"headcount": 5}, lists=lists, role="engineering", enrichments={"custom": {"value": "unknown"}}
    )
    versions = {"current_fetch": "example-fetch", "enrichment/custom": "example-result"}
    result = score_context(inputs, source=lists.rules.source, lists_version=lists.version, input_versions=versions)
    assert result.input_values == inputs
    assert result.input_versions == versions
    assert result.input_hash == scoring_input_hash(inputs, versions)
    assert result.input_hash == scoring_input_hash(
        dict(reversed(list(inputs.items()))), dict(reversed(list(versions.items())))
    )
    changed_versions = {**versions, "enrichment/custom": "new-result"}
    changed_label = {**inputs, "enrichments": {"custom": {"value": False}}}
    changed_company = {**inputs, "company": {"headcount": 10}}
    assert all(
        scoring_input_hash(changed, revision) != result.input_hash
        for changed, revision in [(inputs, changed_versions), (changed_label, versions), (changed_company, versions)]
    )
    inputs["signup"]["role"] = "student"
    versions["current_fetch"] = "changed-fetch"
    assert result.input_values["signup"]["role"] == "engineering"
    assert result.input_versions["current_fetch"] == "example-fetch"
