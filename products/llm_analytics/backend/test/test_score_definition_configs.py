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

        self.assertEqual(
            {field: [str(detail) for detail in details] for field, details in err.exception.detail.items()},
            expected_detail,
        )

    @parameterized.expand(
        [
            (
                "categorical",
                "categorical",
                {"options": [{"key": "good", "label": "Good"}, {"key": "bad", "label": "Bad"}]},
            ),
            ("numeric", "numeric", {"min": 0, "max": 5, "step": 1}),
            ("boolean", "boolean", {"true_label": "Yes", "false_label": "No"}),
        ]
    )
    def test_valid_configs_pass_validation(self, _name: str, kind: str, payload: dict) -> None:
        serializer = build_score_definition_config_serializer(kind, data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
