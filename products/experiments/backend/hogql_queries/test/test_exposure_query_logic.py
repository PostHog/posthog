import pytest
from unittest.mock import MagicMock

from posthog.schema import ExperimentEventExposureConfig, ExperimentExposureCriteria

from posthog.hogql import ast

from products.experiments.backend.hogql_queries.exposure_query_logic import (
    build_exposure_event_conditions,
    build_exposure_mapping_variant_expr,
    build_exposure_variant_expr,
    normalize_to_exposure_criteria,
)


class TestNormalizeToExposureCriteria:
    @pytest.mark.parametrize(
        "input_value,expected_type",
        [
            (None, type(None)),
            (ExperimentExposureCriteria(), ExperimentExposureCriteria),
            ({}, ExperimentExposureCriteria),
            ({"exposure_config": {"event": "test", "properties": []}}, ExperimentExposureCriteria),
        ],
    )
    def test_handles_different_input_types(self, input_value, expected_type):
        result = normalize_to_exposure_criteria(input_value)
        assert isinstance(result, expected_type)

    def test_does_not_mutate_input_dict(self):
        original = {"exposure_config": {"event": "test", "properties": []}}
        original_copy = original.copy()

        normalize_to_exposure_criteria(original)

        # Original dict should remain unchanged
        assert original == original_copy
        assert isinstance(original["exposure_config"], dict)

    def test_converts_nested_exposure_config(self):
        input_dict = {"exposure_config": {"event": "test_event", "properties": []}}

        result = normalize_to_exposure_criteria(input_dict)

        assert result is not None
        assert isinstance(result.exposure_config, ExperimentEventExposureConfig)
        assert result.exposure_config.event == "test_event"

    def test_preserves_already_typed_object(self):
        typed_criteria = ExperimentExposureCriteria()

        result = normalize_to_exposure_criteria(typed_criteria)

        # Should return the exact same object, not a copy
        assert result is typed_criteria


class TestDualReadExposureContract:
    def test_default_exposure_reads_legacy_and_dedicated_events(self):
        conditions = build_exposure_event_conditions(None, MagicMock(), "checkout-cta")

        assert isinstance(conditions[0], ast.Or)
        assert [
            expr.right.value
            for expr in conditions[0].exprs
            if isinstance(expr, ast.CompareOperation) and isinstance(expr.right, ast.Constant)
        ] == [
            "$feature_flag_called",
            "$experiment_exposure",
        ]

        variant_expr = build_exposure_variant_expr("checkout-cta")
        assert isinstance(variant_expr, ast.Call)
        assert variant_expr.name == "if"

    def test_custom_exposure_prefers_mapping_and_falls_back_to_legacy_property(self):
        criteria = {
            "exposure_config": {
                "kind": "ExperimentEventExposureConfig",
                "event": "checkout started",
                "properties": [],
            }
        }

        expression = build_exposure_variant_expr("checkout-cta", criteria)

        assert expression == build_exposure_mapping_variant_expr("checkout-cta")
        assert isinstance(expression, ast.Call)
        assert expression.name == "coalesce"
