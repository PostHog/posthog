import pytest
from posthog.test.base import BaseTest

from posthog.schema import (
    EventPropertyFilter,
    ExperimentEventExposureConfig,
    ExperimentExposureCriteria,
    PersonPropertyFilter,
    PropertyOperator,
)

from posthog.hogql import ast

from products.experiments.backend.hogql_queries.exposure_query_logic import (
    UnsupportedExposureExclusionError,
    build_exposure_exclusion_expr,
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


class TestBuildExposureExclusionExpr(BaseTest):
    def test_person_filter_reads_current_state_not_the_event_snapshot(self):
        expr = build_exposure_exclusion_expr(
            [PersonPropertyFilter(key="consent_withdrawn", value=["true"], operator=PropertyOperator.EXACT)],
            self.team,
        )

        # The subquery against `persons` is the whole point: reading `person.properties` off the
        # events row would give the value snapshotted when the event was ingested, so nobody
        # exposed before the property was set would ever be removed. Keying it on `person_id`
        # rather than the row is what takes the person's earlier exposures with them.
        assert isinstance(expr, ast.Not)
        membership = expr.expr
        assert isinstance(membership, ast.CompareOperation)
        assert membership.op == ast.CompareOperationOp.In
        assert membership.left == ast.Field(chain=["person_id"])
        assert isinstance(membership.right, ast.SelectQuery)
        assert membership.right.select_from is not None
        assert membership.right.select_from.table == ast.Field(chain=["persons"])

    def test_rejects_filters_that_cannot_resolve_at_query_time(self):
        with pytest.raises(UnsupportedExposureExclusionError):
            build_exposure_exclusion_expr(
                [EventPropertyFilter(key="plan", value=["paid"], operator=PropertyOperator.EXACT)], self.team
            )

    def test_no_exclusions_is_no_predicate(self):
        assert build_exposure_exclusion_expr([], self.team) is None
