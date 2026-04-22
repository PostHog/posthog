import unittest

from parameterized import parameterized
from rest_framework import serializers

from products.llm_analytics.backend.score_definition_configs import build_score_definition_config_serializer


class TestScoreDefinitionConfigValidation(unittest.TestCase):
    @parameterized.expand(
        [
            (
                "categorical_requires_options",
                "categorical",
                {"options": []},
                {"options": ["Provide at least one categorical option."]},
            ),
            (
                "categorical_requires_unique_keys",
                "categorical",
                {"options": [{"key": "good", "label": "Good"}, {"key": "good", "label": "Bad"}]},
                {"options": ["Categorical option keys must be unique."]},
            ),
            (
                "categorical_single_rejects_min_selections",
                "categorical",
                {
                    "options": [{"key": "good", "label": "Good"}, {"key": "bad", "label": "Bad"}],
                    "min_selections": 1,
                },
                {"min_selections": ["`min_selections` is only supported when `selection_mode` is `multiple`."]},
            ),
            (
                "categorical_multiple_requires_min_to_fit_options",
                "categorical",
                {
                    "options": [{"key": "good", "label": "Good"}, {"key": "bad", "label": "Bad"}],
                    "selection_mode": "multiple",
                    "min_selections": 3,
                },
                {"min_selections": ["Ensure `min_selections` is less than or equal to the number of options."]},
            ),
            (
                "categorical_multiple_requires_max_to_fit_options",
                "categorical",
                {
                    "options": [{"key": "good", "label": "Good"}, {"key": "bad", "label": "Bad"}],
                    "selection_mode": "multiple",
                    "max_selections": 3,
                },
                {"max_selections": ["Ensure `max_selections` is less than or equal to the number of options."]},
            ),
            (
                "categorical_multiple_requires_max_above_min",
                "categorical",
                {
                    "options": [
                        {"key": "good", "label": "Good"},
                        {"key": "mixed", "label": "Mixed"},
                        {"key": "bad", "label": "Bad"},
                    ],
                    "selection_mode": "multiple",
                    "min_selections": 3,
                    "max_selections": 2,
                },
                {"max_selections": ["Ensure `max_selections` is greater than or equal to `min_selections`."]},
            ),
            (
                "numeric_requires_positive_step",
                "numeric",
                {"step": 0},
                {"step": ["Ensure `step` is greater than 0."]},
            ),
            (
                "numeric_requires_max_above_min",
                "numeric",
                {"min": 5, "max": 2},
                {"max": ["Ensure `max` is greater than or equal to `min`."]},
            ),
        ]
    )
    def test_invalid_configs_raise_validation_error(
        self, _name: str, kind: str, payload: dict, expected_detail: dict[str, list[str]]
    ) -> None:
        serializer = build_score_definition_config_serializer(kind, data=payload)

        with self.assertRaises(serializers.ValidationError) as err:
            serializer.is_valid(raise_exception=True)

        detail = err.exception.detail
        assert isinstance(detail, dict)
        self.assertEqual(
            {field: [str(item) for item in details] for field, details in detail.items()},
            expected_detail,
        )

    @parameterized.expand(
        [
            (
                "categorical",
                "categorical",
                {"options": [{"key": "good", "label": "Good"}, {"key": "bad", "label": "Bad"}]},
            ),
            (
                "categorical_multiple",
                "categorical",
                {
                    "options": [
                        {"key": "good", "label": "Good"},
                        {"key": "mixed", "label": "Mixed"},
                        {"key": "bad", "label": "Bad"},
                    ],
                    "selection_mode": "multiple",
                    "min_selections": 1,
                    "max_selections": 2,
                },
            ),
            ("numeric", "numeric", {"min": 0, "max": 5, "step": 1}),
            ("boolean", "boolean", {"true_label": "Yes", "false_label": "No"}),
        ]
    )
    def test_valid_configs_pass_validation(self, _name: str, kind: str, payload: dict) -> None:
        serializer = build_score_definition_config_serializer(kind, data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
