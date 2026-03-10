from decimal import Decimal

import unittest

from parameterized import parameterized
from rest_framework import serializers

from products.llm_analytics.backend.trace_review_validation import normalize_and_validate_score_fields


class TestTraceReviewValidation(unittest.TestCase):
    @parameterized.expand(
        [
            (
                "label_with_numeric",
                {"score_kind": "label", "score_label": "good", "score_numeric": "1.000"},
                {},
                {"score_numeric": ["Clear `score_numeric` when `score_kind` is `label`."]},
            ),
            (
                "numeric_with_label",
                {"score_kind": "numeric", "score_numeric": Decimal("1.000"), "score_label": "good"},
                {},
                {"score_label": ["Clear `score_label` when `score_kind` is `numeric`."]},
            ),
            (
                "null_kind_with_label",
                {"score_kind": None, "score_label": "good"},
                {},
                {"score_kind": ["Clear `score_label` and `score_numeric` when `score_kind` is null."]},
            ),
            (
                "score_without_kind",
                {"score_label": "good"},
                {},
                {"score_kind": ["Set `score_kind` when providing `score_label` or `score_numeric`."]},
            ),
        ]
    )
    def test_invalid_score_state_raises_validation_error(
        self,
        _name: str,
        attrs: dict,
        current_values: dict,
        expected_detail: dict,
    ) -> None:
        with self.assertRaises(serializers.ValidationError) as err:
            normalize_and_validate_score_fields(
                attrs,
                current_score_kind=current_values.get("score_kind"),
                current_score_label=current_values.get("score_label"),
                current_score_numeric=current_values.get("score_numeric"),
            )

        self.assertEqual({field: [str(detail)] for field, detail in err.exception.detail.items()}, expected_detail)

    @parameterized.expand(
        [
            (
                "clear_score_kind",
                {"score_kind": None},
                {"score_kind": "label", "score_label": "good", "score_numeric": None},
                {"score_kind": None, "score_label": None, "score_numeric": None},
            ),
            (
                "switch_label_to_numeric",
                {"score_kind": "numeric", "score_numeric": Decimal("4.250")},
                {"score_kind": "label", "score_label": "good", "score_numeric": None},
                {"score_kind": "numeric", "score_numeric": Decimal("4.250"), "score_label": None},
            ),
            (
                "switch_numeric_to_label",
                {"score_kind": "label", "score_label": "bad"},
                {"score_kind": "numeric", "score_label": None, "score_numeric": Decimal("2.000")},
                {"score_kind": "label", "score_label": "bad", "score_numeric": None},
            ),
            (
                "preserve_existing_label_on_partial_patch",
                {"comment": "Updated"},
                {"score_kind": "label", "score_label": "good", "score_numeric": None},
                {"comment": "Updated", "score_numeric": None},
            ),
        ]
    )
    def test_valid_score_state_is_normalized(
        self,
        _name: str,
        attrs: dict,
        current_values: dict,
        expected_attrs: dict,
    ) -> None:
        normalized_attrs = normalize_and_validate_score_fields(
            attrs,
            current_score_kind=current_values.get("score_kind"),
            current_score_label=current_values.get("score_label"),
            current_score_numeric=current_values.get("score_numeric"),
        )

        self.assertEqual(normalized_attrs, expected_attrs)
